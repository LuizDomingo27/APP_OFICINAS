"""Ponto de entrada do painel — tema, navbar e roteamento. Nada além disso.

Este arquivo não sabe o que é uma meta, uma ordem em aberto ou uma previsão.
Ele monta a moldura (barra fixa no topo), confirma que há banco utilizável e
entrega o desenho da seção ativa a `gestao_fluxo.paginas`.

Arquitetura, de fora para dentro:

    app.py             -> moldura e roteamento
    paginas/           -> uma tela por módulo
    servicos.py        -> engine, cache, ETL, uploads (a ponte com o Streamlit)
    metricas / metas   -> regras de cálculo, pandas puro, sem Streamlit
    etl / excel / db   -> leitura das planilhas e persistência

Cada seta aponta só para dentro. Nenhuma camada de baixo importa uma de cima, e
é isso que mantém as regras de cálculo testáveis sem subir uma tela.
"""
from __future__ import annotations

import streamlit as st

from gestao_fluxo import log, paginas, servicos, ui
from gestao_fluxo.exceptions import GestaoFluxoError
from gestao_fluxo.paginas import comum

st.set_page_config(page_title="Fluxo de Produção", layout="wide")

_LOG = log.obter("app")


def _navbar_marca():
    """Abre a barra fixa e devolve as colunas do menu e das ações.

    As duas nascem vazias: só dá para preenchê-las depois de confirmado que há
    banco pronto (mesma regra que a sidebar antiga já seguia — nada de navegação
    numa tela sem dado nenhum).

    Proporções: a marca pede pouca largura (logo + título curto), o menu leva a
    maior fatia para centralizar de fato na faixa, e a ação fica com o mínimo
    para o botão não esticar de ponta a ponta.
    """
    with st.container(key="navbar"):
        col_brand, col_nav, col_acoes = st.columns(
            [1.5, 4, 1.2], vertical_alignment="center")
        with col_brand:
            ui.cabecalho("Fluxo de Produção")
    return col_nav, col_acoes


def _banco_utilizavel() -> bool | None:
    """Confere o schema. Devolve None quando nem a checagem foi possível.

    Abrir o engine e olhar o schema é a primeira coisa que toca disco. Falhando
    aqui não há painel para mostrar, então esta checagem tem tratamento próprio
    em vez de entrar na blindagem de uma seção.
    """
    try:
        return servicos.schema_pronto()
    except GestaoFluxoError as exc:
        _LOG.error("Verificação do banco: %s", exc.detalhe or exc.mensagem_usuario)
        st.error(exc.mensagem_usuario)
        return None
    except Exception:  # noqa: BLE001
        codigo = log.novo_codigo()
        _LOG.exception("[%s] falha ao verificar o banco", codigo)
        st.error("Não foi possível abrir o banco de dados. "
                 f"Código do erro: `{codigo}`.")
        return None


def main() -> None:
    ui.injetar_tema()
    col_nav, col_acoes = _navbar_marca()

    pronto = _banco_utilizavel()
    if pronto is None:
        return
    if not pronto:
        paginas.dados.carga_inicial()
        return

    with col_nav:
        secao = st.segmented_control(
            "Navegação", list(paginas.REGISTRO), default=paginas.SECAO_PADRAO,
            required=True, label_visibility="collapsed", key="aba_ativa",
        )
    # `use_container_width=False`: o botão se mede pelo próprio rótulo. Esticado
    # na coluna inteira ele virava uma barra larga solta no canto, que era boa
    # parte do desconforto do layout anterior.
    with col_acoes, comum.blindar("Dados"):
        with st.popover("Dados", use_container_width=False):
            paginas.dados.menu()

    # Sticky/scroll e hamburguer só fazem sentido com a barra já montada, então
    # o script entra depois de as três colunas estarem preenchidas.
    ui.navbar_comportamento()

    # Só a seção ativa é renderizada, e blindada por fora: um erro aqui não
    # derruba a navbar acima. Dentro da página, cada bloco tem blindagem própria
    # (ver paginas.comum.bloco), então uma tabela quebrada não apaga os cards.
    with comum.blindar(secao):
        paginas.REGISTRO[secao]()


if __name__ == "__main__":
    # Última linha de defesa. Se algo escapar de tudo acima (falha ao injetar o
    # tema, ao desenhar a marca, ao montar a navbar), o operador ainda recebe
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
