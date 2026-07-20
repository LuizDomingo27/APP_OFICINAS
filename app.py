"""Dashboard Streamlit — Fluxo de Produção, em 4 abas.

    Acompanhamento / Recebimento / Envios -> mesmas métricas sobre bases diferentes
    Metas                                 -> cadastro, diluição por dia útil e relógios

Este módulo só orquestra: `metricas` calcula, `charts` desenha, `ui` estiliza.
Toda falha de domínio vira mensagem amigável, sem stack trace na tela.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from gestao_fluxo import charts, config, log, metas, metricas, ui
from gestao_fluxo.db import database
from gestao_fluxo.etl import executar_etl, prever_carga
from gestao_fluxo.exceptions import GestaoFluxoError

st.set_page_config(page_title="Fluxo de Produção", layout="wide")

ACENTOS_CICLO = ["teal", "emerald", "amber", "sky", "rose"]

_LOG = log.obter("app")


@contextmanager
def _blindar(secao: str):
    """Isola um trecho da tela: o que falhar aqui não derruba o resto da página.

    Duas classes de falha, dois tratamentos:

    * `GestaoFluxoError` é falha *prevista* (planilha ausente, banco sem carga).
      Já traz mensagem escrita para o operador, então vai direto para a tela.
    * Qualquer outra é bug. O operador não tem o que fazer com um traceback, mas
      quem for corrigir precisa dele — então a tela recebe um código curto e o
      arquivo de log recebe o traceback completo sob o mesmo código.

    `except Exception` é seguro aqui: `st.rerun()` e `st.stop()` sinalizam por
    `ScriptControlException`, que herda de `BaseException` e passa reto. Trocar
    por `BaseException` quebraria os dois.
    """
    try:
        yield
    except GestaoFluxoError as exc:
        _LOG.error("%s: %s", secao, exc.detalhe or exc.mensagem_usuario)
        st.error(exc.mensagem_usuario)
    except Exception:  # noqa: BLE001
        codigo = log.novo_codigo()
        _LOG.exception("[%s] falha inesperada em %s", codigo, secao)
        st.error(
            f"Algo inesperado aconteceu em **{secao}**. O restante do painel "
            f"continua funcionando. Código do erro: `{codigo}`."
        )


@st.cache_resource
def _engine():
    return database.get_engine()


@st.cache_data(show_spinner=False)
def _fato(fonte: str, _versao: int):
    """Fato completo em cache. `_versao` invalida o cache após uma recarga."""
    return metricas.carregar_fato(_engine(), fonte)


def _versao_dados() -> int:
    return st.session_state.get("versao_dados", 0)


# --------------------------------------------------------------------------- #
# ETL
# --------------------------------------------------------------------------- #
def _rodar_etl(caminhos: dict | None = None) -> None:
    with st.spinner("Lendo as planilhas e atualizando o banco..."):
        rel = executar_etl(_engine(), caminhos=caminhos)
    st.session_state["ultimo_etl"] = {
        "quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "rel": rel,
    }
    st.session_state["versao_dados"] = _versao_dados() + 1
    st.cache_data.clear()


# --------------------------------------------------------------------------- #
# UPLOAD DAS PLANILHAS
# --------------------------------------------------------------------------- #
def _pasta_uploads() -> Path:
    """Pasta temporária desta sessão, onde os arquivos enviados são guardados.

    O upload precisa sobreviver ao rerun que acontece entre "Analisar" e
    "Confirmar": o Streamlit reexecuta o script inteiro a cada clique, e o objeto
    devolvido pelo `file_uploader` só pode ser lido uma vez.
    """
    if "pasta_uploads" not in st.session_state:
        st.session_state["pasta_uploads"] = tempfile.mkdtemp(prefix="fluxo_upload_")
    return Path(st.session_state["pasta_uploads"])


def _salvar_enviados(enviados: dict) -> dict:
    """Grava os arquivos enviados em disco e devolve {fonte: caminho}."""
    destino = _pasta_uploads()
    caminhos = {}
    for fonte, arquivo in enviados.items():
        alvo = destino / f"{fonte}_{arquivo.name}"
        alvo.write_bytes(arquivo.getbuffer())
        caminhos[fonte] = alvo
    return caminhos


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
                caminhos = _salvar_enviados(enviados)
                st.session_state["previa"] = {
                    "caminhos": caminhos,
                    "fontes": prever_carga(_engine(), caminhos=caminhos),
                }
            except GestaoFluxoError as exc:
                st.session_state.pop("previa", None)
                st.error(exc.mensagem_usuario)
                _LOG.warning("Prévia da carga falhou: %s", exc.detalhe)

        _painel_previa()


def _painel_previa() -> None:
    """Mostra o que a carga faria e pede confirmação."""
    previa = st.session_state.get("previa")
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
            _rodar_etl(previa["caminhos"])
            st.session_state.pop("previa", None)
            st.rerun()
        except GestaoFluxoError as exc:
            st.error(exc.mensagem_usuario)
            _LOG.error("Carga confirmada falhou: %s", exc.detalhe)
    if col2.button("Cancelar", use_container_width=True):
        st.session_state.pop("previa", None)
        st.rerun()


def _menu_dados() -> None:
    """Conteúdo do popover "Dados" da navbar: upload, recarga e histórico.

    Substitui a antiga barra lateral — mesmas ações, agora dentro de
    `st.popover` em vez de `st.sidebar`, por isso os widgets usam `st.*`
    direto (o próprio popover já é o contêiner).
    """
    _formulario_upload()

    if st.button("Recarregar da pasta do projeto", use_container_width=True):
        try:
            _rodar_etl()
            st.rerun()
        except GestaoFluxoError as exc:
            st.error(exc.mensagem_usuario)

    info = st.session_state.get("ultimo_etl")
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
                f"Peças: {ui.fmt_int(f.total_pecas)} · Minutos: {ui.fmt_int(f.total_minutos)}  \n"
                f"Oficinas: {f.oficinas} · Sem data: {f.sem_data}{prazos}"
            )

    with st.expander("Histórico de cargas"):
        try:
            hist = database.historico_cargas(_engine(), limite=15)
        except GestaoFluxoError as exc:
            st.caption("Histórico indisponível.")
            _LOG.warning("Histórico de cargas falhou: %s", exc.detalhe)
            return
        if hist.empty:
            st.caption("Nenhuma carga registrada ainda.")
            return
        hist["quando"] = pd.to_datetime(hist["quando"], errors="coerce")
        st.dataframe(
            hist.rename(columns={
                "fonte": "Fonte", "arquivo": "Arquivo", "quando": "Quando",
                "modo": "Modo", "linhas_lidas": "Lidas", "linhas_novas": "Novas",
                "linhas_repetidas": "Repetidas",
            }),
            hide_index=True, use_container_width=True,
            column_config={"Quando": st.column_config.DatetimeColumn(
                format="DD/MM/YYYY HH:mm")},
        )


# --------------------------------------------------------------------------- #
# FILTROS (uma barra por aba — cada aba filtra de forma independente)
# --------------------------------------------------------------------------- #
def _barra_filtros(df, chave: str):
    """Devolve (inicio, fim, mps, oficinas, semanas_do_mes, rotulo_periodo)."""
    meses = metricas.meses_disponiveis(df)
    if not meses:
        return None

    col1, col2, col3, col4 = st.columns([1.1, 1.5, 1.4, 1.6])
    ano, mes = col1.selectbox(
        "Mês", meses, format_func=lambda m: metricas.rotulo_mes(*m), key=f"mes_{chave}",
    )
    semanas = metricas.semanas_do_mes(ano, mes)
    # As opções de semana são recriadas a cada mês escolhido, então nunca aparece
    # uma semana que não pertence ao mês filtrado.
    opcoes = ["Mês inteiro"] + [s.rotulo for s in semanas]
    escolha = col2.selectbox("Análise", opcoes, key=f"sem_{chave}")
    mps = col3.multiselect("Matéria-prima (MP)", sorted(df["mp"].dropna().unique()),
                           key=f"mp_{chave}")
    oficinas = col4.multiselect("Oficina", sorted(df["oficina"].dropna().unique()),
                                key=f"of_{chave}")

    if escolha == "Mês inteiro":
        inicio, fim = metas.limites_do_mes(ano, mes)
        rotulo = metricas.rotulo_mes(ano, mes)
    else:
        semana = semanas[opcoes.index(escolha) - 1]
        inicio, fim, rotulo = semana.inicio, semana.fim, semana.rotulo
    return inicio, fim, mps, oficinas, semanas, rotulo


# --------------------------------------------------------------------------- #
# ABAS DE ANÁLISE
# --------------------------------------------------------------------------- #
def _cards_totais(m: metricas.Metricas, rotulo: str) -> None:
    ui.grade_cards([
        {"label": "Total de peças", "valor": ui.fmt_int(m.total_pecas),
         "sub": rotulo, "accent": ui.ACENTOS["emerald"]},
        {"label": "Total de minutos", "valor": ui.fmt_int(m.total_minutos),
         "sub": rotulo, "accent": ui.ACENTOS["teal"]},
        {"label": "Oficinas envolvidas", "valor": ui.fmt_int(m.oficinas),
         "sub": f"{ui.fmt_int(m.linhas)} lançamento(s)", "accent": ui.ACENTOS["sky"]},
    ])


UNIDADES = (("pecas", "peças"), ("minutos", "minutos"))


def _cards_medias_periodo(medias: dict) -> None:
    """4 cards (diária e semanal × peças e minutos) do recorte que está na tela.

    Valor e delta respondem à mesma pergunta aqui — os dois saem do recorte
    filtrado —, ao contrário dos cards de referência logo abaixo.
    """
    cards = []
    for i, (unidade, nome) in enumerate(UNIDADES):
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
        for unidade, nome in UNIDADES
    ])


def _aba_analise(fonte: str) -> None:
    spec = config.FONTES[fonte]
    try:
        df = _fato(fonte, _versao_dados())
    except GestaoFluxoError as exc:
        st.error(exc.mensagem_usuario)
        return
    if df.empty:
        st.warning(f"A tabela de {spec['rotulo']} está vazia. Recarregue as planilhas.")
        return

    filtros = _barra_filtros(df, fonte)
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
    medias = metricas.calcular_medias_periodo(df, inicio, fim, mps, oficinas)
    referencia = metricas.calcular_media_mensal(df, ini_mes, fim_mes)
    ini_ant, fim_ant = metricas.periodo_anterior(inicio, fim)

    ui.titulo_secao(f"Visão geral — {rotulo}")
    _cards_totais(m, rotulo)

    ui.titulo_secao(f"Médias do período — {rotulo}")
    _cards_medias_periodo(medias)
    st.caption(
        "Média do recorte filtrado (total ÷ períodos com movimento), acompanhando "
        "semana, MP e oficina. A variação compara "
        f"{ui.fmt_data(inicio)} — {ui.fmt_data(fim)} contra "
        f"{ui.fmt_data(ini_ant)} — {ui.fmt_data(fim_ant)}, com os mesmos filtros."
    )

    ui.titulo_secao("Referência da base — todo o histórico")
    _cards_referencia_mensal(referencia, rotulo_mes)
    st.caption(
        "Média mensal de toda a base, imune aos filtros — é o parâmetro de "
        f"comparação. A variação mostra o quanto {rotulo_mes} ficou acima ou "
        "abaixo desse padrão."
    )

    ui.titulo_secao("Granularidade por matéria-prima (MP)")
    mp = metricas.por_mp(atual)
    esq, dir_ = st.columns(2)
    with esq:
        charts.renderizar(charts.rosca_por_mp(mp, "qtd_pecas", "Peças por MP"), altura=460)
    with dir_:
        charts.renderizar(charts.rosca_por_mp(mp, "minutos", "Minutos por MP"), altura=460)

    ui.titulo_secao("Evolução no período")
    # Uma série temporal por linha (largura cheia): com o eixo Y sem rótulos, o
    # que importa é a forma da curva, e ela só se lê bem com espaço horizontal.
    # A visão semanal cobre o mês inteiro de propósito: é a comparação entre as
    # semanas do mês filtrado, mesmo quando o recorte atual é uma semana só.
    mes_todo = metricas.filtrar(df, semanas[0].inicio, semanas[-1].fim, mps, oficinas)
    charts.renderizar(
        charts.linha_por_semana(metricas.por_semana(mes_todo, semanas)), altura=320)
    charts.renderizar(charts.linha_por_dia(metricas.por_dia(atual)), altura=320)

    ui.titulo_secao(f"Base de {spec['rotulo']} — {rotulo}")
    ui.tabela_fato(atual.sort_values("data", ascending=False), fonte,
                   titulo=f"Base de {spec['rotulo']}", subtitulo=rotulo)


# --------------------------------------------------------------------------- #
# ABA DE ACOMPANHAMENTO — o que há para receber
# --------------------------------------------------------------------------- #
# Esta aba não repete a estrutura das outras duas de propósito. Recebimento e
# Envios são históricos: fazem sentido em médias, variação e evolução no tempo.
# Acompanhamento é um saldo em aberto — o que já saiu e ainda não voltou. Média
# diária de um saldo não diz nada; o que o time precisa é prazo, volume e há
# quanto tempo cada oficina está devendo. Daí cards + tabelas, sem gráficos.

ACENTO_STATUS = {
    config.STATUS_ATRASADO: ui.ACENTOS["rose"],
    config.STATUS_VENCE_BREVE: ui.ACENTOS["amber"],
    config.STATUS_NO_PRAZO: ui.ACENTOS["emerald"],
    config.STATUS_SEM_PRAZO: ui.ACENTOS["sky"],
}


def _filtros_acompanhamento(df):
    """Barra própria: aqui não se filtra por mês — o saldo em aberto é atemporal."""
    col1, col2, col3 = st.columns([1.4, 1.6, 1.4])
    mps = col1.multiselect("Matéria-prima (MP)", sorted(df["mp"].dropna().unique()),
                           key="mp_acomp")
    oficinas = col2.multiselect("Oficina", sorted(df["oficina"].dropna().unique()),
                                key="of_acomp")
    situacoes = col3.multiselect("Situação do prazo", list(config.STATUS_PRAZO),
                                 key="st_acomp")
    return mps, oficinas, situacoes


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
         "sub": f"{ui.fmt_int(dados['pecas'])} peça(s)", "accent": ACENTO_STATUS[status]}
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


def _tabela_oficinas_abertas(aberto) -> None:
    agg = metricas.por_oficina_a_receber(aberto)
    visao = pd.DataFrame({
        "oficina": agg["oficina"],
        "ordens": agg["ordens"].map(ui.fmt_int),
        "atrasadas": agg["atrasadas"].map(ui.fmt_int),
        "qtd_pecas": agg["qtd_pecas"].map(ui.fmt_int),
        "minutos": agg["minutos"].map(ui.fmt_int),
        "envio_mais_antigo": agg["envio_mais_antigo"].map(ui.fmt_data),
        "dias_aberto": agg["dias_aberto"].map(ui.fmt_int),
        "prazo_mais_proximo": agg["prazo_mais_proximo"].map(ui.fmt_data),
    })
    ui.tabela_paginada(
        visao,
        {"oficina": "Oficina", "ordens": "Ordens", "atrasadas": "Atrasadas",
         "qtd_pecas": "Peças", "minutos": "Minutos",
         "envio_mais_antigo": "Envio mais antigo", "dias_aberto": "Dias em aberto",
         "prazo_mais_proximo": "Prazo mais próximo"},
        "acomp_oficinas", col_oficina="oficina",
        col_num=("ordens", "atrasadas", "qtd_pecas", "minutos", "dias_aberto"),
        vazio="Nenhuma oficina com ordem em aberto no filtro atual.",
    )
    # A planilha sai do `agg` cru, não do `visao`: no Excel os números precisam
    # continuar números para somar e ordenar.
    ui.botao_excel(
        agg,
        {"oficina": "Oficina", "ordens": "Ordens", "atrasadas": "Atrasadas",
         "qtd_pecas": "Peças", "minutos": "Minutos",
         "envio_mais_antigo": "Envio mais antigo", "dias_aberto": "Dias em aberto",
         "prazo_mais_proximo": "Prazo mais próximo"},
        "acomp_oficinas", titulo="Oficinas com ordens em aberto",
        rotulo="Baixar oficinas em Excel",
        subtitulo="Acompanhamento — saldo a receber por oficina",
        somar=("ordens", "atrasadas", "qtd_pecas", "minutos"),
    )


def _tabela_ordens_abertas(aberto) -> None:
    # Pior caso primeiro: prazo mais estourado no topo, desempatado pela espera.
    detalhe = aberto.sort_values(["dias_prazo", "dias_aberto"],
                                 ascending=[True, False], na_position="last")
    visao = pd.DataFrame({
        "oficina": detalhe["oficina"],
        "om": detalhe["om"].map(lambda v: "—" if pd.isna(v) else f"{int(v)}"),
        "mp": detalhe["mp"],
        "data": detalhe["data"].map(ui.fmt_data),
        "deadline": detalhe["deadline"].map(ui.fmt_data),
        "status": detalhe["status"].map(ui.pill),
        "dias_prazo": detalhe["dias_prazo"].map(ui.fmt_int),
        "qtd_pecas": detalhe["qtd_pecas"].map(ui.fmt_int),
        "minutos": detalhe["minutos"].map(ui.fmt_int),
    })
    ui.tabela_paginada(
        visao,
        {"oficina": "Oficina", "om": "OM", "mp": "MP", "data": "Envio",
         "deadline": "Prazo", "status": "Situação", "dias_prazo": "Dias p/ o prazo",
         "qtd_pecas": "Peças", "minutos": "Minutos"},
        "acomp_ordens", col_oficina="oficina", col_html=("status",),
        col_num=("om", "dias_prazo", "qtd_pecas", "minutos"),
        vazio="Nenhuma ordem em aberto no filtro atual.",
    )
    ui.botao_excel(
        detalhe,
        {"oficina": "Oficina", "om": "OM", "mp": "MP", "data": "Envio",
         "deadline": "Prazo", "status": "Situação", "dias_prazo": "Dias p/ o prazo",
         "qtd_pecas": "Peças", "minutos": "Minutos"},
        "acomp_ordens", titulo="Ordens em aberto",
        rotulo="Baixar ordens em Excel",
        subtitulo="Acompanhamento — pior prazo primeiro",
        somar=("qtd_pecas", "minutos"),
    )


_COLUNAS_FLUXO_MP = {
    "mp": "MP", "enviado_pecas": "Enviado (peças)",
    "recebido_pecas": "Recebido (peças)", "progresso_pecas": "Em progresso",
    "pct_concluido": "% concluído", "enviado_minutos": "Enviado (min)",
    "recebido_minutos": "Recebido (min)", "ordens_abertas": "Ordens abertas",
    "recebido_sem_envio": "Recebido sem envio",
}


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


_TITULO_FLUXO_MP = "Fluxo por matéria-prima — enviado x recebido"
_PERIODO_TODO = "Todo o período"


def _filtros_periodo_fluxo(base) -> tuple:
    """Título e recorte de mês/semana na mesma linha. Devolve (inicio, fim).

    Só esta tabela da aba aceita período: o resto do Acompanhamento mede saldo em
    aberto, que é atemporal, mas aqui a fonte é o histórico de Envios e
    Recebimento. O padrão é `_PERIODO_TODO` — sem recorte o número é o acumulado
    das duas bases, que é o que a legenda abaixo da tabela explica.
    """
    meses = metricas.meses_disponiveis(base)
    col_tit, col_mes, col_sem = st.columns([2.4, 1.1, 1.6],
                                           vertical_alignment="bottom")
    with col_tit:
        ui.titulo_secao(_TITULO_FLUXO_MP, inline=True)
    if not meses:
        return None, None

    escolha = col_mes.selectbox(
        "Mês", [_PERIODO_TODO] + meses, key="mes_fluxo_mp",
        format_func=lambda m: m if m == _PERIODO_TODO else metricas.rotulo_mes(*m),
    )
    if escolha == _PERIODO_TODO:
        # Chave própria (e não a do seletor real) para o Streamlit não tentar
        # casar o valor guardado com uma lista de opções que mudou de natureza.
        col_sem.selectbox("Análise", [_PERIODO_TODO], key="sem_fluxo_mp_off",
                          disabled=True)
        return None, None

    ano, mes = escolha
    semanas = metricas.semanas_do_mes(ano, mes)
    opcoes = ["Mês inteiro"] + [s.rotulo for s in semanas]
    sem = col_sem.selectbox("Análise", opcoes, key="sem_fluxo_mp")
    if sem == "Mês inteiro":
        return metas.limites_do_mes(ano, mes)
    semana = semanas[opcoes.index(sem) - 1]
    return semana.inicio, semana.fim


def _tabela_fluxo_mp(mps: list, oficinas: list) -> None:
    """Enviado x recebido x em progresso, por matéria-prima.

    Lê Envios e Recebimento direto (não o Acompanhamento filtrado da aba): esta
    tabela mede o acumulado das duas bases, não o saldo declarado em aberto.
    """
    try:
        envios = _fato("envios", _versao_dados())
        recebimento = _fato("recebimento", _versao_dados())
        acomp = _fato("acompanhamento", _versao_dados())
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

    visao = pd.DataFrame({
        "mp": agg["mp"],
        "enviado_pecas": agg["enviado_pecas"].map(ui.fmt_int),
        "recebido_pecas": agg["recebido_pecas"].map(ui.fmt_int),
        "progresso_pecas": agg["progresso_pecas"].map(ui.fmt_int),
        "pct_concluido": agg["pct_concluido"].map(
            lambda v: "—" if pd.isna(v) else f"{v:.1f}%"),
        "enviado_minutos": agg["enviado_minutos"].map(ui.fmt_int),
        "recebido_minutos": agg["recebido_minutos"].map(ui.fmt_int),
        "ordens_abertas": agg["ordens_abertas"].map(ui.fmt_int),
        "recebido_sem_envio": agg["recebido_sem_envio"].map(ui.fmt_int),
    })
    ui.tabela_paginada(
        visao, _COLUNAS_FLUXO_MP, "fluxo_mp",
        col_num=("enviado_pecas", "recebido_pecas", "progresso_pecas",
                 "pct_concluido", "enviado_minutos", "recebido_minutos",
                 "ordens_abertas", "recebido_sem_envio"),
        vazio="Sem movimento de envio ou recebimento no filtro atual.",
    )
    st.caption(
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
    ui.botao_excel(
        agg, _COLUNAS_FLUXO_MP, "fluxo_mp",
        titulo="Fluxo por matéria-prima",
        rotulo="Baixar fluxo por MP em Excel",
        subtitulo="Enviado x recebido x em progresso",
        somar=("enviado_pecas", "recebido_pecas", "progresso_pecas",
               "enviado_minutos", "recebido_minutos", "ordens_abertas",
               "recebido_sem_envio"),
    )


def _aba_acompanhamento() -> None:
    try:
        df = _fato("acompanhamento", _versao_dados())
    except GestaoFluxoError as exc:
        st.error(exc.mensagem_usuario)
        return
    if df.empty:
        st.warning("A tabela de Acompanhamento está vazia. Recarregue as planilhas.")
        return

    mps, oficinas, situacoes = _filtros_acompanhamento(df)
    aberto = metricas.classificar_prazo(metricas.filtrar(df, mps=mps, oficinas=oficinas))
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
    _tabela_fluxo_mp(mps, oficinas)

    ui.titulo_secao("Oficinas com ordens em aberto")
    _tabela_oficinas_abertas(aberto)

    ui.titulo_secao("Ordens em aberto — detalhe")
    _tabela_ordens_abertas(aberto)


# --------------------------------------------------------------------------- #
# ABA DE PREVISÃO — o que está agendado para voltar
# --------------------------------------------------------------------------- #
# A base de Previsão é a agenda do retorno: cada linha é uma ordem que já saiu e
# tem data PREVISTA de recebimento. Por isso o período desta aba é filtrado pela
# data de recebimento, e não pela de envio como nas outras — a pergunta aqui é
# "o que temos para receber nesta semana", não "o que despachamos".
#
# Como no Acompanhamento, não há média nem variação: previsão não tem período
# anterior com que se comparar. O que a tela mede é volume, distribuição e risco.

_COLUNAS_PREVISAO = {
    "om": "Ordem mestre", "oficina": "Oficina", "envio": "Envio",
    "deadline": "Deadline", "qtd_pecas": "Peças", "minutos": "Minutos",
    "data": "Recebimento", "mp": "MP",
}


def _filtros_previsao(df) -> tuple | None:
    """(inicio, fim, mps, semanas, rotulo) — recorte sobre a data prevista.

    O padrão é `_PERIODO_TODO` e não o mês mais recente: a previsão atravessa a
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
        "Mês do recebimento", [_PERIODO_TODO] + meses, key="mes_previsao",
        format_func=lambda m: m if m == _PERIODO_TODO else metricas.rotulo_mes(*m),
    )
    # A MP é lida da base inteira, não do recorte: uma MP que só aparece em agosto
    # precisa continuar escolhível enquanto o filtro está em julho, senão a opção
    # some da lista no exato momento em que o operador iria usá-la.
    mps = col_mp.multiselect("Matéria-prima (MP)",
                             sorted(df["mp"].dropna().unique()), key="mp_previsao")

    if escolha == _PERIODO_TODO:
        # Chave própria (e não a do seletor real) para o Streamlit não tentar casar
        # o valor guardado com uma lista de opções que mudou de natureza — mesma
        # precaução do filtro de fluxo por MP.
        col_sem.selectbox("Semana", [_PERIODO_TODO], key="sem_previsao_off",
                          disabled=True)
        # Sem mês escolhido, a grade semanal cobre todos os meses da base, em ordem
        # cronológica — mas só as semanas que de fato tocam o período com previsão.
        # Um mês entra em `meses` por causa de um único dia de recebimento, e sem
        # este recorte metade das barras nasceria zerada só porque o mês tem cinco
        # semanas: o gráfico ficaria dizendo "não temos nada a receber" em faixas
        # que simplesmente estão fora da janela da planilha.
        #
        # No recorte por mês a regra é a oposta e igualmente deliberada: ali a grade
        # é o mês inteiro, porque a leitura é a comparação entre as semanas dele.
        datas = df["data"].dropna()
        primeira, ultima = datas.min().date(), datas.max().date()
        todas = [s for ano, mes in sorted(meses)
                 for s in metricas.semanas_do_mes(ano, mes)
                 if s.inicio <= ultima and s.fim >= primeira]
        return None, None, mps, todas, _PERIODO_TODO

    ano, mes = escolha
    semanas = metricas.semanas_do_mes(ano, mes)
    opcoes = ["Mês inteiro"] + [s.rotulo for s in semanas]
    sem = col_sem.selectbox("Semana", opcoes, key="sem_previsao")
    if sem == "Mês inteiro":
        inicio, fim = metas.limites_do_mes(ano, mes)
        return inicio, fim, mps, semanas, metricas.rotulo_mes(ano, mes)
    semana = semanas[opcoes.index(sem) - 1]
    return semana.inicio, semana.fim, mps, semanas, semana.rotulo


