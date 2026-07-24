"""Fixtures compartilhadas dos testes."""
from __future__ import annotations

import pandas as pd
import pytest

from gestao_fluxo.db import database


@pytest.fixture
def engine(tmp_path):
    """Engine SQLite em arquivo temporário (isolado por teste)."""
    return database.get_engine(tmp_path / "teste.db")


@pytest.fixture
def planilhas(tmp_path) -> dict:
    """Escreve 3 planilhas sintéticas em disco e devolve {fonte: caminho}.

    Julho/2026 tem movimento em 2 dias de semanas diferentes; junho existe para
    servir de período anterior nos testes de variação.
    """
    acomp = pd.DataFrame({
        "ORDEM MESTRE": [1, 2],
        "OFICINA": ["Oficina A", "oficina a"],   # mesma oficina, grafias diferentes
        "ENVIO": ["2026-07-06", "2026-07-15"],
        "QTD": [100, 200],
        "MINUTOS": [1000.0, 2000.0],
        "DEAD LINE": ["2026-08-01", "2026-08-01"],
        "MP": ["JEANS", "Malha"],
    })
    receb = pd.DataFrame({
        "DIA": ["2026-06-10", "2026-07-06", "2026-07-06", "2026-07-15"],
        "OFICINA": ["Oficina A", "Oficina A", "Oficina B", "Oficina B"],
        "ORDEM MESTRE": [9, 1, 1, 2],
        "MP": ["JEANS", "JEANS", "Malha", "Sem MP Informada"],
        "REAL CORTADO": [50, 60, 40, 30],
        "MINUTOS": [500.0, 600.0, 400.0, 300.0],
    })
    envios = pd.DataFrame({
        "ORIGEM": ["SAP"] * 3,
        "ORDEM": [1, 1, 2],                       # linha repetida de propósito
        "OFICINA": ["Oficina A", "Oficina A", "Não informado"],
        "QTD": [100, 100, 70],
        "MINUTOS": [1000.0, 1000.0, 700.0],
        "ENVIO": ["2026-07-06", "2026-07-06", "2026-07-15"],
        "MP": ["JEANS", "JEANS", "TEAR"],
        "PDV": ["N", "N", "N"],
        "FRETE": ["RA", "RA", "RA"],
        "SITUAÇÃO": ["Enviado", "Enviado", "Corte"],
    })
    # Previsão: agenda do retorno. As três linhas cobrem os três casos que a aba
    # precisa distinguir — dentro do prazo, prazo estourado e sem prazo cadastrado.
    previsao = pd.DataFrame({
        "ORDEM MESTRE": [1, 2, 3],
        "OFICINA": ["Oficina A", "Oficina B", "Oficina B"],
        "ENVIO": ["2026-07-06", "2026-07-06", "2026-07-08"],
        "QTD": [100, 200, 50],
        "MINUTOS": [1000.0, 2000.0, 500.0],
        # A 2ª estoura (volta depois do prazo); a 3ª não tem prazo cadastrado.
        "DEAD LINE": ["2026-08-01", "2026-07-10", None],
        "MP": ["JEANS", "Malha", "TEAR"],
        "RECEBIMENTO": ["2026-07-20", "2026-07-25", "2026-08-03"],
    })

    # Status: as mesmas ordens em aberto, com o estágio do fluxo em que pararam.
    # As quatro linhas cobrem o que a normalização precisa distinguir — grafia suja
    # do vocabulário conhecido, estágio fora do mapa e estágio em branco.
    status = pd.DataFrame({
        "ORDEM MESTRE": [1, 2, 3, 4],
        "OFICINA": ["Oficina A", "Oficina B", "Oficina B", "Oficina A"],
        "ENVIO": ["2026-07-06", "2026-07-06", "2026-07-08", "2026-07-09"],
        "QTD": [100, 200, 50, 40],
        "MINUTOS": [1000.0, 2000.0, 500.0, 400.0],
        "DEAD LINE": ["2026-08-01", "2026-07-10", None, "2026-08-05"],
        "SITUAÇÃO": ["Costura", "Costura", "Costura", "Costura"],
        "MP": ["JEANS", "Malha", "TEAR", "JEANS"],
        # 1ª e 2ª entram no mapa apesar da grafia; a 3ª é estágio novo (preservado
        # como veio); a 4ª chega em branco.
        "RECEBIMENTO": ["Coletando datas", "agua. reposicao", "Aguarda tecido", None],
    })

    caminhos = {}
    for fonte, df in (("acompanhamento", acomp), ("recebimento", receb),
                      ("envios", envios), ("previsao", previsao),
                      ("status", status)):
        destino = tmp_path / f"{fonte}.xlsx"
        df.to_excel(destino, index=False)
        caminhos[fonte] = destino
    return caminhos


@pytest.fixture
def de_para(tmp_path):
    caminho = tmp_path / "de_para.xlsx"
    pd.DataFrame({"Nome padrão (oficina)": ["Oficina A", "Oficina B"]}).to_excel(
        caminho, index=False)
    return caminho
