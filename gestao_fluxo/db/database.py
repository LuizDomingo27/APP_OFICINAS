"""Acesso de baixo nível ao banco: engine, schema e leitura em DataFrame.

Responsabilidade única: falar com o banco. Sem regra de negócio.
Erros do driver viram BancoDeDadosError (mensagem amigável).

O módulo é agnóstico ao banco: fala Postgres (Supabase) em produção e SQLite nos
testes, despachando pelo dialeto do próprio engine. Tudo que difere entre os dois
mora em `dialeto.py` — aqui não deve existir SQL específico de um deles.

A identidade de linha (`calcular_identidade`) mora aqui, e não no ETL, porque é
questão de persistência: é o que o índice único do schema usa para decidir se uma
linha já está gravada. Manter junto evita que o backfill de bancos antigos
(`migrar_schema`) precise importar o ETL, que por sua vez importa este módulo.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from .. import config
from ..exceptions import BancoDeDadosError
from . import dialeto

# Campos que definem a identidade de uma linha de fato. `deadline` fica de fora de
# propósito: só o Acompanhamento o possui, e essa tabela é substituída por inteiro
# a cada carga — incluí-lo tornaria o hash incomparável entre as três tabelas.
CAMPOS_IDENTIDADE = ("om", "oficina", "data", "mp", "qtd_pecas", "minutos")

# Colunas de controle da carga incremental, presentes nas três tabelas de fato.
COLUNAS_CONTROLE = ("hash_linha", "ocorrencia", "carga_id")

TABELAS_FATO = tuple(spec["tabela"] for spec in config.FONTES.values())


def get_engine(db_path: str | Path | None = None) -> Engine:
    """Cria o engine do banco configurado.

    Com `db_path` explícito abre um SQLite naquele arquivo — é assim que cada
    teste pede um banco isolado. Sem argumento, quem decide é
    `config.url_do_banco()`: o Postgres do Supabase quando `DATABASE_URL` estiver
    definida, e o SQLite local caso contrário.

    Abrir o engine é a primeira coisa que o app faz — se falhar (disco cheio,
    pasta somente leitura, driver ausente, credencial errada) a exceção viraria
    stack trace antes de existir qualquer tela. Daí a tradução para
    `BancoDeDadosError` já aqui.
    """
    if db_path is not None:
        return _engine_sqlite(Path(db_path))
    url = config.url_do_banco()
    return _engine_sqlite(config.DB_PATH) if url.startswith("sqlite") else _engine_postgres(url)


def _engine_sqlite(path: Path) -> Engine:
    """Engine sobre arquivo local, com foreign keys ligadas."""
    try:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}", future=True)
    except OSError as exc:
        raise BancoDeDadosError(
            f"Não foi possível preparar a pasta do banco em {path.parent}: {exc}",
            mensagem_usuario=("Não foi possível gravar na pasta de dados. "
                              "Verifique as permissões e o espaço em disco."),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(f"Falha ao abrir o banco em {path}: {exc}") from exc

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):  # pragma: no cover
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def _engine_postgres(url: str) -> Engine:
    """Engine do Supabase, com o pool ajustado ao modo de conexão.

    O Supabase oferece dois modos, e eles pedem configurações opostas:

    * **Session pooler** (porta 5432) entrega uma conexão de verdade, que dura o
      quanto quisermos. Vale manter um pool próprio aqui.
    * **Transaction pooler** (porta 6543) já faz o pooling do lado do Supabase e
      devolve a conexão ao fim de cada transação. Empilhar um segundo pool sobre
      ele desperdiça as conexões do projeto, que no plano gratuito são poucas.

    `pool_pre_ping` existe porque o pooler derruba conexões ociosas sem avisar: sem
    ele, a primeira consulta depois de um período parado morre com "server closed
    the connection" em vez de simplesmente reconectar.
    """
    transacao = ":6543" in url
    extras: dict = ({"poolclass": NullPool} if transacao else
                    {"pool_size": 5, "max_overflow": 2,
                     "pool_recycle": 300, "pool_pre_ping": True})
    try:
        return create_engine(url, future=True, **extras)
    except ModuleNotFoundError as exc:
        raise BancoDeDadosError(
            f"Driver do Postgres ausente: {exc}",
            mensagem_usuario=("O driver do banco de dados não está instalado. "
                              "Rode: pip install -r requirements.txt"),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(
            f"Falha ao abrir o banco Postgres: {exc}",
            mensagem_usuario=("Não foi possível preparar a conexão com o banco. "
                              "Verifique a variável DATABASE_URL."),
        ) from exc


def init_schema(engine: Engine) -> None:
    """Garante o schema atual, migrando bancos anteriores à carga incremental.

    A ordem importa. O schema.sql termina criando os índices ÚNICOS sobre
    (hash_linha, ocorrencia); num banco antigo essas colunas ainda não existem e o
    CREATE INDEX derrubaria o script inteiro. Por isso as colunas são acrescentadas
    e preenchidas *antes* de o schema rodar. Nos bancos novos os dois primeiros
    passos não fazem nada.
    """
    d = dialeto.de(engine)
    migrar_schema(engine)
    try:
        sql = config.caminho_schema(d.arquivo_schema).read_text(encoding="utf-8")
    except OSError as exc:
        raise BancoDeDadosError(f"Não foi possível ler o schema: {exc}") from exc
    try:
        d.executar_schema(engine, sql)
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(f"Falha ao criar o schema: {exc}") from exc


# =========================================================================== #
# IDENTIDADE DA LINHA
# =========================================================================== #
def _coluna_texto(serie: pd.Series) -> pd.Series:
    """Normaliza uma coluna para compor a chave de texto do hash.

    Datas viram ISO e ausentes viram string vazia: o hash precisa ser idêntico
    quer o valor chegue do Excel (texto) ou de volta do SQLite (também texto, mas
    já convertido para datetime em alguns caminhos de leitura).
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie.dt.strftime("%Y-%m-%d").fillna("")
    return serie.astype("object").where(serie.notna(), "").astype(str)