def _cards_previsao(r: metricas.ResumoPrevisao, rotulo: str) -> None:
    ui.grade_cards([
        {"label": "Total de ordens", "valor": ui.fmt_int(r.ordens),
         "sub": f"{ui.fmt_int(r.oficinas)} oficina(s) · {rotulo}",
         "accent": ui.ACENTOS["teal"]},
        {"label": "Total de peças", "valor": ui.fmt_int(r.pecas),
         "sub": f"previstas para receber · {rotulo}", "accent": ui.ACENTOS["emerald"]},
        {"label": "Total de minutos", "valor": ui.fmt_int(r.minutos),
         "sub": f"previstos para receber · {rotulo}", "accent": ui.ACENTOS["sky"]},
    ])


def _cards_risco_previsao(r: metricas.ResumoPrevisao) -> None:
    """As duas leituras de risco, em cards separados — ver config.STATUS_PREV_*.

    Uma ordem pode estar nas duas ao mesmo tempo (prazo já vencido *e* previsão
    posterior ao prazo), então os dois números não se somam: cada card responde uma
    pergunta diferente, e juntá-los daria um total maior que a quantidade de ordens.
    """
    ui.grade_cards([
        {"label": config.STATUS_PREV_FURA_PRAZO, "valor": ui.fmt_int(r.fura_prazo),
         "sub": f"{ui.fmt_int(r.pecas_fura_prazo)} peça(s) — recebimento previsto "
                f"depois do deadline", "accent": ui.ACENTOS["amber"]},
        {"label": config.STATUS_PREV_VENCIDA, "valor": ui.fmt_int(r.vencidas),
         "sub": f"{ui.fmt_int(r.pecas_vencidas)} peça(s) — deadline já passou e a "
                f"ordem não voltou", "accent": ui.ACENTOS["rose"]},
    ])


