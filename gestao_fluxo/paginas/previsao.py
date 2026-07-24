"""Aba de Previsão — o que está agendado para voltar das oficinas.

Cada linha da base é uma ordem que já saiu e tem data PREVISTA de recebimento.
Por isso o período desta aba é filtrado pela data de recebimento, e não pela de
envio como nas outras: a pergunta aqui é "o que temos para receber nesta
semana", não "o que despachamos".

Como no Acompanhamento, não há média nem variação: previsão não tem período
anterior com que se comparar. O que a tela mede é volume, distribuição e risco.
"""
from __future__ import annotations

import streamlit as st

from gestao_fluxo import charts, config, metricas, ui

from . import comum


# =========================================================================== #
# FILTROS
# =========================================================================== #
def _filtros(df) -> tuple | None:
    """(inicio, fim, mps, semanas, rotulo) — recorte sobre a data prevista.

    O padrão é `PERIODO_TODO` e não o mês mais recente: a previsão atravessa a
    virada do mês, e abrir a tela já recortada esconderia justamente o que ainda
    vai voltar no mês seguinte — o oposto do que o gestor abre esta aba para ver.

    O seletor de semana só liga depois de escolhido um mês: "Semana 3" não
    significa nada sem ele.
    """
    meses = metricas.meses_disponiveis(df)
    if not meses:
        return None

    col_mes, col_sem, col_mp = st.columns([1.3, 1.8, 1.6])
    escolha = col_mes.selectbox(
        "Mês do recebimento", [comum.PERIODO_TODO] + meses, key="mes_previsao",
        format_func=lambda m: (m if m == comum.PERIODO_TODO
                               else metricas.rotulo_mes(*m)),
    )
    # A MP é lida da base inteira, não do recorte: uma MP que só aparece em agosto
    # precisa continuar escolhível enquanto o filtro está em julho, senão a opção
    # some da lista no exato momento em que o operador iria usá-la.
    mps = col_mp.multiselect("Matéria-prima (MP)",
                             sorted(df["mp"].dropna().unique()), key="mp_previsao")

    if escolha == comum.PERIODO_TODO:
        comum.seletor_semana_desligado(col_sem, "Semana", "sem_previsao_off")
        return None, None, mps, _grade_de_todo_periodo(df, meses), comum.PERIODO_TODO

    ano, mes = escolha
    semanas = metricas.semanas_do_mes(ano, mes)
    sem = col_sem.selectbox("Semana", comum.opcoes_de_semana(semanas),
                            key="sem_previsao")
    inicio, fim, rotulo = comum.resolver_semana(sem, semanas, ano, mes)
    return inicio, fim, mps, semanas, rotulo


def _grade_de_todo_periodo(df, meses: list) -> list:
    """Semanas de todos os meses da base, em ordem, tocando o período com dados.

    Sem este recorte metade das barras nasceria zerada só porque um mês entra em
    `meses` por causa de um único dia de recebimento e tem cinco semanas: o
    gráfico ficaria dizendo "não temos nada a receber" em faixas que simplesmente
    estão fora da janela da planilha.

    No recorte por mês a regra é a oposta e igualmente deliberada: ali a grade é
    o mês inteiro, porque a leitura é a comparação entre as semanas dele.
    """
    datas = df["data"].dropna()
    if datas.empty:
        return []
    primeira, ultima = datas.min().date(), datas.max().date()
    return [s for ano, mes in sorted(meses)
            for s in metricas.semanas_do_mes(ano, mes)
            if s.inicio <= ultima and s.fim >= primeira]


# =========================================================================== #
# CARDS
# =========================================================================== #
def _cards_previsao(r: metricas.ResumoPrevisao, rotulo: str) -> None:
    ui.grade_cards([
        {"label": "Total de ordens", "valor": ui.fmt_int(r.ordens),
         "sub": f"{ui.fmt_int(r.oficinas)} oficina(s) · {rotulo}",
         "accent": ui.ACENTOS["teal"]},
        {"label": "Total de peças", "valor": ui.fmt_int(r.pecas),
         "sub": f"previstas para receber · {rotulo}",
         "accent": ui.ACENTOS["emerald"]},
        {"label": "Total de minutos", "valor": ui.fmt_int(r.minutos),
         "sub": f"previstos para receber · {rotulo}", "accent": ui.ACENTOS["sky"]},
    ])


def _cards_risco(r: metricas.ResumoPrevisao) -> None:
    """As duas leituras de risco, em cards separados — ver config.STATUS_PREV_*.

    Uma ordem pode estar nas duas ao mesmo tempo (prazo já vencido *e* previsão
    posterior ao prazo), então os dois números não se somam: cada card responde
    uma pergunta diferente, e juntá-los daria um total maior que a quantidade de
    ordens.
    """
    ui.grade_cards([
        {"label": config.STATUS_PREV_FURA_PRAZO, "valor": ui.fmt_int(r.fura_prazo),
         "sub": f"{ui.fmt_int(r.pecas_fura_prazo)} peça(s) — recebimento previsto "
                f"depois do deadline", "accent": ui.ACENTOS["amber"]},
        {"label": config.STATUS_PREV_VENCIDA, "valor": ui.fmt_int(r.vencidas),
         "sub": f"{ui.fmt_int(r.pecas_vencidas)} peça(s) — deadline já passou e a "
                f"ordem não voltou", "accent": ui.ACENTOS["rose"]},
    ])


