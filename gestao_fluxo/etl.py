"""ETL plano: cada planilha vira uma tabela do banco, linha a linha.

Regra única e deliberada: **não alteramos totais**. Não há corte por ano, filtro
escondido nem escolha de "linha atual". O que fazemos é:

    ler a planilha -> renomear 6 colunas -> limpar texto (oficina, MP)
                   -> converter data para ISO -> calcular identidade -> gravar

Assim, `SUM(qtd_pecas)` no banco bate com a soma da coluna no Excel, e qualquer
número da tela pode ser conferido pelo time.

A carga é incremental: o banco acumula o histórico e cada planilha só acrescenta
as linhas que ainda não existem. Isso não é deduplicação por regra de negócio —
duas linhas idênticas na mesma planilha continuam valendo duas linhas no banco
(ver database.calcular_identidade). O que se evita é o mesmo arquivo entrar duas
vezes. A exceção é o Acompanhamento, substituído por inteiro a cada carga porque
representa o que está em aberto *agora*, não um histórico.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from . import config
from .db import database
from .exceptions import ETLError, FonteDeDadosError

_ESPACOS = re.compile(r"\s+")


# =========================================================================== #
# NORMALIZAÇÃO DE TEXTO
# =========================================================================== #
def limpar_texto(valor) -> str:
    """Tira espaços não-quebráveis (\\xa0), colapsa espaços e faz strip."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    s = str(valor).replace("\xa0", " ").replace("​", "")
    return _ESPACOS.sub(" ", s).strip()


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


_PLACEHOLDERS_CHAVE = {_sem_acento(p.upper()) for p in config.OFICINA_PLACEHOLDERS}


def normalizar_mp(valor) -> str:
    """'Malha'/'MALHA' -> MALHA; vazio ou 'Sem MP Informada' -> A CLASSIFICAR."""
    s = limpar_texto(valor).upper()
    if not s or s in config.MP_ROTULOS_SEM_INFO:
        return config.MP_A_CLASSIFICAR
    return s


def normalizar_oficina(valor, canonicos: dict | None = None) -> str:
    """Aplica o de-para de oficinas; placeholders viram 'A CLASSIFICAR'.

    `canonicos` mapeia chave-sem-acento -> nome padrão (de de_para_oficinas.xlsx).
    Nome fora do de-para é mantido como veio (limpo) — descartá-lo seria perder
    produção real.
    """
    disp = limpar_texto(valor)
    chave = _sem_acento(disp.upper())
    if not disp or chave in _PLACEHOLDERS_CHAVE:
        return config.OFICINA_A_CLASSIFICAR
    if canonicos and chave in canonicos:
        return canonicos[chave]
    return disp


def datas_para_iso(series: pd.Series) -> pd.Series:
    """Converte para strings ISO 'YYYY-MM-DD'; datas inválidas viram None."""
    dt = pd.to_datetime(series, errors="coerce")
    # `.astype(object)` antes do where: em série de strings o pandas devolveria
    # NaN no lugar de None, e o SQLite grava o texto 'nan' em vez de NULL.
    return dt.dt.strftime("%Y-%m-%d").astype(object).where(dt.notna(), None)


def _trocar_ano(ts: pd.Timestamp, ano: int) -> pd.Timestamp:
    try:
        return ts.replace(year=ano)
    except ValueError:  # 29/02 caindo em ano não bissexto
        return ts.replace(year=ano, day=28)


def corrigir_ano_deadline(series: pd.Series, ano_vigente: int | None = None) -> pd.Series:
    """Reescreve o ano dos prazos que vieram defasados na origem.

    A planilha de Acompanhamento exporta parte da coluna DEAD LINE com o ano
    anterior — mais da metade das linhas na carga de julho/2026, todas com ENVIO em
    2026, o que produziria um prazo anterior ao próprio envio. O time confirmou que
    todo prazo pertence ao ano vigente, então trocamos só o ano, preservando dia e mês.

    A correção é deliberadamente unidirecional: mexe apenas no que está *antes* do
    ano vigente. Um prazo legítimo que atravessa o ano (dezembro para janeiro) não
    pode ser puxado para trás.
    """
    ano = ano_vigente if ano_vigente is not None else date.today().year
    dt = pd.to_datetime(series, errors="coerce")
    defasadas = dt.notna() & (dt.dt.year < ano)
    if not defasadas.any():
        return dt
    return dt.mask(defasadas, dt[defasadas].map(lambda ts: _trocar_ano(ts, ano)))


