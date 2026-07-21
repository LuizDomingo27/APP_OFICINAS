"""As diferenças entre SQLite e Postgres, isoladas num só lugar.

O projeto fala com dois bancos, por motivos diferentes:

* **Postgres (Supabase)** é a produção — histórico compartilhado entre máquinas,
  acesso simultâneo e backup fora do computador de quem opera.
* **SQLite** continua sendo o banco dos testes. A suíte roda em arquivo
  temporário, sem credencial, sem rede e em milissegundos. Exigir um Postgres de
  verdade a cada teste os tornaria lentos e dependentes de infraestrutura sem
  cobrir nada que já não esteja coberto — o que os testes exercitam é a regra de
  carga incremental, não o dialeto.

O SQLAlchemy resolve sozinho quase toda a diferença: `text()` com parâmetros
nomeados, tipos, transações e pool são iguais nos dois. Sobram os pontos tratados
aqui, e é justamente por serem poucos e enumeráveis que vale contê-los em vez de
espalhar `if` pelo `database.py`.

Nenhum outro módulo do projeto precisa saber em qual banco está falando.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

# Alvo do índice único que sustenta a carga incremental. Uma linha já gravada é
# reconhecida por este par — ver database.calcular_identidade.
CONFLITO_IDENTIDADE = ("hash_linha", "ocorrencia")


class Dialeto:
    """Contrato comum aos dois bancos. Obtenha a instância certa com `de()`."""

    nome: str = ""
    #: Placeholder posicional do driver DBAPI: sqlite3 usa `?`, psycopg2 usa `%s`.
    marcador: str = ""
    #: Nome do arquivo de schema, ao lado deste módulo.
    arquivo_schema: str = ""
    #: Bancos criados antes da carga incremental só existem em SQLite — o Postgres
    #: nasce completo pelo script de migração e nunca precisa de backfill.
    migra_bancos_antigos: bool = False

    # --------------------------------------------------------------------- #
    # SQL
    # --------------------------------------------------------------------- #
    def marcadores(self, n: int) -> str:
        return ", ".join([self.marcador] * n)

    def sql_insert(self, tabela: str, colunas: list, *, ignorar_conflito: bool) -> str:
        raise NotImplementedError

    def sql_colunas(self, tabela: str) -> tuple[str, dict]:
        """(query, params) que devolve uma coluna `name` com os nomes das colunas."""
        raise NotImplementedError

    def sql_tabela_existe(self) -> str:
        """Query com parâmetro nomeado `:n` que devolve 0 ou 1 linha."""
        raise NotImplementedError

    def sql_listar_tabelas(self) -> str:
        """Query sem parâmetros que devolve a coluna `name` com TODAS as tabelas e
        views do schema atual.

        Existe para perguntar "quais destas tabelas existem?" numa única ida ao
        banco, em vez de uma consulta por tabela — ver database.tabelas_existentes.
        """
        raise NotImplementedError

    # --------------------------------------------------------------------- #
    # Operações
    # --------------------------------------------------------------------- #
    def executar_schema(self, engine: Engine, sql: str) -> None:
        """Roda o arquivo de schema inteiro (várias instruções separadas por `;`)."""
        raise NotImplementedError

    def inserir_muitas(self, conn: Connection, tabela: str, colunas: list,
                       linhas: list, *, ignorar_conflito: bool) -> int:
        """Insere as linhas e devolve quantas *de fato* entraram.

        Devolver a contagem real é o que alimenta a conferência "312 novas, 28 já
        existentes" mostrada ao operador antes de confirmar a carga. Os dois bancos
        chegam nesse número por caminhos diferentes — ver cada implementação.
        """
        raise NotImplementedError

    def inserir_retornando_id(self, conn: Connection, tabela: str, colunas: list,
                              valores: tuple) -> int:
        """Insere uma linha e devolve o id gerado."""
        raise NotImplementedError

    def travar_tabela(self, conn: Connection, tabela: str) -> None:
        """Serializa a substituição da tabela contra outra carga simultânea."""

    def ajustar_sequence(self, conn: Connection, tabela: str) -> None:
        """Realinha o gerador de `id` após inserts com id explícito.

        Só a migração precisa disso, e só no Postgres: lá a sequence é um objeto
        independente da tabela e não toma conhecimento de ids gravados à mão. O
        SQLite deriva o próximo id do maior já existente, então não há nada a
        corrigir — daí o no-op aqui valer como implementação, não como omissão.
        """


class DialetoSQLite(Dialeto):
    """SQLite — backend dos testes."""

    nome = "sqlite"
    marcador = "?"
    arquivo_schema = "schema.sql"
    migra_bancos_antigos = True

    def sql_insert(self, tabela: str, colunas: list, *, ignorar_conflito: bool) -> str:
        verbo = "INSERT OR IGNORE INTO" if ignorar_conflito else "INSERT INTO"
        return (f"{verbo} {tabela} ({', '.join(colunas)}) "
                f"VALUES ({self.marcadores(len(colunas))})")

    def sql_colunas(self, tabela: str) -> tuple[str, dict]:
        # PRAGMA não aceita parâmetro; o nome vem de config.FONTES, nunca do usuário.
        return f"PRAGMA table_info({tabela})", {}

    def sql_tabela_existe(self) -> str:
        return ("SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') AND name = :n")

    def sql_listar_tabelas(self) -> str:
        return "SELECT name FROM sqlite_master WHERE type IN ('table','view')"

    def executar_schema(self, engine: Engine, sql: str) -> None:
        raw = engine.raw_connection()
        try:
            raw.executescript(sql)
            raw.commit()
        finally:
            raw.close()

    def inserir_muitas(self, conn: Connection, tabela: str, colunas: list,
                       linhas: list, *, ignorar_conflito: bool) -> int:
        # Conta com COUNT(*) antes e depois em vez de usar `rowcount`: o suporte a
        # rowcount em executemany varia entre drivers e o SQLAlchemy não o garante.
        # Aqui o custo é irrelevante (banco de teste, conexão única) e o número é
        # exato — no Postgres a história é outra, ver DialetoPostgres.
        antes = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {tabela}").scalar()
        conn.exec_driver_sql(
            self.sql_insert(tabela, colunas, ignorar_conflito=ignorar_conflito), linhas)
        depois = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {tabela}").scalar()
        return int(depois) - int(antes)

    def inserir_retornando_id(self, conn: Connection, tabela: str, colunas: list,
                              valores: tuple) -> int:
        resultado = conn.exec_driver_sql(
            self.sql_insert(tabela, colunas, ignorar_conflito=False), valores)
        return int(resultado.lastrowid)


class DialetoPostgres(Dialeto):
    """Postgres — produção, hospedado no Supabase."""

    nome = "postgresql"
    marcador = "%s"
    arquivo_schema = "schema_postgres.sql"
    migra_bancos_antigos = False

    def sql_insert(self, tabela: str, colunas: list, *, ignorar_conflito: bool) -> str:
        sql = (f"INSERT INTO {tabela} ({', '.join(colunas)}) "
               f"VALUES ({self.marcadores(len(colunas))})")
        if ignorar_conflito:
            sql += f" ON CONFLICT ({', '.join(CONFLITO_IDENTIDADE)}) DO NOTHING"
        return sql

    def sql_colunas(self, tabela: str) -> tuple[str, dict]:
        return (
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t",
            {"t": tabela},
        )

    def sql_tabela_existe(self) -> str:
        return ("SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :n")

    def sql_listar_tabelas(self) -> str:
        return ("SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = current_schema()")

    def executar_schema(self, engine: Engine, sql: str) -> None:
        # psycopg2 aceita várias instruções num único execute, e o `begin()` torna
        # o schema inteiro atômico — melhor que o executescript do SQLite, que
        # commita no meio e pode deixar o schema pela metade.
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)

    def inserir_muitas(self, conn: Connection, tabela: str, colunas: list,
                       linhas: list, *, ignorar_conflito: bool) -> int:
        # `rowcount` do psycopg2 já exclui o que o ON CONFLICT descartou, e é a
        # única contagem correta sob concorrência: com dois operadores subindo
        # planilhas ao mesmo tempo, COUNT(*) antes/depois enxergaria as linhas do
        # outro e reportaria um número inventado.
        resultado = conn.exec_driver_sql(
            self.sql_insert(tabela, colunas, ignorar_conflito=ignorar_conflito), linhas)
        return max(int(resultado.rowcount or 0), 0)

    def inserir_retornando_id(self, conn: Connection, tabela: str, colunas: list,
                              valores: tuple) -> int:
        # psycopg2 não expõe lastrowid de forma utilizável; RETURNING é o caminho
        # nativo e evita uma segunda consulta.
        sql = self.sql_insert(tabela, colunas, ignorar_conflito=False) + " RETURNING id"
        return int(conn.exec_driver_sql(sql, valores).scalar())

    def travar_tabela(self, conn: Connection, tabela: str) -> None:
        # Acompanhamento é apagado e regravado por inteiro. Sem trava, duas cargas
        # simultâneas se intercalam e o retrato final vira a mistura de duas
        # planilhas. A trava cai sozinha no fim da transação.
        conn.execute(text(f"LOCK TABLE {tabela} IN EXCLUSIVE MODE"))

    def ajustar_sequence(self, conn: Connection, tabela: str) -> None:
        # Sem isto, o primeiro INSERT do app depois da migração pediria o id 1 —
        # que já veio do SQLite — e morreria com violação de chave primária.
        # O terceiro argumento do setval trata a tabela vazia: `false` faz o
        # próximo valor ser 1 em vez de 2.
        conn.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabela}), 1), "
            f"(SELECT COUNT(*) > 0 FROM {tabela}))"
        ))


_POR_NOME = {
    "sqlite": DialetoSQLite(),
    "postgresql": DialetoPostgres(),
}


def de(fonte: Engine | Connection) -> Dialeto:
    """Descobre o dialeto a partir do engine ou da conexão.

    Despachar pelo próprio objeto de conexão — e não por uma configuração global —
    é o que permite ao script de migração manter os dois bancos abertos ao mesmo
    tempo, cada um respondendo no seu dialeto.
    """
    nome = fonte.engine.dialect.name if isinstance(fonte, Connection) else fonte.dialect.name
    try:
        return _POR_NOME[nome]
    except KeyError:
        raise NotImplementedError(
            f"Banco não suportado: {nome}. O projeto fala SQLite (testes) e "
            f"Postgres (produção)."
        ) from None
