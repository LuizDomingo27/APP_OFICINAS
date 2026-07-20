"""Testes do ETL plano.

A garantia central que estes testes protegem: o ETL **não altera totais**. Se um
dia alguém reintroduzir dedup ou corte por ano, `test_totais_batem_com_a_origem`
quebra.
"""
from __future__ import annotations

import pandas as pd
import pytest

from gestao_fluxo import config, etl, metas
from gestao_fluxo.db import database
from gestao_fluxo.exceptions import FonteDeDadosError


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("entrada,esperado", [
    ("Malha", "MALHA"), ("  jeans ", "JEANS"), ("TEAR", "TEAR"),
    ("Sem MP Informada", config.MP_A_CLASSIFICAR),
    ("", config.MP_A_CLASSIFICAR), (None, config.MP_A_CLASSIFICAR),
])
def test_normalizar_mp(entrada, esperado):
    assert etl.normalizar_mp(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "0", "Não informado", "NAO INFORMADO", None])
def test_oficina_placeholder_vira_a_classificar(entrada):
    assert etl.normalizar_oficina(entrada) == config.OFICINA_A_CLASSIFICAR


def test_oficina_usa_o_de_para_ignorando_caixa_e_acento():
    canonicos = {"OFICINA A": "Oficina A"}
    assert etl.normalizar_oficina("oficina a", canonicos) == "Oficina A"


def test_oficina_fora_do_de_para_e_mantida():
    """Descartar um nome desconhecido esconderia produção real."""
    assert etl.normalizar_oficina("Oficina Nova", {"OFICINA A": "Oficina A"}) == "Oficina Nova"


def test_datas_invalidas_viram_none():
    resultado = etl.datas_para_iso(pd.Series(["2026-07-06", "não é data", None]))
    assert resultado.tolist() == ["2026-07-06", None, None]


# --------------------------------------------------------------------------- #
# Extração
# --------------------------------------------------------------------------- #
def test_extrair_devolve_apenas_os_seis_campos(planilhas):
    df = etl.extrair_fonte("recebimento", planilhas["recebimento"])
    assert list(df.columns) == config.CAMPOS_FATO


def test_extrair_nao_deduplica(planilhas):
    """ENVIOS tem duas linhas idênticas — as duas precisam sobreviver."""
    df = etl.extrair_fonte("envios", planilhas["envios"])
    assert len(df) == 3
    assert df["qtd_pecas"].sum() == 270


def test_extrair_mantem_datas_de_qualquer_ano(planilhas):
    """Junho/2026 continua na base: não há corte temporal escondido."""
    df = etl.extrair_fonte("recebimento", planilhas["recebimento"])
    assert "2026-06-10" in set(df["data"])


def test_coluna_ausente_gera_erro_amigavel(tmp_path):
    caminho = tmp_path / "quebrada.xlsx"
    pd.DataFrame({"DIA": ["2026-07-01"]}).to_excel(caminho, index=False)
    with pytest.raises(FonteDeDadosError) as exc:
        etl.extrair_fonte("recebimento", caminho)
    assert "OFICINA" in exc.value.mensagem_usuario


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
def test_totais_batem_com_a_origem(engine, planilhas, de_para):
    """Soma no banco == soma na planilha, para as 3 fontes."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    for fonte, caminho in planilhas.items():
        origem = pd.read_excel(caminho)
        coluna = config.FONTES[fonte]["colunas"]["qtd_pecas"]
        tabela = config.FONTES[fonte]["tabela"]
        no_banco = database.read_sql(
            f"SELECT COUNT(*) AS n, SUM(qtd_pecas) AS pecas FROM {tabela}", engine)
        assert no_banco.loc[0, "n"] == len(origem)
        assert no_banco.loc[0, "pecas"] == pytest.approx(origem[coluna].sum())


def test_relatorio_reflete_o_que_foi_gravado(engine, planilhas, de_para):
    rel = etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    assert rel.total_linhas == 2 + 4 + 3 + 3   # acomp + receb + envios + previsão
    envios = next(f for f in rel.fontes if f.rotulo == "Envios")
    assert envios.linhas == 3
    assert envios.total_pecas == pytest.approx(270)


def test_recarga_nao_duplica_linhas(engine, planilhas, de_para):
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    n = database.read_sql("SELECT COUNT(*) AS n FROM fato_envios", engine).loc[0, "n"]
    assert n == 3


def test_recarga_preserva_as_metas(engine, planilhas, de_para):
    """Recarregar planilha não pode apagar meta cadastrada pelo time."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    metas.salvar_metas(engine, {"mes_pecas": 10000})
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    assert metas.ler_metas(engine)["mes_pecas"] == 10000


