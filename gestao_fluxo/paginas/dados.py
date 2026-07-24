"""Menu "Dados" da navbar: subir planilhas, recarregar e conferir o histórico.

É a única tela que ESCREVE no banco — todas as outras só leem. Manter isso num
módulo separado é o que deixa a diferença visível: quem for mexer numa aba de
análise não passa perto do caminho de gravação.

Substituiu a antiga barra lateral: mesmas ações, agora dentro de `st.popover`,
por isso os widgets usam `st.*` direto (o próprio popover já é o contêiner).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from gestao_fluxo import config, log, servicos, ui
from gestao_fluxo.exceptions import GestaoFluxoError

from . import comum

_LOG = log.obter("paginas.dados")

_CHAVE_PREVIA = "previa"


# =========================================================================== #
# UPLOAD
# =========================================================================== #
def _formulario_upload() -> None:
    """Uploaders + prévia + confirmação, em dois passos deliberados.

    Nada é gravado no clique de "Analisar". A prévia mostra quantas linhas são
    novas e quantas já existem, e só o segundo clique escreve no banco — é o que
    torna a carga incremental auditável em vez de mágica.
    """
    with st.expander("Subir planilhas novas", expanded=False):
        enviados = {}
        for fonte, spec in config.FONTES.items():
            arquivo = st.file_uploader(
                spec["rotulo"], type=["xlsx", "xls"], key=f"up_{fonte}")
            if arquivo is not None:
                enviados[fonte] = arquivo

        st.caption(
            "Envie só as planilhas que mudaram. Envios e Recebimento **somam** ao "
            "histórico (registro repetido é ignorado); Acompanhamento **substitui** "
            "a lista de ordens em aberto."
        )

        if st.button("Analisar planilhas", use_container_width=True,
                     disabled=not enviados):
            try:
                caminhos = servicos.salvar_enviados(enviados)
                st.session_state[_CHAVE_PREVIA] = {
                    "caminhos": caminhos,
                    "fontes": servicos.prever(caminhos),
                }
            except GestaoFluxoError as exc:
                st.session_state.pop(_CHAVE_PREVIA, None)
                st.error(exc.mensagem_usuario)
                _LOG.warning("Prévia da carga falhou: %s", exc.detalhe)

        _painel_previa()


def _painel_previa() -> None:
    """Mostra o que a carga faria e pede confirmação."""
    previa = st.session_state.get(_CHAVE_PREVIA)
    if not previa:
        return

    st.markdown("**Prévia da carga**")
    for p in previa["fontes"]:
        if p.substituida:
            st.markdown(
                f"**{p.rotulo}** — {ui.fmt_int(p.linhas)} linhas  \n"
                f"Substitui a lista atual de ordens em aberto."
            )
        else:
            st.markdown(
                f"**{p.rotulo}** — {ui.fmt_int(p.linhas)} linhas no arquivo  \n"
                f"Novas: **{ui.fmt_int(p.novas)}** · "
                f"Já existentes: {ui.fmt_int(p.repetidas)}"
            )

    if not any(p.novas for p in previa["fontes"]):
        st.info("Nenhum registro novo — estas planilhas já foram carregadas.")

    col1, col2 = st.columns(2)
    if col1.button("Confirmar", use_container_width=True, type="primary"):
        try:
            servicos.rodar_etl(previa["caminhos"])
            st.session_state.pop(_CHAVE_PREVIA, None)
            st.rerun()
        except GestaoFluxoError as exc:
            st.error(exc.mensagem_usuario)
            _LOG.error("Carga confirmada falhou: %s", exc.detalhe)
    if col2.button("Cancelar", use_container_width=True):
        st.session_state.pop(_CHAVE_PREVIA, None)
        st.rerun()


# =========================================================================== #
# CONFERÊNCIA DA CARGA
# =========================================================================== #
def _conferencia_da_carga() -> None:
    """Detalhe do que a última carga desta sessão gravou."""
    info = servicos.ultimo_etl()
    if not info:
        return
    st.caption(f"Última carga: {info['quando']}")
    with st.expander("Conferência da carga"):
        for f in info["rel"].fontes:
            # O ajuste de prazo é a única correção que o ETL faz nos números da
            # origem, então ele aparece aqui em vez de ficar silencioso.
            prazos = (f"  \nPrazos corrigidos: {ui.fmt_int(f.prazos_corrigidos)}"
                      if f.prazos_corrigidos else "")
            gravadas = (f"Substituídas: {ui.fmt_int(f.novas)}" if f.substituida else
                        f"Novas: {ui.fmt_int(f.novas)} · "
                        f"Já existentes: {ui.fmt_int(f.repetidas)}")
            st.markdown(
                f"**{f.rotulo}** — {ui.fmt_int(f.linhas)} linhas lidas  \n"
                f"{gravadas}  \n"
                f"Peças: {ui.fmt_int(f.total_pecas)} · "
                f"Minutos: {ui.fmt_int(f.total_minutos)}  \n"
                f"Oficinas: {f.oficinas} · Sem data: {f.sem_data}{prazos}"
            )


_COLUNAS_HISTORICO = {
    "fonte": "Fonte", "arquivo": "Arquivo", "quando": "Quando", "modo": "Modo",
    "linhas_lidas": "Lidas", "linhas_novas": "Novas",
    "linhas_repetidas": "Repetidas",
}


def _historico_de_cargas() -> None:
    """Últimas cargas registradas no banco, de todas as sessões.

    Falhar aqui não pode custar o menu inteiro: o upload e a recarga logo acima
    continuam válidos, e é por eles que o operador veio.
    """
    with st.expander("Histórico de cargas"):
        try:
            hist = servicos.historico_cargas(limite=15)
        except GestaoFluxoError as exc:
            st.caption("Histórico indisponível.")
            _LOG.warning("Histórico de cargas falhou: %s", exc.detalhe)
            return
        if hist.empty:
            st.caption("Nenhuma carga registrada ainda.")
            return
        hist["quando"] = pd.to_datetime(hist["quando"], errors="coerce")
        st.dataframe(
            hist.rename(columns=_COLUNAS_HISTORICO),
            hide_index=True, use_container_width=True,
            column_config={"Quando": st.column_config.DatetimeColumn(
                format="DD/MM/YYYY HH:mm")},
        )


# =========================================================================== #
# ENTRADA
# =========================================================================== #
def menu() -> None:
    """Conteúdo do popover "Dados" da navbar."""
    _formulario_upload()

    if st.button("Recarregar da pasta do projeto", use_container_width=True):
        try:
            servicos.rodar_etl()
            st.rerun()
        except GestaoFluxoError as exc:
            st.error(exc.mensagem_usuario)

    # Releitura sem gravar nada: quando alguém subiu planilhas noutra sessão (ou
    # editou o Supabase por fora), este botão descarta o cache e busca o banco de
    # novo — é o que substitui o "reboot do servidor" que antes era necessário.
    if st.button("🔄 Atualizar dados agora", use_container_width=True):
        servicos.invalidar_cache()
        st.rerun()

    with comum.bloco("Conferência da carga"):
        _conferencia_da_carga()
    _historico_de_cargas()


def carga_inicial() -> None:
    """Tela de primeira execução, quando ainda não existe tabela de fato."""
    st.warning("O banco ainda não foi carregado a partir das planilhas.")
    if st.button("Rodar a carga inicial"):
        with comum.blindar("Carga inicial"):
            servicos.rodar_etl()
            st.rerun()
