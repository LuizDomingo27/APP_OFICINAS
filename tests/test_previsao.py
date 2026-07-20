"""Testes da base de Previsão — a agenda do que ainda vai voltar das oficinas.

Duas garantias centrais aqui:

1. O ETL leva a planilha ao banco **sem alterar totais**, com `data` apontando para
   RECEBIMENTO (e não para ENVIO, como nas outras fontes).
2. As duas leituras de risco são independentes e nenhuma delas inventa atraso a
   partir de prazo ausente — ver `config.STATUS_PREV_*`.

Todo teste de risco passa `hoje` explicitamente. Deixar a data do relógio decidir
tornaria a suíte verde hoje e vermelha em novembro, que é o pior tipo de teste.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gestao_fluxo import config, etl, metricas
from gestao_fluxo.db import database
from gestao_fluxo.exceptions import FonteDeDadosError

HOJE = date(2026, 7, 19)


def _fato(linhas: list) -> pd.DataFrame:
    """Monta um fato de previsão já no formato que `carregar_fato` devolveria."""
    df = pd.DataFrame(
        linhas,
        columns=["om", "oficina", "data", "mp", "qtd_pecas", "minutos",
                 "deadline", "envio"],
    )
    for coluna in ("data", "deadline", "envio"):
        df[coluna] = pd.to_datetime(df[coluna], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# Extração e carga
# --------------------------------------------------------------------------- #
def test_extrai_os_campos_da_previsao(planilhas):
    df = etl.extrair_fonte("previsao", planilhas["previsao"])
    assert list(df.columns) == config.campos_da_fonte("previsao")


def test_data_da_previsao_e_o_recebimento_e_nao_o_envio(planilhas):
    """O evento desta base é o retorno previsto — é ele que vai para `data`."""
    df = etl.extrair_fonte("previsao", planilhas["previsao"])
    assert df["data"].tolist() == ["2026-07-20", "2026-07-25", "2026-08-03"]
    assert df["envio"].tolist() == ["2026-07-06", "2026-07-06", "2026-07-08"]


def test_prazo_ausente_vira_none_e_nao_texto(planilhas):
    """`None` e não a string 'nan': o banco precisa gravar NULL de verdade."""
    df = etl.extrair_fonte("previsao", planilhas["previsao"])
    assert df["deadline"].iloc[2] is None


def test_totais_da_previsao_batem_com_a_planilha(engine, planilhas, de_para):
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    origem = pd.read_excel(planilhas["previsao"])
    no_banco = database.read_sql(
        "SELECT COUNT(*) AS n, SUM(qtd_pecas) AS pecas, SUM(minutos) AS minutos "
        "FROM fato_previsao", engine)
    assert no_banco.loc[0, "n"] == len(origem)
    assert no_banco.loc[0, "pecas"] == pytest.approx(origem["QTD"].sum())
    assert no_banco.loc[0, "minutos"] == pytest.approx(origem["MINUTOS"].sum())


def test_previsao_e_substituida_e_nao_acumulada(engine, planilhas, de_para, tmp_path):
    """Ordem que voltou some da planilha e precisa sumir da previsão.

    A previsão é um retrato do que está agendado *agora*. Acumulando, uma ordem já
    recebida ficaria para sempre na agenda e o card de risco nunca zeraria.
    """
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    assert database.read_sql(
        "SELECT COUNT(*) AS n FROM fato_previsao", engine).loc[0, "n"] == 3

    restante = pd.read_excel(planilhas["previsao"]).iloc[[0]]
    caminho = tmp_path / "previsao_dia2.xlsx"
    restante.to_excel(caminho, index=False)

    etl.executar_etl(engine, caminhos={"previsao": caminho}, de_para_path=de_para)
    ordens = database.read_sql("SELECT om FROM fato_previsao", engine)
    assert list(ordens["om"]) == [1]


def test_carregar_fato_devolve_as_datas_como_datetime(engine, planilhas, de_para):
    """Sem isso a comparação de prazo faria texto contra Timestamp e explodiria."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    df = metricas.carregar_fato(engine, "previsao")
    for coluna in ("data", "deadline", "envio"):
        assert pd.api.types.is_datetime64_any_dtype(df[coluna]), coluna


