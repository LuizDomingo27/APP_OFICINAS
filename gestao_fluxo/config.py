"""Configuração central: caminhos, nomes de coluna das planilhas e chaves de meta.

Mantém num só lugar tudo que é "mágico" no domínio, para que as regras fiquem
explícitas e testáveis, e não espalhadas em strings soltas pelo código.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #
PACKAGE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = PACKAGE_DIR.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
DB_PATH: Path = DATA_DIR / "fluxo_producao.db"
SCHEMA_DIR: Path = PACKAGE_DIR / "db"


def caminho_schema(arquivo: str) -> Path:
    """Caminho do schema do dialeto em uso — ver `db/dialeto.py`."""
    return SCHEMA_DIR / arquivo


# --------------------------------------------------------------------------- #
# Conexão com o banco
# --------------------------------------------------------------------------- #
#: Variável de ambiente que carrega a URL SQLAlchemy do banco de produção.
VAR_URL_BANCO: str = "DATABASE_URL"


def _carregar_dotenv() -> None:
    """Lê o `.env` da raiz do projeto, se houver.

    O arquivo guarda a senha do banco e por isso não entra no repositório (ver
    `.gitignore`). O import é opcional de propósito: sem o python-dotenv instalado
    o app continua subindo, apenas exigindo a variável já no ambiente.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


_carregar_dotenv()


def url_do_banco() -> str:
    """URL do banco: Postgres quando configurado, SQLite local caso contrário.

    A URL vem do ambiente e nunca do código — ela carrega a senha do banco. Sem a
    variável definida o app segue funcionando no SQLite local, que é o que permite
    clonar o projeto numa máquina nova e rodar sem nenhum setup de infraestrutura.

    O `postgres://` que o painel do Supabase exibe é aceito e reescrito: o
    SQLAlchemy 2 só reconhece o esquema `postgresql://`, e colar a URL do painel
    direto é o erro mais fácil de cometer aqui.
    """
    url = os.environ.get(VAR_URL_BANCO, "").strip()
    if not url:
        return f"sqlite:///{DB_PATH}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url

# Planilhas de origem (ficam na raiz do projeto)
EXCEL_ENVIOS: Path = PROJECT_ROOT / "ENVIOS_OFICINAS.xlsx"
EXCEL_RECEBIMENTO: Path = PROJECT_ROOT / "RECEBIMENTO.xlsx"
EXCEL_ACOMPANHAMENTO: Path = PROJECT_ROOT / "ACOMPANHAMENTO.xlsx"
EXCEL_DE_PARA: Path = PROJECT_ROOT / "de_para_oficinas.xlsx"

# --------------------------------------------------------------------------- #
# Normalização (só texto — nenhum filtro que altere totais)
# --------------------------------------------------------------------------- #
MP_A_CLASSIFICAR: str = "A CLASSIFICAR"
MP_ROTULOS_SEM_INFO: frozenset = frozenset({"SEM MP INFORMADA", "SEM MP"})

OFICINA_A_CLASSIFICAR: str = "A CLASSIFICAR"
OFICINA_PLACEHOLDERS: frozenset = frozenset({"", "0", "NAO INFORMADO", "NÃO INFORMADO"})

# --------------------------------------------------------------------------- #
# Modo de carga
# --------------------------------------------------------------------------- #
# INCREMENTAL   -> a planilha só acrescenta o que ainda não está no banco. O banco
#                  é o histórico acumulado; subir a mesma planilha duas vezes não
#                  duplica nada (ver database.calcular_identidade).
# SUBSTITUICAO  -> a tabela é esvaziada e regravada com o conteúdo do arquivo.
#                  Só o Acompanhamento usa: ele é um retrato do que está em aberto
#                  *agora*, e a linha some da origem quando a ordem é recebida.
#                  Acrescentar sem apagar deixaria ordens concluídas para sempre
#                  na lista de pendências.
MODO_INCREMENTAL: str = "incremental"
MODO_SUBSTITUICAO: str = "substituicao"