_COLUNAS_CONSOL_MP = {"mp": "MP", "qtd_pecas": "Qtd", "minutos": "Minutos",
                      "ordens": "Total de ordens"}


def _tabela_consolidado_mp(df) -> None:
    """O consolidado por MP em números, ao lado do gráfico que mostra a forma."""
    consolidado = metricas.consolidado_por_mp(df)
    visao = pd.DataFrame({
        "mp": consolidado["mp"],
        "qtd_pecas": consolidado["qtd_pecas"].map(ui.fmt_int),
        "minutos": consolidado["minutos"].map(ui.fmt_int),
        "ordens": consolidado["ordens"].map(ui.fmt_int),
    })
    ui.tabela_verde(
        visao, _COLUNAS_CONSOL_MP, col_oficina="mp",
        col_num=("qtd_pecas", "minutos", "ordens"),
        vazio="Nenhuma MP prevista no filtro atual.",
    )
    # Como no detalhe: a planilha sai do consolidado cru para o Excel poder somar.
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
    visao = pd.DataFrame({
        "om": detalhe["om"].map(lambda v: "—" if pd.isna(v) else f"{int(v)}"),
        "oficina": detalhe["oficina"],
        "envio": detalhe["envio"].map(ui.fmt_data),
        "deadline": detalhe["deadline"].map(ui.fmt_data),
        "qtd_pecas": detalhe["qtd_pecas"].map(ui.fmt_int),
        "minutos": detalhe["minutos"].map(ui.fmt_int),
        "data": detalhe["data"].map(ui.fmt_data),
        "mp": detalhe["mp"],
    })
    ui.tabela_paginada(
        visao, _COLUNAS_PREVISAO, "previsao", col_oficina="oficina",
        col_num=("om", "qtd_pecas", "minutos"),
        vazio="Nenhuma ordem prevista no filtro atual.",
    )
    # A planilha sai do `detalhe` cru, não do `visao`: no Excel os números e as
    # datas precisam continuar números e datas para somar, ordenar e filtrar.
    ui.botao_excel(
        detalhe, _COLUNAS_PREVISAO, "previsao", titulo="Previsão de recebimento",
        rotulo="Baixar previsão em Excel",
        subtitulo="Ordens previstas — recebimento mais próximo primeiro",
        somar=("qtd_pecas", "minutos"),
    )