def test_coluna_de_recebimento_ausente_gera_erro_amigavel(tmp_path):
    caminho = tmp_path / "sem_recebimento.xlsx"
    pd.DataFrame({
        "ORDEM MESTRE": [1], "OFICINA": ["A"], "ENVIO": ["2026-07-06"],
        "QTD": [10], "MINUTOS": [100.0], "DEAD LINE": ["2026-08-01"], "MP": ["JEANS"],
    }).to_excel(caminho, index=False)
    with pytest.raises(FonteDeDadosError) as exc:
        etl.extrair_fonte("previsao", caminho)
    assert "RECEBIMENTO" in exc.value.mensagem_usuario


# --------------------------------------------------------------------------- #
# Classificação de risco
# --------------------------------------------------------------------------- #
def test_previsao_depois_do_prazo_e_marcada_como_fura_prazo():
    df = _fato([(1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-07-10", "2026-07-06")])
    out = metricas.classificar_previsao(df, hoje=HOJE)
    assert bool(out["fura_prazo"].iloc[0])
    assert out["atraso_previsto"].iloc[0] == 15


def test_previsao_dentro_do_prazo_nao_fura():
    df = _fato([(1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06")])
    out = metricas.classificar_previsao(df, hoje=HOJE)
    assert not bool(out["fura_prazo"].iloc[0])
    assert out["atraso_previsto"].iloc[0] == -7


def test_prazo_ja_passado_marca_vencida():
    df = _fato([(1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-07-10", "2026-07-06")])
    out = metricas.classificar_previsao(df, hoje=HOJE)
    assert bool(out["vencida"].iloc[0])
    assert out["dias_prazo"].iloc[0] == -9


def test_prazo_no_futuro_nao_esta_vencido():
    df = _fato([(1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06")])
    out = metricas.classificar_previsao(df, hoje=HOJE)
    assert not bool(out["vencida"].iloc[0])


def test_ordem_sem_prazo_nao_entra_em_nenhum_risco():
    """Prazo ausente é falha de cadastro — virar atraso inventaria um número."""
    df = _fato([(1, "A", "2026-07-25", "JEANS", 100, 1000, None, "2026-07-06")])
    out = metricas.classificar_previsao(df, hoje=HOJE)
    assert not bool(out["fura_prazo"].iloc[0])
    assert not bool(out["vencida"].iloc[0])


def test_classificar_previsao_aceita_base_vazia():
    """A tela chama isto antes de saber se o filtro deixou alguma linha de pé."""
    out = metricas.classificar_previsao(_fato([]), hoje=HOJE)
    assert out.empty
    assert {"dias_prazo", "atraso_previsto", "fura_prazo", "vencida"} <= set(out.columns)


# --------------------------------------------------------------------------- #
# Resumo (os cards)
# --------------------------------------------------------------------------- #
def _base_mista() -> pd.DataFrame:
    """Uma ordem de cada tipo: no prazo, vencida, vencida E furando, sem prazo."""
    return _fato([
        (1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06"),
        (2, "B", "2026-07-22", "MALHA", 200, 2000, "2026-07-10", "2026-07-06"),
        (3, "B", "2026-07-30", "MALHA", 300, 3000, "2026-07-15", "2026-07-08"),
        (4, "C", "2026-08-03", "TEAR", 50, 500, None, "2026-07-08"),
    ])


def test_resumo_soma_os_totais_do_recorte():
    r = metricas.resumo_previsao(metricas.classificar_previsao(_base_mista(), hoje=HOJE))
    assert r.ordens == 4
    assert r.pecas == pytest.approx(650)
    assert r.minutos == pytest.approx(6500)
    assert r.oficinas == 3


def test_os_dois_riscos_sao_contados_separadamente():
    """A mesma ordem pode estar nos dois cards — eles não se somam."""
    r = metricas.resumo_previsao(metricas.classificar_previsao(_base_mista(), hoje=HOJE))
    assert r.fura_prazo == 2        # ordens 2 e 3: voltam depois do prazo
    assert r.vencidas == 2          # ordens 2 e 3: prazo já passou
    assert r.pecas_fura_prazo == pytest.approx(500)
    assert r.sem_prazo == 1         # ordem 4


def test_resumo_conta_ordens_distintas_e_nao_linhas():
    """Ordem quebrada em duas parcelas continua sendo uma ordem no card."""
    df = _fato([
        (1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06"),
        (1, "A", "2026-07-27", "JEANS", 40, 400, "2026-08-01", "2026-07-06"),
    ])
    r = metricas.resumo_previsao(metricas.classificar_previsao(df, hoje=HOJE))
    assert r.ordens == 1
    assert r.pecas == pytest.approx(140)


def test_linha_sem_ordem_cadastrada_ainda_conta_como_ordem():
    """Descartá-la sumiria com peças reais do total exibido."""
    df = _fato([
        (1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06"),
        (None, "B", "2026-07-26", "MALHA", 60, 600, "2026-08-01", "2026-07-06"),
    ])
    r = metricas.resumo_previsao(metricas.classificar_previsao(df, hoje=HOJE))
    assert r.ordens == 2


def test_resumo_de_base_vazia_devolve_zeros():
    r = metricas.resumo_previsao(metricas.classificar_previsao(_fato([]), hoje=HOJE))
    assert (r.ordens, r.pecas, r.minutos, r.fura_prazo, r.vencidas) == (0, 0.0, 0.0, 0, 0)


# --------------------------------------------------------------------------- #
# Filtros — tudo que a tela desenha sai do MESMO recorte
# --------------------------------------------------------------------------- #
def test_filtro_de_periodo_recorta_pela_data_de_recebimento():
    """A ordem 4 saiu em julho mas só volta em agosto: fica fora do recorte de julho."""
    recorte = metricas.filtrar(_base_mista(), date(2026, 7, 1), date(2026, 7, 31))
    assert recorte["om"].tolist() == [1, 2, 3]


def test_filtro_de_mp_alcanca_cards_e_graficos():
    """Cards e gráficos saem do mesmo DataFrame, então o filtro vale para os dois."""
    recorte = metricas.filtrar(_base_mista(), mps=["MALHA"])
    r = metricas.resumo_previsao(metricas.classificar_previsao(recorte, hoje=HOJE))
    assert r.ordens == 2
    assert r.pecas == pytest.approx(500)
    assert metricas.por_mp(recorte)["mp"].tolist() == ["MALHA"]


def test_consolidado_por_mp_soma_pecas_minutos_e_ordens():
    df = metricas.consolidado_por_mp(_base_mista())
    assert list(df.columns) == ["mp", "qtd_pecas", "minutos", "ordens"]
    # MALHA lidera em peças (500) e vem primeiro; JEANS e TEAR na sequência.
    assert df["mp"].tolist() == ["MALHA", "JEANS", "TEAR"]
    malha = df[df["mp"] == "MALHA"].iloc[0]
    assert malha["qtd_pecas"] == pytest.approx(500)
    assert malha["minutos"] == pytest.approx(5000)
    assert malha["ordens"] == 2


def test_consolidado_por_mp_respeita_o_filtro_de_periodo():
    """Filtrando a semana, o consolidado só enxerga o que cai nela."""
    semana = metricas.filtrar(_base_mista(), date(2026, 7, 20), date(2026, 7, 26))
    df = metricas.consolidado_por_mp(semana)
    assert df["mp"].tolist() == ["MALHA", "JEANS"]
    assert df["qtd_pecas"].sum() == pytest.approx(300)
    assert df["ordens"].sum() == 2


def test_consolidado_por_mp_conta_ordens_distintas_e_nao_linhas():
    """Ordem em duas parcelas da mesma MP continua sendo uma ordem."""
    df = _fato([
        (1, "A", "2026-07-25", "JEANS", 100, 1000, "2026-08-01", "2026-07-06"),
        (1, "A", "2026-07-27", "JEANS", 40, 400, "2026-08-01", "2026-07-06"),
        (None, "B", "2026-07-26", "JEANS", 60, 600, "2026-08-01", "2026-07-06"),
    ])
    linha = metricas.consolidado_por_mp(df).iloc[0]
    assert linha["ordens"] == 2      # a ordem 1 (duas parcelas) + a linha sem OM
    assert linha["qtd_pecas"] == pytest.approx(200)


def test_consolidado_por_mp_de_base_vazia_devolve_as_colunas():
    """A tela desenha o cabeçalho antes de saber se o filtro deixou algo de pé."""
    df = metricas.consolidado_por_mp(_fato([]))
    assert df.empty
    assert list(df.columns) == ["mp", "qtd_pecas", "minutos", "ordens"]


def test_agregacao_por_dia_usa_a_data_prevista():
    por_dia = metricas.por_dia(_base_mista())
    assert por_dia["data"].tolist() == [
        date(2026, 7, 22), date(2026, 7, 25), date(2026, 7, 30), date(2026, 8, 3)]


def test_agregacao_por_semana_respeita_a_grade_do_mes():
    semanas = metricas.semanas_do_mes(2026, 7)
    por_semana = metricas.por_semana(_base_mista(), semanas)
    assert len(por_semana) == len(semanas)
    # As semanas de julho somam só o que cai em julho — a ordem de agosto fica fora.
    assert por_semana["qtd_pecas"].sum() == pytest.approx(600)
