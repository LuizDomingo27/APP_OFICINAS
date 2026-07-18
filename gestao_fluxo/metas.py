"""Metas: cadastro, diluição por dias úteis e confronto com o realizado.

O time cadastra 6 valores (mês/semana/dia x peças/minutos). A partir da meta
mensal, diluímos pelos dias úteis do mês vigente para achar a necessidade por dia
e por semana — é essa necessidade que diz se o ritmo atual chega no fim do mês.

O realizado vem da base de RECEBIMENTO ("o cálculo será feito de acordo com o que
recebemos").
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config, metricas
from .db import database
from .exceptions import BancoDeDadosError


# =========================================================================== #
# PERSISTÊNCIA
# =========================================================================== #
def garantir_tabela(engine: Engine) -> None:
    """Cria `metas` se ainda não existir (ela sobrevive às recargas do ETL)."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS metas ("
                " chave TEXT PRIMARY KEY,"
                " valor REAL NOT NULL DEFAULT 0,"
                " atualizado_em TEXT)"
            ))
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(f"Falha ao preparar a tabela de metas: {exc}") from exc


def ler_metas(engine: Engine) -> dict:
    """Devolve as 6 chaves sempre presentes; as não cadastradas valem 0."""
    garantir_tabela(engine)
    df = database.read_sql("SELECT chave, valor FROM metas", engine)
    salvas = dict(zip(df["chave"], df["valor"])) if not df.empty else {}
    return {chave: float(salvas.get(chave, 0.0)) for chave in config.METAS_CHAVES}


def salvar_metas(engine: Engine, valores: dict) -> None:
    """Grava (upsert) as metas informadas. Chaves desconhecidas são ignoradas."""
    garantir_tabela(engine)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.begin() as conn:
            for chave, valor in valores.items():
                if chave not in config.METAS_CHAVES:
                    continue
                conn.execute(
                    text("INSERT INTO metas (chave, valor, atualizado_em)"
                         " VALUES (:c, :v, :a)"
                         " ON CONFLICT(chave) DO UPDATE SET"
                         " valor = excluded.valor, atualizado_em = excluded.atualizado_em"),
                    {"c": chave, "v": float(valor or 0), "a": agora},
                )
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(f"Falha ao salvar as metas: {exc}") from exc


# =========================================================================== #
# DIAS ÚTEIS E DILUIÇÃO
# =========================================================================== #
def dias_uteis(inicio: date, fim: date) -> int:
    """Conta segunda a sexta no intervalo.

    Feriado não é descontado — não temos calendário de feriados cadastrado, e
    inventar um daria uma diluição que o time não conseguiria conferir.
    """
    total, cursor = 0, inicio
    while cursor <= fim:
        if cursor.weekday() < 5:
            total += 1
        cursor += timedelta(days=1)
    return total


def limites_do_mes(ano: int, mes: int) -> tuple:
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


@dataclass
class Acompanhamento:
    """Uma meta e onde estamos em relação a ela."""

    rotulo: str
    meta: float = 0.0
    realizado: float = 0.0

    @property
    def falta(self) -> float:
        return max(self.meta - self.realizado, 0.0)

    @property
    def percentual(self) -> float:
        return (self.realizado / self.meta * 100) if self.meta else 0.0

    @property
    def batida(self) -> bool:
        return self.meta > 0 and self.realizado >= self.meta


@dataclass
class PlanoMetas:
    """Tudo que a aba de Metas precisa exibir, já calculado."""

    ano: int
    mes: int
    dias_uteis_mes: int
    dias_uteis_decorridos: int
    dias_uteis_restantes: int
    necessidade_dia: dict           # meta mensal diluída por dia útil
    necessidade_semana: dict        # necessidade_dia x dias úteis da semana corrente
    ritmo_necessario: dict          # o que falta / dias úteis restantes
    semana_rotulo: str
    acompanhamentos: dict           # {"mes_pecas": Acompanhamento, ...}


