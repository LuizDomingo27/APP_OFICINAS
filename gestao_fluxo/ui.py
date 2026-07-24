"""Camada de apresentação — tema (CSS) e componentes visuais do Streamlit.

Tema escuro de painel operacional (ver DESIGN.md): canvas quase preto, superfícies
elevadas em grafite azulado, borda fina de 1px e acentos de cor reservados para
dado — nunca para decoração. Sem emojis: os ícones são SVG inline.
Nenhuma regra de negócio aqui — só renderização a partir de valores já calculados.
"""
from __future__ import annotations

import html
import math

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from gestao_fluxo import excel, log
from gestao_fluxo.exceptions import GestaoFluxoError

_LOG = log.obter("ui")

# Paleta do tema escuro (ver DESIGN.md).
VERDE = "#2DD4BF"
VERDE_ESCURO = "#14B8A6"
ACENTOS = {
    "teal": "#2DD4BF",
    "rose": "#FB7185",
    "amber": "#F59E0B",
    "emerald": "#34D399",
    "sky": "#38BDF8",
    "violet": "#A78BFA",
}

# Superfícies e tinta — usados também por charts.py para casar os gráficos.
FUNDO = "#0B0F14"
SUPERFICIE = "#121821"
SUPERFICIE_2 = "#182029"
LINHA = "#212B36"
TINTA = "#E6EDF3"
MUTED = "#8B98A9"

