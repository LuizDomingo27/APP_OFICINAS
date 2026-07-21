"""Caminhos de falha — o app não pode quebrar na frente do operador.

Os demais testes cobrem o que acontece quando os dados estão certos. Estes
cobrem o contrário: origem suja, coluna faltando, disco sem permissão, valor de
tipo inesperado. A regra verificada aqui é sempre a mesma — a falha vira
mensagem tratada, nunca stack trace.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gestao_fluxo import excel, ui
from gestao_fluxo.db import database
from gestao_fluxo.exceptions import BancoDeDadosError, GestaoFluxoError, RelatorioError

COLUNAS = {"oficina": "Oficina", "qtd_pecas": "Peças"}


# =========================================================================== #
# PLANILHA DE DOWNLOAD
# =========================================================================== #
def test_caractere_de_controle_nao_derruba_a_planilha():
    """A origem exporta \\x01 no meio do nome; o openpyxl recusa esse byte.

    Antes o download morria com IllegalCharacterError e levava a tela junto.
    O caractere é removido e a planilha sai — o nome continua legível.
    """
    df = pd.DataFrame({"oficina": ["OFICINA\x01ABC"], "qtd_pecas": [10.0]})
    conteudo = excel.gerar_xlsx(df, COLUNAS, titulo="Teste")
    assert conteudo[:2] == b"PK"   # .xlsx é um zip


def test_coluna_ausente_vira_erro_de_dominio():
    """Pedir coluna inexistente é bug de chamada, mas mesmo assim tem que chegar
    à UI como `RelatorioError` (com mensagem pronta), não como KeyError cru."""
    df = pd.DataFrame({"oficina": ["A"], "qtd_pecas": [1.0]})
    with pytest.raises(RelatorioError) as capturado:
        excel.gerar_xlsx(df, {"inexistente": "X"}, titulo="Teste")
    assert capturado.value.mensagem_usuario
    assert isinstance(capturado.value, GestaoFluxoError)


def test_planilha_vazia_ainda_gera_arquivo():
    """Filtro sem resultado é rotina, não erro: o arquivo sai só com cabeçalho."""
    vazio = pd.DataFrame({"oficina": [], "qtd_pecas": []})
    assert excel.gerar_xlsx(vazio, COLUNAS, titulo="Vazio",
                            somar=("qtd_pecas",))[:2] == b"PK"


# =========================================================================== #
# BANCO
# =========================================================================== #
def test_pasta_sem_permissao_vira_erro_de_banco(tmp_path, monkeypatch):
    """Disco cheio / pasta somente leitura acontecem em máquina de chão de fábrica.

    Como é a primeira coisa que o app toca, escapar daqui significaria stack
    trace antes de existir qualquer tela.
    """
    def _recusar(*_args, **_kwargs):
        raise PermissionError("acesso negado")

    monkeypatch.setattr("pathlib.Path.mkdir", _recusar)
    with pytest.raises(BancoDeDadosError) as capturado:
        database.get_engine(tmp_path / "sub" / "fluxo.db")
    assert "permiss" in capturado.value.mensagem_usuario.lower()


def test_consulta_a_tabela_inexistente_vira_erro_de_banco(engine):
    with pytest.raises(BancoDeDadosError):
        database.read_sql("SELECT * FROM tabela_que_nao_existe", engine)


def test_tabela_existe_responde_sem_levantar(engine):
    """Usada no arranque para decidir entre o painel e a tela de carga inicial."""
    assert database.tabela_existe(engine, "fato_envios") is False


def test_tabelas_existentes_responde_em_uma_consulta(engine):
    """O arranque pergunta todas as tabelas de fato de uma vez (ver app._banco_pronto).

    Num banco recém-aberto nada existe: o retorno é conjunto vazio, sem levantar.
    Depois do schema cada fato aparece — e um nome inventado nunca entra no
    resultado, mesmo pedido junto com os reais.
    """
    pedidas = {"fato_envios", "fato_recebimento", "nao_existe"}
    assert database.tabelas_existentes(engine, pedidas) == set()

    database.init_schema(engine)
    assert database.tabelas_existentes(engine, pedidas) == {
        "fato_envios", "fato_recebimento"}


# =========================================================================== #
# FORMATADORES — chamados milhares de vezes por render
# =========================================================================== #
@pytest.mark.parametrize("valor", [None, float("nan"), pd.NA, pd.NaT])
def test_fmt_int_trata_ausente(valor):
    assert ui.fmt_int(valor) == "—"


@pytest.mark.parametrize("valor", ["texto", object(), [1, 2]])
def test_fmt_int_nao_levanta_com_tipo_estranho(valor):
    """Uma célula de tipo inesperado não pode derrubar a tabela inteira."""
    assert ui.fmt_int(valor) == "—"


def test_fmt_int_formata_padrao_brasileiro():
    assert ui.fmt_int(1234567) == "1.234.567"


@pytest.mark.parametrize("valor", [None, pd.NaT])
def test_fmt_data_trata_ausente(valor):
    assert ui.fmt_data(valor) == "—"


def test_fmt_data_formata_e_nao_levanta():
    assert ui.fmt_data(date(2026, 7, 15)) == "15/07/2026"
    # Valor impróprio devolve o texto cru: esconder num travessão faria o
    # problema de cadastro passar despercebido.
    assert ui.fmt_data("data quebrada") == "data quebrada"