def _aba_previsao() -> None:
    try:
        df = _fato("previsao", _versao_dados())
    except GestaoFluxoError as exc:
        st.error(exc.mensagem_usuario)
        return
    if df.empty:
        st.warning("A tabela de Previsão está vazia. Suba a planilha PREVISAO.xlsx "
                   "em **Dados**, no canto superior direito.")
        return

    filtros = _filtros_previsao(df)
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
    _cards_risco_previsao(r)
    if r.sem_prazo:
        st.caption(
            f"{ui.fmt_int(r.sem_prazo)} ordem(ns) sem deadline cadastrado não entram "
            "em nenhum dos dois riscos — a ausência do dado é problema de cadastro, "
            "e contá-la como atraso inventaria um número que não dá para conferir "
            "na planilha."
        )

    ui.titulo_secao("Distribuição por matéria-prima (MP)")
    charts.renderizar(charts.barras_por_mp(metricas.por_mp(atual)), altura=340)

    ui.titulo_secao(f"Consolidado por matéria-prima (MP) — {rotulo}")
    _tabela_consolidado_mp(atual)

    ui.titulo_secao("Distribuição por semana")
    # A visão semanal cobre a grade inteira de propósito (o mês todo, ou todos os
    # meses em "Todo o período"): é a comparação *entre* semanas, mesmo quando o
    # recorte atual é uma semana só. Mesma decisão das abas de análise.
    grade = metricas.filtrar(df, semanas[0].inicio, semanas[-1].fim, mps)
    charts.renderizar(
        charts.barras_por_semana(metricas.por_semana(grade, semanas)), altura=340)

    ui.titulo_secao("Distribuição por dia")
    charts.renderizar(charts.barras_por_dia(metricas.por_dia(atual)), altura=340)

    ui.titulo_secao(f"Ordens previstas — {rotulo}")
    _tabela_previsao(atual)