def _semana_corrente(ano: int, mes: int, hoje: date):
    """Semana do mês que contém `hoje`; se `hoje` cai fora do mês, usa a última."""
    semanas = metricas.semanas_do_mes(ano, mes)
    for s in semanas:
        if s.inicio <= hoje <= s.fim:
            return s
    return semanas[-1]


def montar_plano(df_realizado: pd.DataFrame, metas_salvas: dict, ano: int, mes: int,
                 hoje: date | None = None) -> PlanoMetas:
    """Cruza metas cadastradas com o realizado e dilui a meta mensal por dia útil.

    `df_realizado` é o fato de recebimento completo — a função recorta os períodos.
    """
    hoje = hoje or date.today()
    inicio_mes, fim_mes = limites_do_mes(ano, mes)
    uteis_mes = dias_uteis(inicio_mes, fim_mes)
    # Mês já encerrado -> tudo decorrido; mês futuro -> nada decorrido.
    uteis_decorridos = 0 if hoje < inicio_mes else dias_uteis(inicio_mes, min(hoje, fim_mes))
    uteis_restantes = max(uteis_mes - uteis_decorridos, 0)

    semana = _semana_corrente(ano, mes, hoje)
    uteis_semana = dias_uteis(semana.inicio, semana.fim)

    realizado_mes = metricas.filtrar(df_realizado, inicio_mes, fim_mes)
    realizado_semana = metricas.filtrar(df_realizado, semana.inicio, semana.fim)
    realizado_dia = metricas.filtrar(df_realizado, hoje, hoje)

    def soma(df: pd.DataFrame, coluna: str) -> float:
        return float(df[coluna].sum()) if not df.empty else 0.0

    meta_mes = {"pecas": metas_salvas.get("mes_pecas", 0.0),
                "minutos": metas_salvas.get("mes_minutos", 0.0)}

    necessidade_dia = {k: (v / uteis_mes if uteis_mes else 0.0) for k, v in meta_mes.items()}
    necessidade_semana = {k: v * uteis_semana for k, v in necessidade_dia.items()}

    def efetiva(chave: str, diluida: float) -> float:
        """Meta cadastrada quando houver; senão, a diluída a partir do mês."""
        cadastrada = metas_salvas.get(chave, 0.0)
        return cadastrada if cadastrada > 0 else diluida

    falta_mes = {
        "pecas": max(meta_mes["pecas"] - soma(realizado_mes, "qtd_pecas"), 0.0),
        "minutos": max(meta_mes["minutos"] - soma(realizado_mes, "minutos"), 0.0),
    }
    ritmo = {k: (v / uteis_restantes if uteis_restantes else 0.0) for k, v in falta_mes.items()}

    acomp = {
        "mes_pecas": Acompanhamento("Peças no mês", meta_mes["pecas"],
                                    soma(realizado_mes, "qtd_pecas")),
        "mes_minutos": Acompanhamento("Minutos no mês", meta_mes["minutos"],
                                      soma(realizado_mes, "minutos")),
        "semana_pecas": Acompanhamento(
            "Peças na semana", efetiva("semana_pecas", necessidade_semana["pecas"]),
            soma(realizado_semana, "qtd_pecas")),
        "semana_minutos": Acompanhamento(
            "Minutos na semana", efetiva("semana_minutos", necessidade_semana["minutos"]),
            soma(realizado_semana, "minutos")),
        "dia_pecas": Acompanhamento(
            "Peças no dia", efetiva("dia_pecas", necessidade_dia["pecas"]),
            soma(realizado_dia, "qtd_pecas")),
        "dia_minutos": Acompanhamento(
            "Minutos no dia", efetiva("dia_minutos", necessidade_dia["minutos"]),
            soma(realizado_dia, "minutos")),
    }

    return PlanoMetas(
        ano=ano, mes=mes,
        dias_uteis_mes=uteis_mes,
        dias_uteis_decorridos=uteis_decorridos,
        dias_uteis_restantes=uteis_restantes,
        necessidade_dia=necessidade_dia,
        necessidade_semana=necessidade_semana,
        ritmo_necessario=ritmo,
        semana_rotulo=semana.rotulo,
        acompanhamentos=acomp,
    )
