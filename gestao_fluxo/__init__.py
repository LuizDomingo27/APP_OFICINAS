"""Sistema de Gestão de Fluxo de Produção (Oficinas).

Arquitetura em camadas (módulos planos, um por responsabilidade):

    config.py    -> caminhos, mapa planilha->tabela, chaves de meta
    excel.py     -> leitura e normalização das planilhas de origem
    etl.py       -> transformação e carga (incremental ou substituição)
    db/          -> schema SQL, engine e acesso de baixo nível ao banco
    metricas.py  -> consultas e cálculo dos indicadores do painel
    metas.py     -> leitura e gravação das metas
    charts.py    -> gráficos ECharts
    ui.py        -> tema e componentes visuais do Streamlit

O app (`app.py`) depende de metricas/metas -> db. Nenhuma dependência
circula no sentido contrário.

O banco de produção é o Postgres do Supabase, definido pela variável de
ambiente `DATABASE_URL`. Sem ela o projeto cai num SQLite local — que é o
que mantém a suíte de testes rodando sem infraestrutura. As diferenças
entre os dois ficam contidas em `db/dialeto.py`.
"""

__version__ = "0.1.0"