# =========================================================================== #
# TABELAS
# =========================================================================== #
_COLUNAS_CONSOL_MP = {"mp": "MP", "qtd_pecas": "Qtd", "minutos": "Minutos",
                      "ordens": "Total de ordens"}
_FORMATO_CONSOL_MP = {"qtd_pecas": ui.fmt_int, "minutos": ui.fmt_int,
                      "ordens": ui.fmt_int}

_COLUNAS_PREVISAO = {
    "om": "Ordem mestre", "oficina": "Oficina", "envio": "Envio",
    "deadline": "Deadline", "qtd_pecas": "Peças", "minutos": "Minutos",
    "data": "Recebimento", "mp": "MP",
}
_FORMATO_PREVISAO = {
    "om": ui.fmt_om, "envio": ui.fmt_data, "deadline": ui.fmt_data,
    "qtd_pecas": ui.fmt_int, "minutos": ui.fmt_int, "data": ui.fmt_data,
}


def _tabela_consolidado_mp(df) -> None:
    """O consolidado por MP em números, ao lado do gráfico que mostra a forma."""
    consolidado = metricas.consolidado_por_mp(df)
    ui.tabela_verde(
        consolidado, _COLUNAS_CONSOL_MP, formato=_FORMATO_CONSOL_MP,
        col_oficina="mp", col_num=tuple(_FORMATO_CONSOL_MP),
        vazio="Nenhuma MP prevista no filtro atual.",
    )
    ui.botao_excel(
        consolidado, _COLUNAS_CONSOL_MP, "previsao_mp",
        titulo="Previsão consolidada por MP",
        rotulo="Baixar consolidado por MP em Excel",
        subtitulo="Peças, minutos e ordens previstas por matéria-prima",
        somar=("qtd_pecas", "minutos", "ordens"),
    )


def _tabela_previsao(df) -> None:
    """Detalhe da previsão, do recebimento mais próximo para o mais distante."""
    detalhe = df.sort_values(["data", "deadline"], na_position="last")
    ui.tabela_paginada(
        detalhe, _COLUNAS_PREVISAO, "previsao", formato=_FORMATO_PREVISAO,
        col_oficina="oficina", col_num=("om", "qtd_pecas", "minutos"),
        vazio="Nenhuma ordem prevista no filtro atual.",
    )
    ui.botao_excel(
        detalhe, _COLUNAS_PREVISAO, "previsao", titulo="Previsão de recebimento",
        rotulo="Baixar previsão em Excel",
        subtitulo="Ordens previstas — recebimento mais próximo primeiro",
        somar=("qtd_pecas", "minutos"),
    )


# =========================================================================== #
# ENTRADA
# =========================================================================== #
def renderizar() -> None:
    df = comum.carregar_fato(
        "previsao",
        vazio="A tabela de Previsão está vazia. Suba a planilha PREVISAO.xlsx "
              "em **Dados**, no canto superior direito.")
    if df is None:
        return

    filtros = _filtros(df)
    if filtros is None:
        st.warning("Nenhuma data de recebimento válida nesta base — não há período "
                   "para filtrar.")
        return
    inicio, fim, mps, semanas, rotulo = filtros

    # Um único recorte alimenta cards, gráficos e tabela: é o que garante que os
    # três nunca divirjam entre si por construção, e não por disciplina.
    atual = metricas.classificar_previsao(metricas.filtrar(df, inicio, fim, mps))
    r = metricas.resumo_previsao(atual)

    ui.titulo_secao(f"Visão geral — {rotulo}")
    _cards_previsao(r, rotulo)

    ui.titulo_secao("Risco de prazo")
    _cards_risco(r)
    if r.sem_prazo:
        st.caption(
            f"{ui.fmt_int(r.sem_prazo)} ordem(ns) sem deadline cadastrado não entram "
            "em nenhum dos dois riscos — a ausência do dado é problema de cadastro, "
            "e contá-la como atraso inventaria um número que não dá para conferir "
            "na planilha."
        )

    with comum.bloco("Distribuição por MP"):
        ui.titulo_secao("Distribuição por matéria-prima (MP)")
        charts.renderizar(charts.barras_por_mp(metricas.por_mp(atual)), altura=340)

    with comum.bloco("Consolidado por MP"):
        ui.titulo_secao(f"Consolidado por matéria-prima (MP) — {rotulo}")
        _tabela_consolidado_mp(atual)

    with comum.bloco("Distribuição por semana"):
        ui.titulo_secao("Distribuição por semana")
        # A visão semanal cobre a grade inteira de propósito (o mês todo, ou todos
        # os meses em "Todo o período"): é a comparação *entre* semanas, mesmo
        # quando o recorte atual é uma semana só. Mesma decisão das abas de análise.
        grade = (metricas.filtrar(df, semanas[0].inicio, semanas[-1].fim, mps)
                 if semanas else atual)
        charts.renderizar(
            charts.barras_por_semana(metricas.por_semana(grade, semanas)), altura=340)

    with comum.bloco("Distribuição por dia"):
        ui.titulo_secao("Distribuição por dia")
        charts.renderizar(charts.barras_por_dia(metricas.por_dia(atual)), altura=340)

    with comum.bloco("Ordens previstas"):
        ui.titulo_secao(f"Ordens previstas — {rotulo}")
        _tabela_previsao(atual)
