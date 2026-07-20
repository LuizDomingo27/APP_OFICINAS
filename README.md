# APP_OFICINAS — Sistema de Gestão de Fluxo de Produção

Painel operacional que consolida o fluxo de produção terceirizada em oficinas:
o que foi **enviado** para corte, o que **retornou** (recebimento), o que segue
**em aberto** (acompanhamento) e o quanto disso cumpre as **metas** do time.

É uma aplicação [Streamlit](https://streamlit.io) de tema escuro, alimentada por
planilhas Excel que o time já mantém, com um banco de dados como histórico
acumulado. A regra que atravessa o projeto inteiro é uma só: **nenhum número da
tela é inventado**. `SUM(qtd_pecas)` no banco bate com a soma da coluna no Excel,
e qualquer indicador exibido pode ser conferido à mão pela equipe.

---

## Sumário

- [Visão em uma tela](#visão-em-uma-tela)
- [Arquitetura em camadas](#arquitetura-em-camadas)
- [Fluxo de dados de ponta a ponta](#fluxo-de-dados-de-ponta-a-ponta)
- [Os módulos, um a um](#os-módulos-um-a-um)
  - [Camada de configuração e domínio](#camada-de-configuração-e-domínio)
  - [Camada de dados (`db/`)](#camada-de-dados-db)
  - [Camada de ETL](#camada-de-etl)
  - [Camada de cálculo](#camada-de-cálculo)
  - [Camada de apresentação](#camada-de-apresentação)
  - [Infraestrutura transversal](#infraestrutura-transversal)
  - [Pontos de entrada](#pontos-de-entrada)
- [O banco de dados](#o-banco-de-dados)
- [Decisões de projeto que valem conhecer](#decisões-de-projeto-que-valem-conhecer)
- [Como rodar](#como-rodar)
- [Configuração (`.env`)](#configuração-env)
- [Deploy no Streamlit Cloud](#deploy-no-streamlit-cloud)
- [Testes](#testes)
- [Estrutura de arquivos](#estrutura-de-arquivos)

---

## Visão em uma tela

O app tem **cinco abas**, cada uma filtrada de forma independente:

| Aba | O que responde | Base de dados | Forma |
|-----|----------------|---------------|-------|
| **Acompanhamento** | O que já saiu e ainda não voltou — saldo em aberto, prazos e há quanto tempo cada oficina está devendo | `fato_acompanhamento` (+ Envios/Recebimento no fluxo por MP) | Cards + tabelas (sem gráficos: média de saldo não diz nada) |
| **Previsão** | Quando o que está fora volta, e quanto disso fura o prazo | `fato_previsao` | Cards + barras (MP / semana / dia) + tabela |
| **Recebimento** | O que retornou das oficinas — totais, médias e variação vs. período anterior | `fato_recebimento` | Cards + roscas + evolução temporal + tabela |
| **Envios** | O que foi despachado para corte — mesma estrutura do Recebimento | `fato_envios` | Cards + roscas + evolução temporal + tabela |
| **Metas** | Onde estamos frente à meta do mês, diluída por dia útil | `fato_recebimento` (realizado) + tabela `metas` | Formulário + cards de necessidade + badges + relógios |

O tema visual (paleta, componentes, tokens) é descrito em detalhe em
[DESIGN.md](DESIGN.md).

---

## Arquitetura em camadas

O projeto é organizado em **módulos planos, um por responsabilidade**. As
dependências fluem numa única direção — da apresentação para os dados — e nunca
circulam de volta:

```
                        ┌─────────────────────────────────────────┐
   PONTOS DE ENTRADA    │  app.py (Streamlit)     run_etl.py (CLI) │
                        └────────────┬──────────────────┬─────────┘
                                     │                  │
                        ┌────────────▼──────────┐       │
   APRESENTAÇÃO         │  ui.py    charts.py    │       │
                        │  excel.py              │       │
                        └────────────┬───────────┘       │
                                     │                   │
                        ┌────────────▼───────────────────▼─────────┐
   CÁLCULO / DOMÍNIO    │  metricas.py     metas.py                 │
                        └────────────┬──────────────────┬──────────┘
                                     │                  │
                        ┌────────────▼──────────────────▼──────────┐
   ETL                  │  etl.py                                   │
                        └────────────┬──────────────────────────────┘
                                     │
                        ┌────────────▼──────────────────────────────┐
   DADOS                │  db/database.py   db/dialeto.py            │
                        │  db/schema.sql    db/schema_postgres.sql   │
                        │  db/migracao.py                            │
                        └────────────┬──────────────────────────────┘
                                     │
                        ┌────────────▼──────────────────────────────┐
   CONFIG / TRANSVERSAL │  config.py   exceptions.py   log.py        │
                        └────────────────────────────────────────────┘
```

`config.py`, `exceptions.py` e `log.py` são transversais: qualquer camada pode
importá-los, mas eles não importam ninguém de volta.

---

## Fluxo de dados de ponta a ponta

**Da planilha ao banco (carga / ETL):**

```
ENVIOS_OFICINAS.xlsx  ┐
RECEBIMENTO.xlsx      ├─►  excel/etl: ler → renomear 6 colunas → limpar texto
ACOMPANHAMENTO.xlsx   ┘         (oficina, MP) → data p/ ISO → corrigir ano
                                do prazo → calcular identidade (hash, ocorrência)
                                     │
                                     ▼
                         db.inserir_novas / substituir_tabela
                                     │
                                     ▼
                    Postgres (Supabase) em produção   ·   SQLite nos testes
```

**Do banco à tela (consulta):**

```
db.read_sql → metricas.carregar_fato → filtrar(mês/semana/MP/oficina)
     → calcular_metricas / classificar_prazo / fluxo_por_mp / montar_plano
     → charts (ECharts) + ui (tabelas verdes, cards, badges)
     → excel.gerar_xlsx (botão de download)
```

Cards e gráficos de uma aba saem do **mesmo DataFrame filtrado**, então nunca
divergem entre si.

---

## Os módulos, um a um

### Camada de configuração e domínio

#### [`gestao_fluxo/config.py`](gestao_fluxo/config.py)
Configuração central e o único lugar onde vivem as constantes "mágicas" do
domínio. Concentra:

- **Caminhos**: raiz do projeto, pasta `data/`, arquivo SQLite, pasta de backups
  e as quatro planilhas de origem.
- **Conexão**: `url_do_banco()` decide entre Postgres e SQLite (ver
  [O banco de dados](#o-banco-de-dados)) e reescreve o esquema `postgres://` →
  `postgresql://`. Lê o `.env` opcionalmente via `python-dotenv`.
- **Mapa `FONTES`**: para cada fonte (acompanhamento / recebimento / envios /
  previsão), qual tabela de destino, qual rótulo, qual **modo de carga** e de qual
  coluna da planilha sai cada um dos 6 campos do fato, mais os campos extras de
  cada uma (`CAMPOS_EXTRA`).
- **Modos de carga**: `MODO_INCREMENTAL` (acrescenta ao histórico) e
  `MODO_SUBSTITUICAO` (esvazia e regrava — Acompanhamento e Previsão, os dois
  retratos do agora).
- **Regras de prazo**: janela de "vence em breve" (`PRAZO_ALERTA_DIAS = 7`) e os
  quatro status de prazo.
- **Metas**: as 6 chaves (mês/semana/dia × peças/minutos) e a base que mede o
  realizado (`FONTE_META = "recebimento"`).

#### [`gestao_fluxo/exceptions.py`](gestao_fluxo/exceptions.py)
Hierarquia de exceções de domínio, todas descendentes de `GestaoFluxoError`.
Cada uma carrega uma `.mensagem_usuario` amigável em português (exibida ao
operador) e um `.detalhe` técnico (mandado ao log). A UI captura a base e mostra
só a mensagem amigável, sem stack trace.

- `FonteDeDadosError` — falha ao ler/validar uma planilha.
- `ETLError` — falha na transformação/carga.
- `BancoDeDadosError` — falha de acesso ao banco.
- `RelatorioError` — falha ao montar o `.xlsx` de download (tratada como extra
  indisponível, nunca como perda de dados).

---

### Camada de dados (`db/`)

#### [`gestao_fluxo/db/database.py`](gestao_fluxo/db/database.py)
Acesso de baixo nível ao banco — **responsabilidade única: falar com o banco, sem
regra de negócio**. Agnóstico ao SGBD: despacha para o dialeto certo pelo próprio
engine. Contém:

- **Engine**: `get_engine()` abre Postgres ou SQLite conforme a configuração, com
  pool ajustado ao modo de conexão do Supabase (session vs. transaction pooler).
- **Schema**: `init_schema()` garante o schema atual e migra bancos antigos antes.
- **Identidade da linha**: `calcular_identidade()` acrescenta `hash_linha`
  (SHA-1 dos 6 campos do fato) e `ocorrencia` (ordinal de linhas idênticas dentro
  do mesmo arquivo). É o coração da carga incremental.
- **Migração de schema**: `migrar_schema()` traz bancos SQLite anteriores à carga
  incremental para o formato atual (idempotente; no-op no Postgres).
- **Escrita**: `inserir_novas()` (incremental, ignora conflito),
  `substituir_tabela()` (esvazia e regrava, com trava contra carga simultânea),
  `contar_novas()` (prévia), e o log de cargas (`abrir_carga`, `finalizar_carga`,
  `historico_cargas`).

#### [`gestao_fluxo/db/dialeto.py`](gestao_fluxo/db/dialeto.py)
As diferenças entre SQLite e Postgres, **isoladas num só lugar**. O SQLAlchemy
resolve quase tudo; sobram poucos pontos enumeráveis, contidos aqui em vez de
espalhados por `if`s pelo `database.py`:

- Placeholder do driver (`?` vs. `%s`), nome do arquivo de schema.
- SQL de `INSERT` (`INSERT OR IGNORE` vs. `ON CONFLICT … DO NOTHING`).
- Contagem de linhas realmente inseridas (COUNT antes/depois no SQLite; `rowcount`
  do psycopg2 no Postgres, correto sob concorrência).
- `RETURNING id`, `LOCK TABLE`, ajuste de sequence — cada um implementado onde faz
  sentido, no-op onde não faz.

`de(engine_ou_conn)` descobre o dialeto certo a partir do objeto de conexão,
permitindo manter os dois bancos abertos ao mesmo tempo (usado na migração).

#### [`gestao_fluxo/db/schema.sql`](gestao_fluxo/db/schema.sql) e [`schema_postgres.sql`](gestao_fluxo/db/schema_postgres.sql)
Os dois schemas descrevem a **mesma modelagem**, divergindo só no dialeto. Três
tabelas de fato (`fato_acompanhamento`, `fato_recebimento`, `fato_envios`), a
tabela `metas` (chave/valor, preservada nas recargas) e o log `cargas`. O índice
único sobre `(hash_linha, ocorrencia)` é o mecanismo inteiro da carga incremental.
O Postgres usa `DOUBLE PRECISION` (e não `REAL`) para não arredondar somas, e
`TEXT` para datas (para o hash bater com o do SQLite).

#### [`gestao_fluxo/db/migracao.py`](gestao_fluxo/db/migracao.py)
Cópia verificada de banco a banco, nos dois sentidos:

- **Migração** SQLite → Postgres (já feita e conferida).
- **Backup** Postgres → SQLite datado (`--backup`) — o uso vivo do módulo.
- **Conferência** (`--conferir`) sem gravar nada.

Copia os hashes **literalmente** (nunca recalcula no destino) e confere linha a
linha e soma a soma nas duas pontas. Se qualquer tabela divergir, a operação
falha e a origem fica intacta.

---

### Camada de ETL

#### [`gestao_fluxo/etl.py`](gestao_fluxo/etl.py)
Transformação e carga: **cada planilha vira uma tabela do banco, linha a linha,
sem alterar totais**. O pipeline por fonte é: ler → renomear 6 colunas → limpar
texto (oficina via de-para, MP) → converter data para ISO → corrigir o ano do
prazo defasado → calcular identidade → gravar. Principais funções:

- **Normalização**: `limpar_texto`, `normalizar_mp`, `normalizar_oficina`
  (aplica o de-para de oficinas), `datas_para_iso`, `corrigir_ano_deadline`
  (reescreve prazos que a origem exportou com o ano anterior).
- **Extração**: `extrair_fonte` casa colunas ignorando acento/caixa (header vem
  sujo) e devolve o DataFrame no formato da tabela de fato.
- **Prévia e carga**: `prever_carga` simula a carga (para o operador ver "312
  novas, 28 já existentes" antes de confirmar) e `executar_etl` grava de forma
  **transacional** — se qualquer fonte falhar, nada é gravado pela metade.
- **Relatório**: `RelatorioCarga` / `ResumoFonte` / `PreviaFonte` — o que a carga
  leu e gravou, para conferência com o Excel.

---

### Camada de cálculo

#### [`gestao_fluxo/metricas.py`](gestao_fluxo/metricas.py)
Regras de leitura e agregação — **pandas puro, nada de Streamlit**. Grupos:

- **Períodos**: meses disponíveis, `semanas_do_mes` (semanas recortadas nos
  limites do próprio mês), `periodo_anterior` — mês inteiro compara com mês
  inteiro; **semana compara com a semana de mesmo número do mês anterior** (S3 de
  julho × S3 de junho), caindo para a última semana quando o mês anterior é mais
  curto.
- **Filtro**: `filtrar` recorta o fato por intervalo, MPs e oficinas.
- **Métricas**: `calcular_metricas` (totais do recorte filtrado) e **duas** funções
  de média, com naturezas deliberadamente diferentes:
  - `calcular_medias_periodo` (diária e semanal) — **acompanha todos os filtros**
    (mês, semana, MP, oficina) e compara com o recorte equivalente do mês anterior,
    com os mesmos filtros aplicados dos dois lados.
  - `calcular_media_mensal` — média mensal de **todo o histórico**, imune a
    qualquer filtro. É referência, não recorte: média mensal do mês selecionado
    seria total ÷ 1 mês, ou seja, o próprio card de total. O delta mede o quanto o
    mês escolhido foge desse padrão.

  Ambas dividem só pelos períodos **com movimento**, e o denominador semanal usa as
  mesmas semanas de `semanas_do_mes` (não a semana ISO), para o card não divergir
  do gráfico de semanas.
- **Agregações para gráficos**: `por_oficina`, `por_mp`, `por_dia`, `por_semana`.
- **Acompanhamento**: `classificar_prazo` (status, dias para o prazo, dias em
  aberto), `resumo_a_receber`, `por_oficina_a_receber`.
- **Fluxo por matéria-prima**: `fluxo_por_mp` — enviado × recebido × em progresso,
  reatribuindo o recebimento à MP do envio da mesma ordem (a MP pode mudar entre
  sair e voltar).

#### [`gestao_fluxo/metas.py`](gestao_fluxo/metas.py)
Cadastro de metas, diluição por dias úteis e confronto com o realizado:

- **Persistência**: `garantir_tabela`, `ler_metas` (6 chaves sempre presentes),
  `salvar_metas` (upsert).
- **Dias úteis e diluição**: `dias_uteis` (segunda a sexta; feriado não
  descontado), `montar_plano` — cruza metas cadastradas com o realizado
  (Recebimento) e dilui a meta mensal por dia útil para achar necessidade por dia
  e por semana e o ritmo necessário para fechar o mês.
- **Modelos**: `Acompanhamento` (meta vs. realizado, com `falta`, `percentual`,
  `batida`) e `PlanoMetas` (tudo que a aba precisa exibir, já calculado).

---

### Camada de apresentação

#### [`gestao_fluxo/ui.py`](gestao_fluxo/ui.py)
Tema (CSS) e componentes visuais do Streamlit — **só renderização a partir de
valores já calculados**. É a fonte única do tema escuro (ver [DESIGN.md](DESIGN.md)):
tokens de cor, `injetar_tema` (injeta o CSS), cabeçalho com marca em SVG, títulos
de seção, `grade_cards`, `badges`, pílulas de status, e as tabelas de header verde
(`tabela_verde`, `tabela_paginada`, `tabela_fato`). Também os formatadores
tolerantes a falha (`fmt_int`, `fmt_data`, `delta_html` — que jamais derrubam a
tela por uma célula estranha) e `botao_excel` (download em `.xlsx`, com cache).

#### [`gestao_fluxo/charts.py`](gestao_fluxo/charts.py)
Gráficos interativos com [ECharts](https://echarts.apache.org) (CDN dentro de um
iframe). **Nenhuma consulta ou regra aqui** — recebe DataFrame já agregado por
`metricas` e devolve pixels. Monta o `option` do ECharts como dicionário Python,
com um truque (`js()` + `_serializar`) para embutir funções JS na serialização.
Gráficos: `rosca_por_mp`, `linha_por_dia`, `linha_por_semana` (série temporal
dupla peças/minutos) e `relogio_meta` (gauge de progresso da meta).

#### [`gestao_fluxo/excel.py`](gestao_fluxo/excel.py)
Geração das planilhas de download — relatório executivo em `.xlsx` via openpyxl.
Recebe o DataFrame **cru** (número como número, data como data) e devolve os bytes
da pasta de trabalho: a formatação vive aqui, então o Excel continua somando,
ordenando e filtrando. Trata caracteres de controle ilegais que o Excel recusaria,
deduz formatos numéricos por dtype, faz zebra, linha de totais, painel congelado,
filtro e preparo de impressão.

---

### Infraestrutura transversal

#### [`gestao_fluxo/log.py`](gestao_fluxo/log.py)
Log técnico — o outro lado do tratamento de exceções. A UI mostra a mensagem
amigável; o detalhe técnico vai para o arquivo `data/gestao_fluxo.log` (rotativo,
1 MB × 5 gerações). Cada falha inesperada recebe um **código curto** (ex.:
`a3f9c1`) que aparece na tela e no log, ligando o que o operador vê ao traceback
completo.

#### [`gestao_fluxo/__init__.py`](gestao_fluxo/__init__.py)
Docstring da arquitetura em camadas e a versão do pacote (`__version__`).

---

### Pontos de entrada

#### [`app.py`](app.py)
Dashboard Streamlit — **só orquestra**: `metricas` calcula, `charts` desenha, `ui`
estiliza. Monta a barra lateral (upload de planilhas em dois passos —
analisar/confirmar —, recarga da pasta, conferência e histórico de cargas) e as
cinco abas. Cada aba é **blindada individualmente** (`_blindar`): um erro numa
aba não derruba as outras, e toda falha de domínio vira mensagem amigável com
código de erro em vez de stack trace.

#### [`run_etl.py`](run_etl.py)
CLI para rodar o ETL fora do Streamlit (carga inicial ou recarga). Executa
`executar_etl` sobre as planilhas da raiz e imprime o relatório de carga. Uso:
`python run_etl.py`.

---

## O banco de dados

O projeto fala com **dois bancos, por motivos diferentes** — e nenhum outro módulo
precisa saber em qual está falando (o `dialeto` resolve):

- **Postgres (Supabase)** é a **produção**: histórico compartilhado entre
  máquinas, acesso simultâneo e backup fora do computador de quem opera. Ativado
  pela variável de ambiente `DATABASE_URL`.
- **SQLite** é o backend dos **testes** (e o fallback local quando não há
  `DATABASE_URL`). A suíte roda em arquivo temporário, sem credencial, sem rede,
  em milissegundos. **Não é uma camada obsoleta** — é o que mantém os testes
  rápidos e sem infraestrutura.

> **Nota:** a migração para o Supabase já foi concluída e conferida. O caminho de
> volta (`migracao.py --backup`) segue em uso para gerar backups datados em
> `data/backups/`.

### Modelo de dados

| Tabela | Papel | Modo de carga |
|--------|-------|---------------|
| `fato_acompanhamento` | Ordens **ainda em aberto** (já enviadas, não recebidas) + prazo | **Substituição** — é um retrato do agora |
| `fato_recebimento` | Histórico do que **retornou** das oficinas | Incremental |
| `fato_envios` | Histórico do que foi **despachado** para corte | Incremental |
| `fato_previsao` | Agenda do que **ainda vai voltar**, com prazo e envio | **Substituição** — é um retrato do agora |
| `metas` | 6 metas cadastradas pelo time (chave/valor) | Preservada nas recargas |
| `cargas` | Log de auditoria: o que entrou, quando, de qual arquivo | Append |

Os 6 campos do fato são `oficina, data, mp, qtd_pecas, minutos, om`; o
Acompanhamento carrega ainda `deadline`, e a Previsão `deadline` e `envio` (ver
`config.CAMPOS_EXTRA`). Datas ficam em ISO `YYYY-MM-DD`. Colunas de controle da
carga incremental: `hash_linha, ocorrencia, carga_id`.

Atenção ao campo `data` da Previsão: ele aponta para a coluna **RECEBIMENTO** da
planilha, e não para ENVIO como nas demais fontes. O evento daquela base é o
retorno previsto — é ele que responde "o que temos para receber nesta semana",
que é a pergunta da aba. Filtrar aquela tabela por `data` esperando envio dá um
recorte silenciosamente errado.

---

## Decisões de projeto que valem conhecer

- **Não se alteram totais.** Nenhum corte por ano, filtro escondido ou "linha
  atual". A única correção que o ETL faz nos números da origem é reescrever o ano
  de prazos exportados defasados — e ela é reportada na conferência da carga.
- **Carga incremental por identidade.** Uma linha é identificada pelo par
  `(hash_linha, ocorrencia)`. Re-subir a mesma planilha não insere nada, mas
  duas linhas legítimas idênticas na origem continuam valendo duas no banco. A
  direção é sempre conservadora: nunca inventa produção.
- **Acompanhamento é a exceção.** É um saldo em aberto, não um histórico — por
  isso é substituído por inteiro a cada carga (senão ordens já concluídas ficariam
  eternamente listadas como pendentes).
- **Falha nunca derruba a tela toda.** Abas blindadas, formatadores tolerantes,
  download tratado como extra opcional, e uma última linha de defesa no topo do
  app. O operador sempre recebe uma tela explicada com um código de erro.
- **O tema mora num só lugar.** Todo o CSS é injetado por `ui.py`; não existe
  `.streamlit/config.toml`. `charts.py` espelha as superfícies para os gráficos
  casarem com os cards.

---

## Como rodar

Requer **Python 3.10+** (o código usa `X | Y` em anotações de tipo).

```bash
# 1. Ambiente e dependências
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash);  .venv/bin/activate no Linux/macOS
pip install -r requirements.txt

# 2. (Opcional) Configurar o Postgres do Supabase — ver seção abaixo.
#    Sem isso, o app usa um SQLite local em data/fluxo_producao.db.

# 3. Carga inicial dos dados (lê as planilhas da raiz do projeto)
python run_etl.py

# 4. Subir o painel
streamlit run app.py
```

As planilhas de origem ficam na raiz do projeto: `ENVIOS_OFICINAS.xlsx`,
`RECEBIMENTO.xlsx`, `ACOMPANHAMENTO.xlsx` e `de_para_oficinas.xlsx` (mapa opcional
de nomes-padrão de oficina). Dentro do app, a barra lateral também permite subir
planilhas novas com prévia antes de gravar.

### Operações de banco

```bash
python -m gestao_fluxo.db.migracao --conferir   # compara SQLite e Postgres, sem gravar
python -m gestao_fluxo.db.migracao --backup     # Postgres → SQLite datado em data/backups/
```

---

## Configuração (`.env`)

A URL do banco de produção vem **do ambiente, nunca do código** (ela carrega a
senha). Crie um `.env` na raiz do projeto — ele fica fora do controle de versão:

```dotenv
# URL SQLAlchemy do Supabase. O painel do Supabase mostra "postgres://...";
# o app aceita e reescreve para "postgresql://" automaticamente.
DATABASE_URL=postgresql://usuario:senha@host:5432/postgres
```

- **Porta 5432** (session pooler) mantém um pool próprio; **porta 6543**
  (transaction pooler) desativa o pool local, pois o Supabase já faz o pooling.
- Sem `DATABASE_URL` definida, o app cai no SQLite local — útil para clonar e
  rodar numa máquina nova sem nenhum setup de infraestrutura.

---

## Deploy no Streamlit Cloud

O `.env` fica de fora do repositório (ver `.gitignore`), então ele nunca chega à
nuvem. Sem `DATABASE_URL` no ambiente do Streamlit Cloud, o app cai no SQLite
local — só que lá é um arquivo **novo e vazio** dentro do container efêmero, sem
nenhuma tabela. O sintoma é o app pedir para subir as planilhas de novo mesmo com
os dados já carregados no Supabase: ele não está enxergando um Supabase vazio, e
sim um SQLite que nunca existiu antes.

Para apontar o deploy para o Postgres do Supabase:

1. No painel do app, abra **Settings → Secrets**.
2. Cole a mesma URL usada no `.env` local, como chave de **nível raiz** do TOML
   (não dentro de uma seção `[...]` — só assim o Streamlit a expõe como variável
   de ambiente, que é o que `config.url_do_banco()` lê):

   ```toml
   DATABASE_URL = "postgresql://usuario:senha@host:5432/postgres"
   ```

3. Salve e reinicie o app (**Reboot**) para o processo pegar a variável nova.

Se depois disso o app ainda cair no SQLite, confira se a chave não ficou aninhada
sob uma seção e se não há espaços ou aspas extras na URL colada.

---

## Testes

A suíte (89 testes, [pytest](https://pytest.org)) roda sobre SQLite em arquivo
temporário, com planilhas sintéticas geradas nas fixtures
([tests/conftest.py](tests/conftest.py)). Cobre o que importa: a **regra de carga
incremental**, não o dialeto.

```bash
pytest
```

| Arquivo | Foco |
|---------|------|
| [test_etl.py](tests/test_etl.py) | Normalização, extração, carga incremental, substituição do Acompanhamento, prévia, log de cargas, migração, correção de prazo |
| [test_metas.py](tests/test_metas.py) | Persistência das metas, dias úteis, diluição, ritmo necessário, prioridade de meta cadastrada vs. diluída |
| [test_metricas.py](tests/test_metricas.py) | Períodos e semanas, filtros, médias e variação, agregações, classificação de prazo, saldo a receber, fluxo por MP |
| [test_previsao.py](tests/test_previsao.py) | Extração da previsão (`data` = RECEBIMENTO), substituição da tabela, classificação dos dois riscos de prazo, resumo dos cards, filtros de período/MP |
| [test_robustez.py](tests/test_robustez.py) | Casos-limite que não podem derrubar a tela (caractere de controle no Excel, coluna ausente) |

---

## Estrutura de arquivos

```
APP_OFICINAS/
├── app.py                      # Dashboard Streamlit (5 abas) — ponto de entrada
├── run_etl.py                  # CLI de carga fora do Streamlit
├── requirements.txt
├── README.md                   # este arquivo
├── DESIGN.md                   # design system do tema escuro
├── LICENSE
├── .env                        # DATABASE_URL (fora do git)
│
├── gestao_fluxo/               # o pacote da aplicação
│   ├── __init__.py             # docstring da arquitetura + versão
│   ├── config.py               # caminhos, mapa planilha→tabela, chaves de meta
│   ├── exceptions.py           # exceções de domínio com mensagem amigável
│   ├── log.py                  # log técnico rotativo + códigos de erro
│   ├── etl.py                  # transformação e carga (incremental / substituição)
│   ├── excel.py                # relatório executivo .xlsx para download
│   ├── metricas.py             # consultas e cálculo dos indicadores
│   ├── metas.py                # metas: diluição por dia útil e realizado
│   ├── charts.py               # gráficos ECharts
│   ├── ui.py                   # tema (CSS) e componentes do Streamlit
│   └── db/
│       ├── __init__.py
│       ├── database.py         # engine, schema, identidade, escrita, leitura
│       ├── dialeto.py          # diferenças SQLite × Postgres isoladas
│       ├── schema.sql          # schema SQLite (testes)
│       ├── schema_postgres.sql # schema Postgres (Supabase / produção)
│       └── migracao.py         # cópia verificada de banco a banco / backup
│
├── tests/                      # suíte pytest (SQLite temporário)
│   ├── conftest.py             # fixtures: engine e planilhas sintéticas
│   ├── test_etl.py
│   ├── test_metas.py
│   ├── test_metricas.py
│   └── test_robustez.py
│
└── data/                       # gerado em runtime (banco, log, backups)
    ├── fluxo_producao.db       # SQLite local (quando sem DATABASE_URL)
    ├── gestao_fluxo.log
    └── backups/                # backups datados do Postgres
```
