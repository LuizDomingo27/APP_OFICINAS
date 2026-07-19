"""Cópia verificada de banco a banco: migração para o Supabase e backup de volta.

    python -m gestao_fluxo.db.migracao            # SQLite  -> Postgres (migra)
    python -m gestao_fluxo.db.migracao --conferir # só confere, não grava
    python -m gestao_fluxo.db.migracao --backup   # Postgres -> SQLite datado

A migração para o Supabase já foi feita e conferida; o que mantém este módulo
vivo é o `--backup`. Copiar tabela a tabela e conferir linhas e somas nas duas
pontas é a mesma operação nos dois sentidos — `migrar()` recebe dois engines
quaisquer e o `dialeto` resolve o resto, então o caminho de volta não custa
código novo. O backup sai em SQLite justamente por ser um arquivo único que
abre em qualquer ferramenta, sem servidor e sem credencial.

O que precisa sobreviver a esta cópia não é "os dados" em abstrato: é a
**identidade incremental** de cada linha. O par (hash_linha, ocorrencia) é o que
faz re-subir uma planilha já carregada não inserir nada. Por isso os hashes são
copiados literalmente, nunca recalculados no destino — qualquer diferença de
formatação numérica entre os dois bancos geraria hash novo, e a próxima planilha
reinseriria o histórico inteiro em duplicidade.

A ordem das tabelas também não é livre: `cargas` vai primeiro, com os ids
originais, porque cada linha de fato aponta para ela por `carga_id`. Migrar na
ordem inversa deixaria o histórico de auditoria apontando para o nada.

A conferência ao final é o aceite: mesmo número de linhas e mesmas somas de peças
e minutos, tabela a tabela. Se qualquer uma divergir, a migração falhou — e o
SQLite original continua intacto para tentar de novo.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from .. import config
from . import database, dialeto

#: Ordem de migração. `cargas` primeiro: as tabelas de fato referenciam seus ids.
#: `metas` por último, por ser independente de tudo.
ORDEM = ("cargas", *database.TABELAS_FATO, "metas")

#: Colunas cujo valor tem que chegar ao Postgres como inteiro. O pandas promove
#: coluna inteira com nulo para float64, e gravar 7.0 numa coluna BIGINT passaria a
#: depender de cast implícito — melhor não depender.
COLUNAS_INTEIRAS = ("id", "om", "ocorrencia", "carga_id",
                    "linhas_lidas", "linhas_novas", "linhas_repetidas")

#: Somas conferidas nas tabelas de fato.
COLUNAS_SOMADAS = ("qtd_pecas", "minutos")


@dataclass
class Conferencia:
    """Comparação de uma tabela entre origem e destino."""

    tabela: str
    linhas_origem: int = 0
    linhas_destino: int = 0
    somas_origem: dict = field(default_factory=dict)
    somas_destino: dict = field(default_factory=dict)

    @property
    def confere(self) -> bool:
        if self.linhas_origem != self.linhas_destino:
            return False
        # Tolerância de ponto flutuante: os dois bancos guardam float de 8 bytes,
        # mas a soma percorre as linhas em ordens possivelmente diferentes.
        return all(
            abs(self.somas_origem[c] - self.somas_destino.get(c, 0.0)) < 0.01
            for c in self.somas_origem
        )

    def descrever(self) -> str:
        marca = "OK    " if self.confere else "FALHOU"
        partes = [f"{marca} {self.tabela:<22} "
                  f"{self.linhas_origem:>7} -> {self.linhas_destino:>7} linhas"]
        for coluna, valor in self.somas_origem.items():
            partes.append(f"{coluna}: {valor:,.2f} -> "
                          f"{self.somas_destino.get(coluna, 0.0):,.2f}")
        return "   ".join(partes)


def _normalizar_inteiros(df: pd.DataFrame) -> pd.DataFrame:
    """Devolve as colunas inteiras como inteiro nativo (ou None quando ausente)."""
    out = df.copy()
    for coluna in COLUNAS_INTEIRAS:
        if coluna not in out.columns:
            continue
        numerica = pd.to_numeric(out[coluna], errors="coerce")
        out[coluna] = [None if pd.isna(v) else int(v) for v in numerica]
    return out


def _somas(df: pd.DataFrame) -> dict:
    return {c: float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum())
            for c in COLUNAS_SOMADAS if c in df.columns}


def _destino_vazio(destino: Engine) -> bool:
    for tabela in ORDEM:
        if not database.tabela_existe(destino, tabela):
            continue
        n = database.read_sql(f"SELECT COUNT(*) AS n FROM {tabela}", destino).loc[0, "n"]
        if int(n):
            return False
    return True


def _copiar(origem: Engine, destino: Engine, tabela: str) -> Conferencia:
    """Copia uma tabela inteira e devolve a conferência correspondente."""
    df = database.read_sql(f"SELECT * FROM {tabela}", origem)
    conf = Conferencia(tabela=tabela, linhas_origem=len(df), somas_origem=_somas(df))

    if not df.empty:
        dados = _normalizar_inteiros(df)
        colunas = dados.columns.tolist()
        d = dialeto.de(destino)
        with destino.begin() as conn:
            # `ignorar_conflito=False` de propósito: numa tabela que deveria estar
            # vazia, conflito não é linha repetida a descartar — é sinal de que a
            # migração já rodou antes. Melhor estourar do que mascarar.
            d.inserir_muitas(conn, tabela, colunas,
                             database.linhas_para_sql(dados, colunas),
                             ignorar_conflito=False)
            if "id" in colunas:
                d.ajustar_sequence(conn, tabela)

    gravado = database.read_sql(f"SELECT * FROM {tabela}", destino)
    conf.linhas_destino = len(gravado)
    conf.somas_destino = _somas(gravado)
    return conf


def conferir(origem: Engine, destino: Engine) -> list:
    """Compara origem e destino sem gravar nada."""
    resultado = []
    for tabela in ORDEM:
        df_o = database.read_sql(f"SELECT * FROM {tabela}", origem)
        df_d = (database.read_sql(f"SELECT * FROM {tabela}", destino)
                if database.tabela_existe(destino, tabela) else pd.DataFrame())
        resultado.append(Conferencia(
            tabela=tabela,
            linhas_origem=len(df_o), linhas_destino=len(df_d),
            somas_origem=_somas(df_o), somas_destino=_somas(df_d),
        ))
    return resultado


def migrar(origem: Engine, destino: Engine, *, forcar: bool = False) -> list:
    """Executa a migração e devolve a conferência de cada tabela.

    `forcar` dispensa a exigência de destino vazio. Use apenas para retomar uma
    migração que falhou no meio, e depois de esvaziar o que ficou pela metade —
    rodar duas vezes sobre um destino povoado viola o índice único e aborta.
    """
    # Garante que TODA linha do SQLite já tem hash e ocorrência. Sem este passo,
    # linhas gravadas antes da carga incremental chegariam ao Postgres com
    # hash_linha nulo, que lá é NOT NULL — a migração morreria no meio.
    database.migrar_schema(origem)
    database.init_schema(destino)

    if not forcar and not _destino_vazio(destino):
        raise RuntimeError(
            "O banco de destino já tem dados. Migrar por cima duplicaria o "
            "histórico. Esvazie-o ou rode com --forcar se souber o que está fazendo."
        )

    return [_copiar(origem, destino, tabela) for tabela in ORDEM]


def caminho_backup(agora: datetime | None = None) -> Path:
    """Arquivo de destino do backup, carimbado com a hora de início.

    O carimbo vai até o minuto: dois backups no mesmo minuto colidiriam, e é
    exatamente o que deve acontecer — `migrar()` recusa destino povoado, então a
    colisão vira erro em vez de sobrescrever silenciosamente um backup bom.
    """
    return config.BACKUPS_DIR / f"fluxo_producao_{agora or datetime.now():%Y%m%d-%H%M}.db"


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--origem", default=str(config.DB_PATH),
                        help="arquivo SQLite de origem (padrão: data/fluxo_producao.db)")
    parser.add_argument("--conferir", action="store_true",
                        help="só compara origem e destino, sem gravar")
    parser.add_argument("--forcar", action="store_true",
                        help="migra mesmo com o destino já povoado")
    parser.add_argument("--backup", action="store_true",
                        help="inverte o sentido: copia o Postgres para um SQLite "
                             "datado em data/backups/")
    args = parser.parse_args(argv)

    if args.backup and args.conferir:
        print("--conferir não se aplica a --backup: o destino é um arquivo novo, "
              "que por definição ainda não tem nada a comparar.", file=sys.stderr)
        return 2

    url = config.url_do_banco()
    if url.startswith("sqlite"):
        ponta = "a origem do backup" if args.backup else "o destino"
        print(f"DATABASE_URL não está definida — {ponta} seria o próprio SQLite.\n"
              "Configure o .env antes de rodar (ver .env.example).", file=sys.stderr)
        return 2

    servidor = url.rsplit("@", 1)[-1]   # sem a senha
    if args.backup:
        arquivo = caminho_backup()
        origem, destino = database.get_engine(), database.get_engine(arquivo)
        acao, rotulo_origem, rotulo_destino = "Backup", servidor, str(arquivo)
    else:
        origem, destino = database.get_engine(args.origem), database.get_engine()
        acao, rotulo_origem, rotulo_destino = "Migração", args.origem, servidor

    print(f"Origem : {rotulo_origem}")
    print(f"Destino: {rotulo_destino}\n")

    try:
        conferencias = (conferir(origem, destino) if args.conferir
                        else migrar(origem, destino, forcar=args.forcar))
    except Exception as exc:  # noqa: BLE001
        print(f"{acao} abortada: {exc}", file=sys.stderr)
        return 1

    for c in conferencias:
        print(c.descrever())

    if not all(c.confere for c in conferencias):
        print(f"\nCONFERÊNCIA FALHOU. A origem ({rotulo_origem}) não foi tocada — "
              "corrija e rode de novo.", file=sys.stderr)
        return 1

    print("\nConferência OK — linhas e somas idênticas nas duas pontas.")
    if args.backup:
        print(f"Backup gravado em {rotulo_destino}")
    else:
        print("Falta o teste decisivo: suba no app uma planilha JÁ carregada e "
              "confirme que a prévia acusa 0 novas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
