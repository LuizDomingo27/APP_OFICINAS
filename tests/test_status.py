"""Status — normalização do estágio, gravação do extra de texto e agregação.

O que estes testes protegem é a exceção que a fonte introduziu: até ela, TODO campo
extra era data em ISO e ETL e leitura os convertiam em bloco. `estagio` e `situacao`
são texto, e o risco real é uma mudança futura reintroduzir a conversão cega e
transformar o estágio em NaT sem ninguém notar — a tela só mostraria "Sem estágio".
"""
from __future__ import annotations

import pandas as pd
import pytest

from gestao_fluxo import config, etl, metricas


# =========================================================================== #
# NORMALIZAÇÃO DO ESTÁGIO
# =========================================================================== #
@pytest.mark.parametrize("bruto, esperado", [
    ("Coletando datas", "Coletando datas"),
    ("agua. reposicao", "Aguardando reposição"),   # sem acento e em minúsculas
    ("AGUA. CHAMADO", "Aguardando chamado"),
    ("devolução", "Devolução"),                    # a origem escreve em minúsculas
    ("  Ordem   extraviada ", "Ordem extraviada"),  # espaços colapsados
])
def test_estagio_conhecido_vira_o_rotulo_canonico(bruto, esperado):
    assert etl.normalizar_estagio(bruto) == esperado


def test_estagio_desconhecido_e_preservado():
    """Estágio novo na origem tem que aparecer na tela, não sumir num balde."""
    assert etl.normalizar_estagio("Aguarda tecido") == "Aguarda tecido"


@pytest.mark.parametrize("vazio", [None, "", "   ", float("nan")])
def test_estagio_ausente_vira_rotulo_proprio(vazio):
    assert etl.normalizar_estagio(vazio) == config.ESTAGIO_SEM_INFO


# =========================================================================== #
# EXTRAÇÃO
# =========================================================================== #
def test_status_grava_estagio_e_situacao_como_texto(planilhas):
    """O extra de texto não pode passar pela conversão de data dos outros extras."""
    df = etl.extrair_fonte("status", planilhas["status"])

    assert list(df.columns) == config.campos_da_fonte("status")
    assert df["estagio"].tolist() == [
        "Coletando datas", "Aguardando reposição", "Aguarda tecido",
        config.ESTAGIO_SEM_INFO,
    ]
    assert set(df["situacao"]) == {"Costura"}


def test_status_continua_convertendo_o_prazo_para_iso(planilhas):
    """Deadline segue sendo data: o tratamento de texto vale só para os extras dele."""
    df = etl.extrair_fonte("status", planilhas["status"])
    assert df["deadline"].tolist() == ["2026-08-01", "2026-07-10", None, "2026-08-05"]


def test_outras_fontes_nao_ganham_estagio(planilhas):
    df = etl.extrair_fonte("previsao", planilhas["previsao"])
    assert "estagio" not in df.columns


def test_extras_de_data_excluem_os_de_texto():
    assert config.extras_data_da_fonte("status") == ["deadline"]
    assert config.extras_data_da_fonte("previsao") == ["deadline", "envio"]


# =========================================================================== #
# CARGA E LEITURA
# =========================================================================== #
def test_carga_preserva_o_estagio_ate_a_leitura(engine, planilhas, de_para):
    """Ida e volta pelo banco: o estágio chega à tela como texto, não como data."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    df = metricas.carregar_fato(engine, "status")

    assert len(df) == 4
    assert df["estagio"].dtype == object
    assert set(df["estagio"]) == {
        "Coletando datas", "Aguardando reposição", "Aguarda tecido",
        config.ESTAGIO_SEM_INFO,
    }
    # O prazo, esse sim, volta como data — é o que `classificar_prazo` compara.
    assert pd.api.types.is_datetime64_any_dtype(df["deadline"])


def test_status_e_substituido_e_nao_acumulado(engine, planilhas, de_para):
    """Retrato do agora: recarregar troca a lista, não soma uma segunda cópia."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    assert len(metricas.carregar_fato(engine, "status")) == 4


