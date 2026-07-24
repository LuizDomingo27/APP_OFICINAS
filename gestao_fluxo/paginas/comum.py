"""O que todas as páginas compartilham: blindagem de falha, carga e filtros.

Nada específico de uma tela mora aqui. A régua é simples: entra quando duas
páginas precisariam escrever a mesma coisa, e o que muda entre elas cabe num
parâmetro. Filtro que só existe numa aba (o de situação do prazo, o de período
do fluxo por MP) fica na página dela.
"""
from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import streamlit as st

from gestao_fluxo import config, log, metas, metricas, servicos, ui
from gestao_fluxo.exceptions import GestaoFluxoError

_LOG = log.obter("paginas")

#: Rótulo do recorte "sem filtro de mês". Usado pela Previsão e pelo fluxo por
#: MP, as duas telas cuja pergunta atravessa a virada do mês.
PERIODO_TODO = "Todo o período"
MES_INTEIRO = "Mês inteiro"


# =========================================================================== #
# BLINDAGEM
# =========================================================================== #
@contextmanager
def blindar(secao: str):
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


@contextmanager
def bloco(nome: str):
    """Blindagem de uma seção *dentro* de uma página.

    A página inteira já roda dentro de `blindar`, mas isso é grosso demais: um
    gráfico com dado estranho apagava também os cards acima dele, que estavam
    corretos e respondiam a pergunta do operador. Envolvendo cada bloco
    separável (gráfico, tabela, download), a falha fica do tamanho do que
    falhou e o resto da tela continua de pé.
    """
    with blindar(nome):
        yield


# =========================================================================== #
# CARGA DO FATO
# =========================================================================== #
def carregar_fato(fonte: str, *, vazio: str) -> pd.DataFrame | None:
    """Lê uma tabela de fato e trata os dois desfechos que não são dados.

    Devolve `None` quando não há o que desenhar — a página só precisa dar
    `return`. Os quatro pontos de entrada repetiam este mesmo try/except mais a
    checagem de vazio, e era o tipo de trecho em que uma aba nova nasce sem o
    tratamento porque ninguém lembrou de copiá-lo.
    """
    try:
        df = servicos.fato(fonte)
    except GestaoFluxoError as exc:
        _LOG.error("Leitura de %s: %s", fonte, exc.detalhe or exc.mensagem_usuario)
        st.error(exc.mensagem_usuario)
        return None
    if df.empty:
        st.warning(vazio)
        return None
    return df


# =========================================================================== #
# FILTROS
# =========================================================================== #
def opcoes_de_semana(semanas: list) -> list:
    """['Mês inteiro', 'Semana 1 (...)', ...] — a lista dos seletores de semana."""
    return [MES_INTEIRO] + [s.rotulo for s in semanas]


def resolver_semana(escolha: str, semanas: list, ano: int, mes: int) -> tuple:
    """(inicio, fim, rotulo) a partir do que foi escolhido no seletor de semana."""
    if escolha == MES_INTEIRO:
        inicio, fim = metas.limites_do_mes(ano, mes)
        return inicio, fim, metricas.rotulo_mes(ano, mes)
    semana = semanas[opcoes_de_semana(semanas).index(escolha) - 1]
    return semana.inicio, semana.fim, semana.rotulo


def barra_filtros(df: pd.DataFrame, chave: str):
    """Mês / semana / MP / oficina. Uma barra por aba, cada aba independente.

    Devolve (inicio, fim, mps, oficinas, semanas, rotulo), ou `None` quando a
    base não tem nenhuma data válida para recortar.
    """
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
    escolha = col2.selectbox("Análise", opcoes_de_semana(semanas), key=f"sem_{chave}")
    mps = col3.multiselect("Matéria-prima (MP)", sorted(df["mp"].dropna().unique()),
                           key=f"mp_{chave}")
    oficinas = col4.multiselect("Oficina", sorted(df["oficina"].dropna().unique()),
                                key=f"of_{chave}")

    inicio, fim, rotulo = resolver_semana(escolha, semanas, ano, mes)
    return inicio, fim, mps, oficinas, semanas, rotulo


def seletor_mes_opcional(coluna, chave: str, meses: list):
    """Seletor de mês que aceita `PERIODO_TODO` como primeira opção.

    Usado pelas telas cuja pergunta atravessa a virada do mês (Previsão e fluxo
    por MP). Devolve `PERIODO_TODO` ou a tupla (ano, mes).
    """
    return coluna.selectbox(
        "Mês", [PERIODO_TODO] + meses, key=chave,
        format_func=lambda m: m if m == PERIODO_TODO else metricas.rotulo_mes(*m),
    )


def seletor_semana_desligado(coluna, rotulo: str, chave: str) -> None:
    """Caixa de semana inerte, exibida enquanto nenhum mês foi escolhido.

    A chave é própria (e não a do seletor real) para o Streamlit não tentar
    casar o valor guardado com uma lista de opções que mudou de natureza — o
    widget passaria a carregar o rótulo de uma semana que não existe mais.
    """
    coluna.selectbox(rotulo, [PERIODO_TODO], key=chave, disabled=True)


# =========================================================================== #
# CARDS RECORRENTES
# =========================================================================== #
#: (chave da unidade, nome exibido) — a ordem em que peças e minutos aparecem.
UNIDADES = (("pecas", "peças"), ("minutos", "minutos"))

ACENTO_STATUS = {
    config.STATUS_ATRASADO: ui.ACENTOS["rose"],
    config.STATUS_VENCE_BREVE: ui.ACENTOS["amber"],
    config.STATUS_NO_PRAZO: ui.ACENTOS["emerald"],
    config.STATUS_SEM_PRAZO: ui.ACENTOS["sky"],
}
