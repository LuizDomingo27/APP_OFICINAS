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
.block-container { padding-top: 1.6rem; max-width: 1470px; }

/* Cabeçalho do app — a marca fica num quadrado de acento, como num produto real. */
.app-header {
    display:flex; align-items:center; gap:16px;
    background:var(--surface); border:1px solid var(--linha); border-radius:16px;
    padding:18px 22px;
}
.app-logo {
    width:46px; height:46px; border-radius:13px; display:grid; place-items:center;
    background:linear-gradient(135deg,#2DD4BF,#14B8A6); color:#08131A; flex:none;
}
.app-logo svg { width:24px; height:24px; display:block; }
.app-title {
    font-size:1.2rem; font-weight:700; color:var(--tinta);
    line-height:1.2; letter-spacing:-.01em;
}
.app-sub { font-size:.875rem; color:var(--muted); margin-top:3px; }

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
[data-testid="stTabs"] [role="tablist"] {
    gap:4px; border-bottom:1px solid var(--linha);
}
[data-testid="stTab"] {
    color:var(--muted); font-weight:600; font-size:.9rem; padding:10px 16px;
}
[data-testid="stTab"][aria-selected="true"] { color:var(--tinta); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background:var(--verde); }

section[data-testid="stSidebar"] {
    background:var(--surface); border-right:1px solid var(--linha);
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


def cabecalho(titulo: str, subtitulo: str) -> None:
    st.markdown(
        f"""<div class="app-header">
            <div class="app-logo">{_LOGO_SVG}</div>
            <div>
                <div class="app-title">{html.escape(titulo)}</div>
                <div class="app-sub">{html.escape(subtitulo)}</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


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


def tabela_verde(df: pd.DataFrame, colunas: dict, *, col_oficina: str | None = None,
                 col_num: tuple = (), col_html: tuple = (),
                 vazio: str = "Sem dados no filtro atual.") -> None:
    """Renderiza um DataFrame como tabela de header verde (fiel à imagem).

    colunas: {chave_df: 'Rótulo exibido'} na ordem desejada.
    col_oficina: chave destacada em verde. col_num: chaves alinhadas à direita.
    col_html: chaves cujo conteúdo já é HTML confiável (pílulas) e não deve ser
    escapado — tudo o mais passa por `html.escape`.
    """
    if df.empty:
        st.info(vazio)
        return
    ths = "".join(
        f'<th class="{"num" if chave in col_num else ""}">{html.escape(rotulo)}</th>'
        for chave, rotulo in colunas.items()
    )
    linhas = []
    for _, row in df.iterrows():
        tds = []
        for chave in colunas:
            bruto = "" if pd.isna(row[chave]) else str(row[chave])
            valor = bruto if chave in col_html else html.escape(bruto)
            classe = "of" if chave == col_oficina else ("num" if chave in col_num else "")
            tds.append(f'<td class="{classe}">{valor}</td>')
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
    """`tabela_verde` com navegação de páginas quando a base é grande."""
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


def tabela_fato(df: pd.DataFrame, chave: str, *, titulo: str = "",
                subtitulo: str = "") -> None:
    """Tabela do fato com os 6 campos pedidos, no layout verde e paginada."""
    if df.empty:
        st.info("Sem linhas no filtro atual.")
        return
    visao = pd.DataFrame({
        "oficina": df["oficina"],
        "data": df["data"].map(fmt_data),
        "mp": df["mp"],
        "qtd_pecas": df["qtd_pecas"].map(fmt_int),
        "minutos": df["minutos"].map(lambda v: f"{float(v):,.2f}"
                                     .replace(",", "@").replace(".", ",").replace("@", ".")),
        "om": df["om"].map(lambda v: "—" if pd.isna(v) else f"{int(v)}"),
    })
    tabela_paginada(
        visao, COLUNAS_FATO, chave,
        col_oficina="oficina", col_num=("qtd_pecas", "minutos", "om"),
    )
    botao_excel(
        df, COLUNAS_FATO, chave,
        titulo=titulo or chave.replace("_", " ").capitalize(),
        subtitulo=subtitulo, somar=("qtd_pecas", "minutos"),
    )