_CSS = """
<style>
:root {
    --verde:#2DD4BF; --verde-escuro:#14B8A6;
    --bg:#0B0F14; --surface:#121821; --surface-2:#182029;
    --linha:#212B36; --tinta:#E6EDF3; --muted:#8B98A9;
}
.stApp { background:var(--bg); }

/* ================================================================== *
 * NAVBAR — barra fixa no topo (substitui a antiga sidebar)
 *
 * A barra nativa do Streamlit fica transparente e a toolbar (Deploy /
 * menu) some: sem isso dois "topos" disputam a mesma faixa e o botão de
 * ação da direita cai embaixo do menu do próprio Streamlit.
 * ================================================================== */
/* `pointer-events:none` no header não é cosmético: ele é uma faixa fixa de
   60px com z-index 999990, então ficava por cima da navbar e engolia TODOS os
   cliques dela (abas, botão de ação e hamburguer). Deixá-lo transparente
   resolvia só a aparência — a barra continuava inerte. Como a toolbar está
   escondida, não sobra nada de interativo nele para perder. */
[data-testid="stHeader"] { background:transparent; pointer-events:none; }
[data-testid="stToolbar"] { display:none; }

/* padding-top abre espaço para a barra fixa (~64px) sem que o primeiro
   bloco da página nasça escondido embaixo dela. */
.block-container { padding-top: 6rem; max-width: 1470px; }

/* `position:fixed` e não `sticky`: o Streamlit envolve cada `st.container`
   num wrapper que abraça só a altura do próprio conteúdo, e isso deixa o
   sticky sem folga para "grudar" — na prática a barra sumia ao rolar. */
.st-key-navbar {
    /* z-index acima do header do Streamlit (999990) — ver a nota lá em cima. */
    position:fixed; top:0; left:0; right:0; z-index:999991;
    background:rgba(18,24,33,.82);
    -webkit-backdrop-filter:blur(14px) saturate(150%);
    backdrop-filter:blur(14px) saturate(150%);
    border-bottom:1px solid var(--linha);
    transition:background-color .25s ease, box-shadow .25s ease;
}
/* Alinha o conteúdo da barra com a coluna de conteúdo da página: mesmo
   teto de largura e mesma respiração lateral do `.block-container`. */
.st-key-navbar > [data-testid="stLayoutWrapper"] {
    max-width:1470px; margin:0 auto;
    padding:13px clamp(20px, 5.5vw, 80px);
    transition:padding .25s ease;
}
/* Estado rolado (classe posta pelo script da navbar): barra mais baixa,
   fundo mais opaco e sombra — vira uma camada sobre o conteúdo. */
.st-key-navbar.nav-scrolled {
    background:rgba(13,18,25,.94);
    box-shadow:0 8px 26px -12px rgba(0,0,0,.85);
}
.st-key-navbar.nav-scrolled > [data-testid="stLayoutWrapper"] {
    padding-top:7px; padding-bottom:7px;
}
/* As colunas da barra nunca quebram em linhas: é uma faixa só. */
.st-key-navbar [data-testid="stHorizontalBlock"] {
    align-items:center; flex-wrap:nowrap; gap:16px;
}

/* ---- Marca (logo + título) ---- */
.navbar-brand { display:flex; align-items:center; gap:12px; }
.app-logo {
    width:34px; height:34px; border-radius:10px; display:grid; place-items:center;
    background:linear-gradient(135deg,#2DD4BF,#14B8A6); color:#08131A; flex:none;
    box-shadow:0 4px 14px -6px rgba(45,212,191,.7);
}
.app-logo svg { width:19px; height:19px; display:block; }
.app-title {
    font-size:1.02rem; font-weight:700; color:var(--tinta);
    line-height:1.2; letter-spacing:-.01em; white-space:nowrap;
}

/* ---- Botão de ação "Dados" (gatilho do popover) ---- */
/* A coluna da ação é mais larga que o botão (ela reserva a fatia da faixa) e
   o wrapper do popover encolhe até o conteúdo — sem `align-items:flex-end` o
   botão fica boiando no meio da coluna em vez de ancorar na direita. */
.st-key-navbar [data-testid="stColumn"]:nth-child(3) > [data-testid="stVerticalBlock"] {
    align-items:flex-end;
}
/* Reusa o formato de ação primária que já existe no app (o mesmo de
   "Salvar metas" e dos downloads): gradiente verde e tinta escura. */
.st-key-navbar [data-testid="stPopoverButton"] {
    background:linear-gradient(135deg,#2DD4BF,#14B8A6);
    border:none; border-radius:10px;
    font-weight:700; font-size:.85rem; letter-spacing:.01em;
    padding:9px 18px; white-space:nowrap;
    transition:filter .15s ease, transform .15s ease;
}
.st-key-navbar [data-testid="stPopoverButton"]:hover {
    filter:brightness(1.08); transform:translateY(-1px);
}
/* O Streamlit repinta o texto no hover/active; travamos a tinta escura. */
.st-key-navbar [data-testid="stPopoverButton"],
.st-key-navbar [data-testid="stPopoverButton"] p,
.st-key-navbar [data-testid="stPopoverButton"]:hover,
.st-key-navbar [data-testid="stPopoverButton"]:active { color:#08131A; }
.st-key-navbar [data-testid="stPopoverButton"] svg { fill:#08131A; }
.st-key-navbar [data-testid="stPopoverButton"]:focus-visible {
    outline:none; box-shadow:0 0 0 3px rgba(45,212,191,.32);
}
/* Painel flutuante do popover. */
div[data-testid="stPopoverBody"] {
    background:var(--surface); border:1px solid var(--linha); border-radius:14px;
}

/* ---- Botão hamburguer (só no mobile; criado pelo script da navbar) ---- */
.nav-burger {
    display:none; flex:none; width:38px; height:38px; padding:0;
    background:var(--surface-2); border:1px solid var(--linha); border-radius:10px;
    cursor:pointer; position:relative;
    transition:border-color .15s ease;
}
.nav-burger:hover { border-color:var(--verde); }
.nav-burger span {
    position:absolute; left:50%; width:16px; height:2px; border-radius:2px;
    background:var(--tinta); transform:translateX(-50%);
    transition:transform .25s ease, opacity .2s ease;
}
.nav-burger span:nth-child(1) { top:12px; }
.nav-burger span:nth-child(2) { top:18px; }
.nav-burger span:nth-child(3) { top:24px; }
/* Aberto: as duas pontas viram X e a do meio some. */
.nav-open .nav-burger span:nth-child(1) { transform:translate(-50%,6px) rotate(45deg); }
.nav-open .nav-burger span:nth-child(2) { opacity:0; }
.nav-open .nav-burger span:nth-child(3) { transform:translate(-50%,-6px) rotate(-45deg); }

/* O iframe do script da navbar não ocupa espaço nem intercepta cliques. */
.st-key-navbar-js { height:0; overflow:hidden; pointer-events:none; }

.sec-title {
    font-weight:700; color:var(--tinta); font-size:1rem; letter-spacing:-.01em;
    margin:30px 0 14px; padding-left:12px; border-left:3px solid var(--verde);
}
/* Variante para quando o título divide a linha com filtros (st.columns com
   vertical_alignment="bottom"). A coluna alinha as bases, mas a do título não
   tem o rótulo do campo acima: o padding inferior é o que sobe o texto até a
   altura da caixa do select, em vez de deixá-lo pendurado embaixo dela. */
.sec-title.inline { margin:0; padding:2px 0 22px 12px; }

.kpi-grid { display:flex; flex-wrap:wrap; gap:14px; }
.kpi-card {
    flex:1 1 200px; background:var(--surface); border:1px solid var(--linha);
    border-radius:14px; padding:18px 18px 16px;
    position:relative; overflow:hidden; transition:border-color .15s;
}
/* Fio de acento no topo: identifica a métrica sem gastar cor no fundo. */
.kpi-card::before {
    content:""; position:absolute; inset:0 0 auto 0; height:2px;
    background:var(--accent, #2DD4BF);
}
.kpi-card:hover { border-color:#2E3A47; }
.kpi-top { display:flex; align-items:center; gap:8px; }
/* Ponto de acento no lugar do antigo ícone — marcador discreto, sem emoji. */
.kpi-dot {
    width:6px; height:6px; border-radius:50%; flex:none;
    background:var(--accent, #2DD4BF);
}
.kpi-label {
    font-size:.7rem; font-weight:600; letter-spacing:.08em;
    text-transform:uppercase; color:var(--muted);
}
.kpi-valor {
    font-size:1.9rem; font-weight:700; color:var(--tinta); margin:10px 0 3px;
    letter-spacing:-.02em; font-variant-numeric:tabular-nums;
}
.kpi-sub    { font-size:.8rem; color:var(--muted); line-height:1.3; }
.kpi-strong { font-size:1rem; font-weight:700; color:var(--tinta); }

/* max-height (e não height) mantém tabelas curtas na altura do conteúdo:
   a barra de rolagem só aparece quando as linhas ultrapassam o limite. */
.tbl-wrap {
    overflow:auto; max-height:60vh; border-radius:14px; border:1px solid var(--linha);
    margin-top:6px; background:var(--surface);
    scrollbar-width:thin; scrollbar-color:#2E3A47 var(--surface-2);
}
.tbl-wrap::-webkit-scrollbar { width:10px; height:10px; }
.tbl-wrap::-webkit-scrollbar-track { background:var(--surface-2); }
.tbl-wrap::-webkit-scrollbar-thumb {
    background:#2E3A47; border-radius:8px; border:2px solid var(--surface-2);
}
.tbl-wrap::-webkit-scrollbar-thumb:hover { background:#3C4A59; }
table.gf {
    border-collapse:collapse; width:100%; background:var(--surface); font-size:.875rem;
}
/* Header na mesma faixa verde dos botões de ação (o gradiente é o mesmo, ver o
   bloco de botão primária adiante): a tabela passa a ser reconhecida como um
   bloco do produto, não como um trecho solto de texto. A tinta escura sobre o
   verde é a mesma dos botões e mantém o contraste alto. */
table.gf thead th {
    background:linear-gradient(135deg,#2DD4BF,#14B8A6); color:#08131A;
    text-align:center;
    padding:12px 16px; white-space:nowrap; font-size:.68rem; font-weight:700;
    letter-spacing:.09em; text-transform:uppercase;
    border-bottom:1px solid var(--verde-escuro); position:sticky; top:0; z-index:2;
}
table.gf tbody td {
    padding:11px 16px; border-bottom:1px solid var(--linha); color:var(--tinta);
    text-align:center;
}
table.gf tbody tr:last-child td { border-bottom:none; }
table.gf tbody tr:hover { background:var(--surface-2); }
table.gf tbody td.num { font-variant-numeric:tabular-nums; }
/* Única exceção ao alinhamento central: o nome da oficina fica à esquerda,
   por ser texto longo e servir de âncora de leitura da linha. */
table.gf tbody td.of { color:var(--verde); font-weight:600; text-align:left; }

/* Pílula de situação (prazo) — fundo translúcido + borda da própria cor. */
.pill {
    display:inline-block; padding:3px 10px; border-radius:6px;
    font-size:.7rem; font-weight:600; letter-spacing:.03em; white-space:nowrap;
    border:1px solid transparent;
}
.pill.atrasado    { background:rgba(248,113,113,.12); color:#F87171;
                    border-color:rgba(248,113,113,.28); }
.pill.vence-breve { background:rgba(245,158,11,.12);  color:#FBBF24;
                    border-color:rgba(245,158,11,.28); }
.pill.no-prazo    { background:rgba(52,211,153,.12);  color:#34D399;
                    border-color:rgba(52,211,153,.28); }
.pill.sem-prazo   { background:rgba(139,152,169,.12); color:var(--muted);
                    border-color:rgba(139,152,169,.26); }

.tbl-rodape { font-size:.8rem; color:var(--muted); margin:8px 2px 0; }

/* Variação percentual dentro do card (atual vs. período anterior) */
.delta { font-weight:700; font-size:.84rem; }
.delta.up   { color:#34D399; }
.delta.down { color:#F87171; }
.delta.flat { color:var(--muted); }

/* Badges da aba de Metas — no escuro o gradiente saturado vira ruído, então o
   estado é dito pela borda e por um fundo translúcido da mesma cor. */
.badge-row { display:flex; flex-wrap:wrap; gap:12px; margin-top:10px; }
.badge {
    flex:1 1 220px; border-radius:14px; padding:16px 18px;
    background:var(--surface); border:1px solid var(--linha);
    border-left:3px solid var(--estado, #8B98A9);
}
.badge.ok     { --estado:#34D399; background:linear-gradient(90deg,
                rgba(52,211,153,.07), var(--surface) 55%); }
.badge.falta  { --estado:#F87171; background:linear-gradient(90deg,
                rgba(248,113,113,.07), var(--surface) 55%); }
.badge.neutro { --estado:#8B98A9; }
.badge-label {
    font-size:.7rem; font-weight:600; letter-spacing:.08em;
    text-transform:uppercase; color:var(--muted);
}
.badge-valor {
    font-size:1.55rem; font-weight:700; margin:6px 0 3px; color:var(--tinta);
    letter-spacing:-.02em; font-variant-numeric:tabular-nums;
}
.badge-sub { font-size:.8rem; color:var(--muted); }

/* ---- Widgets nativos do Streamlit ---- */
/* Navegação principal — pills dentro da própria navbar, no lugar das antigas
   abas (`st.tabs` não dava para embutir na mesma linha da marca e do botão
   "Dados": o conteúdo de cada aba nasce preso à largura de onde o widget foi
   criado). Com `st.segmented_control` só o seletor mora na navbar; o conteúdo
   da seção ativa renderiza solto, em largura cheia, logo abaixo.
   ATENÇÃO ao seletor: o `st.segmented_control` NÃO gera um
   `[data-testid="stSegmentedControl"]` — ele sai como `stButtonGroup` com
   `button[data-variant="segmented_control"]`, e o estado ativo vem em
   `aria-checked`, não em `:checked` nem em `<label>`. Mirar no testid errado
   é silencioso: o CSS simplesmente não casa e as abas ficam com o visual
   cru do Streamlit. */
.st-key-navbar [data-testid="stButtonGroup"] {
    display:flex; justify-content:center;
}
.st-key-navbar [data-testid="stButtonGroup"] > div[role="radiogroup"] {
    display:flex; gap:4px; background:rgba(24,32,41,.55);
    border:1px solid var(--linha); border-radius:12px; padding:4px;
}
.st-key-navbar [data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
    background:transparent; border:none; border-radius:9px;
    color:var(--muted); font-weight:600; font-size:.85rem;
    padding:7px 16px; white-space:nowrap;
    transition:color .18s ease, background-color .18s ease;
}
.st-key-navbar [data-testid="stButtonGroup"] button[data-variant="segmented_control"] p {
    color:inherit; font-weight:inherit; font-size:inherit;
}
.st-key-navbar [data-testid="stButtonGroup"]
    button[data-variant="segmented_control"]:hover {
    background:var(--surface-2); color:var(--tinta);
}
/* Seção ativa: superfície elevada + tinta clara e um fio verde embaixo — o
   acento marca o item sem competir com o botão de ação (o único gradiente
   da barra). */
.st-key-navbar [data-testid="stButtonGroup"]
    button[data-variant="segmented_control"][aria-checked="true"] {
    background:var(--surface-2); color:var(--tinta);
    box-shadow:inset 0 -2px 0 0 var(--verde);
}
.st-key-navbar [data-testid="stButtonGroup"]
    button[data-variant="segmented_control"]:focus-visible {
    outline:none; box-shadow:0 0 0 2px rgba(45,212,191,.45);
}

/* ================= Responsivo ================= */
/* Até 900px o menu central sai da faixa e vira um painel que desce sob a
   barra, aberto pelo hamburguer. As colunas do Streamlit são forçadas a
   continuar em linha: sem isso elas empilham e a barra vira um bloco alto. */
@media (max-width: 900px) {
    .nav-burger { display:block; }
    .st-key-navbar > [data-testid="stLayoutWrapper"] { padding:10px 18px; }
    .st-key-navbar [data-testid="stHorizontalBlock"] { gap:10px; }

    /* Abaixo do seu breakpoint o Streamlit põe `min-width:calc(100% - 24px)`
       em cada coluna — é assim que ele empilha. Como aqui a faixa é forçada a
       continuar em linha, esse mínimo faz as colunas somarem mais que a tela e
       o hamburguer é empurrado para fora dela. Zerar o mínimo devolve o
       controle da largura ao flex. */
    .st-key-navbar [data-testid="stColumn"] { min-width:0 !important; }
    /* Marca ocupa a folga; a ação fica só com o tamanho do próprio botão.
       `min-width:max-content` na coluna da ação é o que impede o botão de ser
       espremido pela coluna da marca até o rótulo truncar. */
    .st-key-navbar [data-testid="stColumn"]:nth-child(1) { flex:1 1 auto !important; }
    .st-key-navbar [data-testid="stColumn"]:nth-child(3) {
        flex:0 0 auto !important; min-width:max-content !important;
    }

    /* Coluna do meio (menu) — painel suspenso, escondido por padrão. */
    /* `width:100%` explícito: só `left:0; right:0` não basta porque a coluna
       herda uma largura calculada do flex e ela vence o esticamento. */
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) {
        position:absolute; top:100%; left:0; right:0; width:100% !important;
        background:var(--surface); border-bottom:1px solid var(--linha);
        box-shadow:0 14px 30px -18px rgba(0,0,0,.9);
        padding:12px 18px;
        opacity:0; visibility:hidden; transform:translateY(-8px);
        transition:opacity .2s ease, transform .2s ease, visibility .2s;
    }
    /* Os contêineres intermediários do Streamlit também encolhem ao conteúdo —
       o `stElementContainer` em especial recebe uma largura calculada e, sem
       este reset, o menu fica com a largura do rótulo mais longo em vez da
       largura do painel. */
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) [data-testid="stVerticalBlock"],
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) [data-testid="stLayoutWrapper"],
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) [data-testid="stElementContainer"],
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) [data-testid="stButtonGroup"],
    .st-key-navbar [data-testid="stColumn"]:nth-child(2) div[role="radiogroup"] {
        /* `max-width` também precisa cair: o Streamlit põe `fit-content` no
           radiogroup, e isso sozinho anula o `width:100%`. */
        width:100% !important; max-width:none !important;
    }
    .st-key-navbar.nav-open [data-testid="stColumn"]:nth-child(2) {
        opacity:1; visibility:visible; transform:translateY(0);
    }
    /* No painel o menu ocupa a largura toda, um item por linha. */
    .st-key-navbar [data-testid="stButtonGroup"] > div[role="radiogroup"] {
        flex-direction:column; width:100%; background:transparent;
        border:none; padding:0; gap:2px;
    }
    .st-key-navbar [data-testid="stButtonGroup"]
        button[data-variant="segmented_control"] {
        width:100%; text-align:left; justify-content:flex-start; padding:11px 14px;
    }
    /* O rótulo mora em dois contêineres flex (div > span) que centralizam por
       conta própria: só `text-align:left` não move nada, porque o parágrafo é
       mais estreito que o botão e quem o posiciona é o `justify-content`. Sem
       isto o texto fica no meio, brigando com o fio verde da esquerda que
       marca o item ativo. */
    .st-key-navbar [data-testid="stButtonGroup"]
        button[data-variant="segmented_control"] > div,
    .st-key-navbar [data-testid="stButtonGroup"]
        button[data-variant="segmented_control"] > div > span {
        width:100%; justify-content:flex-start !important;
    }
    .st-key-navbar [data-testid="stButtonGroup"]
        button[data-variant="segmented_control"] p { text-align:left; }
    .st-key-navbar [data-testid="stButtonGroup"]
        button[data-variant="segmented_control"][aria-checked="true"] {
        box-shadow:inset 2px 0 0 0 var(--verde);
    }
}
/* Telas bem estreitas: o título da marca sai e fica só o logo. */
@media (max-width: 460px) {
    .app-title { display:none; }
    .st-key-navbar [data-testid="stPopoverButton"] { padding:9px 13px; }
}

[data-testid="stDataFrame"], [data-testid="stExpander"] {
    border-radius:12px; border-color:var(--linha);
}
.stApp [data-testid="stMetricValue"] { color:var(--tinta); }

/* ------------------------------------------------------------------ *
 * Cadastro de metas — o formulário é o ponto de entrada da aba, então
 * ganha cartão próprio, rótulos grandes em negrito e campos estreitos
 * (o conteúdo é um número curto; caixa larga só dispersa a leitura).
 * O escopo `.st-key-metas-form` vem do `key` do container no app.py.
 * ------------------------------------------------------------------ */
.st-key-metas-form [data-testid="stForm"] {
    background:var(--surface); border:1px solid var(--linha); border-radius:16px;
    padding:24px 26px 20px;
}
.metas-hint {
    font-size:.9rem; font-weight:400; color:var(--muted);
    line-height:1.5; margin:0 0 22px; max-width:70ch;
}
.metas-grupo {
    display:flex; align-items:center; gap:9px;
    font-size:.95rem; font-weight:700; color:var(--tinta);
    letter-spacing:.05em; text-transform:uppercase;
    padding:10px 14px; margin-bottom:18px; border-radius:10px;
    background:var(--surface-2); border-left:3px solid var(--accent);
}
/* Ponto de acento no lugar do ícone — mesmo marcador dos cards de KPI. */
.metas-grupo-dot {
    width:7px; height:7px; border-radius:50%; background:var(--accent); flex:none;
}

/* Rótulo do campo: maior e em negrito, como pedido. */
.st-key-metas-form [data-testid="stWidgetLabel"] p {
    font-size:.95rem !important; font-weight:700 !important;
    color:var(--tinta) !important; letter-spacing:.01em;
}
/* Largura presa ao conteúdo (número + steppers), não à coluna. */
.st-key-metas-form [data-testid="stNumberInputContainer"] { max-width:230px; }
.st-key-metas-form [data-baseweb="input"] {
    border-radius:10px; border:1px solid var(--linha); background:var(--surface-2);
    transition:border-color .15s, box-shadow .15s;
}
.st-key-metas-form [data-baseweb="input"]:focus-within {
    border-color:var(--verde); box-shadow:0 0 0 3px rgba(45,212,191,.14);
}
.st-key-metas-form input[type="number"] {
    font-size:1.2rem !important; font-weight:700 !important;
    color:var(--tinta) !important; text-align:right;
    font-variant-numeric:tabular-nums; background:transparent;
}
/* ------------------------------------------------------------------ *
 * Botão de ação primária — o mesmo desenho para "Salvar metas" e para
 * os downloads de planilha, que são as duas ações que o usuário executa
 * de fato nesta tela. Um só estilo evita hierarquia falsa entre elas.
 * ------------------------------------------------------------------ */
.st-key-metas-form [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
    font-size:.92rem; font-weight:700; letter-spacing:.01em;
    padding:11px 22px; border-radius:10px; border:none; color:#08131A;
    background:linear-gradient(135deg,#2DD4BF,#14B8A6);
    transition:filter .12s, transform .12s;
}
.st-key-metas-form [data-testid="stFormSubmitButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {
    filter:brightness(1.08); transform:translateY(-1px);
}
/* O Streamlit repinta o texto no hover/active; travamos a tinta escura. */
[data-testid="stDownloadButton"] button:hover,
[data-testid="stDownloadButton"] button:active,
[data-testid="stDownloadButton"] button:focus,
[data-testid="stDownloadButton"] button p { color:#08131A; }
[data-testid="stDownloadButton"] button:focus-visible {
    outline:none; box-shadow:0 0 0 3px rgba(45,212,191,.32);
}
/* O botão nasce colado na tabela; um respiro acima o separa do bloco. */
[data-testid="stDownloadButton"] { margin-top:14px; }
</style>
"""