# =========================================================================== #
# LEITURA
# =========================================================================== #
def _ler_excel(caminho: Path) -> pd.DataFrame:
    try:
        return pd.read_excel(caminho)
    except FileNotFoundError as exc:
        raise FonteDeDadosError(
            f"Arquivo não encontrado: {caminho.name}",
            mensagem_usuario=f"A planilha '{caminho.name}' não foi encontrada.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise FonteDeDadosError(f"Erro ao ler {caminho.name}: {exc}") from exc


def carregar_de_para_oficinas(caminho: Path | None = None) -> dict:
    """Lê os nomes-padrão de oficina e devolve {chave_sem_acento: nome_padrao}."""
    try:
        df = _ler_excel(caminho or config.EXCEL_DE_PARA)
    except FonteDeDadosError:
        return {}  # de-para é opcional: sem ele os nomes ficam como vêm da origem
    if df.shape[1] == 0:
        return {}
    nomes = [limpar_texto(v) for v in df.iloc[:, 0].dropna().tolist()]
    return {_sem_acento(n.upper()): n for n in nomes if n}


def _localizar_coluna(df: pd.DataFrame, alvo: str) -> str | None:
    """Casa o nome da coluna ignorando acento/caixa (o header vem com encoding sujo)."""
    alvo_chave = _sem_acento(limpar_texto(alvo).upper())
    for col in df.columns:
        if _sem_acento(limpar_texto(col).upper()) == alvo_chave:
            return col
    return None


def extrair_fonte(fonte: str, caminho: Path | None = None,
                  canonicos: dict | None = None) -> pd.DataFrame:
    """Lê uma planilha e devolve o DataFrame já no formato da tabela de fato."""
    spec = config.FONTES[fonte]
    df = _ler_excel(caminho or config.arquivo_da_fonte(fonte))

    achadas: dict = {}
    faltando: list = []
    for campo, coluna in spec["colunas"].items():
        real = _localizar_coluna(df, coluna)
        if real is None:
            faltando.append(coluna)
        else:
            achadas[campo] = real
    if faltando:
        raise FonteDeDadosError(
            f"{spec['rotulo']}: colunas ausentes {faltando}",
            mensagem_usuario=(
                f"A planilha de {spec['rotulo']} está sem as colunas: {', '.join(faltando)}."
            ),
        )

    out = pd.DataFrame({
        "oficina": df[achadas["oficina"]].map(lambda v: normalizar_oficina(v, canonicos)),
        "data": datas_para_iso(df[achadas["data"]]),
        "mp": df[achadas["mp"]].map(normalizar_mp),
        "qtd_pecas": pd.to_numeric(df[achadas["qtd_pecas"]], errors="coerce").fillna(0.0),
        "minutos": pd.to_numeric(df[achadas["minutos"]], errors="coerce").fillna(0.0),
        "om": pd.to_numeric(df[achadas["om"]], errors="coerce").astype("Int64"),
    })
    # `om` como object para o SQLite receber None no lugar de pd.NA.
    out["om"] = out["om"].astype("object").where(out["om"].notna(), None)

    # Campos extras da fonte (deadline, envio) — todos datas, ver config.CAMPOS_EXTRA.
    corrigidos = 0
    for campo in config.CAMPOS_EXTRA.get(fonte, ()):
        valores = pd.to_datetime(df[achadas[campo]], errors="coerce")
        if campo == "deadline":
            prazos = corrigir_ano_deadline(valores)
            # Só conta o que mudou de fato: `NaT != NaT` é True no pandas, e sem os
            # dois `notna` a conferência da carga reportaria como "prazo corrigido"
            # toda linha que chegou simplesmente sem prazo nenhum.
            corrigidos = int(
                (valores.notna() & prazos.notna() & (prazos != valores)).sum())
            valores = prazos
        out[campo] = datas_para_iso(valores)

    out = out[config.campos_da_fonte(fonte)]
    # Atributo (e não coluna) porque é metadado da carga, não do fato: alimenta o
    # relatório de conferência exibido na barra lateral.
    out.attrs["prazos_corrigidos"] = corrigidos
    return out


# =========================================================================== #
# RELATÓRIO E CARGA
# =========================================================================== #
@dataclass
class ResumoFonte:
    rotulo: str
    linhas: int = 0                 # linhas lidas do arquivo
    novas: int = 0                  # linhas que de fato entraram no banco
    total_pecas: float = 0.0
    total_minutos: float = 0.0
    sem_data: int = 0
    oficinas: int = 0
    prazos_corrigidos: int = 0
    modo: str = config.MODO_INCREMENTAL

    @property
    def repetidas(self) -> int:
        """Linhas do arquivo que já estavam no banco e foram ignoradas."""
        return max(self.linhas - self.novas, 0)

    @property
    def substituida(self) -> bool:
        return self.modo == config.MODO_SUBSTITUICAO


@dataclass
class RelatorioCarga:
    """O que o ETL gravou — exibido após a carga para conferência com o Excel."""

    fontes: list = field(default_factory=list)

    @property
    def total_linhas(self) -> int:
        """Linhas lidas das planilhas (não necessariamente gravadas)."""
        return sum(f.linhas for f in self.fontes)

    @property
    def total_novas(self) -> int:
        return sum(f.novas for f in self.fontes)


def _resumir(fonte: str, df: pd.DataFrame, novas: int) -> ResumoFonte:
    return ResumoFonte(
        rotulo=config.FONTES[fonte]["rotulo"],
        linhas=len(df),
        novas=novas,
        total_pecas=float(df["qtd_pecas"].sum()),
        total_minutos=float(df["minutos"].sum()),
        sem_data=int(df["data"].isna().sum()),
        oficinas=int(df["oficina"].nunique()),
        prazos_corrigidos=int(df.attrs.get("prazos_corrigidos", 0)),
        modo=config.modo_da_fonte(fonte),
    )


def _preparar(caminhos: dict, de_para_path: Path | None) -> dict:
    """Lê as planilhas informadas e devolve {fonte: df já com identidade}.

    Só as fontes presentes em `caminhos` são lidas — subir apenas o Recebimento do
    dia não deve exigir ter as outras duas planilhas em mãos. Quando `caminhos` vem
    vazio, mantém-se o comportamento antigo de carregar as três da raiz do projeto.
    """
    canonicos = carregar_de_para_oficinas(de_para_path)
    fontes = caminhos.keys() if caminhos else config.FONTES.keys()
    preparados = {}
    for fonte in fontes:
        df = extrair_fonte(fonte, caminhos.get(fonte), canonicos)
        prazos = df.attrs.get("prazos_corrigidos", 0)
        df = database.calcular_identidade(df)
        # `calcular_identidade` devolve uma cópia, e `attrs` não sobrevive à cópia.
        df.attrs["prazos_corrigidos"] = prazos
        preparados[fonte] = df
    return preparados


@dataclass
class PreviaFonte:
    """O que uma planilha faria com o banco, antes de qualquer gravação."""

    fonte: str
    rotulo: str
    linhas: int = 0
    novas: int = 0
    modo: str = config.MODO_INCREMENTAL

    @property
    def repetidas(self) -> int:
        return max(self.linhas - self.novas, 0)

    @property
    def substituida(self) -> bool:
        return self.modo == config.MODO_SUBSTITUICAO


def prever_carga(engine: Engine, *, caminhos: dict | None = None,
                 de_para_path: Path | None = None) -> list:
    """Simula a carga e devolve o que entraria, sem gravar nada.

    Existe para que a carga incremental não seja uma caixa-preta: o operador vê
    "312 novas, 28 já existentes" e confirma. Sem essa conferência o time não tem
    como distinguir "a planilha estava repetida" de "o app engoliu meus dados".
    """
    caminhos = caminhos or {}
    try:
        database.init_schema(engine)
        previas = []
        for fonte, df in _preparar(caminhos, de_para_path).items():
            modo = config.modo_da_fonte(fonte)
            tabela = config.FONTES[fonte]["tabela"]
            # Na substituição a tabela inteira é trocada, então toda linha do
            # arquivo entra no retrato novo — não há o que comparar com o antigo.
            novas = (len(df) if modo == config.MODO_SUBSTITUICAO
                     else database.contar_novas(engine, tabela, df))
            previas.append(PreviaFonte(
                fonte=fonte, rotulo=config.FONTES[fonte]["rotulo"],
                linhas=len(df), novas=novas, modo=modo,
            ))
        return previas
    except FonteDeDadosError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ETLError(f"Falha ao analisar as planilhas: {exc}") from exc


def executar_etl(engine: Engine, *, caminhos: dict | None = None,
                 de_para_path: Path | None = None) -> RelatorioCarga:
    """Carrega as planilhas no banco. Metas e histórico anterior são preservados.

    `caminhos` permite apontar planilhas alternativas: {"envios": Path(...), ...}.
    Informar só uma fonte carrega só ela.

    Envios e Recebimento são **incrementais**: acrescentam ao histórico apenas as
    linhas que ainda não existem, então re-subir a mesma planilha é inofensivo.
    Acompanhamento é **substituído** por inteiro — ver config.MODO_SUBSTITUICAO.

    A carga é transacional: se qualquer fonte falhar, nada é gravado pela metade.
    """
    caminhos = caminhos or {}
    try:
        dados = _preparar(caminhos, de_para_path)
        database.init_schema(engine)
        resumos = []
        with engine.begin() as conn:
            for fonte, df in dados.items():
                spec = config.FONTES[fonte]
                modo = config.modo_da_fonte(fonte)
                origem = caminhos.get(fonte) or config.arquivo_da_fonte(fonte)
                carga_id = database.abrir_carga(
                    conn, fonte=fonte, arquivo=Path(origem).name, modo=modo)
                gravar = (database.substituir_tabela
                          if modo == config.MODO_SUBSTITUICAO
                          else database.inserir_novas)
                novas = gravar(conn, spec["tabela"], df,
                               config.campos_da_fonte(fonte), carga_id)
                database.finalizar_carga(
                    conn, carga_id, linhas_lidas=len(df), linhas_novas=novas)
                resumos.append(_resumir(fonte, df, novas))
        return RelatorioCarga(fontes=resumos)
    except FonteDeDadosError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ETLError(f"Falha no ETL: {exc}") from exc
