"""Testes de períodos, filtros e métricas."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gestao_fluxo import config, metricas


# --------------------------------------------------------------------------- #
# Fluxo por matéria-prima
# --------------------------------------------------------------------------- #
def _fato_mp(linhas: list) -> pd.DataFrame:
    """DataFrame de fato a partir de tuplas (om, mp, qtd, minutos)."""
    return pd.DataFrame(
        [{"om": om, "mp": mp, "qtd_pecas": float(q), "minutos": float(m),
          "oficina": "OFICINA A", "data": pd.Timestamp("2026-07-06")}
         for om, mp, q, m in linhas]
    )


def test_fluxo_mp_soma_enviado_recebido_e_diferenca():
    envios = _fato_mp([(1, "JEANS", 100, 1000), (2, "MALHA", 200, 2000)])
    receb = _fato_mp([(1, "JEANS", 60, 600), (2, "MALHA", 200, 2000)])
    df = metricas.fluxo_por_mp(envios, receb)

    jeans = df[df["mp"] == "JEANS"].iloc[0]
    assert jeans["enviado_pecas"] == 100
    assert jeans["recebido_pecas"] == 60
    assert jeans["progresso_pecas"] == 40
    assert jeans["pct_concluido"] == pytest.approx(60.0)

    malha = df[df["mp"] == "MALHA"].iloc[0]
    assert malha["progresso_pecas"] == 0
    assert malha["pct_concluido"] == pytest.approx(100.0)


def test_fluxo_mp_usa_a_mp_do_envio_quando_a_ordem_e_reclassificada():
    """Ordem que sai JEANS e volta ECOBAGS conta como JEANS nos dois lados.

    Sem isso, ECOBAGS apareceria com recebimento sem envio nenhum e diferença
    negativa — ruído de reclassificação, não produção.
    """
    envios = _fato_mp([(1, "JEANS", 100, 1000)])
    receb = _fato_mp([(1, "ECOBAGS", 80, 800)])
    df = metricas.fluxo_por_mp(envios, receb)

    assert list(df["mp"]) == ["JEANS"]
    jeans = df.iloc[0]
    assert jeans["recebido_pecas"] == 80
    assert jeans["progresso_pecas"] == 20
    assert jeans["recebido_sem_envio"] == 0


def test_fluxo_mp_isola_recebimento_sem_envio_correspondente():
    """Recebimento de ordem que não existe em Envios fica visível, não escondido."""
    envios = _fato_mp([(1, "JEANS", 100, 1000)])
    receb = _fato_mp([(1, "JEANS", 60, 600), (999, "ECOBAGS", 50, 500)])
    df = metricas.fluxo_por_mp(envios, receb)

    eco = df[df["mp"] == "ECOBAGS"].iloc[0]
    assert eco["enviado_pecas"] == 0
    assert eco["recebido_pecas"] == 50
    assert eco["recebido_sem_envio"] == 50
    # Sem envio não há denominador: percentual fica vazio em vez de infinito.
    assert pd.isna(eco["pct_concluido"])


def test_fluxo_mp_conta_ordens_abertas_do_acompanhamento():
    envios = _fato_mp([(1, "JEANS", 100, 1000), (2, "JEANS", 50, 500),
                       (3, "MALHA", 30, 300)])
    receb = _fato_mp([(1, "JEANS", 100, 1000)])
    acomp = _fato_mp([(2, "JEANS", 50, 500), (3, "MALHA", 30, 300)])
    df = metricas.fluxo_por_mp(envios, receb, acomp)

    assert df[df["mp"] == "JEANS"].iloc[0]["ordens_abertas"] == 1
    assert df[df["mp"] == "MALHA"].iloc[0]["ordens_abertas"] == 1


def test_fluxo_mp_com_bases_vazias():
    vazio = _fato_mp([]).reindex(
        columns=["om", "mp", "qtd_pecas", "minutos", "oficina", "data"])
    df = metricas.fluxo_por_mp(vazio, vazio)
    assert df.empty
    assert list(df.columns) == metricas.COLUNAS_FLUXO_MP
    assert metricas.totais_fluxo_mp(df).enviado == 0


def test_fluxo_mp_ignora_ordem_nula_no_mapeamento():
    """Linha sem OM não pode virar chave e arrastar recebimento para a MP errada."""
    envios = _fato_mp([(None, "JEANS", 100, 1000)])
    receb = _fato_mp([(None, "MALHA", 40, 400)])
    df = metricas.fluxo_por_mp(envios, receb)

    assert df[df["mp"] == "MALHA"].iloc[0]["recebido_sem_envio"] == 40
    assert df[df["mp"] == "JEANS"].iloc[0]["enviado_pecas"] == 100


def test_totais_fluxo_mp_consolida_a_tabela():
    envios = _fato_mp([(1, "JEANS", 100, 1000), (2, "MALHA", 200, 2000)])
    receb = _fato_mp([(1, "JEANS", 60, 600), (2, "MALHA", 140, 1400)])
    t = metricas.totais_fluxo_mp(metricas.fluxo_por_mp(envios, receb))

    assert t.enviado == 300
    assert t.recebido == 200
    assert t.progresso == 100
    assert t.pct_concluido == pytest.approx(200 / 300 * 100)


@pytest.fixture
def fato() -> pd.DataFrame:
    """Julho/2026: 06 (semana 2) e 15 (semana 3). Junho serve de período anterior."""
    return pd.DataFrame({
        "oficina": ["A", "B", "A", "A"],
        "data": pd.to_datetime(["2026-06-10", "2026-07-06", "2026-07-06", "2026-07-15"]),
        "mp": ["JEANS", "JEANS", "MALHA", "MALHA"],
        "qtd_pecas": [100.0, 60.0, 40.0, 200.0],
        "minutos": [1000.0, 600.0, 400.0, 2000.0],
        "om": [9, 1, 1, 2],
    })


# --------------------------------------------------------------------------- #
# Semanas
# --------------------------------------------------------------------------- #
def test_semanas_ficam_dentro_do_mes():
    """Julho/2026 começa numa quarta: a semana 1 não pode invadir junho."""
    semanas = metricas.semanas_do_mes(2026, 7)
    assert semanas[0].inicio == date(2026, 7, 1)
    assert semanas[-1].fim == date(2026, 7, 31)
    assert all(s.inicio.month == 7 and s.fim.month == 7 for s in semanas)


def test_semanas_cobrem_o_mes_sem_buraco():
    semanas = metricas.semanas_do_mes(2026, 7)
    assert sum((s.fim - s.inicio).days + 1 for s in semanas) == 31


def test_semanas_de_mes_que_comeca_na_segunda():
    """Junho/2026 começa numa segunda — a primeira semana é cheia."""
    semanas = metricas.semanas_do_mes(2026, 6)
    assert semanas[0].inicio == date(2026, 6, 1)
    assert semanas[0].fim == date(2026, 6, 7)


def test_rotulo_da_semana_mostra_o_intervalo():
    assert metricas.semanas_do_mes(2026, 7)[0].rotulo == "Semana 1 (01/07 a 05/07)"


def test_periodo_anterior_tem_a_mesma_duracao():
    inicio, fim = metricas.periodo_anterior(date(2026, 7, 1), date(2026, 7, 31))
    assert (inicio, fim) == (date(2026, 6, 1), date(2026, 6, 30))


# --------------------------------------------------------------------------- #
# Filtro
# --------------------------------------------------------------------------- #
def test_filtro_por_intervalo(fato):
    julho = metricas.filtrar(fato, date(2026, 7, 1), date(2026, 7, 31))
    assert len(julho) == 3
    assert julho["qtd_pecas"].sum() == 300


def test_filtro_por_mp_e_oficina(fato):
    recorte = metricas.filtrar(fato, mps=["MALHA"], oficinas=["A"])
    assert recorte["qtd_pecas"].sum() == 240


def test_filtro_vazio_nao_restringe(fato):
    assert len(metricas.filtrar(fato, mps=[], oficinas=[])) == len(fato)


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def test_totais_do_periodo(fato):
    atual = metricas.filtrar(fato, date(2026, 7, 1), date(2026, 7, 31))
    m = metricas.calcular_metricas(atual, atual.iloc[0:0])
    assert m.total_pecas == 300
    assert m.total_minutos == 3000
    assert m.oficinas == 2


def test_media_diaria_divide_pelos_dias_com_movimento(fato):
    """Julho tem 31 dias, mas só 2 com lançamento: 300 / 2 = 150."""
    atual = metricas.filtrar(fato, date(2026, 7, 1), date(2026, 7, 31))
    m = metricas.calcular_metricas(atual, atual.iloc[0:0])
    assert m.medias["dia_pecas"].atual == 150


def test_media_semanal_usa_semanas_com_movimento(fato):
    atual = metricas.filtrar(fato, date(2026, 7, 1), date(2026, 7, 31))
    m = metricas.calcular_metricas(atual, atual.iloc[0:0])
    assert m.medias["semana_pecas"].atual == 150  # 300 em 2 semanas distintas


def test_variacao_percentual_entre_atual_e_anterior(fato):
    atual = metricas.filtrar(fato, date(2026, 7, 1), date(2026, 7, 31))
    anterior = metricas.filtrar(fato, date(2026, 6, 1), date(2026, 6, 30))
    m = metricas.calcular_metricas(atual, anterior)
    # mensal: 300 em julho contra 100 em junho -> +200%
    assert m.medias["mes_pecas"].variacao == pytest.approx(200.0)


def test_variacao_e_none_sem_base_anterior(fato):
    m = metricas.calcular_metricas(fato, fato.iloc[0:0])
    assert m.medias["mes_pecas"].variacao is None


# --------------------------------------------------------------------------- #
# Agregações
# --------------------------------------------------------------------------- #
def test_por_oficina_ordena_pelo_maior(fato):
    agg = metricas.por_oficina(fato)
    assert agg.loc[0, "oficina"] == "A"
    assert agg.loc[0, "qtd_pecas"] == 340


def test_por_oficina_respeita_o_limite(fato):
    assert len(metricas.por_oficina(fato, limite=1)) == 1


def test_por_mp_agrupa_a_granularidade(fato):
    agg = metricas.por_mp(fato).set_index("mp")
    assert agg.loc["MALHA", "qtd_pecas"] == 240
    assert agg.loc["JEANS", "qtd_pecas"] == 160


def test_por_dia_soma_lancamentos_do_mesmo_dia(fato):
    agg = metricas.por_dia(fato).set_index("data")
    assert agg.loc[date(2026, 7, 6), "qtd_pecas"] == 100


def test_por_semana_usa_os_recortes_do_mes(fato):
    semanas = metricas.semanas_do_mes(2026, 7)
    agg = metricas.por_semana(fato, semanas).set_index("semana")
    assert len(agg) == len(semanas)
    assert agg.loc["S2", "qtd_pecas"] == 100   # 06/07
    assert agg.loc["S3", "qtd_pecas"] == 200   # 15/07
    assert agg.loc["S1", "qtd_pecas"] == 0


def test_agregacoes_com_base_vazia_nao_quebram():
    vazio = pd.DataFrame(columns=["oficina", "data", "mp", "qtd_pecas", "minutos", "om"])
    assert metricas.por_oficina(vazio).empty
    assert metricas.por_mp(vazio).empty
    assert metricas.por_dia(vazio).empty


# --------------------------------------------------------------------------- #
# Acompanhamento — o que há para receber
# --------------------------------------------------------------------------- #
@pytest.fixture
def em_aberto() -> pd.DataFrame:
    """4 ordens em aberto cobrindo os 4 status de prazo, medidas em 18/07/2026."""
    return pd.DataFrame({
        "oficina": ["Oficina A", "Oficina A", "Oficina B", "Oficina C"],
        "data": pd.to_datetime(["2026-05-10", "2026-07-10", "2026-07-15", "2026-07-01"]),
        "mp": ["JEANS", "MALHA", "JEANS", "MALHA"],
        "qtd_pecas": [100.0, 200.0, 300.0, 400.0],
        "minutos": [1000.0, 2000.0, 3000.0, 4000.0],
        "om": [1, 2, 3, 4],
        "deadline": pd.to_datetime(["2026-07-06", "2026-07-20", "2026-08-30", None]),
    })


HOJE = date(2026, 7, 18)


def test_classificar_prazo_cobre_os_quatro_status(em_aberto):
    st = metricas.classificar_prazo(em_aberto, hoje=HOJE)["status"].tolist()
    assert st == [config.STATUS_ATRASADO, config.STATUS_VENCE_BREVE,
                  config.STATUS_NO_PRAZO, config.STATUS_SEM_PRAZO]


def test_dias_prazo_negativo_quando_venceu(em_aberto):
    cls = metricas.classificar_prazo(em_aberto, hoje=HOJE)
    assert cls.loc[0, "dias_prazo"] == -12      # prazo 06/07, hoje 18/07
    assert cls.loc[2, "dias_prazo"] == 43       # prazo 30/08


def test_dias_aberto_conta_desde_o_envio(em_aberto):
    cls = metricas.classificar_prazo(em_aberto, hoje=HOJE)
    assert cls.loc[0, "dias_aberto"] == 69      # enviado em 10/05


def test_ordem_sem_prazo_nao_vira_atraso(em_aberto):
    """Prazo em branco é falha de cadastro — cobrar a oficina por isso seria injusto."""
    cls = metricas.classificar_prazo(em_aberto, hoje=HOJE)
    assert cls.loc[3, "status"] == config.STATUS_SEM_PRAZO


def test_resumo_a_receber_soma_o_saldo(em_aberto):
    r = metricas.resumo_a_receber(metricas.classificar_prazo(em_aberto, hoje=HOJE))
    assert r.ordens == 4
    assert r.pecas == 1000.0
    assert r.minutos == 10000.0
    assert r.oficinas == 3
    assert r.por_status[config.STATUS_ATRASADO]["ordens"] == 1
    assert r.por_status[config.STATUS_ATRASADO]["pecas"] == 100.0


def test_resumo_aponta_a_espera_mais_longa_e_o_maior_atraso(em_aberto):
    r = metricas.resumo_a_receber(metricas.classificar_prazo(em_aberto, hoje=HOJE))
    assert r.espera_mais_longa.oficina == "Oficina A"
    assert r.espera_mais_longa.dias == 69
    assert r.maior_atraso.oficina == "Oficina A"
    assert r.maior_atraso.dias == 12


def test_por_oficina_a_receber_poe_atrasadas_no_topo(em_aberto):
    agg = metricas.por_oficina_a_receber(
        metricas.classificar_prazo(em_aberto, hoje=HOJE))
    assert agg.loc[0, "oficina"] == "Oficina A"
    assert agg.loc[0, "atrasadas"] == 1
    assert agg.loc[0, "ordens"] == 2
    assert agg.loc[0, "qtd_pecas"] == 300.0


def test_acompanhamento_com_base_vazia_nao_quebra():
    vazio = pd.DataFrame(columns=["oficina", "data", "mp", "qtd_pecas",
                                  "minutos", "om", "deadline"])
    cls = metricas.classificar_prazo(vazio)
    assert cls.empty
    r = metricas.resumo_a_receber(cls)
    assert r.ordens == 0
    assert r.espera_mais_longa.oficina == "—"
    assert metricas.por_oficina_a_receber(cls).empty
