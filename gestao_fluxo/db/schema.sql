-- Schema plano: uma tabela por planilha, com os mesmos números da origem.
--
-- Decisão: nada de deduplicação por regra de negócio, corte por ano ou filtro
-- escondido. Cada linha da planilha vira uma linha da tabela. O que muda é só a
-- limpeza de texto (oficina, MP) e a conversão de data para ISO. Assim qualquer
-- total exibido na tela pode ser conferido somando a coluna no Excel.
--
-- CARGA INCREMENTAL
-- As tabelas de fato NÃO são mais dropadas a cada carga: o banco é o histórico
-- acumulado e as planilhas novas só acrescentam o que ainda não existe. A
-- identidade de uma linha é o par (hash_linha, ocorrencia):
--
--   hash_linha -> sha1 dos 6 campos do fato (om, oficina, data, mp, qtd, minutos)
--   ocorrencia -> 1, 2, 3... para linhas idênticas DENTRO do mesmo arquivo
--
-- O ordinal existe porque linhas 100% idênticas são produção real, não erro:
-- a mesma ordem recebida em duas parcelas iguais no mesmo dia aparece duas vezes
-- na origem e precisa continuar aparecendo aqui, senão o total deixa de bater com
-- o Excel. Com o ordinal, re-subir a mesma planilha não insere nada (o par já
-- existe), mas as duas cópias legítimas são preservadas.
--
-- Acompanhamento é a exceção e continua sendo substituído por inteiro a cada
-- carga — ver o comentário na tabela.

DROP VIEW  IF EXISTS vw_saldo_a_receber;
DROP TABLE IF EXISTS recebimentos;
DROP TABLE IF EXISTS ordens_eventos;
DROP TABLE IF EXISTS ordens;
DROP TABLE IF EXISTS oficinas_apelidos;
DROP TABLE IF EXISTS materias_primas;
DROP TABLE IF EXISTS oficinas;

-- Acompanhamento não é histórico: cada linha é uma ordem **ainda em aberto**, e
-- ela some da planilha quando a ordem é recebida. Por isso esta tabela é limpa e
-- regravada a cada carga (ver etl.executar_etl). Carga incremental aqui manteria
-- ordens já concluídas eternamente listadas como pendentes.
CREATE TABLE IF NOT EXISTS fato_acompanhamento (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina    TEXT    NOT NULL,
    data       TEXT,                            -- ISO 'YYYY-MM-DD' (coluna ENVIO)
    mp         TEXT    NOT NULL,
    qtd_pecas  REAL    NOT NULL DEFAULT 0,
    minutos    REAL    NOT NULL DEFAULT 0,
    om         INTEGER,                         -- ORDEM MESTRE
    -- Prazo de entrega. A origem exporta parte das linhas com o ano anterior; o
    -- ETL reescreve o ano antes de gravar (ver etl.corrigir_ano_deadline).
    deadline   TEXT,                            -- ISO 'YYYY-MM-DD' (coluna DEAD LINE)
    hash_linha TEXT,
    ocorrencia INTEGER DEFAULT 1,
    carga_id   INTEGER
);

CREATE TABLE IF NOT EXISTS fato_recebimento (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina    TEXT    NOT NULL,
    data       TEXT,                            -- ISO 'YYYY-MM-DD' (coluna DIA)
    mp         TEXT    NOT NULL,
    qtd_pecas  REAL    NOT NULL DEFAULT 0,      -- REAL CORTADO
    minutos    REAL    NOT NULL DEFAULT 0,
    om         INTEGER,
    hash_linha TEXT,
    ocorrencia INTEGER DEFAULT 1,
    carga_id   INTEGER
);

CREATE TABLE IF NOT EXISTS fato_envios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina    TEXT    NOT NULL,
    data       TEXT,                            -- ISO 'YYYY-MM-DD' (coluna ENVIO)
    mp         TEXT    NOT NULL,
    qtd_pecas  REAL    NOT NULL DEFAULT 0,
    minutos    REAL    NOT NULL DEFAULT 0,
    om         INTEGER,
    hash_linha TEXT,
    ocorrencia INTEGER DEFAULT 1,
    carga_id   INTEGER
);

-- Previsão: a agenda do que ainda vai voltar das oficinas. Como o Acompanhamento,
-- é um retrato do momento (a ordem some da planilha quando volta), e por isso a
-- tabela é substituída por inteiro a cada carga.
--
-- Aqui `data` é a data PREVISTA de recebimento, e não o envio: é ela que responde
-- "o que temos para receber nesta semana", que é a pergunta da tela. O envio ganha
-- coluna própria justamente porque perdeu o lugar de `data`.
CREATE TABLE IF NOT EXISTS fato_previsao (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina    TEXT    NOT NULL,
    data       TEXT,                            -- ISO 'YYYY-MM-DD' (coluna RECEBIMENTO)
    mp         TEXT    NOT NULL,
    qtd_pecas  REAL    NOT NULL DEFAULT 0,
    minutos    REAL    NOT NULL DEFAULT 0,
    om         INTEGER,                         -- ORDEM MESTRE
    deadline   TEXT,                            -- ISO 'YYYY-MM-DD' (coluna DEAD LINE)
    envio      TEXT,                            -- ISO 'YYYY-MM-DD' (coluna ENVIO)
    hash_linha TEXT,
    ocorrencia INTEGER DEFAULT 1,
    carga_id   INTEGER
);

CREATE INDEX IF NOT EXISTS ix_acomp_data  ON fato_acompanhamento (data);
CREATE INDEX IF NOT EXISTS ix_receb_data  ON fato_recebimento (data);
CREATE INDEX IF NOT EXISTS ix_envios_data ON fato_envios (data);
CREATE INDEX IF NOT EXISTS ix_prev_data   ON fato_previsao (data);

-- A identidade da linha vive num índice único (e não numa constraint inline)
-- porque o SQLite não permite acrescentar UNIQUE via ALTER TABLE: bancos antigos,
-- criados antes da carga incremental, ganham a mesma garantia só rodando este
-- CREATE INDEX depois do backfill (ver database.migrar_schema).
CREATE UNIQUE INDEX IF NOT EXISTS ux_acomp_linha  ON fato_acompanhamento (hash_linha, ocorrencia);
CREATE UNIQUE INDEX IF NOT EXISTS ux_receb_linha  ON fato_recebimento (hash_linha, ocorrencia);
CREATE UNIQUE INDEX IF NOT EXISTS ux_envios_linha ON fato_envios (hash_linha, ocorrencia);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prev_linha   ON fato_previsao (hash_linha, ocorrencia);

-- Metas: chave/valor. Fica FORA dos DROPs acima de propósito — recarregar as
-- planilhas não pode apagar as metas cadastradas pelo time.
CREATE TABLE IF NOT EXISTS metas (
    chave         TEXT PRIMARY KEY,
    valor         REAL NOT NULL DEFAULT 0,
    atualizado_em TEXT
);

-- Log de cargas: o que entrou, quando e de qual arquivo. É o que permite auditar
-- uma carga suspeita e responder "por que este número mudou ontem?".
CREATE TABLE IF NOT EXISTS cargas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte            TEXT NOT NULL,
    arquivo          TEXT,
    quando           TEXT NOT NULL,
    modo             TEXT NOT NULL,     -- 'incremental' ou 'substituicao'
    linhas_lidas     INTEGER NOT NULL DEFAULT 0,
    linhas_novas     INTEGER NOT NULL DEFAULT 0,
    linhas_repetidas INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_cargas_quando ON cargas (quando);
