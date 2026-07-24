"""Aba de Status — em que estágio do fluxo cada ordem SEM previsão de retorno parou.

A base não é o Acompanhamento inteiro: a origem exclui da planilha de STATUS toda
ordem que já tem data prevista de recebimento (confirmado pelo time). Ou seja,
Acompanhamento = Previsão + Status, sem interseção — o que esta tela lista é
exatamente o que ainda não conseguimos agendar para voltar.

O que a base acrescenta é a coluna RECEBIMENTO, que não é uma data e sim a **etapa**
em que a ordem está ("Coletando datas", "Ordem extraviada", "Aguardando reposição").
Por isso o campo se chama `estagio` — ver config.ESTAGIOS_CANONICOS.

Não há recorte por mês nem por semana aqui, ao contrário das abas de análise: a
pergunta é "onde está parado o que ainda não voltou", e ela vale para a lista
inteira. Filtrar por período esconderia justamente a ordem antiga que travou.
"""
from __future__ import annotations

import streamlit as st

from gestao_fluxo import charts, config, metricas, ui

from . import comum


# =========================================================================== #
# FILTROS
# =========================================================================== #
def _filtros(df) -> tuple:
    """(estagios, mps, oficinas) — o recorte da aba, sem filtro de período.

    As opções saem da base inteira e não do recorte já aplicado: um estágio que
    some da lista no instante em que o operador filtra outra coisa é um filtro que
    não dá para desfazer sem limpar tudo.
    """
    col_est, col_mp, col_of = st.columns([1.9, 1.4, 1.8])
    estagios = col_est.multiselect(
        "Estágio (coluna RECEBIMENTO)",
        sorted(df["estagio"].dropna().unique()), key="est_status")
    mps = col_mp.multiselect("Matéria-prima (MP)",
                             sorted(df["mp"].dropna().unique()), key="mp_status")
    oficinas = col_of.multiselect("Oficina",
                                  sorted(df["oficina"].dropna().unique()),
                                  key="of_status")
    return estagios, mps, oficinas


def _aplicar(df, estagios: list, mps: list, oficinas: list):
    """Recorte único que alimenta cards, gráfico e tabelas — nunca divergem."""
    recorte = metricas.filtrar(df, mps=mps, oficinas=oficinas)
    if estagios:
        recorte = recorte[recorte["estagio"].isin(estagios)]
    return recorte


# =========================================================================== #
# CARDS
# =========================================================================== #
def _cards(r: metricas.ResumoAReceber) -> None:
    """Volume em aberto + o que já estourou o prazo.

    O card de prazo vencido usa o mesmo critério do Acompanhamento
    (`config.STATUS_ATRASADO`): ordem sem deadline cadastrado fica de fora, porque
    ausência de dado é problema de cadastro e não atraso de oficina.
    """
    vencidas = r.por_status.get(config.STATUS_ATRASADO,
                                {"ordens": 0, "pecas": 0.0})
    ui.grade_cards([
        {"label": "Total de ordens", "valor": ui.fmt_int(r.ordens),
         "sub": f"{ui.fmt_int(r.oficinas)} oficina(s) com ordem em aberto",
         "accent": ui.ACENTOS["teal"]},
        {"label": "Total de peças", "valor": ui.fmt_int(r.pecas),
         "sub": "ainda nas oficinas", "accent": ui.ACENTOS["emerald"]},
        {"label": "Total de minutos", "valor": ui.fmt_int(r.minutos),
         "sub": "ainda nas oficinas", "accent": ui.ACENTOS["sky"]},
        {"label": config.STATUS_ATRASADO, "valor": ui.fmt_int(vencidas["ordens"]),
         "sub": f"{ui.fmt_int(vencidas['pecas'])} peça(s) — deadline já passou e a "
                f"ordem não voltou", "accent": ui.ACENTOS["rose"]},
    ])


def _cards_cobertura(c: metricas.CoberturaPrevisao) -> None:
    """Quanto da carteira em aberto já tem data de retorno — e quanto não tem.

    Os dois cards somam a carteira inteira porque as duas bases são disjuntas por
    construção da origem (ver o docstring do módulo). É a única leitura da tela que
    depende de outra base, e por isso ela mora num bloco próprio, blindado à parte:
    a Previsão faltar não pode apagar o resto da página.
    """
    ui.grade_cards([
        {"label": "Cobertura de previsão", "valor": ui.fmt_pct(c.pct_coberto),
         "sub": f"{ui.fmt_int(c.com_previsao)} de {ui.fmt_int(c.total)} ordens em "
                f"aberto já têm data de retorno", "accent": ui.ACENTOS["emerald"]},
        {"label": "Sem previsão de retorno",
         "valor": ui.fmt_int(c.sem_previsao),
         "sub": f"{ui.fmt_pct(c.pct_sem_previsao)} da carteira · "
                f"{ui.fmt_int(c.pecas_sem_previsao)} peça(s) sem data para voltar",
         "accent": ui.ACENTOS["amber"]},
    ])


# =========================================================================== #
# TABELAS
# =========================================================================== #
_COLUNAS_ESTAGIO = {"estagio": "Estágio", "ordens": "Ordens",
                    "qtd_pecas": "Peças", "minutos": "Minutos"}