# --------------------------------------------------------------------------- #
# ABA DE METAS
# --------------------------------------------------------------------------- #
def _formulario_metas(salvas: dict) -> None:
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
                metas.salvar_metas(_engine(), novos)
                st.success("Metas salvas.")
                st.rerun()
            except GestaoFluxoError as exc:
                st.error(exc.mensagem_usuario)


def _cards_necessidade(plano: metas.PlanoMetas) -> None:
    ui.grade_cards([
        {"label": "Dias úteis do mês", "valor": ui.fmt_int(plano.dias_uteis_mes),
         "sub": f"{plano.dias_uteis_restantes} restante(s)", "accent": ui.ACENTOS["sky"]},
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
    for unidade, nome in (("pecas", "peças"), ("minutos", "minutos")):
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
                    else ("meta batida" if a.batida else f"para fechar a meta de {nome}")),
            "estado": estado,
        })
    ui.badges(itens)


def _aba_metas() -> None:
    try:
        df = _fato(config.FONTE_META, _versao_dados())
        salvas = metas.ler_metas(_engine())
    except GestaoFluxoError as exc:
        st.error(exc.mensagem_usuario)
        return

    _formulario_metas(salvas)

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
    st.caption("Realizado medido pela base de Recebimento. Dias úteis = segunda a sexta "
               "(feriados não são descontados).")

    ui.titulo_secao("Meta do mês")
    _badges_alcancado(plano, "mes")
    ui.titulo_secao(f"Meta da semana — {plano.semana_rotulo}")
    _badges_alcancado(plano, "semana")

    ui.titulo_secao("Relógios — quanto falta para bater a meta")
    colunas = st.columns(4)
    relogios = [
        ("mes_pecas", "Mês — peças"), ("mes_minutos", "Mês — minutos"),
        ("semana_pecas", "Semana — peças"), ("semana_minutos", "Semana — minutos"),
    ]
    for coluna, (chave, titulo) in zip(colunas, relogios):
        a = plano.acompanhamentos[chave]
        detalhe = "meta batida" if a.batida else f"faltam {ui.fmt_int(a.falta)}"
        with coluna:
            charts.renderizar(charts.relogio_meta(a.percentual, titulo, detalhe), altura=270)

    if plano.dias_uteis_restantes:
        st.info(
            f"Para fechar o mês faltam **{plano.dias_uteis_restantes} dia(s) útil(eis)** — "
            f"é preciso produzir **{ui.fmt_int(plano.ritmo_necessario['pecas'])} peças** e "
            f"**{ui.fmt_int(plano.ritmo_necessario['minutos'])} minutos** por dia útil."
        )


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #
def _banco_pronto() -> bool:
    """Há banco carregado o bastante para montar o painel?

    Faltar *todas* as tabelas é banco novo: a tela de carga inicial é a resposta
    certa. Faltar só algumas é outra história — acontece quando uma fonte nova
    entra no `config` e o banco em uso ainda não conhece a tabela dela. Aí criar o
    schema (idempotente) resolve, e é bem melhor que mandar o operador rodar uma
    carga completa, que exigiria ter em mãos *todas* as planilhas só para voltar a
    abrir o painel. A tabela nova nasce vazia e a própria aba orienta a subir a
    planilha correspondente.
    """
    engine = _engine()
    faltando = [spec["tabela"] for spec in config.FONTES.values()
                if not database.tabela_existe(engine, spec["tabela"])]
    if not faltando:
        return True
    if len(faltando) == len(config.FONTES):
        return False
    _LOG.info("Criando tabela(s) ausente(s) no banco: %s", ", ".join(faltando))
    database.init_schema(engine)
    return True


