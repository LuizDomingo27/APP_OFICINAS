# Design System — Fluxo de Produção

Painel operacional de tema escuro. A direção é **densa, quieta e escaneável**: a
tela é usada todo dia pelas mesmas pessoas, então cor é reservada para dado e
estado — nunca para decoração. Sem emojis em nenhuma superfície; os poucos
ícones são SVG inline.

## Tokens de cor

| Token             | Hex       | Uso                                              |
|-------------------|-----------|--------------------------------------------------|
| Fundo (canvas)    | `#0B0F14` | `backgroundColor` — o plano mais ao fundo        |
| Superfície        | `#121821` | Cartões, tabela, formulários, sidebar            |
| Superfície 2      | `#182029` | Campos, header de tabela, hover de linha         |
| Linha             | `#212B36` | Todas as bordas de 1px                           |
| Tinta (texto)     | `#E6EDF3` | Texto principal e números                        |
| Muted             | `#8B98A9` | Rótulos, legendas, eixos                         |
| Verde (primary)   | `#2DD4BF` | Barra de seção, aba ativa, botão primário        |
| Verde escuro      | `#14B8A6` | Fim do gradiente do botão primário               |

Três planos de profundidade (canvas → superfície → superfície 2) substituem a
sombra: no escuro, sombra some e só elevação por cor separa as camadas.

### Acentos dos cartões (fio de 2px no topo + ponto no rótulo)

| Token   | Hex       |
|---------|-----------|
| teal    | `#2DD4BF` |
| emerald | `#34D399` |
| sky     | `#38BDF8` |
| violet  | `#A78BFA` |
| amber   | `#F59E0B` |
| rose    | `#FB7185` |

### Estado (pílulas de prazo e badges de meta)

Fundo translúcido a 12% + borda a 28% da própria cor, texto na cor cheia.
Atrasado `#F87171` · Vence em breve `#FBBF24` · No prazo `#34D399` · Sem prazo `#8B98A9`.

Contraste medido no runtime: mínimo 5.6:1 (muted sobre superfície 2), tinta a
15:1 — todos acima do AA (4.5:1).

## Componentes

- **Header**: superfície + borda 1px, marca em SVG dentro de quadrado com
  gradiente teal→verde. Título 700/1.2rem, subtítulo muted.
- **Título de seção**: peso 700 + barra vertical verde de 3px à esquerda.
- **KPI card**: fio de acento de 2px no topo, ponto de acento antes do rótulo em
  caixa-alta, número 1.9rem/700 com numerais tabulares. Raio 14px, sem sombra.
- **Tabela**: header em superfície 2 com rótulo muted em caixa-alta espaçada —
  sem faixa colorida, que roubaria atenção dos dados. Sem zebra; a separação vem
  da borda de 1px e do hover. Oficina em verde, à esquerda; números centralizados.
- **Formulário de metas**: cartão único com três blocos (Mês / Semana / Dia),
  cada um aberto por uma faixa com ponto de acento. Rótulo 700, valor 1.2rem/700
  alinhado à direita, campo limitado a 230px — a caixa acompanha o conteúdo.
- **Gráficos (ECharts)**: rodam em iframe com fundo próprio, então cada um pinta
  a superfície e a borda para casar com os cartões. Eixos e legendas em muted.

## Onde vive

- CSS e componentes: [gestao_fluxo/ui.py](gestao_fluxo/ui.py)
- Paleta dos gráficos: [gestao_fluxo/charts.py](gestao_fluxo/charts.py)

Não existe `.streamlit/config.toml`: o tema inteiro é CSS injetado por `ui.py`,
e o único ajuste de página é o `set_page_config` em [app.py](app.py). Manter o
tema num só lugar evita a paleta viver em duas fontes que saem de sincronia.

Para trocar a paleta, ajuste os hex em `ui.py` (`VERDE`, `ACENTOS`, `SUPERFICIE`
e vizinhos) e espelhe as superfícies em `charts.py` — o restante herda via
variáveis CSS (`--verde`, `--surface`, `--accent`).
