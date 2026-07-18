"""Sistema de Gestão de Fluxo de Produção (Oficinas).

Arquitetura em camadas:

    etl/          -> extração, normalização e carga das planilhas no banco
    db/           -> schema SQL e acesso de baixo nível ao banco
    repositories/ -> consultas SQL (camada de acesso a dados)
    services/     -> regras de negócio / cálculo de métricas do dashboard
    ui/           -> tema e componentes visuais do Streamlit

A UI depende de services -> repositories -> db. Nenhuma dependência
circula no sentido contrário.
"""

__version__ = "0.1.0"