def _carga_inicial() -> None:
    """Tela de primeira execução, quando ainda não existe tabela de fato."""
    st.warning("O banco ainda não foi carregado a partir das planilhas.")
    if st.button("Rodar a carga inicial"):
        with _blindar("Carga inicial"):
            _rodar_etl()
            st.rerun()


def main() -> None:
    ui.injetar_tema()

    # Navbar (barra fixa no topo): marca à esquerda, menu de seções ao centro
    # e a ação "Dados" à direita — substitui a antiga sidebar. As colunas do
    # meio e da direita nascem vazias aqui e só são preenchidas mais abaixo,
    # depois de confirmado que há banco pronto (mesma regra da sidebar antiga,
    # que também não aparecia na tela de carga inicial).
    # Proporções: a marca pede pouca largura (logo + título curto), o menu leva
    # a maior fatia para centralizar de fato na faixa, e a ação fica com o
    # mínimo para o botão não esticar de ponta a ponta.
    with st.container(key="navbar"):
        col_brand, col_nav, col_acoes = st.columns(
            [1.5, 4, 1.2], vertical_alignment="center")
        with col_brand:
            ui.cabecalho("Fluxo de Produção")

    # Abrir o engine e olhar o schema é a primeira coisa que toca disco. Falhando
    # aqui não há painel para mostrar, então esta checagem tem tratamento próprio
    # em vez de entrar no `_blindar` de uma seção.
    try:
        pronto = _banco_pronto()
    except GestaoFluxoError as exc:
        _LOG.error("Verificação do banco: %s", exc.detalhe or exc.mensagem_usuario)
        st.error(exc.mensagem_usuario)
        return
    except Exception:  # noqa: BLE001
        codigo = log.novo_codigo()
        _LOG.exception("[%s] falha ao verificar o banco", codigo)
        st.error("Não foi possível abrir o banco de dados. "
                 f"Código do erro: `{codigo}`.")
        return

    if not pronto:
        _carga_inicial()
        return

    # `col_nav` e `col_acoes` nasceram vazias lá em cima, dentro da navbar — só
    # dá para preenchê-las depois de saber que há banco pronto (mesma regra que
    # a sidebar antiga já seguia: nada de navegação numa tela sem dado nenhum).
    renderizadores = {
        "Acompanhamento": _aba_acompanhamento,
        "Previsão": _aba_previsao,
        "Recebimento": lambda: _aba_analise("recebimento"),
        "Envios": lambda: _aba_analise("envios"),
        "Metas": _aba_metas,
    }
    with col_nav:
        aba_ativa = st.segmented_control(
            "Navegação", list(renderizadores), default="Acompanhamento",
            required=True, label_visibility="collapsed", key="aba_ativa",
        )
    # `use_container_width=False`: o botão se mede pelo próprio rótulo. Esticado
    # na coluna inteira ele virava uma barra larga solta no canto, que era boa
    # parte do desconforto do layout anterior.
    with col_acoes, _blindar("Dados"):
        with st.popover("Dados", use_container_width=False):
            _menu_dados()

    # Sticky/scroll e hamburguer só fazem sentido com a barra já montada, então
    # o script entra depois de as três colunas estarem preenchidas.
    ui.navbar_comportamento()

    # Só a aba ativa é blindada e renderizada — mesmo isolamento de falha que
    # as antigas `st.tabs` já davam (um erro aqui não derruba a navbar acima).
    with _blindar(aba_ativa):
        renderizadores[aba_ativa]()


if __name__ == "__main__":
    # Última linha de defesa. Se algo escapar de tudo acima (falha ao injetar o
    # tema, ao desenhar o cabeçalho, ao criar as abas), o operador ainda recebe
    # uma tela explicada em vez do stack trace vermelho do Streamlit.
    try:
        main()
    except Exception:  # noqa: BLE001
        _codigo = log.novo_codigo()
        _LOG.exception("[%s] falha não tratada no topo do app", _codigo)
        st.error(
            "O painel não conseguiu carregar. Recarregue a página; se persistir, "
            f"informe o código `{_codigo}` ao suporte."
        )