# --------------------------------------------------------------------------- #
# Mapa planilha -> tabela de fato
# --------------------------------------------------------------------------- #
# Cada entrada define de qual coluna da planilha sai cada campo do fato. O campo
# "data" aponta para a coluna que representa o evento daquela planilha.
FONTES: dict = {
    "acompanhamento": {
        "tabela": "fato_acompanhamento",
        "rotulo": "Acompanhamento",
        "modo": MODO_SUBSTITUICAO,
        "colunas": {
            "om": "ORDEM MESTRE", "oficina": "OFICINA", "data": "ENVIO",
            "qtd_pecas": "QTD", "minutos": "MINUTOS", "mp": "MP",
            "deadline": "DEAD LINE",
        },
    },
    "recebimento": {
        "tabela": "fato_recebimento",
        "rotulo": "Recebimento",
        "modo": MODO_INCREMENTAL,
        "colunas": {
            "om": "ORDEM MESTRE", "oficina": "OFICINA", "data": "DIA",
            "qtd_pecas": "REAL CORTADO", "minutos": "MINUTOS", "mp": "MP",
        },
    },
    "envios": {
        "tabela": "fato_envios",
        "rotulo": "Envios",
        "modo": MODO_INCREMENTAL,
        "colunas": {
            "om": "ORDEM", "oficina": "OFICINA", "data": "ENVIO",
            "qtd_pecas": "QTD", "minutos": "MINUTOS", "mp": "MP",
        },
    },
}


def arquivo_da_fonte(fonte: str) -> Path:
    """Planilha de origem de cada fonte (função para respeitar overrides em teste)."""
    return {
        "acompanhamento": EXCEL_ACOMPANHAMENTO,
        "recebimento": EXCEL_RECEBIMENTO,
        "envios": EXCEL_ENVIOS,
    }[fonte]


CAMPOS_FATO = ["oficina", "data", "mp", "qtd_pecas", "minutos", "om"]

# Campos além do núcleo comum. Só o Acompanhamento carrega prazo, porque é a única
# base que representa saldo em aberto — nas outras a linha já é um fato consumado.
CAMPOS_EXTRA: dict = {"acompanhamento": ["deadline"]}


def campos_da_fonte(fonte: str) -> list:
    """Colunas da tabela de fato daquela fonte, na ordem de gravação."""
    return CAMPOS_FATO + CAMPOS_EXTRA.get(fonte, [])


def modo_da_fonte(fonte: str) -> str:
    """Como a fonte é gravada: acrescenta ao histórico ou substitui o retrato."""
    return FONTES[fonte].get("modo", MODO_INCREMENTAL)


# --------------------------------------------------------------------------- #
# Acompanhamento — o que está em aberto para receber
# --------------------------------------------------------------------------- #
# Quantos dias antes do prazo uma ordem entra em "vence em breve".
PRAZO_ALERTA_DIAS: int = 7

STATUS_ATRASADO: str = "Atrasado"
STATUS_VENCE_BREVE: str = "Vence em breve"
STATUS_NO_PRAZO: str = "No prazo"
STATUS_SEM_PRAZO: str = "Sem prazo"

# Ordem de exibição: do mais crítico para o menos crítico.
STATUS_PRAZO: tuple = (
    STATUS_ATRASADO, STATUS_VENCE_BREVE, STATUS_NO_PRAZO, STATUS_SEM_PRAZO,
)

# --------------------------------------------------------------------------- #
# Metas — 6 chaves (mês / semana / dia) x (peças / minutos)
# --------------------------------------------------------------------------- #
METAS_CHAVES: dict = {
    "mes_pecas": "Meta mensal — peças",
    "mes_minutos": "Meta mensal — minutos",
    "semana_pecas": "Meta semanal — peças",
    "semana_minutos": "Meta semanal — minutos",
    "dia_pecas": "Meta diária — peças",
    "dia_minutos": "Meta diária — minutos",
}

# Base usada para medir o realizado contra a meta ("de acordo com o que recebemos").
FONTE_META: str = "recebimento"
