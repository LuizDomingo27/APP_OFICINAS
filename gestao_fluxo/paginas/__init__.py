"""Camada de apresentação — uma tela por módulo, e o registro que as liga ao menu.

Estrutura:

    comum.py           -> blindagem, carga do fato e filtros compartilhados
    dados.py           -> menu "Dados": upload, carga, histórico (a única escrita)
    analise.py         -> Recebimento e Envios (mesma tela, parametrizada)
    acompanhamento.py  -> saldo em aberto e fluxo por matéria-prima
    previsao.py        -> agenda de retorno e risco de prazo
    status.py          -> em que estágio do fluxo cada ordem parou
    metas.py           -> cadastro, diluição e relógios

Regra de dependência: `paginas` -> `servicos` -> domínio (`metricas`, `metas`,
`etl`, `db`). Nenhuma página importa outra — o que duas telas compartilham sobe
para `comum.py`. É isso que permite mexer numa aba sem risco de mover outra.

`REGISTRO` é a única fonte da navegação: o rótulo que aparece na navbar e a
função que desenha a tela ficam no mesmo lugar, então acrescentar uma seção é
uma linha aqui e um módulo novo ao lado — `app.py` não muda.
"""
from __future__ import annotations

from collections.abc import Callable

from . import acompanhamento, analise, dados, metas, previsao, status

#: {rótulo na navbar: função que renderiza a seção}. A ordem é a da barra, e a
#: primeira chave é a seção aberta por padrão.
REGISTRO: dict[str, Callable[[], None]] = {
    "Acompanhamento": acompanhamento.renderizar,
    "Previsão": previsao.renderizar,
    "Status": status.renderizar,
    "Recebimento": lambda: analise.renderizar("recebimento"),
    "Envios": lambda: analise.renderizar("envios"),
    "Metas": metas.renderizar,
}

SECAO_PADRAO = next(iter(REGISTRO))

__all__ = ["REGISTRO", "SECAO_PADRAO", "dados"]
