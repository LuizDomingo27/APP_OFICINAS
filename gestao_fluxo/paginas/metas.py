"""Aba de Metas — cadastro, diluição por dia útil e relógios de progresso.

Única aba com escrita além do menu de Dados: o formulário grava as 6 metas.
O cálculo todo vive em `gestao_fluxo.metas`; aqui só há tela.

Nota de leitura: `from gestao_fluxo import metas` importa o módulo de DOMÍNIO,
não este arquivo — imports em Python 3 são absolutos, então `gestao_fluxo.metas`
e `gestao_fluxo.paginas.metas` são dois nomes distintos que não se confundem.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from gestao_fluxo import charts, config, metas, metricas, servicos, ui
from gestao_fluxo.exceptions import GestaoFluxoError

from . import comum

#: Os 4 relógios, na ordem em que aparecem na linha.
_RELOGIOS = (
    ("mes_pecas", "Mês — peças"), ("mes_minutos", "Mês — minutos"),
    ("semana_pecas", "Semana — peças"), ("semana_minutos", "Semana — minutos"),
)

#: Centraliza o `st.info` do rodapé. Mora aqui, e não no CSS global de `ui`,
#: porque é a única ocorrência do padrão em todo o painel.
_CSS_INFO = ('<style>.st-key-info_meta [data-testid^="stAlert"]'
             '{text-align:center;justify-content:center;}</style>')


# =========================================================================== #
# FORMULÁRIO
# =========================================================================== #
def _formulario(salvas: dict) -> None:
    ui.titulo_secao("Cadastro das metas")
    # O `key` do container é o gancho do CSS (.st-key-metas-form) que estiliza
    # o cartão, os rótulos e a largura dos campos — ver gestao_fluxo/ui.py.
    with st.container(key="metas-form"), st.form("form_metas"):
        ui.texto_apoio("Informe as metas em peças e em minutos. Semana e dia são "
                       "opcionais: deixando 0, o sistema usa a diluição da meta mensal.")
        novos: dict = {}
        colunas = st.columns(3, gap="large")
        for coluna, (periodo, titulo, accent) in zip(colunas, ui.METAS_GRUPOS):
            with coluna:
                ui.cabecalho_grupo(titulo, accent)
                # O período já aparece no cabeçalho do bloco, então o rótulo do
                # campo fica curto — é o que permite estreitar a caixa.
                for unidade, rotulo in (("pecas", "Peças"), ("minutos", "Minutos")):
                    chave = f"{periodo}_{unidade}"
                    novos[chave] = st.number_input(
                        rotulo, min_value=0.0,
                        value=float(salvas.get(chave, 0.0)), step=100.0,
                        format="%.0f", key=f"in_{chave}",
                        help=config.METAS_CHAVES[chave],
                    )
        # Sem `use_container_width`: o botão fica do tamanho do rótulo, em vez de
        # esticar por toda a largura do formulário.
        if st.form_submit_button("Salvar metas"):
            try:
                metas.salvar_metas(servicos.engine(), novos)
                st.success("Metas salvas.")
                st.rerun()
            except GestaoFluxoError as exc:
                st.error(exc.mensagem_usuario)


# =========================================================================== #
# CARDS E BADGES
# =========================================================================== #
def _cards_necessidade(plano: metas.PlanoMetas) -> None:
    ui.grade_cards([
        {"label": "Dias úteis do mês", "valor": ui.fmt_int(plano.dias_uteis_mes),
         "sub": f"{plano.dias_uteis_restantes} restante(s)",
         "accent": ui.ACENTOS["sky"]},
        {"label": "Necessidade / dia — peças",
         "valor": ui.fmt_int(plano.necessidade_dia["pecas"]),
         "sub": "meta do mês ÷ dias úteis", "accent": ui.ACENTOS["emerald"]},
        {"label": "Necessidade / dia — minutos",
         "valor": ui.fmt_int(plano.necessidade_dia["minutos"]),
         "sub": "meta do mês ÷ dias úteis", "accent": ui.ACENTOS["teal"]},
        {"label": "Necessidade / semana — peças",
         "valor": ui.fmt_int(plano.necessidade_semana["pecas"]),
         "sub": plano.semana_rotulo, "accent": ui.ACENTOS["amber"]},
        {"label": "Necessidade / semana — minutos",
         "valor": ui.fmt_int(plano.necessidade_semana["minutos"]),
         "sub": plano.semana_rotulo, "accent": ui.ACENTOS["rose"]},
    ])


def _badges_alcancado(plano: metas.PlanoMetas, periodo: str) -> None:
    """Alcançado e o que falta. Sem meta cadastrada o badge fica neutro — vermelho
    ali sugeriria atraso, quando na verdade ninguém definiu o alvo ainda."""
    itens = []
    for unidade, nome in comum.UNIDADES:
        a = plano.acompanhamentos[f"{periodo}_{unidade}"]
        sem_meta = a.meta <= 0
        estado = "neutro" if sem_meta else ("ok" if a.batida else "falta")
        itens.append({
            "label": f"Alcançado — {nome}",
            "valor": ui.fmt_int(a.realizado),
            "sub": ("meta não cadastrada" if sem_meta
                    else f"de {ui.fmt_int(a.meta)} ({a.percentual:.1f}%)"),
            "estado": estado,
        })
        itens.append({
            "label": f"Falta — {nome}",
            "valor": "—" if sem_meta else ui.fmt_int(a.falta),
            "sub": ("cadastre a meta para acompanhar" if sem_meta
                    else ("meta batida" if a.batida
                          else f"para fechar a meta de {nome}")),
            "estado": estado,
        })
    ui.badges(itens)


def _relogios(plano: metas.PlanoMetas) -> None:
    ui.titulo_secao("Relógios — quanto falta para bater a meta")
    colunas = st.columns(4, gap="small")
    for coluna, (chave, titulo) in zip(colunas, _RELOGIOS):
        a = plano.acompanhamentos[chave]
        detalhe = "meta batida" if a.batida else f"faltam {ui.fmt_int(a.falta)}"
        with coluna:
            charts.renderizar(
                charts.relogio_meta(a.percentual, titulo, detalhe), altura=300)


def _rodape_ritmo(plano: metas.PlanoMetas) -> None:
    if not plano.dias_uteis_restantes:
        return
    st.markdown(_CSS_INFO, unsafe_allow_html=True)
    with st.container(key="info_meta"):
        st.info(
            f"Para fechar o mês faltam **{plano.dias_uteis_restantes} dia(s) "
            f"útil(eis)** — é preciso produzir "
            f"**{ui.fmt_int(plano.ritmo_necessario['pecas'])} peças** e "
            f"**{ui.fmt_int(plano.ritmo_necessario['minutos'])} minutos** "
            f"por dia útil."
        )


# =========================================================================== #
# ENTRADA
# =========================================================================== #
def renderizar() -> None:
    try:
        df = servicos.fato(config.FONTE_META)
        salvas = metas.ler_metas(servicos.engine())
    except GestaoFluxoError as exc:
        st.error(exc.mensagem_usuario)
        return

    _formulario(salvas)

    meses = metricas.meses_disponiveis(df)
    if not meses:
        st.warning("Sem dados de recebimento para medir as metas.")
        return
    hoje = date.today()
    padrao = (hoje.year, hoje.month) if (hoje.year, hoje.month) in meses else meses[0]
    ano, mes = st.selectbox(
        "Mês vigente", meses, index=meses.index(padrao),
        format_func=lambda m: metricas.rotulo_mes(*m), key="mes_metas",
    )
    plano = metas.montar_plano(df, salvas, ano, mes, hoje)

    ui.titulo_secao(f"Necessidade diluída — {metricas.rotulo_mes(ano, mes)}")
    _cards_necessidade(plano)
    st.caption("Realizado medido pela base de Recebimento. Dias úteis = segunda a "
               "sexta (feriados não são descontados).")

    ui.titulo_secao("Meta do mês")
    _badges_alcancado(plano, "mes")
    ui.titulo_secao(f"Meta da semana — {plano.semana_rotulo}")
    _badges_alcancado(plano, "semana")

    with comum.bloco("Relógios das metas"):
        _relogios(plano)

    _rodape_ritmo(plano)
