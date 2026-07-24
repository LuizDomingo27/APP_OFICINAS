"""Aba de Acompanhamento — o que já saiu para as oficinas e ainda não voltou.

Esta aba não repete a estrutura das de análise de propósito. Recebimento e
Envios são históricos: fazem sentido em médias, variação e evolução no tempo.
Acompanhamento é um saldo em aberto — média diária de um saldo não diz nada. O
que o time precisa é prazo, volume e há quanto tempo cada oficina está devendo.
Daí cards + tabelas, sem gráficos.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from gestao_fluxo import config, metas, metricas, servicos, ui
from gestao_fluxo.exceptions import GestaoFluxoError

from . import comum


# =========================================================================== #
# FILTROS
# =========================================================================== #
def _filtros(df):
    """Barra própria: aqui não se filtra por mês — o saldo em aberto é atemporal."""
    col1, col2, col3 = st.columns([1.4, 1.6, 1.4])
    mps = col1.multiselect("Matéria-prima (MP)", sorted(df["mp"].dropna().unique()),
                           key="mp_acomp")
    oficinas = col2.multiselect("Oficina", sorted(df["oficina"].dropna().unique()),
                                key="of_acomp")
    situacoes = col3.multiselect("Situação do prazo", list(config.STATUS_PRAZO),
                                 key="st_acomp")
    return mps, oficinas, situacoes


# =========================================================================== #
# CARDS
# =========================================================================== #
def _cards_a_receber(r: metricas.ResumoAReceber) -> None:
    ui.grade_cards([
        {"label": "Ordens em aberto", "valor": ui.fmt_int(r.ordens),
         "sub": "já enviadas, ainda não recebidas", "accent": ui.ACENTOS["teal"]},
        {"label": "Peças a receber", "valor": ui.fmt_int(r.pecas),
         "sub": "saldo do filtro atual", "accent": ui.ACENTOS["emerald"]},
        {"label": "Minutos a receber", "valor": ui.fmt_int(r.minutos),
         "sub": "saldo do filtro atual", "accent": ui.ACENTOS["sky"]},
        {"label": "Oficinas com pendência", "valor": ui.fmt_int(r.oficinas),
         "sub": "com ao menos uma ordem em aberto", "accent": ui.ACENTOS["amber"]},
    ])


def _cards_prazos(r: metricas.ResumoAReceber) -> None:
    ui.grade_cards([
        {"label": status, "valor": ui.fmt_int(dados["ordens"]),
         "sub": f"{ui.fmt_int(dados['pecas'])} peça(s)",
         "accent": comum.ACENTO_STATUS[status]}
        for status, dados in r.por_status.items()
    ])


def _cards_pendencias(r: metricas.ResumoAReceber) -> None:
    ui.grade_cards([
        {"label": "Espera mais longa",
         "valor": f"{ui.fmt_int(r.espera_mais_longa.dias)} dia(s)",
         "sub": r.espera_mais_longa.oficina, "accent": ui.ACENTOS["amber"]},
        {"label": "Maior atraso", "valor": f"{ui.fmt_int(r.maior_atraso.dias)} dia(s)",
         "sub": r.maior_atraso.oficina, "accent": ui.ACENTOS["rose"]},
    ])


# =========================================================================== #
# TABELA DE OFICINAS
# =========================================================================== #
_COLUNAS_OFICINAS = {
    "oficina": "Oficina", "ordens": "Ordens", "atrasadas": "Atrasadas",
    "qtd_pecas": "Peças", "minutos": "Minutos",
    "envio_mais_antigo": "Envio mais antigo", "dias_aberto": "Dias em aberto",
    "prazo_mais_proximo": "Prazo mais próximo",
}
_FORMATO_OFICINAS = {
    "ordens": ui.fmt_int, "atrasadas": ui.fmt_int, "qtd_pecas": ui.fmt_int,
    "minutos": ui.fmt_int, "envio_mais_antigo": ui.fmt_data,
    "dias_aberto": ui.fmt_int, "prazo_mais_proximo": ui.fmt_data,
}
_NUM_OFICINAS = ("ordens", "atrasadas", "qtd_pecas", "minutos", "dias_aberto")


def _tabela_oficinas_abertas(aberto) -> None:
    # A tabela e a planilha saem do MESMO `agg` cru: a tela formata na hora de
    # desenhar (só a página visível) e o Excel aplica o próprio formato, então os
    # números continuam números para somar e ordenar na planilha.
    agg = metricas.por_oficina_a_receber(aberto)
    ui.tabela_paginada(
        agg, _COLUNAS_OFICINAS, "acomp_oficinas", formato=_FORMATO_OFICINAS,
        col_oficina="oficina", col_num=_NUM_OFICINAS,
        vazio="Nenhuma oficina com ordem em aberto no filtro atual.",
    )
    ui.botao_excel(
        agg, _COLUNAS_OFICINAS, "acomp_oficinas",
        titulo="Oficinas com ordens em aberto",
        rotulo="Baixar oficinas em Excel",
        subtitulo="Acompanhamento — saldo a receber por oficina",
        somar=("ordens", "atrasadas", "qtd_pecas", "minutos"),
    )


# =========================================================================== #
# TABELA DE ORDENS
# =========================================================================== #
_COLUNAS_ORDENS = {
    "oficina": "Oficina", "om": "OM", "mp": "MP", "data": "Envio",
    "deadline": "Prazo", "status": "Situação", "dias_prazo": "Dias p/ o prazo",
    "qtd_pecas": "Peças", "minutos": "Minutos",
}
_FORMATO_ORDENS = {
    "om": ui.fmt_om, "data": ui.fmt_data, "deadline": ui.fmt_data,
    "status": ui.pill, "dias_prazo": ui.fmt_int, "qtd_pecas": ui.fmt_int,
    "minutos": ui.fmt_int,
}


def _tabela_ordens_abertas(aberto) -> None:
    # Pior caso primeiro: prazo mais estourado no topo, desempatado pela espera.
    detalhe = aberto.sort_values(["dias_prazo", "dias_aberto"],
                                 ascending=[True, False], na_position="last")
    ui.tabela_paginada(
        detalhe, _COLUNAS_ORDENS, "acomp_ordens", formato=_FORMATO_ORDENS,
        col_oficina="oficina", col_html=("status",),
        col_num=("om", "dias_prazo", "qtd_pecas", "minutos"),
        vazio="Nenhuma ordem em aberto no filtro atual.",
    )
    ui.botao_excel(
        detalhe, _COLUNAS_ORDENS, "acomp_ordens", titulo="Ordens em aberto",
        rotulo="Baixar ordens em Excel",
        subtitulo="Acompanhamento — pior prazo primeiro",
        somar=("qtd_pecas", "minutos"),
    )


# =========================================================================== #
# FLUXO POR MATÉRIA-PRIMA
# =========================================================================== #
_COLUNAS_FLUXO_MP = {
    "mp": "MP", "enviado_pecas": "Enviado (peças)",
    "recebido_pecas": "Recebido (peças)", "progresso_pecas": "Em progresso",
    "pct_concluido": "% concluído", "enviado_minutos": "Enviado (min)",
    "recebido_minutos": "Recebido (min)", "ordens_abertas": "Ordens abertas",
    "recebido_sem_envio": "Recebido sem envio",
}
_FORMATO_FLUXO_MP = {
    "enviado_pecas": ui.fmt_int, "recebido_pecas": ui.fmt_int,
    "progresso_pecas": ui.fmt_int, "pct_concluido": ui.fmt_pct,
    "enviado_minutos": ui.fmt_int, "recebido_minutos": ui.fmt_int,
    "ordens_abertas": ui.fmt_int, "recebido_sem_envio": ui.fmt_int,
}
_TITULO_FLUXO_MP = "Fluxo por matéria-prima — enviado x recebido"

_LEGENDA_FLUXO_MP = (
    "O recebimento é somado na **MP do envio** da mesma ordem: parte das ordens "
    "sai com uma MP e volta reclassificada, e agregar cada base pela sua própria "
    "MP criaria diferença negativa que não é produção. "
    "**'Recebido sem envio'** é o que voltou de ordens sem registro de envio — o "
    "histórico de Envios começa depois do de Recebimento, e é isso que explica um "
    "'em progresso' negativo. "
    "Estes números **não batem** com os cards de saldo acima: aqui é o acumulado "
    "de duas bases com janelas diferentes, lá é a lista de ordens que a origem "
    "declara em aberto hoje. "
    "O filtro ao lado do título recorta as duas bases pela **data do lançamento**; "
    "em 'Todo o período' o valor é o acumulado inteiro."
)


def _cards_fluxo_mp(t: metricas.TotaisFluxoMP) -> None:
    pct = "—" if t.pct_concluido is None else f"{t.pct_concluido:.1f}% concluído"
    ui.grade_cards([
        {"label": "Total enviado", "valor": ui.fmt_int(t.enviado),
         "sub": "peças despachadas às oficinas", "accent": ui.ACENTOS["sky"]},
        {"label": "Total recebido", "valor": ui.fmt_int(t.recebido),
         "sub": pct, "accent": ui.ACENTOS["emerald"]},
        {"label": "Em progresso", "valor": ui.fmt_int(t.progresso),
         "sub": "diferença entre enviado e recebido", "accent": ui.ACENTOS["amber"]},
    ])


def _filtros_periodo_fluxo(base) -> tuple:
    """Título e recorte de mês/semana na mesma linha. Devolve (inicio, fim).

    Só esta tabela da aba aceita período: o resto do Acompanhamento mede saldo em
    aberto, que é atemporal, mas aqui a fonte é o histórico de Envios e
    Recebimento. O padrão é `PERIODO_TODO` — sem recorte o número é o acumulado
    das duas bases, que é o que a legenda abaixo da tabela explica.
    """
    meses = metricas.meses_disponiveis(base)
    col_tit, col_mes, col_sem = st.columns([2.4, 1.1, 1.6],
                                           vertical_alignment="bottom")
    with col_tit:
        ui.titulo_secao(_TITULO_FLUXO_MP, inline=True)
    if not meses:
        return None, None

    escolha = comum.seletor_mes_opcional(col_mes, "mes_fluxo_mp", meses)
    if escolha == comum.PERIODO_TODO:
        comum.seletor_semana_desligado(col_sem, "Análise", "sem_fluxo_mp_off")
        return None, None

    ano, mes = escolha
    semanas = metricas.semanas_do_mes(ano, mes)
    sem = col_sem.selectbox("Análise", comum.opcoes_de_semana(semanas),
                            key="sem_fluxo_mp")
    if sem == comum.MES_INTEIRO:
        return metas.limites_do_mes(ano, mes)
    inicio, fim, _ = comum.resolver_semana(sem, semanas, ano, mes)
    return inicio, fim


def _tabela_fluxo_mp(mps: list, oficinas: list) -> None:
    """Enviado x recebido x em progresso, por matéria-prima.

    Lê Envios e Recebimento direto (não o Acompanhamento filtrado da aba): esta
    tabela mede o acumulado das duas bases, não o saldo declarado em aberto.
    """
    try:
        envios = servicos.fato("envios")
        recebimento = servicos.fato("recebimento")
        acomp = servicos.fato("acompanhamento")
    except GestaoFluxoError as exc:
        ui.titulo_secao(_TITULO_FLUXO_MP)
        st.error(exc.mensagem_usuario)
        return

    # Os meses ofertados saem das duas bases juntas: um mês que só tem
    # Recebimento continua escolhível, e é justamente ele que mostra o
    # "recebido sem envio" que a tabela existe para explicar.
    datas = pd.concat([envios[["data"]], recebimento[["data"]]], ignore_index=True)
    inicio, fim = _filtros_periodo_fluxo(datas)

    # Filtra por período e oficina nas três bases, mas NÃO por MP: a MP de uma
    # ordem pode mudar entre sair e voltar, então recortar cada base pela sua
    # própria MP deixaria de fora justamente o recebimento reclassificado que a
    # tabela existe para reconciliar. O recorte por MP é aplicado no resultado.
    # `envios_referencia` sai sem recorte de data de propósito: a ordem que saiu
    # num mês e voltou no seguinte tem envio, e sem isso ela cairia em "recebido
    # sem envio" só por causa do filtro. Ver `metricas.fluxo_por_mp`.
    agg = metricas.fluxo_por_mp(
        metricas.filtrar(envios, inicio, fim, oficinas=oficinas),
        metricas.filtrar(recebimento, inicio, fim, oficinas=oficinas),
        metricas.filtrar(acomp, inicio, fim, oficinas=oficinas),
        envios_referencia=metricas.filtrar(envios, oficinas=oficinas),
    )
    if mps:
        agg = agg[agg["mp"].isin(mps)].reset_index(drop=True)

    _cards_fluxo_mp(metricas.totais_fluxo_mp(agg))
    ui.tabela_paginada(
        agg, _COLUNAS_FLUXO_MP, "fluxo_mp", formato=_FORMATO_FLUXO_MP,
        col_num=tuple(_FORMATO_FLUXO_MP),
        vazio="Sem movimento de envio ou recebimento no filtro atual.",
    )
    st.caption(_LEGENDA_FLUXO_MP)
    ui.botao_excel(
        agg, _COLUNAS_FLUXO_MP, "fluxo_mp",
        titulo="Fluxo por matéria-prima",
        rotulo="Baixar fluxo por MP em Excel",
        subtitulo="Enviado x recebido x em progresso",
        somar=("enviado_pecas", "recebido_pecas", "progresso_pecas",
               "enviado_minutos", "recebido_minutos", "ordens_abertas",
               "recebido_sem_envio"),
    )


# =========================================================================== #
# ENTRADA
# =========================================================================== #
def renderizar() -> None:
    df = comum.carregar_fato(
        "acompanhamento",
        vazio="A tabela de Acompanhamento está vazia. Recarregue as planilhas.")
    if df is None:
        return

    mps, oficinas, situacoes = _filtros(df)
    aberto = metricas.classificar_prazo(
        metricas.filtrar(df, mps=mps, oficinas=oficinas))
    if situacoes:
        aberto = aberto[aberto["status"].isin(situacoes)]
    r = metricas.resumo_a_receber(aberto)

    ui.titulo_secao("Visão geral — a receber")
    _cards_a_receber(r)

    ui.titulo_secao("Situação dos prazos")
    _cards_prazos(r)
    st.caption(
        f"'Vence em breve' cobre os próximos {config.PRAZO_ALERTA_DIAS} dias. "
        "Os prazos são corrigidos na carga: a planilha exporta parte da coluna "
        "DEAD LINE com o ano anterior."
    )

    ui.titulo_secao("Pendências")
    _cards_pendencias(r)

    # O título desta seção sai de dentro de `_tabela_fluxo_mp`: ele divide a
    # linha com os seletores de mês e semana, que só existem aqui.
    with comum.bloco("Fluxo por matéria-prima"):
        _tabela_fluxo_mp(mps, oficinas)

    with comum.bloco("Oficinas com ordens em aberto"):
        ui.titulo_secao("Oficinas com ordens em aberto")
        _tabela_oficinas_abertas(aberto)

    with comum.bloco("Ordens em aberto"):
        ui.titulo_secao("Ordens em aberto — detalhe")
        _tabela_ordens_abertas(aberto)