_FORMATO_ESTAGIO = {"ordens": ui.fmt_int, "qtd_pecas": ui.fmt_int,
                    "minutos": ui.fmt_int}

_COLUNAS_STATUS = {
    "om": "Ordem mestre", "oficina": "Oficina", "estagio": "Estágio",
    "situacao": "Situação", "mp": "MP", "data": "Envio", "deadline": "Deadline",
    "qtd_pecas": "Peças", "minutos": "Minutos",
}
_FORMATO_STATUS = {
    "om": ui.fmt_om, "data": ui.fmt_data, "deadline": ui.fmt_data,
    "qtd_pecas": ui.fmt_int, "minutos": ui.fmt_int,
}


def _tabela_por_estagio(df) -> None:
    """Os números exatos ao lado do gráfico, que mostra só a forma.

    O gráfico oculta os rótulos do eixo Y (padrão do painel) e entrega o valor
    pela tooltip; esta tabela é onde o total de peças e minutos por estágio pode
    ser lido e conferido contra a planilha.
    """
    consolidado = metricas.por_estagio(df)
    ui.tabela_verde(
        consolidado, _COLUNAS_ESTAGIO, formato=_FORMATO_ESTAGIO,
        col_oficina="estagio", col_num=tuple(_FORMATO_ESTAGIO),
        vazio="Nenhum estágio no filtro atual.",
    )
    ui.botao_excel(
        consolidado, _COLUNAS_ESTAGIO, "status_estagio",
        titulo="Status consolidado por estágio",
        rotulo="Baixar consolidado por estágio em Excel",
        subtitulo="Ordens, peças e minutos em cada estágio do fluxo",
        somar=("ordens", "qtd_pecas", "minutos"),
    )


def _tabela_ordens(df) -> None:
    """Detalhe das ordens, da mais antiga para a mais recente.

    Ordem crescente de envio de propósito: quem está fora há mais tempo aparece
    primeiro, que é a fila que o time cobra na prática.
    """
    detalhe = df.sort_values(["data", "deadline"], na_position="last")
    ui.tabela_paginada(
        detalhe, _COLUNAS_STATUS, "status", formato=_FORMATO_STATUS,
        col_oficina="oficina", col_num=("om", "qtd_pecas", "minutos"),
        vazio="Nenhuma ordem no filtro atual.",
    )
    ui.botao_excel(
        detalhe, _COLUNAS_STATUS, "status", titulo="Status das ordens em aberto",
        rotulo="Baixar status em Excel",
        subtitulo="Ordens em aberto e o estágio em que cada uma está",
        somar=("qtd_pecas", "minutos"),
    )


# =========================================================================== #
# ENTRADA
# =========================================================================== #
def renderizar() -> None:
    df = comum.carregar_fato(
        "status",
        vazio="A tabela de Status está vazia. Suba a planilha STATUS.xlsx "
              "em **Dados**, no canto superior direito.")
    if df is None:
        return

    estagios, mps, oficinas = _filtros(df)
    # `classificar_prazo` é a mesma classificação do Acompanhamento — é ela que
    # alimenta o card de prazo vencido sem inventar regra nova aqui.
    atual = metricas.classificar_prazo(_aplicar(df, estagios, mps, oficinas))
    r = metricas.resumo_a_receber(atual)

    ui.titulo_secao("Visão geral")
    _cards(r)
    # Sem esta linha o operador lê os totais como "tudo que está em aberto" e eles
    # divergem dos cards do Acompanhamento sem explicação — a diferença é o que já
    # tem data prevista e por isso vive na aba de Previsão.
    st.caption(
        "Ordens em aberto **sem data prevista de retorno** — assim que a previsão "
        "é cadastrada, a ordem sai desta lista e passa a aparecer em **Previsão**."
    )

    with comum.bloco("Cobertura de previsão"):
        ui.titulo_secao("Cobertura de previsão")
        previsao = comum.carregar_fato(
            "previsao",
            vazio="A base de Previsão está vazia — sem ela não dá para medir quanto "
                  "da carteira em aberto já tem data de retorno.")
        if previsao is not None:
            # `df`, e não `atual`: este bloco mede a carteira INTEIRA e por isso é
            # imune aos filtros da aba — mesma decisão da média mensal de
            # referência em `metricas.calcular_media_mensal`. Um indicador de saúde
            # do fluxo que muda a cada clique de oficina deixa de ser referência, e
            # aqui seria pior: o filtro de estágio não existe do lado da Previsão,
            # então o percentual passaria a comparar um recorte com uma base cheia.
            _cards_cobertura(metricas.cobertura_previsao(df, previsao))
            st.caption(
                "Toda a carteira em aberto, sem os filtros acima — as duas bases "
                "não se sobrepõem: a ordem sai daqui quando ganha data prevista."
            )

    with comum.bloco("Distribuição por estágio"):
        ui.titulo_secao("Peças e minutos por estágio")
        charts.renderizar(charts.barras_por_estagio(metricas.por_estagio(atual)),
                          altura=380)
        _tabela_por_estagio(atual)

    with comum.bloco("Ordens por estágio"):
        ui.titulo_secao("Ordens em aberto")
        _tabela_ordens(atual)
