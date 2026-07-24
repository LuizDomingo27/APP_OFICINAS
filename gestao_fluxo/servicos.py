"""Camada de aplicação — o que as telas usam para chegar aos dados.

Fica entre o domínio puro (`metricas`, `metas`, `etl`, `db`) e as páginas
(`paginas/`). É o **único** módulo que conhece ao mesmo tempo as duas coisas:
as regras do domínio e o runtime do Streamlit (cache, `session_state`).

Por que existe: o Streamlit reexecuta o script inteiro a cada clique. Decidir
quando reabrir o engine, quando reler o banco e quando invalidar o cache é uma
responsabilidade de verdade — não é "código de tela". Enquanto morava no meio
das telas, cada página precisava lembrar de passar a versão dos dados na mão, e
qualquer página nova nascia com uma chance a mais de ler um cache velho.

Regra de dependência: `paginas/` -> `servicos` -> domínio. Nada aqui importa
`paginas`, e nada do domínio importa este módulo — é o que mantém `metricas` e
`metas` testáveis sem Streamlit nenhum.
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.engine import Engine

from . import config, log, metricas
from .db import database
from .etl import PreviaFonte, executar_etl, prever_carga
from .exceptions import UploadError

_LOG = log.obter("servicos")

#: Janela do cache de leitura do fato. É a rede de segurança para o painel
#: aberto passivamente noutra aba: uma carga feita numa sessão limpa o cache só
#: do processo que a atendeu, então sem `ttl` a outra aba nunca perceberia a
#: mudança. Com ele, qualquer sessão relê o banco em no máximo 5 minutos por
#: conta própria — e `invalidar_cache()` força a releitura na hora.
TTL_FATO_SEGUNDOS = 300

_CHAVE_VERSAO = "versao_dados"
_CHAVE_ULTIMO_ETL = "ultimo_etl"
_CHAVE_UPLOADS = "pasta_uploads"


# =========================================================================== #
# ENGINE E VERSÃO DOS DADOS
# =========================================================================== #
@st.cache_resource
def engine() -> Engine:
    """Engine do banco, um por processo (não por sessão)."""
    return database.get_engine()


def versao_dados() -> int:
    """Contador que sobe a cada carga/recarga — a chave de invalidação do cache."""
    return st.session_state.get(_CHAVE_VERSAO, 0)


def invalidar_cache() -> None:
    """Descarta o cache de leitura e marca uma versão nova dos dados.

    Usado depois de uma carga e pelo botão "Atualizar dados agora", que existe
    para quando alguém subiu planilhas noutra sessão (ou editou o Supabase por
    fora): sem ele a única saída era reiniciar o servidor.
    """
    st.session_state[_CHAVE_VERSAO] = versao_dados() + 1
    st.cache_data.clear()


# =========================================================================== #
# LEITURA DO FATO
# =========================================================================== #
@st.cache_data(show_spinner=False, ttl=TTL_FATO_SEGUNDOS)
def _ler_fato(fonte: str, _versao: int) -> pd.DataFrame:
    """Leitura crua, memorizada. `_versao` participa da chave do cache."""
    return metricas.carregar_fato(engine(), fonte)


def fato(fonte: str) -> pd.DataFrame:
    """Tabela de fato completa, em cache.

    As páginas chamam esta função e não `_ler_fato`: a versão dos dados entra
    aqui dentro, então nenhuma tela precisa lembrar de repassá-la — era essa a
    parte que dava para esquecer e ler cache velho sem ninguém notar.
    """
    return _ler_fato(fonte, versao_dados())


# =========================================================================== #
# SCHEMA
# =========================================================================== #
def _banco_pronto() -> bool:
    """Há banco carregado o bastante para montar o painel?

    Faltar *todas* as tabelas é banco novo: a tela de carga inicial é a resposta
    certa. Faltar só algumas é outra história — acontece quando uma fonte nova
    entra no `config` e o banco em uso ainda não conhece a tabela dela. Aí criar
    o schema (idempotente) resolve, e é bem melhor que mandar o operador rodar
    uma carga completa, que exigiria ter em mãos *todas* as planilhas só para
    voltar a abrir o painel. A tabela nova nasce vazia e a própria aba orienta a
    subir a planilha correspondente.
    """
    eng = engine()
    tabelas = {spec["tabela"] for spec in config.FONTES.values()}
    # Uma consulta só em vez de uma por fato — ver database.tabelas_existentes.
    faltando = tabelas - database.tabelas_existentes(eng, tabelas)
    if not faltando:
        return True
    if faltando == tabelas:              # nenhuma existe -> banco novo
        return False
    _LOG.info("Criando tabela(s) ausente(s) no banco: %s", ", ".join(sorted(faltando)))
    database.init_schema(eng)
    return True


@st.cache_data(show_spinner=False)
def _schema_pronto(_versao: int) -> bool:
    """Cache de `_banco_pronto`, resolvido uma vez por versão dos dados.

    A verificação rodava a cada rerun do Streamlit (todo clique de filtro ou
    troca de aba), disparando uma consulta de existência por tabela de fato. O
    schema, porém, só muda quando o ETL cria/recria tabelas — e `rodar_etl` já
    invalida o cache ao final, então uma tabela recém-criada é reavaliada na
    execução seguinte. Entre cargas, o custo de rede dessa checagem cai a zero.

    Exceções (`BancoDeDadosError` e afins) NÃO são memorizadas pelo cache do
    Streamlit: uma falha transitória de rede é retentada no rerun seguinte em
    vez de ficar presa.
    """
    return _banco_pronto()


def schema_pronto() -> bool:
    """Fachada de `_schema_pronto` já com a versão dos dados aplicada."""
    return _schema_pronto(versao_dados())


# =========================================================================== #
# CARGA (ETL)
# =========================================================================== #
def rodar_etl(caminhos: dict | None = None) -> None:
    """Executa a carga e invalida tudo que dependia dos dados antigos."""
    with st.spinner("Lendo as planilhas e atualizando o banco..."):
        relatorio = executar_etl(engine(), caminhos=caminhos)
    st.session_state[_CHAVE_ULTIMO_ETL] = {
        "quando": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rel": relatorio,
    }
    invalidar_cache()


def prever(caminhos: dict) -> list[PreviaFonte]:
    """O que a carga faria, sem gravar nada — alimenta a tela de confirmação."""
    return prever_carga(engine(), caminhos=caminhos)


def ultimo_etl() -> dict | None:
    """Resumo da última carga feita *nesta sessão*, ou None."""
    return st.session_state.get(_CHAVE_ULTIMO_ETL)


def historico_cargas(limite: int = 15) -> pd.DataFrame:
    """Últimas cargas registradas no banco (todas as sessões)."""
    return database.historico_cargas(engine(), limite=limite)


# =========================================================================== #
# UPLOAD DAS PLANILHAS
# =========================================================================== #
def _pasta_uploads() -> Path:
    """Pasta temporária desta sessão, onde os arquivos enviados são guardados.

    O upload precisa sobreviver ao rerun que acontece entre "Analisar" e
    "Confirmar": o Streamlit reexecuta o script inteiro a cada clique, e o
    objeto devolvido pelo `file_uploader` só pode ser lido uma vez.
    """
    if _CHAVE_UPLOADS not in st.session_state:
        try:
            st.session_state[_CHAVE_UPLOADS] = tempfile.mkdtemp(prefix="fluxo_upload_")
        except OSError as exc:
            raise UploadError(f"Falha ao criar a pasta temporária: {exc}") from exc
    return Path(st.session_state[_CHAVE_UPLOADS])


def salvar_enviados(enviados: dict) -> dict:
    """Grava os arquivos enviados em disco e devolve {fonte: caminho}.

    A gravação é o primeiro passo que toca o disco e falha por motivo de
    ambiente (disco cheio, pasta sem permissão), não por conteúdo da planilha.
    Sem esta tradução o `OSError` subia cru até a blindagem genérica da tela e o
    operador recebia um código de erro em vez da causa, que ele mesmo resolve.
    """
    destino = _pasta_uploads()
    caminhos = {}
    for fonte, arquivo in enviados.items():
        alvo = destino / f"{fonte}_{arquivo.name}"
        try:
            alvo.write_bytes(arquivo.getbuffer())
        except OSError as exc:
            raise UploadError(
                f"Falha ao gravar '{arquivo.name}' em {destino}: {exc}") from exc
        caminhos[fonte] = alvo
    return caminhos
