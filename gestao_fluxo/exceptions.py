"""Exceções de domínio com mensagens amigáveis em português.

Cada camada levanta a exceção específica da sua responsabilidade. A UI captura
`GestaoFluxoError` (a base) e mostra `.mensagem_usuario` ao operador, sem vazar
stack trace. O detalhe técnico fica em `.detalhe` para o log.
"""
from __future__ import annotations


class GestaoFluxoError(Exception):
    """Base de todas as exceções do sistema."""

    mensagem_usuario: str = "Ocorreu um erro inesperado no sistema."

    def __init__(self, detalhe: str = "", mensagem_usuario: str | None = None) -> None:
        self.detalhe = detalhe
        if mensagem_usuario is not None:
            self.mensagem_usuario = mensagem_usuario
        super().__init__(detalhe or self.mensagem_usuario)


class FonteDeDadosError(GestaoFluxoError):
    """Falha ao ler/validar uma planilha de origem."""

    mensagem_usuario = "Não foi possível ler uma das planilhas de origem. Verifique o arquivo e tente novamente."


class ETLError(GestaoFluxoError):
    """Falha durante a transformação/carga do ETL."""

    mensagem_usuario = "Falha ao processar e carregar os dados. Nenhuma alteração foi gravada."


class BancoDeDadosError(GestaoFluxoError):
    """Falha de acesso ao banco de dados."""

    mensagem_usuario = "Não foi possível acessar o banco de dados. Rode a carga (ETL) e tente de novo."


class RelatorioError(GestaoFluxoError):
    """Falha ao montar a planilha de download."""

    # Falhar o Excel não pode derrubar a tela: a tabela ao lado continua válida e
    # é ela que responde a pergunta do operador. Por isso a mensagem trata o
    # download como um extra indisponível, não como perda dos dados.
    mensagem_usuario = ("Não foi possível gerar a planilha para download. "
                        "Os dados exibidos na tela continuam corretos.")
