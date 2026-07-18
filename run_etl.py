"""CLI para rodar o ETL fora do Streamlit (carga inicial / recarga).

Uso:
    python run_etl.py
"""
from __future__ import annotations

import sys

from gestao_fluxo.db import database
from gestao_fluxo.etl import executar_etl
from gestao_fluxo.exceptions import GestaoFluxoError


def main() -> int:
    engine = database.get_engine()
    try:
        rel = executar_etl(engine)
    except GestaoFluxoError as exc:
        print(f"[ERRO] {exc.mensagem_usuario}", file=sys.stderr)
        print(f"       detalhe: {exc.detalhe}", file=sys.stderr)
        return 1

    print("Carga concluída com sucesso.\n")
    print(f"  Linhas lidas das planilhas ..... {rel.total_linhas}")
    print(f"  Linhas gravadas no banco ....... {rel.total_novas}\n")
    for f in rel.fontes:
        print(f"  {f.rotulo}  [{f.modo}]")
        print(f"      linhas lidas ............. {f.linhas}")
        if f.substituida:
            print(f"      linhas regravadas ........ {f.novas}")
        else:
            print(f"      linhas novas ............. {f.novas}")
            print(f"      já existentes (ignoradas)  {f.repetidas}")
        print(f"      total de peças ........... {f.total_pecas:,.0f}")
        print(f"      total de minutos ......... {f.total_minutos:,.2f}")
        print(f"      oficinas distintas ....... {f.oficinas}")
        print(f"      linhas sem data .......... {f.sem_data}")
    print("\nOs totais de peças/minutos acima são os da planilha lida. Registro já")
    print("existente no banco é ignorado, então re-rodar a carga não duplica nada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
