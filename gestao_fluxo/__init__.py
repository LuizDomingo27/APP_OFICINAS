"""Sistema de Gestão de Fluxo de Produção (Oficinas).

Arquitetura em camadas, de fora para dentro:

    APRESENTAÇÃO
    app.py       -> moldura: tema, navbar e roteamento (só isso)
    paginas/     -> uma tela por módulo, mais o registro da navegação
    ui.py        -> tema e componentes visuais do Streamlit
    charts.py    -> gráficos ECharts

    APLICAÇÃO
    servicos.py  -> engine, cache do fato, ETL e uploads; a ponte com o
                    runtime do Streamlit, e o único lugar que conhece os dois
                    lados

    DOMÍNIO (pandas puro, sem Streamlit — é o que o torna testável)
    metricas.py  -> consultas e cálculo dos indicadores do painel
    metas.py     -> leitura, gravação e diluição das metas
    config.py    -> caminhos, mapa planilha->tabela, chaves de meta

    INFRAESTRUTURA
    excel.py     -> leitura e normalização das planilhas de origem
    etl.py       -> transformação e carga (incremental ou substituição)
    db/          -> schema SQL, engine e acesso de baixo nível ao banco

As setas apontam só para dentro: `paginas` -> `servicos` -> domínio -> db.
Nenhuma dependência circula no sentido contrário, e nenhuma página importa
outra — o que duas telas compartilham sobe para `paginas/comum.py`.

O banco de produção é o Postgres do Supabase, definido pela variável de
ambiente `DATABASE_URL`. Sem ela o projeto cai num SQLite local — que é o
que mantém a suíte de testes rodando sem infraestrutura. As diferenças
entre os dois ficam contidas em `db/dialeto.py`.
"""

__version__ = "0.1.0"