# --------------------------------------------------------------------------- #
# Carga incremental
# --------------------------------------------------------------------------- #
def _contar(engine, tabela: str) -> int:
    return int(database.read_sql(
        f"SELECT COUNT(*) AS n FROM {tabela}", engine).loc[0, "n"])


def test_linhas_identicas_na_origem_sao_preservadas(engine, planilhas, de_para):
    """Duas linhas iguais na planilha são produção real, não duplicata.

    A fixture de envios traz a ORDEM 1 repetida de propósito. Descartá-la faria o
    total do banco divergir da soma da coluna no Excel.
    """
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    iguais = database.read_sql(
        "SELECT ocorrencia FROM fato_envios WHERE om = 1 ORDER BY ocorrencia", engine)
    assert list(iguais["ocorrencia"]) == [1, 2]


def test_carga_incremental_acrescenta_so_o_que_e_novo(engine, planilhas, de_para,
                                                      tmp_path):
    """A planilha do dia seguinte traz o histórico + linhas novas."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    antes = _contar(engine, "fato_envios")

    original = pd.read_excel(planilhas["envios"])
    nova = original.iloc[[0]].copy()
    nova["ORDEM"] = 777
    dia = pd.concat([original, nova], ignore_index=True)
    caminho = tmp_path / "envios_dia2.xlsx"
    dia.to_excel(caminho, index=False)

    rel = etl.executar_etl(engine, caminhos={"envios": caminho}, de_para_path=de_para)
    envios = next(f for f in rel.fontes if f.rotulo == "Envios")
    assert envios.linhas == len(dia)      # leu o arquivo inteiro
    assert envios.novas == 1              # gravou só a linha inédita
    assert envios.repetidas == len(original)
    assert _contar(engine, "fato_envios") == antes + 1


def test_subir_a_mesma_planilha_duas_vezes_nao_muda_nada(engine, planilhas, de_para):
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    total = database.read_sql(
        "SELECT COUNT(*) AS n, SUM(qtd_pecas) AS p FROM fato_recebimento", engine)
    rel = etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)

    receb = next(f for f in rel.fontes if f.rotulo == "Recebimento")
    assert receb.novas == 0
    depois = database.read_sql(
        "SELECT COUNT(*) AS n, SUM(qtd_pecas) AS p FROM fato_recebimento", engine)
    assert depois.loc[0, "n"] == total.loc[0, "n"]
    assert depois.loc[0, "p"] == pytest.approx(total.loc[0, "p"])


def test_carregar_uma_fonte_nao_exige_as_outras(engine, planilhas, de_para):
    """Subir só o Recebimento do dia não pode zerar Envios nem Acompanhamento."""
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    envios_antes = _contar(engine, "fato_envios")

    rel = etl.executar_etl(engine, caminhos={"recebimento": planilhas["recebimento"]},
                           de_para_path=de_para)
    assert [f.rotulo for f in rel.fontes] == ["Recebimento"]
    assert _contar(engine, "fato_envios") == envios_antes


def test_acompanhamento_e_substituido_e_nao_acumulado(engine, planilhas, de_para,
                                                      tmp_path):
    """Ordem recebida some da planilha e precisa sumir da lista de pendências.

    Acompanhamento é um retrato do que está em aberto agora. Se a carga apenas
    acrescentasse, ordens já concluídas ficariam para sempre como pendentes.
    """
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    assert _contar(engine, "fato_acompanhamento") == 2

    restante = pd.read_excel(planilhas["acompanhamento"]).iloc[[0]]
    caminho = tmp_path / "acomp_dia2.xlsx"
    restante.to_excel(caminho, index=False)

    etl.executar_etl(engine, caminhos={"acompanhamento": caminho},
                     de_para_path=de_para)
    ordens = database.read_sql("SELECT om FROM fato_acompanhamento", engine)
    assert list(ordens["om"]) == [1]


def test_previa_nao_grava_nada(engine, planilhas, de_para):
    previa = etl.prever_carga(engine, caminhos=planilhas, de_para_path=de_para)
    assert _contar(engine, "fato_envios") == 0
    envios = next(p for p in previa if p.rotulo == "Envios")
    assert envios.linhas == 3 and envios.novas == 3

    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    depois = etl.prever_carga(engine, caminhos=planilhas, de_para_path=de_para)
    envios = next(p for p in depois if p.rotulo == "Envios")
    assert envios.novas == 0 and envios.repetidas == 3


def test_log_de_cargas_registra_cada_execucao(engine, planilhas, de_para):
    etl.executar_etl(engine, caminhos=planilhas, de_para_path=de_para)
    hist = database.historico_cargas(engine)
    assert set(hist["fonte"]) == set(config.FONTES)
    envios = hist[hist["fonte"] == "envios"].iloc[0]
    assert envios["linhas_lidas"] == 3
    assert envios["linhas_novas"] == 3
    assert envios["modo"] == config.MODO_INCREMENTAL


# --------------------------------------------------------------------------- #
# Migração de banco anterior à carga incremental
# --------------------------------------------------------------------------- #
def test_migracao_preserva_os_dados_ja_carregados(tmp_path):
    """Banco antigo (sem hash_linha) não pode perder registro ao ser migrado.

    Recriar as tabelas do zero exigiria ter em mãos todas as planilhas históricas
    — exatamente o que a carga incremental dispensa.
    """
    caminho = tmp_path / "antigo.db"
    engine = database.get_engine(caminho)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE fato_envios (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "oficina TEXT NOT NULL, data TEXT, mp TEXT NOT NULL, "
            "qtd_pecas REAL, minutos REAL, om INTEGER)")
        conn.exec_driver_sql(
            "INSERT INTO fato_envios (oficina, data, mp, qtd_pecas, minutos, om) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [("OFICINA A", "2026-07-06", "JEANS", 100.0, 1000.0, 1),
             ("OFICINA A", "2026-07-06", "JEANS", 100.0, 1000.0, 1),   # gêmea
             ("OFICINA B", "2026-07-15", "TEAR", 70.0, 700.0, 2)],
        )

    database.init_schema(engine)

    gravadas = database.read_sql(
        "SELECT om, hash_linha, ocorrencia FROM fato_envios ORDER BY id", engine)
    assert len(gravadas) == 3
    assert gravadas["hash_linha"].notna().all()
    # As duas gêmeas sobrevivem, distinguidas pelo ordinal.
    assert list(gravadas[gravadas["om"] == 1]["ocorrencia"]) == [1, 2]


def test_migracao_e_idempotente(tmp_path):
    caminho = tmp_path / "repetida.db"
    engine = database.get_engine(caminho)
    database.init_schema(engine)
    assert database.migrar_schema(engine) == {}
    database.init_schema(engine)   # não pode estourar no CREATE INDEX


# --------------------------------------------------------------------------- #
# Correção do prazo (DEAD LINE vem com o ano anterior em parte das linhas)
# --------------------------------------------------------------------------- #
def test_corrigir_ano_deadline_puxa_o_ano_defasado_para_o_vigente():
    serie = pd.Series(["2025-08-18", "2026-08-18", None])
    corrigida = etl.corrigir_ano_deadline(serie, ano_vigente=2026)
    assert corrigida.iloc[0] == pd.Timestamp("2026-08-18")
    assert corrigida.iloc[1] == pd.Timestamp("2026-08-18")
    assert pd.isna(corrigida.iloc[2])


def test_corrigir_ano_deadline_preserva_dia_e_mes():
    corrigida = etl.corrigir_ano_deadline(pd.Series(["2025-02-03"]), ano_vigente=2026)
    assert corrigida.iloc[0] == pd.Timestamp("2026-02-03")


def test_corrigir_ano_deadline_nao_mexe_no_futuro():
    """Prazo que atravessa o ano é legítimo — puxá-lo para trás inventaria atraso."""
    corrigida = etl.corrigir_ano_deadline(pd.Series(["2027-01-10"]), ano_vigente=2026)
    assert corrigida.iloc[0] == pd.Timestamp("2027-01-10")


def test_corrigir_ano_deadline_lida_com_29_de_fevereiro():
    corrigida = etl.corrigir_ano_deadline(pd.Series(["2024-02-29"]), ano_vigente=2026)
    assert corrigida.iloc[0] == pd.Timestamp("2026-02-28")


def test_acompanhamento_grava_a_coluna_de_prazo(planilhas):
    df = etl.extrair_fonte("acompanhamento", planilhas["acompanhamento"])
    assert list(df.columns) == config.campos_da_fonte("acompanhamento")
    assert df["deadline"].tolist() == ["2026-08-01", "2026-08-01"]


def test_outras_fontes_nao_ganham_prazo(planilhas):
    df = etl.extrair_fonte("envios", planilhas["envios"])
    assert "deadline" not in df.columns
