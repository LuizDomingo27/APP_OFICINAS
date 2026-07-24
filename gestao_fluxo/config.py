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

#: Onde caem os backups datados do Postgres (ver `db/migracao.py --backup`).
#: Fora do controle de versão: são cópias grandes e regeneráveis do banco.
BACKUPS_DIR: Path = DATA_DIR / "backups"


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
EXCEL_PREVISAO: Path = PROJECT_ROOT / "PREVISAO.xlsx"
EXCEL_STATUS: Path = PROJECT_ROOT / "STATUS.xlsx"
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
    # Previsão é a agenda do que ainda vai voltar das oficinas. O campo "data"
    # aponta para RECEBIMENTO — e não para ENVIO, como nas outras — porque aqui o
    # evento que interessa é a **data prevista de retorno**: é ela que responde
    # "o que temos para receber nesta semana". ENVIO e DEAD LINE vêm junto como
    # campos extras, para medir prazo sem precisar cruzar com outra base.
    #
    # Substituição, pelo mesmo motivo do Acompanhamento: é um retrato do que está
    # previsto *agora*. A ordem some da planilha quando volta, e acumular deixaria
    # ordens já recebidas para sempre na previsão.
    "previsao": {
        "tabela": "fato_previsao",
        "rotulo": "Previsão",
        "modo": MODO_SUBSTITUICAO,
        "colunas": {
            "om": "ORDEM MESTRE", "oficina": "OFICINA", "data": "RECEBIMENTO",
            "qtd_pecas": "QTD", "minutos": "MINUTOS", "mp": "MP",
            "deadline": "DEAD LINE", "envio": "ENVIO",
        },
    },
    # Status são as ordens em aberto que ainda NÃO têm data prevista de retorno: a
    # origem exclui da planilha toda ordem que já entrou na Previsão (confirmado
    # pelo time). Acompanhamento = Previsão + Status, sem interseção. O campo que
    # sustenta a tela é `estagio` (coluna RECEBIMENTO da planilha) — ver
    # ESTAGIOS_CANONICOS logo abaixo para o porquê do nome.
    #
    # Substituição, pelo mesmo motivo do Acompanhamento e da Previsão: é o retrato
    # do agora, e a linha some da origem quando a ordem é recebida.
    "status": {
        "tabela": "fato_status",
        "rotulo": "Status",
        "modo": MODO_SUBSTITUICAO,
        "colunas": {
            "om": "ORDEM MESTRE", "oficina": "OFICINA", "data": "ENVIO",
            "qtd_pecas": "QTD", "minutos": "MINUTOS", "mp": "MP",
            "deadline": "DEAD LINE", "estagio": "RECEBIMENTO",
            "situacao": "SITUAÇÃO",
        },
    },
}


def arquivo_da_fonte(fonte: str) -> Path:
    """Planilha de origem de cada fonte (função para respeitar overrides em teste)."""
    return {
        "acompanhamento": EXCEL_ACOMPANHAMENTO,
        "recebimento": EXCEL_RECEBIMENTO,
        "envios": EXCEL_ENVIOS,
        "previsao": EXCEL_PREVISAO,
        "status": EXCEL_STATUS,
    }[fonte]


CAMPOS_FATO = ["oficina", "data", "mp", "qtd_pecas", "minutos", "om"]

# Campos além do núcleo comum. Só as bases que representam ordem ainda em aberto os
# carregam — nas outras a linha já é um fato consumado, e prazo de algo que já
# aconteceu não tem o que acompanhar.
CAMPOS_EXTRA: dict = {
    "acompanhamento": ["deadline"],
    "previsao": ["deadline", "envio"],
    "status": ["deadline", "estagio", "situacao"],
}

#: Extras que são TEXTO, e não data em ISO. A regra padrão de um extra é ser data:
#: `etl.extrair_fonte` e `metricas.carregar_fato` convertem os extras em bloco por
#: ela. Quem está listado aqui fica de fora das duas conversões e recebe
#: normalização própria no ETL (ver etl.normalizar_estagio).
CAMPOS_EXTRA_TEXTO: frozenset = frozenset({"estagio", "situacao"})


def campos_da_fonte(fonte: str) -> list:
    """Colunas da tabela de fato daquela fonte, na ordem de gravação."""
    return CAMPOS_FATO + CAMPOS_EXTRA.get(fonte, [])


def extras_data_da_fonte(fonte: str) -> list:
    """Extras da fonte que são data em ISO — os que gravação e leitura convertem."""
    return [campo for campo in CAMPOS_EXTRA.get(fonte, ())
            if campo not in CAMPOS_EXTRA_TEXTO]


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
# Previsão — o que está agendado para voltar das oficinas
# --------------------------------------------------------------------------- #
# Duas leituras de risco, deliberadamente medidas em cards separados: a mesma ordem
# pode cair nas duas ao mesmo tempo, e um card único somando-as esconderia qual das
# duas está acontecendo (e o total ficaria maior que a soma real de ordens).
#
# FURA_PRAZO -> a data prevista de retorno é POSTERIOR ao prazo. É projeção: a ordem
#               ainda não estourou, e é justamente por isso que o card existe — dá
#               tempo de cobrar a oficina antes do fato.
# VENCIDA    -> o prazo já passou e a ordem continua na previsão, ou seja, não voltou.
#               É o mesmo critério de STATUS_ATRASADO usado no Acompanhamento.
STATUS_PREV_FURA_PRAZO: str = "Previsão fora do prazo"
STATUS_PREV_VENCIDA: str = "Prazo já vencido"

# --------------------------------------------------------------------------- #
# Status — em que estágio do fluxo a ordem em aberto está parada
# --------------------------------------------------------------------------- #
# A coluna RECEBIMENTO da planilha de STATUS não é uma data: ela diz em que etapa
# a ordem está ("Coletando datas", "Ordem extraviada"...). Por isso o campo se
# chama `estagio` e não `recebimento` — já existe uma fonte com esse nome (o fato
# de recebimento de verdade), e reusar a palavra garantiria confusão permanente.
#
# O estágio é digitado à mão na origem e chega com vocabulário sujo: 'devolução'
# em minúsculas ao lado de 'Ordem extraviada', e 'Agua.' como abreviação de
# "Aguardando". O mapa casa por chave sem acento e em caixa alta (ver
# etl.normalizar_estagio).
#
# Estágio fora do mapa é preservado como veio, pela mesma razão de
# `normalizar_oficina`: renomeá-lo à força, ou jogá-lo num balde "Outro",
# esconderia justamente o estágio novo que a origem acabou de criar.
ESTAGIO_SEM_INFO: str = "Sem estágio"

ESTAGIOS_CANONICOS: dict = {
    "COLETANDO DATAS": "Coletando datas",
    "AGUA. REPOSICAO": "Aguardando reposição",
    "AGUA. CHAMADO": "Aguardando chamado",
    "ORDEM EXTRAVIADA": "Ordem extraviada",
    "MONTA ENVIO": "Monta envio",
    "REMANEJAR": "Remanejar",
    "DEVOLUCAO": "Devolução",
}

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