# Blocos do formulário de metas: (período, título, acento).
METAS_GRUPOS: tuple = (
    ("mes", "Mês", VERDE),
    ("semana", "Semana", ACENTOS["sky"]),
    ("dia", "Dia", ACENTOS["violet"]),
)


def injetar_tema() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# Marca do app: caixa em perspectiva (fluxo de produção), traçada em SVG para não
# depender de fonte de emoji e para herdar a cor do quadrado de acento.
_LOGO_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M21 8V16L12 21L3 16V8L12 3L21 8Z"/>'
    '<path d="M3 8L12 13L21 8"/><path d="M12 13V21"/></svg>'
)


def cabecalho(titulo: str) -> None:
    """Marca do app (logo + título): a ponta esquerda da navbar.

    Só o título — o subtítulo saiu junto com a barra antiga: numa faixa de
    ~64px ele quebrava em duas linhas e repetia, em letra miúda, exatamente
    os nomes das seções que o menu ao lado já mostra.
    """
    st.markdown(
        f"""<div class="navbar-brand">
            <div class="app-logo">{_LOGO_SVG}</div>
            <div class="app-title">{html.escape(titulo)}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# Comportamento da navbar. Vai por `components.html` (um iframe) porque
# `st.markdown` não executa <script> — de dentro do iframe o script alcança a
# página pelo `window.parent`. Duas responsabilidades só:
#   1. classe `nav-scrolled` quando a página sai do topo (encolhe + sombra);
#   2. hamburguer no mobile, que liga/desliga a classe `nav-open`.
# A navegação em si continua sendo o widget do Streamlit — o script nunca
# decide qual seção está ativa, senão o estado do Python e o da tela divergem.
_NAVBAR_JS = """
<script>
(function () {
  const doc = window.parent.document;

  function montar() {
    const nav = doc.querySelector('.st-key-navbar');
    if (!nav) return false;

    // --- 1. Transição ao rolar -------------------------------------------
    if (!nav.dataset.scrollLigado) {
      // Conforme a versão, o Streamlit rola a janela ou um contêiner interno:
      // observamos os dois e ficamos com o maior deslocamento.
      const alvo = doc.querySelector('[data-testid="stMain"]');
      const aoRolar = () => {
        const y = Math.max(
          window.parent.scrollY || 0,
          doc.documentElement.scrollTop || 0,
          alvo ? alvo.scrollTop : 0
        );
        nav.classList.toggle('nav-scrolled', y > 8);
      };
      window.parent.addEventListener('scroll', aoRolar, { passive: true });
      if (alvo) alvo.addEventListener('scroll', aoRolar, { passive: true });
      nav.dataset.scrollLigado = '1';
      aoRolar();
    }

    // --- 2. Hamburguer ----------------------------------------------------
    if (!nav.querySelector('.nav-burger')) {
      const b = doc.createElement('button');
      b.className = 'nav-burger';
      b.type = 'button';
      b.setAttribute('aria-label', 'Abrir menu');
      b.setAttribute('aria-expanded', 'false');
      b.innerHTML = '<span></span><span></span><span></span>';
      b.addEventListener('click', () => {
        const aberto = nav.classList.toggle('nav-open');
        b.setAttribute('aria-expanded', String(aberto));
        b.setAttribute('aria-label', aberto ? 'Fechar menu' : 'Abrir menu');
      });
      // Entra na faixa, entre a marca e o botão de ação.
      const faixa = nav.querySelector('[data-testid="stHorizontalBlock"]');
      (faixa || nav).appendChild(b);
    }

    // Escolher uma seção fecha o painel do mobile.
    nav.querySelectorAll('[data-testid="stButtonGroup"] button').forEach((btn) => {
      if (btn.dataset.fechaMenu) return;
      btn.addEventListener('click', () => nav.classList.remove('nav-open'));
      btn.dataset.fechaMenu = '1';
    });
    return true;
  }

  // O Streamlit troca nós do DOM a cada rerun e leva junto o que penduramos
  // nele, então o observador fica de pé remontando o que sumir. `montar` é
  // idempotente (cada parte checa antes de agir), então repetir não custa.
  montar();
  new MutationObserver(() => montar())
    .observe(doc.body, { childList: true, subtree: true });
})();
</script>
"""


def navbar_comportamento() -> None:
    """Liga o sticky/scroll e o hamburguer da navbar (ver `_NAVBAR_JS`)."""
    with st.container(key="navbar-js"):
        components.html(_NAVBAR_JS, height=0)


def titulo_secao(texto: str, *, inline: bool = False) -> None:
    """Título de seção. `inline=True` quando ele divide a linha com filtros."""
    classe = "sec-title inline" if inline else "sec-title"
    st.markdown(f'<div class="{classe}">{html.escape(texto)}</div>',
                unsafe_allow_html=True)


def _card_html(label: str, valor: str, sub: str, accent: str) -> str:
    return (
        f'<div class="kpi-card" style="--accent:{accent}">'
        f'<div class="kpi-top"><span class="kpi-dot"></span>'
        f'<span class="kpi-label">{html.escape(label)}</span></div>'
        f'<div class="kpi-valor">{valor}</div>'
        f'<div class="kpi-sub">{sub}</div></div>'
    )


def grade_cards(cards: list) -> None:
    """Renderiza uma linha de cards. Cada card: {label, valor, sub, accent}."""
    inner = "".join(_card_html(**c) for c in cards)
    st.markdown(f'<div class="kpi-grid">{inner}</div>', unsafe_allow_html=True)


def fmt_int(valor) -> str:
    """1234567 -> '1.234.567' (padrão pt-BR, sem casas decimais).

    Formatador é total de propósito: roda milhares de vezes por render, no meio da
    montagem de uma tabela. Derrubar a página inteira porque uma célula veio com
    tipo estranho seria desproporcional — o valor impróprio vira travessão, o
    mesmo símbolo que já representa ausência.
    """
    try:
        if valor is None or pd.isna(valor):
            return "—"
        return f"{float(valor):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def fmt_data(iso) -> str:
    """'2026-07-15' -> '15/07/2026'. Total pelo mesmo motivo de `fmt_int`."""
    try:
        if iso is None or pd.isna(iso):
            return "—"
        return pd.Timestamp(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError, OverflowError):
        # Data fora de faixa ainda diz algo ao operador — melhor o valor cru que
        # um travessão que esconde o problema de cadastro.
        return str(iso)


def fmt_om(valor) -> str:
    """Ordem mestre: número inteiro sem separador, travessão quando ausente.

    Vive aqui e não como lambda solta em cada tabela porque a mesma regra
    aparecia em quatro telas — e onde ela era reescrita à mão já havia uma
    variação silenciosa entre elas.
    """
    try:
        if valor is None or pd.isna(valor):
            return "—"
        return str(int(valor))
    except (TypeError, ValueError, OverflowError):
        return "—"


def fmt_pct(valor) -> str:
    """0.0-100.0 -> '12,3%'. Travessão quando não há base para o percentual."""
    try:
        if valor is None or pd.isna(valor):
            return "—"
        return f"{float(valor):.1f}%".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def fmt_dec(valor) -> str:
    """1234.5 -> '1.234,50' (duas casas, padrão pt-BR)."""
    try:
        if valor is None or pd.isna(valor):
            return "—"
        return f"{float(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return "—"


def delta_html(variacao: float | None, rotulo: str = "vs. período anterior") -> str:
    """Seta + percentual de variação, pronto para entrar no `sub` de um card."""
    if variacao is None:
        return f'<span class="delta flat">— sem base anterior</span>'
    classe = "up" if variacao > 0 else ("down" if variacao < 0 else "flat")
    seta = "▲" if variacao > 0 else ("▼" if variacao < 0 else "▬")
    return (f'<span class="delta {classe}">{seta} {abs(variacao):.1f}%</span> '
            f'<span style="color:#64748B">{html.escape(rotulo)}</span>')


def badges(itens: list) -> None:
    """Linha de badges. Cada item: {label, valor, sub, estado: 'ok'|'falta'|'neutro'}."""
    blocos = []
    for it in itens:
        classe = it.get("estado", "falta")
        blocos.append(
            f'<div class="badge {classe}">'
            f'<div class="badge-label">{html.escape(it["label"])}</div>'
            f'<div class="badge-valor">{it["valor"]}</div>'
            f'<div class="badge-sub">{it["sub"]}</div></div>'
        )
    st.markdown(f'<div class="badge-row">{"".join(blocos)}</div>', unsafe_allow_html=True)


def cabecalho_grupo(titulo: str, accent: str) -> None:
    """Faixa que abre cada bloco do formulário de metas."""
    st.markdown(
        f'<div class="metas-grupo" style="--accent:{accent}">'
        f'<span class="metas-grupo-dot"></span>{html.escape(titulo)}</div>',
        unsafe_allow_html=True,
    )


def texto_apoio(texto: str, classe: str = "metas-hint") -> None:
    """Legenda de apoio com peso maior que o `st.caption` padrão."""
    st.markdown(f'<div class="{classe}">{html.escape(texto)}</div>', unsafe_allow_html=True)


def pill(texto: str) -> str:
    """'Vence em breve' -> <span class="pill vence-breve">…</span>."""
    classe = (texto.lower().replace(" em ", "-").replace(" ", "-")
              .replace("ç", "c").replace("ã", "a"))
    return f'<span class="pill {classe}">{html.escape(texto)}</span>'


def _celula(valor, formatador) -> str:
    """Texto de uma célula, com o formatador da coluna quando houver.

    Sem formatador o comportamento é o antigo: ausente vira string vazia. Os
    formatadores (`fmt_int`, `fmt_data`, `fmt_om`) já tratam ausente por conta
    própria — devolvem travessão, que diz mais que um espaço em branco.
    """
    if formatador is not None:
        return formatador(valor)
    try:
        return "" if pd.isna(valor) else str(valor)
    except (TypeError, ValueError):
        return str(valor)


def tabela_verde(df: pd.DataFrame, colunas: dict, *, formato: dict | None = None,
                 col_oficina: str | None = None,
                 col_num: tuple = (), col_html: tuple = (),
                 vazio: str = "Sem dados no filtro atual.") -> None:
    """Renderiza um DataFrame como tabela de header verde (fiel à imagem).

    colunas: {chave_df: 'Rótulo exibido'} na ordem desejada.
    formato: {chave_df: callable} aplicado célula a célula na hora de desenhar.
    col_oficina: chave destacada em verde. col_num: chaves alinhadas à direita.
    col_html: chaves cujo conteúdo já é HTML confiável (pílulas) e não deve ser
    escapado — tudo o mais passa por `html.escape`.

    O DataFrame recebido é o **cru** (números e datas nativos). Formatar aqui
    dentro, e não antes de chamar, é o que permite formatar só as linhas que vão
    de fato para a tela — ver `tabela_paginada`.
    """
    if df.empty:
        st.info(vazio)
        return
    formato = formato or {}
    ths = "".join(
        f'<th class="{"num" if chave in col_num else ""}">{html.escape(rotulo)}</th>'
        for chave, rotulo in colunas.items()
    )
    # As classes de cada coluna são fixas: calcular fora do laço evita refazer a
    # mesma decisão uma vez por célula numa página de 100 linhas.
    classes = {
        chave: ("of" if chave == col_oficina else ("num" if chave in col_num else ""))
        for chave in colunas
    }
    linhas = []
    for row in df[list(colunas)].itertuples(index=False, name=None):
        tds = [
            f'<td class="{classes[chave]}">'
            f'{texto if chave in col_html else html.escape(texto)}</td>'
            for chave, texto in (
                (c, _celula(v, formato.get(c))) for c, v in zip(colunas, row)
            )
        ]
        linhas.append(f"<tr>{''.join(tds)}</tr>")
    st.markdown(
        f'<div class="tbl-wrap"><table class="gf"><thead><tr>{ths}</tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


# Renderizar milhares de <tr> de uma vez trava o navegador, então a tabela verde
# pagina. A planilha do botão de download continua saindo completa.
LINHAS_POR_PAGINA = 100


def tabela_paginada(df: pd.DataFrame, colunas: dict, chave: str, **kwargs) -> None:
    """`tabela_verde` com navegação de páginas quando a base é grande.

    A fatia da página é tirada ANTES de qualquer formatação, e é essa ordem que
    importa: formatar é trabalho por célula em Python (`fmt_int`, `fmt_data`),
    então montar a base inteira formatada para mostrar 100 linhas custava uma
    varredura completa do fato a cada rerun — em toda troca de filtro, de aba ou
    de página. Com o recorte primeiro, o custo passa a ser proporcional ao que
    aparece na tela, não ao tamanho da base.

    O Excel continua saindo completo: `botao_excel` recebe o DataFrame cru e não
    passa por aqui.
    """
    total = len(df)
    if total == 0:
        tabela_verde(df, colunas, **kwargs)
        return

    paginas = math.ceil(total / LINHAS_POR_PAGINA)
    pagina = 1
    if paginas > 1:
        seletor, resumo = st.columns([1, 4])
        pagina = seletor.number_input(
            "Página", min_value=1, max_value=paginas, value=1, step=1,
            key=f"pg_{chave}", label_visibility="collapsed",
        )
        resumo.markdown(
            f'<div class="tbl-rodape">Página {pagina} de {paginas} — '
            f'{fmt_int(total)} linha(s) no filtro atual.</div>',
            unsafe_allow_html=True,
        )
    inicio = (int(pagina) - 1) * LINHAS_POR_PAGINA
    tabela_verde(df.iloc[inicio:inicio + LINHAS_POR_PAGINA], colunas, **kwargs)


XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")


@st.cache_data(show_spinner=False)
def _xlsx(df: pd.DataFrame, colunas: dict, titulo: str, subtitulo: str,
          somar: tuple) -> bytes:
    """Cache da planilha: o Streamlit reexecuta o script a cada interação e
    montar a pasta de trabalho custa segundos numa base grande. Enquanto o
    filtro não muda, o arquivo é reaproveitado."""
    return excel.gerar_xlsx(df, colunas, titulo=titulo, subtitulo=subtitulo,
                            somar=somar)


def botao_excel(df: pd.DataFrame, colunas: dict, chave: str, *, titulo: str,
                rotulo: str = "Baixar em Excel", subtitulo: str = "",
                somar: tuple = ()) -> None:
    """Download da base completa em .xlsx — a paginação limita a tela, não o arquivo.

    Recebe o DataFrame *cru* (número e data nativos), não a versão já formatada
    em texto da tela: é o Excel que aplica o formato, então a planilha continua
    somando, ordenando e filtrando como planilha.

    Se a planilha não puder ser montada, o botão simplesmente não aparece e fica
    um aviso no lugar: a tabela acima continua respondendo a pergunta do
    operador, e perder o anexo não pode custar a tela toda.
    """
    try:
        dados = _xlsx(df, colunas, titulo, subtitulo, somar)
    except GestaoFluxoError as exc:
        _LOG.error("Planilha '%s': %s", titulo, exc.detalhe or exc.mensagem_usuario)
        st.warning(exc.mensagem_usuario)
        return
    st.download_button(
        rotulo, dados,
        file_name=f"{chave}.xlsx", mime=XLSX_MIME, key=f"dl_{chave}",
    )


COLUNAS_FATO = {"oficina": "Oficina", "data": "Data", "mp": "MP",
                "qtd_pecas": "Qtd. de peças", "minutos": "Minutos", "om": "OM"}


FORMATO_FATO = {"data": fmt_data, "qtd_pecas": fmt_int, "minutos": fmt_dec,
                "om": fmt_om}


def tabela_fato(df: pd.DataFrame, chave: str, *, titulo: str = "",
                subtitulo: str = "") -> None:
    """Tabela do fato com os 6 campos pedidos, no layout verde e paginada."""
    if df.empty:
        st.info("Sem linhas no filtro atual.")
        return
    tabela_paginada(
        df, COLUNAS_FATO, chave, formato=FORMATO_FATO,
        col_oficina="oficina", col_num=("qtd_pecas", "minutos", "om"),
    )
    botao_excel(
        df, COLUNAS_FATO, chave,
        titulo=titulo or chave.replace("_", " ").capitalize(),
        subtitulo=subtitulo, somar=("qtd_pecas", "minutos"),
    )
