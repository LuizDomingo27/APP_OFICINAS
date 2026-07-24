"""Abas de análise — Recebimento e Envios sobre a mesma estrutura de tela.

As duas bases são históricos de fatos consumados, então fazem sentido em média,
variação e evolução no tempo. É a única página parametrizada por fonte: o que
muda entre Recebimento e Envios é a tabela lida e o rótulo, nada mais. Duplicar
a tela para cada uma faria as duas divergirem no primeiro ajuste que alguém
fizesse só de um lado.
"""
from __future__ import annotations

import streamlit as st

from gestao_fluxo import charts, config, metricas, ui

from . import comum

#: Acentos dos 4 cards de média, na ordem em que são montados.
ACENTOS_CICLO = ["teal", "emerald", "amber", "sky", "rose"]


def _cards_totais(m: metricas.Metricas, rotulo: str) -> None:
    ui.grade_cards([
        {"label": "Total de peças", "valor": ui.fmt_int(m.total_pecas),
         "sub": rotulo, "accent": ui.ACENTOS["emerald"]},
        {"label": "Total de minutos", "valor": ui.fmt_int(m.total_minutos),
         "sub": rotulo, "accent": ui.ACENTOS["teal"]},
        {"label": "Oficinas envolvidas", "valor": ui.fmt_int(m.oficinas),
         "sub": f"{ui.fmt_int(m.linhas)} lançamento(s)", "accent": ui.ACENTOS["sky"]},
    ])


def _cards_medias_periodo(medias: dict) -> None:
    """4 cards (diária e semanal × peças e minutos) do recorte que está na tela.

    Valor e delta respondem à mesma pergunta aqui — os dois saem do recorte
    filtrado —, ao contrário dos cards de referência logo abaixo.
    """
    cards = []
    for i, (unidade, nome) in enumerate(comum.UNIDADES):
        for j, (chave, titulo) in enumerate(
            (("dia", "Média diária"), ("semana", "Média semanal"))
        ):
            media = medias[f"{chave}_{unidade}"]
            cards.append({
                "label": f"{titulo} — {nome}",
                "valor": ui.fmt_int(media.atual),
                "sub": ui.delta_html(media.variacao, "vs. período anterior"),
                "accent": ui.ACENTOS[ACENTOS_CICLO[i * 2 + j]],
            })
    ui.grade_cards(cards)


def _cards_referencia_mensal(medias: dict, rotulo_mes: str) -> None:
    """2 cards de média mensal — o padrão da base, imune a todos os filtros.

    Ficam fora do bloco acima de propósito: média mensal do mês filtrado seria o
    próprio total do mês, que a visão geral já mostra. Aqui o valor é o padrão
    histórico e o delta diz o quanto o mês escolhido se afasta dele.
    """
    ui.grade_cards([
        {
            "label": f"Média mensal da base — {nome}",
            "valor": ui.fmt_int(medias[f"mes_{unidade}"].historica),
            "sub": ui.delta_html(medias[f"mes_{unidade}"].variacao,
                                 f"{rotulo_mes} vs. essa média"),
            "accent": ui.ACENTOS["violet"],
        }
        for unidade, nome in comum.UNIDADES
    ])


def _graficos_mp(atual) -> None:
    ui.titulo_secao("Granularidade por matéria-prima (MP)")
    mp = metricas.por_mp(atual)
    esq, dir_ = st.columns(2)
    with esq:
        charts.renderizar(charts.rosca_por_mp(mp, "qtd_pecas", "Peças por MP"),
                          altura=460)
    with dir_:
        charts.renderizar(charts.rosca_por_mp(mp, "minutos", "Minutos por MP"),
                          altura=460)


def _graficos_evolucao(df, atual, semanas, mps, oficinas) -> None:
    ui.titulo_secao("Evolução no período")
    # Uma série temporal por linha (largura cheia): com o eixo Y sem rótulos, o
    # que importa é a forma da curva, e ela só se lê bem com espaço horizontal.
    # A visão semanal cobre o mês inteiro de propósito: é a comparação entre as
    # semanas do mês filtrado, mesmo quando o recorte atual é uma semana só.
    mes_todo = metricas.filtrar(df, semanas[0].inicio, semanas[-1].fim, mps, oficinas)
    charts.renderizar(
        charts.linha_por_semana(metricas.por_semana(mes_todo, semanas)), altura=320)
    charts.renderizar(charts.linha_por_dia(metricas.por_dia(atual)), altura=320)


def renderizar(fonte: str) -> None:
    """Monta a aba de análise de uma fonte histórica (recebimento ou envios)."""
    spec = config.FONTES[fonte]
    df = comum.carregar_fato(
        fonte, vazio=f"A tabela de {spec['rotulo']} está vazia. "
                     "Recarregue as planilhas.")
    if df is None:
        return

    filtros = comum.barra_filtros(df, fonte)
    if filtros is None:
        st.warning("Nenhuma data válida nesta base — não há período para filtrar.")
        return
    inicio, fim, mps, oficinas, semanas, rotulo = filtros

    atual = metricas.filtrar(df, inicio, fim, mps, oficinas)
    m = metricas.calcular_metricas(atual)

    # Duas naturezas de média, dois blocos. As de período saem do recorte que está
    # na tela (inclusive MP e oficina) e comparam com o recorte equivalente do mês
    # anterior; a mensal sai de `df` cru e é referência fixa da base.
    ini_mes, fim_mes = semanas[0].inicio, semanas[-1].fim
    rotulo_mes = metricas.rotulo_mes(ini_mes.year, ini_mes.month)

    ui.titulo_secao(f"Visão geral — {rotulo}")
    _cards_totais(m, rotulo)

    with comum.bloco("Médias do período"):
        medias = metricas.calcular_medias_periodo(df, inicio, fim, mps, oficinas)
        ini_ant, fim_ant = metricas.periodo_anterior(inicio, fim)
        ui.titulo_secao(f"Médias do período — {rotulo}")
        _cards_medias_periodo(medias)
        st.caption(
            "Média do recorte filtrado (total ÷ períodos com movimento), acompanhando "
            "semana, MP e oficina. A variação compara "
            f"{ui.fmt_data(inicio)} — {ui.fmt_data(fim)} contra "
            f"{ui.fmt_data(ini_ant)} — {ui.fmt_data(fim_ant)}, com os mesmos filtros."
        )

    with comum.bloco("Referência da base"):
        referencia = metricas.calcular_media_mensal(df, ini_mes, fim_mes)
        ui.titulo_secao("Referência da base — todo o histórico")
        _cards_referencia_mensal(referencia, rotulo_mes)
        st.caption(
            "Média mensal de toda a base, imune aos filtros — é o parâmetro de "
            f"comparação. A variação mostra o quanto {rotulo_mes} ficou acima ou "
            "abaixo desse padrão."
        )

    with comum.bloco("Gráficos por MP"):
        _graficos_mp(atual)

    with comum.bloco("Evolução no período"):
        _graficos_evolucao(df, atual, semanas, mps, oficinas)

    with comum.bloco(f"Base de {spec['rotulo']}"):
        ui.titulo_secao(f"Base de {spec['rotulo']} — {rotulo}")
        ui.tabela_fato(atual.sort_values("data", ascending=False), fonte,
                       titulo=f"Base de {spec['rotulo']}", subtitulo=rotulo)