# =========================================================================== #
# AGREGAÇÃO
# =========================================================================== #
def test_por_estagio_soma_pecas_minutos_e_ordens(engine, planilhas, de_para):
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    agg = metricas.por_estagio(metricas.carregar_fato(engine, "status"))

    assert list(agg.columns) == metricas.COLUNAS_POR_ESTAGIO
    # Ordenado por volume: "Aguardando reposição" (200 peças) vem primeiro.
    assert agg.iloc[0]["estagio"] == "Aguardando reposição"
    assert agg["qtd_pecas"].sum() == 390
    assert agg["minutos"].sum() == 3900
    assert agg["ordens"].sum() == 4


# =========================================================================== #
# COBERTURA DE PREVISÃO
# =========================================================================== #
def _carteira(oms_status: list, oms_previsao: list, pecas: list | None = None):
    """Duas bases mínimas de OMs — só o que `cobertura_previsao` olha."""
    status = pd.DataFrame({
        "om": pd.Series(oms_status, dtype="object"),
        "qtd_pecas": pecas if pecas is not None else [10.0] * len(oms_status),
    })
    previsao = pd.DataFrame({"om": pd.Series(oms_previsao, dtype="object")})
    return status, previsao


def test_cobertura_soma_as_duas_bases_como_carteira_inteira():
    c = metricas.cobertura_previsao(*_carteira([1, 2, 3], [4, 5, 6, 7]))

    assert c.sem_previsao == 3
    assert c.com_previsao == 4
    assert c.total == 7
    assert c.pct_coberto == pytest.approx(57.142857)
    assert c.pct_sem_previsao == pytest.approx(42.857142)
    assert c.pecas_sem_previsao == 30.0


def test_cobertura_conta_a_ordem_repetida_uma_vez_so():
    """A origem promete bases disjuntas; se falhar, a conta não pode inflar o total."""
    c = metricas.cobertura_previsao(*_carteira([1, 2, 3], [3, 4]))

    assert c.com_previsao == 2       # a ordem 3 conta do lado de quem tem previsão
    assert c.sem_previsao == 2       # e sai daqui
    assert c.total == 4              # e não 5
    assert c.pecas_sem_previsao == 20.0


def test_cobertura_sem_previsao_nenhuma_e_zero_por_cento():
    c = metricas.cobertura_previsao(*_carteira([1, 2], []))

    assert c.com_previsao == 0
    assert c.pct_coberto == 0.0
    assert c.pct_sem_previsao == 100.0


def test_cobertura_de_carteira_vazia_nao_divide_por_zero():
    c = metricas.cobertura_previsao(*_carteira([], []))

    assert c.total == 0
    assert c.pct_coberto is None
    assert c.pct_sem_previsao is None


def test_ordem_sem_om_cai_em_sem_previsao():
    """Não há como agendar o retorno de uma linha sem ordem cadastrada."""
    c = metricas.cobertura_previsao(*_carteira([1, None], [9]))

    assert c.sem_previsao == 2
    assert c.pecas_sem_previsao == 20.0


def test_cobertura_com_as_bases_reais_da_fixture(engine, planilhas, de_para):
    """Ida e volta pelo banco, com as duas fontes carregadas de verdade."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    c = metricas.cobertura_previsao(
        metricas.carregar_fato(engine, "status"),
        metricas.carregar_fato(engine, "previsao"),
    )

    # A fixture repete as ordens 1, 2 e 3 nas duas bases de propósito: é o cenário
    # que a regra da origem proíbe, e o que se prova aqui é que ele não infla nada.
    assert c.com_previsao == 3
    assert c.sem_previsao == 1       # só a ordem 4, que não está na previsão
    assert c.total == 4


def test_por_estagio_de_base_vazia_devolve_as_colunas(engine, planilhas, de_para):
    """A tela lê as colunas mesmo sem linha — sem isso o gráfico quebraria vazio."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    vazio = metricas.carregar_fato(engine, "status").iloc[0:0]
    assert list(metricas.por_estagio(vazio).columns) == metricas.COLUNAS_POR_ESTAGIO
