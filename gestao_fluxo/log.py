"""Log técnico da aplicação — o outro lado do tratamento de exceções.

A UI mostra `.mensagem_usuario` (amigável, sem stack trace). O detalhe técnico
tem que ir para algum lugar, senão a falha some: o operador vê "não foi possível
ler a planilha" e ninguém consegue descobrir qual coluna quebrou.

Cada falha inesperada recebe um **código curto** (ex.: `a3f9c1`) que aparece na
tela e no arquivo de log. O operador lê o código para quem for investigar, e o
traceback completo é achado com uma busca só.

O arquivo rotaciona em 1 MB (5 gerações) para não crescer sem limite numa
máquina de chão de fábrica que nunca é limpa.
"""
from __future__ import annotations

import logging
import uuid
from logging.handlers import RotatingFileHandler

from . import config

ARQUIVO_LOG = config.DATA_DIR / "gestao_fluxo.log"

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_configurado = False


def configurar() -> None:
    """Liga o log em arquivo + console. Idempotente (o Streamlit reexecuta o script)."""
    global _configurado
    if _configurado:
        return

    raiz = logging.getLogger("gestao_fluxo")
    raiz.setLevel(logging.INFO)
    raiz.propagate = False  # sem isso o Streamlit duplica cada linha no terminal

    try:
        ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            ARQUIVO_LOG, maxBytes=1_000_000, backupCount=5, encoding="utf-8",
        )
        arquivo.setFormatter(logging.Formatter(_FORMATO))
        raiz.addHandler(arquivo)
    except OSError:
        # Disco cheio ou pasta sem permissão não podem derrubar o app: o console
        # abaixo continua valendo como destino de log.
        pass

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMATO))
    raiz.addHandler(console)

    _configurado = True


def obter(nome: str) -> logging.Logger:
    """Logger de um módulo, já com o log configurado."""
    configurar()
    return logging.getLogger(f"gestao_fluxo.{nome}")


def novo_codigo() -> str:
    """Código curto que liga a mensagem da tela à linha do arquivo de log."""
    return uuid.uuid4().hex[:6]
