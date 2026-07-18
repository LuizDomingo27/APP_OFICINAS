"""Testes de cadastro de metas, diluição por dias úteis e confronto com o realizado."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gestao_fluxo import metas


@pytest.fixture
def realizado() -> pd.DataFrame:
    """Recebimento de julho/2026: 100 peças em 06/07 e 200 em 15/07."""
    return pd.DataFrame({
        "oficina": ["A", "A"],
        "data": pd.to_datetime(["2026-07-06", "2026-07-15"]),
        "mp": ["JEANS", "MALHA"],
        "qtd_pecas": [100.0, 200.0],
        "minutos": [1000.0, 2000.0],
        "om": [1, 2],
    })


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #
def test_ler_metas_devolve_as_seis_chaves_zeradas(engine):
    salvas = metas.ler_metas(engine)
    assert set(salvas) == {"mes_pecas", "mes_minutos", "semana_pecas",
                           "semana_minutos", "dia_pecas", "dia_minutos"}
    assert all(v == 0 for v in salvas.values())


def test_salvar_e_reler(engine):
    metas.salvar_metas(engine, {"mes_pecas": 10000, "mes_minutos": 1_000_000})
    salvas = metas.ler_metas(engine)
    assert salvas["mes_pecas"] == 10000
    assert salvas["mes_minutos"] == 1_000_000


def test_salvar_duas_vezes_atualiza_em_vez_de_duplicar(engine):
    metas.salvar_metas(engine, {"mes_pecas": 100})
    metas.salvar_metas(engine, {"mes_pecas": 250})
    assert metas.ler_metas(engine)["mes_pecas"] == 250


def test_chave_desconhecida_e_ignorada(engine):
    metas.salvar_metas(engine, {"meta_inventada": 999})
    assert "meta_inventada" not in metas.ler_metas(engine)


# --------------------------------------------------------------------------- #
# Dias úteis
# --------------------------------------------------------------------------- #
def test_dias_uteis_de_uma_semana_cheia():
    """06/07/2026 é segunda; 12/07 é domingo."""
    assert metas.dias_uteis(date(2026, 7, 6), date(2026, 7, 12)) == 5


def test_dias_uteis_do_mes():
    inicio, fim = metas.limites_do_mes(2026, 7)
    assert metas.dias_uteis(inicio, fim) == 23


def test_fim_de_semana_isolado_nao_tem_dia_util():
    assert metas.dias_uteis(date(2026, 7, 11), date(2026, 7, 12)) == 0


# --------------------------------------------------------------------------- #
# Diluição e acompanhamento
# --------------------------------------------------------------------------- #
def test_meta_mensal_e_diluida_pelos_dias_uteis(realizado):
    """23 dias úteis em julho/2026: 10.000 peças -> ~434,78 por dia."""
    plano = metas.montar_plano(realizado, {"mes_pecas": 10000, "mes_minutos": 1_000_000},
                               2026, 7, hoje=date(2026, 7, 15))
    assert plano.dias_uteis_mes == 23
    assert plano.necessidade_dia["pecas"] == pytest.approx(10000 / 23)
    assert plano.necessidade_dia["minutos"] == pytest.approx(1_000_000 / 23)


def test_necessidade_da_semana_multiplica_pelos_dias_uteis_dela(realizado):
    """15/07 cai na semana 13–19, que tem 5 dias úteis."""
    plano = metas.montar_plano(realizado, {"mes_pecas": 10000}, 2026, 7,
                               hoje=date(2026, 7, 15))
    assert plano.necessidade_semana["pecas"] == pytest.approx(10000 / 23 * 5)


def test_realizado_e_falta_do_mes(realizado):
    plano = metas.montar_plano(realizado, {"mes_pecas": 1000}, 2026, 7,
                               hoje=date(2026, 7, 15))
    mes = plano.acompanhamentos["mes_pecas"]
    assert mes.realizado == 300
    assert mes.falta == 700
    assert mes.percentual == pytest.approx(30.0)
    assert not mes.batida


def test_meta_batida_nao_gera_falta_negativa(realizado):
    plano = metas.montar_plano(realizado, {"mes_pecas": 200}, 2026, 7,
                               hoje=date(2026, 7, 15))
    mes = plano.acompanhamentos["mes_pecas"]
    assert mes.batida
    assert mes.falta == 0


def test_meta_semanal_cadastrada_tem_prioridade_sobre_a_diluida(realizado):
    plano = metas.montar_plano(realizado, {"mes_pecas": 10000, "semana_pecas": 500},
                               2026, 7, hoje=date(2026, 7, 15))
    assert plano.acompanhamentos["semana_pecas"].meta == 500


def test_sem_meta_semanal_cadastrada_usa_a_diluicao(realizado):
    plano = metas.montar_plano(realizado, {"mes_pecas": 10000}, 2026, 7,
                               hoje=date(2026, 7, 15))
    assert plano.acompanhamentos["semana_pecas"].meta == pytest.approx(10000 / 23 * 5)


def test_ritmo_necessario_usa_os_dias_uteis_restantes(realizado):
    """Em 15/07 já correram 11 dias úteis; sobram 12 para as 700 peças que faltam."""
    plano = metas.montar_plano(realizado, {"mes_pecas": 1000}, 2026, 7,
                               hoje=date(2026, 7, 15))
    assert plano.dias_uteis_decorridos == 11
    assert plano.dias_uteis_restantes == 12
    assert plano.ritmo_necessario["pecas"] == pytest.approx(700 / 12)


def test_mes_ja_encerrado_nao_tem_dia_restante(realizado):
    plano = metas.montar_plano(realizado, {"mes_pecas": 1000}, 2026, 7,
                               hoje=date(2026, 9, 1))
    assert plano.dias_uteis_restantes == 0
    assert plano.ritmo_necessario["pecas"] == 0


def test_sem_meta_cadastrada_o_plano_nao_quebra(realizado):
    plano = metas.montar_plano(realizado, {}, 2026, 7, hoje=date(2026, 7, 15))
    assert plano.necessidade_dia["pecas"] == 0
    assert plano.acompanhamentos["mes_pecas"].percentual == 0