def _chave_identidade(df: pd.DataFrame) -> pd.Series:
    """Texto canônico 'om|oficina|data|mp|qtd|minutos' de cada linha.

    Números são formatados com 4 casas fixas para que 100, 100.0 e 100.0000 —
    todas as três formas em que a quantidade chega do Excel e do SQLite — gerem
    exatamente o mesmo hash.
    """
    om = pd.to_numeric(df["om"], errors="coerce")
    partes = [
        om.map(lambda v: "" if pd.isna(v) else str(int(v))),
        _coluna_texto(df["oficina"]),
        _coluna_texto(df["data"]),
        _coluna_texto(df["mp"]),
        pd.to_numeric(df["qtd_pecas"], errors="coerce").fillna(0.0).map("{:.4f}".format),
        pd.to_numeric(df["minutos"], errors="coerce").fillna(0.0).map("{:.4f}".format),
    ]
    return partes[0].str.cat(partes[1:], sep="|")


def calcular_identidade(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `hash_linha` e `ocorrencia` — a identidade de cada linha.

    `ocorrencia` numera as linhas idênticas *dentro do próprio arquivo* (1, 2, 3).
    É o que permite conviver com duplicata legítima sem abrir a porta para
    duplicata de re-upload: subir a mesma planilha duas vezes reproduz os mesmos
    pares (hash, ocorrencia), que o índice único descarta. Se amanhã a planilha
    trouxer uma terceira cópia da mesma linha, ela entra como ocorrência 3.

    O efeito líquido é "o banco fica com tantas cópias quantas a planilha declara",
    nunca mais — a direção conservadora, que jamais inventa produção.
    """
    out = df.copy()
    if out.empty:
        out["hash_linha"] = pd.Series(dtype="object")
        out["ocorrencia"] = pd.Series(dtype="int64")
        return out
    chave = _chave_identidade(out)
    out["hash_linha"] = chave.map(
        lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()  # noqa: S324
    )
    out["ocorrencia"] = out.groupby("hash_linha").cumcount() + 1
    return out


# =========================================================================== #
# MIGRAÇÃO
# =========================================================================== #
def _colunas(engine: Engine, tabela: str) -> set:
    """Nomes das colunas de uma tabela (conjunto vazio se ela não existe)."""
    if not tabela_existe(engine, tabela):
        return set()
    query, params = dialeto.de(engine).sql_colunas(tabela)
    return set(read_sql(query, engine, params)["name"])


def migrar_schema(engine: Engine) -> dict:
    """Traz bancos SQLite antigos para o formato da carga incremental.

    Devolve {tabela: linhas_preenchidas}. Idempotente: rodar de novo não faz nada.
    Sem esta migração, um banco criado antes desta mudança perderia os 20 mil
    registros já carregados — recriar as tabelas do zero exigiria ter em mãos todas
    as planilhas históricas, que é justamente o que a carga incremental dispensa.

    No Postgres não faz nada, e isso não é omissão: aquele banco nasce completo
    pelo script de `migracao.py`, que copia `hash_linha` e `ocorrencia` já
    calculados do SQLite. Nunca existiu um Postgres nosso sem essas colunas.
    """
    if not dialeto.de(engine).migra_bancos_antigos:
        return {}
    preenchidas: dict = {}
    for tabela in TABELAS_FATO:
        colunas = _colunas(engine, tabela)
        if not colunas:
            continue  # tabela ainda não existe: schema.sql já a cria completa
        faltando = [c for c in COLUNAS_CONTROLE if c not in colunas]
        try:
            with engine.begin() as conn:
                for coluna in faltando:
                    tipo = "INTEGER" if coluna != "hash_linha" else "TEXT"
                    conn.exec_driver_sql(
                        f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            n = _backfill_identidade(engine, tabela)
        except BancoDeDadosError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BancoDeDadosError(
                f"Falha ao migrar a tabela {tabela}: {exc}",
                mensagem_usuario=("Não foi possível atualizar o formato do banco. "
                                  "Restaure o backup da pasta 'data' e tente de novo."),
            ) from exc
        if n:
            preenchidas[tabela] = n
    return preenchidas


def _backfill_identidade(engine: Engine, tabela: str) -> int:
    """Calcula hash/ocorrência das linhas já gravadas que ainda estão sem eles."""
    campos = ", ".join(CAMPOS_IDENTIDADE)
    antigas = read_sql(
        f"SELECT id, {campos} FROM {tabela} WHERE hash_linha IS NULL", engine)
    if antigas.empty:
        return 0
    # A ordem por `id` reproduz a ordem original de gravação, então a numeração de
    # ocorrências sai igual à que o ETL geraria lendo a mesma planilha de novo.
    com_id = calcular_identidade(antigas.sort_values("id"))
    dados = [
        (str(h), int(o), int(i))
        for h, o, i in zip(com_id["hash_linha"], com_id["ocorrencia"], com_id["id"])
    ]
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"UPDATE {tabela} SET hash_linha = ?, ocorrencia = ? WHERE id = ?", dados)
    return len(dados)


def read_sql(query: str, engine: Engine, params: dict | None = None) -> pd.DataFrame:
    """Executa um SELECT e devolve DataFrame. Traduz erros do banco."""
    try:
        with engine.connect() as conn:
            return pd.read_sql_query(text(query), conn, params=params or {})
    except Exception as exc:  # noqa: BLE001
        raise BancoDeDadosError(f"Falha ao consultar o banco: {exc}") from exc


def tabela_existe(engine: Engine, nome: str) -> bool:
    """Indica se uma tabela/view existe — a UI usa para orientar a rodar o ETL."""
    df = read_sql(dialeto.de(engine).sql_tabela_existe(), engine, {"n": nome})
    return not df.empty


def tabelas_existentes(engine: Engine, nomes) -> set:
    """Quais das tabelas pedidas existem, numa ÚNICA consulta.

    Substitui uma rajada de `tabela_existe` — uma ida ao banco por tabela — por uma
    só: lista as tabelas do schema atual e cruza com `nomes` em Python. Numa tela
    Streamlit, que reexecuta o script inteiro a cada clique, o arranque perguntava
    a existência de cada fato separadamente; sobre um Postgres remoto isso somava
    vários round-trips por interação. Ver app._banco_pronto / app._schema_pronto.

    Erros do driver já sobem como `BancoDeDadosError` de dentro de `read_sql`. O
    `"name" in df.columns` protege o caso de um resultado sem linhas: mesmo aí a
    coluna deve vir, mas a checagem evita KeyError se algum driver a suprimir.
    """
    df = read_sql(dialeto.de(engine).sql_listar_tabelas(), engine)
    presentes = set(df["name"]) if "name" in df.columns else set()
    return {nome for nome in nomes if nome in presentes}


# =========================================================================== #
# ESCRITA
# =========================================================================== #
def contar_novas(engine: Engine, tabela: str, df: pd.DataFrame) -> int:
    """Quantas linhas do DataFrame ainda não estão gravadas.

    Serve à prévia mostrada antes de confirmar a carga. Carrega os pares já
    gravados num set em vez de montar um IN gigante: são dezenas de milhares de
    linhas, ordem de grandeza em que o set do Python é mais rápido e não esbarra
    no limite de parâmetros do SQLite.
    """
    if df.empty:
        return 0
    gravados = read_sql(f"SELECT hash_linha, ocorrencia FROM {tabela}", engine)
    if gravados.empty:
        return len(df)
    conhecidos = set(zip(gravados["hash_linha"], gravados["ocorrencia"]))
    novos = [
        par for par in zip(df["hash_linha"], df["ocorrencia"]) if par not in conhecidos
    ]
    return len(novos)


def linhas_para_sql(df: pd.DataFrame, colunas: list) -> list:
    """DataFrame -> lista de tuplas nativas, com ausente virando None.

    Pública porque o script de migração (`migracao.py`) grava por este mesmo
    caminho: é o que garante que uma linha copiada do SQLite chegue ao Postgres
    com exatamente o tratamento de nulos que o ETL daria a ela.
    """
    recorte = df[colunas]
    return [
        tuple(None if pd.isna(v) else v for v in linha)
        for linha in recorte.itertuples(index=False, name=None)
    ]


def _inserir(conn, tabela: str, df: pd.DataFrame, colunas: list,
             carga_id: int | None, ignorar_repetidas: bool) -> int:
    """Insere as linhas e devolve quantas realmente entraram."""
    if df.empty:
        return 0
    dados = df.copy()
    dados["carga_id"] = carga_id
    todas = [*colunas, *COLUNAS_CONTROLE]
    # Descartar o que já existe é trabalho do índice único, dentro do próprio
    # banco: comparar linha a linha em Python custaria uma consulta por registro.
    return dialeto.de(conn).inserir_muitas(
        conn, tabela, todas, linhas_para_sql(dados, todas),
        ignorar_conflito=ignorar_repetidas,
    )


def inserir_novas(conn, tabela: str, df: pd.DataFrame, colunas: list,
                  carga_id: int | None = None) -> int:
    """Acrescenta só o que ainda não existe. Devolve o número de linhas novas."""
    return _inserir(conn, tabela, df, colunas, carga_id, ignorar_repetidas=True)


def substituir_tabela(conn, tabela: str, df: pd.DataFrame, colunas: list,
                      carga_id: int | None = None) -> int:
    """Esvazia a tabela e grava o conteúdo do arquivo. Devolve as linhas gravadas.

    Usado só pelo Acompanhamento, que é um retrato do que está em aberto agora:
    a linha some da origem quando a ordem é recebida, então manter o que saiu
    deixaria ordens concluídas para sempre na lista de pendências.

    A trava antes do DELETE serializa duas cargas simultâneas. Com o banco num
    arquivo local isso não podia acontecer; com o banco compartilhado, dois
    operadores confirmando o Acompanhamento ao mesmo tempo produziriam um retrato
    que é a mistura de duas planilhas — nem uma nem outra.
    """
    dialeto.de(conn).travar_tabela(conn, tabela)
    conn.exec_driver_sql(f"DELETE FROM {tabela}")
    return _inserir(conn, tabela, df, colunas, carga_id, ignorar_repetidas=False)


def abrir_carga(conn, *, fonte: str, arquivo: str, modo: str) -> int:
    """Reserva o id da carga e devolve-o, para as linhas já nascerem apontando nele.

    Os contadores entram zerados e são fechados por `finalizar_carga` — o id
    precisa existir *antes* do INSERT das linhas, que gravam `carga_id`.
    """
    return dialeto.de(conn).inserir_retornando_id(
        conn, "cargas", ["fonte", "arquivo", "quando", "modo"],
        (fonte, arquivo, datetime.now().isoformat(timespec="seconds"), modo),
    )


def finalizar_carga(conn, carga_id: int, *, linhas_lidas: int, linhas_novas: int) -> None:
    """Fecha o log com o que a carga de fato gravou."""
    # Parâmetros nomeados via `text()`: o SQLAlchemy traduz para o marcador de cada
    # driver, então esta instrução não precisa passar pelo dialeto.
    conn.execute(
        text("UPDATE cargas SET linhas_lidas = :lidas, linhas_novas = :novas, "
             "linhas_repetidas = :repetidas WHERE id = :id"),
        {"lidas": linhas_lidas, "novas": linhas_novas,
         "repetidas": max(linhas_lidas - linhas_novas, 0), "id": carga_id},
    )


def historico_cargas(engine: Engine, limite: int = 20) -> pd.DataFrame:
    """Últimas cargas, da mais recente para a mais antiga."""
    return read_sql(
        "SELECT fonte, arquivo, quando, modo, linhas_lidas, linhas_novas, "
        f"linhas_repetidas FROM cargas ORDER BY id DESC LIMIT {int(limite)}", engine)
