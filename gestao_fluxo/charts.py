"""Gráficos interativos com ECharts (carregado por CDN dentro de um iframe).

Cada função monta o `option` do ECharts como dicionário Python e `renderizar`
injeta tudo num componente HTML do Streamlit. Nenhuma consulta ou regra aqui —
recebe DataFrame já agregado por `metricas` e devolve pixels.
"""
from __future__ import annotations

import json
import re
import uuid

import pandas as pd
import streamlit.components.v1 as components

CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"

VERDE = "#2DD4BF"
TEAL = "#34D399"
AMBAR = "#F59E0B"
ROSA = "#FB7185"
AZUL = "#38BDF8"
PALETA = [VERDE, AZUL, "#A78BFA", AMBAR, TEAL, ROSA, "#F472B6", "#22D3EE"]

# Superfícies do tema escuro — espelham as de gestao_fluxo/ui.py. O iframe do
# componente tem fundo próprio, então cada gráfico precisa pintar o seu.
SUPERFICIE = "#121821"
LINHA = "#212B36"
TINTA = "#E6EDF3"
MUTED = "#8B98A9"

# Um `option` é serializado com json.dumps, que não sabe emitir funções. Trechos
# marcados com este prefixo voltam a ser função JS depois da serialização.
_JS_TAG = "@@JS@@"
# Casa a string JSON inteira (respeitando escapes) para desfazer o escape com segurança.
_JS_RE = re.compile(r'"' + _JS_TAG + r'((?:[^"\\]|\\.)*)"')


def js(codigo: str) -> str:
    """Marca `codigo` para virar função JS executável no option final."""
    return _JS_TAG + codigo


def _serializar(option: dict) -> str:
    bruto = json.dumps(option, ensure_ascii=False)
    return _JS_RE.sub(lambda m: json.loads(f'"{m.group(1)}"'), bruto)


# Números sempre em pt-BR (1.234), tanto no eixo quanto na tooltip.
_NUM = "Number(v).toLocaleString('pt-BR')"

# Cartão escuro arredondado — a mesma tooltip em todos os gráficos.
_TOOLTIP = {
    "backgroundColor": "rgba(24,32,41,.96)",
    "borderWidth": 1,
    "borderColor": "#2E3A47",
    "padding": [11, 14],
    "textStyle": {"color": "#E6EDF3", "fontSize": 12,
                  "fontFamily": "Inter, Segoe UI, sans-serif"},
    "extraCssText": ("border-radius:12px;"
                     "box-shadow:0 16px 40px rgba(0,0,0,.5);"
                     "backdrop-filter:blur(6px);"),
}

# Tooltip de eixo: título + uma linha por série, com marcador e valor à direita.
_TOOLTIP_EIXO = js(
    "function (ps) {"
    " var s = '<div style=\"font-weight:700;font-size:12.5px;margin-bottom:7px;"
    "opacity:.85\">' + ps[0].axisValueLabel + '</div>';"
    " ps.forEach(function (p) {"
    "  var v = p.value == null ? 0 : p.value;"
    "  s += '<div style=\"display:flex;align-items:center;gap:9px;margin-top:3px\">'"
    "    + p.marker"
    "    + '<span style=\"flex:1;opacity:.85\">' + p.seriesName + '</span>'"
    "    + '<span style=\"font-weight:800;font-size:13.5px\">' + " + _NUM + " + '</span>'"
    "    + '</div>';"
    " });"
    " return s;"
    "}"
)

_BASE = {
    "textStyle": {"fontFamily": "Inter, Segoe UI, sans-serif", "color": TINTA},
    "grid": {"left": 12, "right": 24, "top": 56, "bottom": 12, "containLabel": True},
    "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
    "legend": {"top": 8, "icon": "roundRect", "itemWidth": 12, "itemHeight": 12,
               "textStyle": {"color": MUTED, "fontSize": 11}},
}

# Título de gráfico: mesmo peso e cor dos títulos de seção da página.
_TITULO = {"fontSize": 13.5, "fontWeight": 600, "color": TINTA}


def renderizar(option: dict, altura: int = 380) -> None:
    """Desenha um option do ECharts. Cada chamada usa um id próprio (iframe isolado).

    O `init` costuma rodar antes de o iframe do Streamlit receber a largura final,
    e aí o ECharts assume 100px e o gráfico nasce espremido. `window.resize` não
    resolve porque não dispara dentro do iframe — quem avisa é o ResizeObserver.
    """
    div_id = f"ec_{uuid.uuid4().hex[:10]}"
    html = f"""
    <style>
      html, body {{ margin:0; padding:0; background:{SUPERFICIE}; }}
      #{div_id} {{
        background:{SUPERFICIE}; border:1px solid {LINHA};
        border-radius:14px; box-sizing:border-box; padding:6px;
      }}
    </style>
    <div id="{div_id}" style="width:100%;height:{altura}px;"></div>
    <script src="{CDN}"></script>
    <script>
      (function () {{
        var el = document.getElementById("{div_id}");
        var chart = echarts.init(el, null, {{ renderer: "canvas" }});
        chart.setOption({_serializar(option)});
        function ajustar() {{ chart.resize(); }}
        new ResizeObserver(ajustar).observe(el);
        window.addEventListener("resize", ajustar);
      }})();
    </script>
    """
    components.html(html, height=altura + 10, scrolling=False)


def _sem_dados(titulo: str) -> dict:
    return {
        "title": {"text": titulo, "left": "left", "textStyle": _TITULO},
        "graphic": {"type": "text", "left": "center", "top": "middle",
                    "style": {"text": "Sem dados no filtro atual",
                              "fill": MUTED, "fontSize": 13}},
    }


# =========================================================================== #
# GRÁFICOS DAS ABAS DE ANÁLISE
# =========================================================================== #
def rosca_por_mp(df: pd.DataFrame, coluna: str, titulo: str) -> dict:
    """Rosca com a participação de cada MP (granularidade de matéria-prima).

    Sem rótulos sobre as fatias: o miolo é reservado ao destaque da fatia sob o
    cursor, o que mantém a leitura limpa mesmo com muitas MPs.
    """
    if df.empty:
        return _sem_dados(titulo)
    return {
        "textStyle": _BASE["textStyle"],
        "title": {"text": titulo, "left": "left", "top": 2, "textStyle": _TITULO},
        "tooltip": {
            **_TOOLTIP,
            "trigger": "item",
            "formatter": js(
                "function (p) {"
                " var v = p.value;"
                " return '<div style=\"font-weight:700;font-size:12.5px;"
                "margin-bottom:7px;opacity:.85\">' + p.name + '</div>'"
                "  + '<div style=\"display:flex;align-items:center;gap:9px\">'"
                "  + p.marker"
                "  + '<span style=\"font-weight:800;font-size:16px\">' + " + _NUM + " + '</span>'"
                "  + '<span style=\"opacity:.65\">(' + p.percent.toFixed(1) + '%)</span>'"
                "  + '</div>';"
                "}"
            ),
        },
        "legend": {"bottom": 0, "icon": "circle", "itemWidth": 9, "itemHeight": 9,
                   "itemGap": 14, "textStyle": {"fontSize": 11, "color": MUTED}},
        "color": PALETA,
        "series": [{
            "type": "pie", "radius": ["58%", "82%"], "center": ["50%", "50%"],
            "avoidLabelOverlap": True,
            # A borda usa a cor da superfície: separa as fatias sem clarear o miolo.
            "itemStyle": {"borderColor": SUPERFICIE, "borderWidth": 3, "borderRadius": 8},
            "label": {"show": False},
            "labelLine": {"show": False},
            "emphasis": {
                "scale": True, "scaleSize": 8,
                "itemStyle": {"shadowBlur": 20, "shadowColor": "rgba(0,0,0,.45)"},
                "label": {
                    "show": True, "position": "center", "lineHeight": 22,
                    "formatter": js(
                        "function (p) {"
                        " return '{pct|' + p.percent.toFixed(1) + '%}\\n{nome|' + p.name + '}';"
                        "}"
                    ),
                    "rich": {
                        "pct": {"fontSize": 26, "fontWeight": 700, "color": TINTA},
                        "nome": {"fontSize": 11, "color": MUTED},
                    },
                },
            },
            "data": [{"name": r["mp"], "value": round(r[coluna])} for _, r in df.iterrows()],
        }],
    }


# Peças e minutos têm ordens de grandeza diferentes, então cada série tem seu
# próprio eixo. Como os rótulos do eixo Y estão ocultos, os valores exatos vêm
# só pela tooltip — o gráfico mostra a forma da curva, não a escala.
_EIXO_Y_OCULTO = [
    {"type": "value", "axisLabel": {"show": False}, "axisTick": {"show": False},
     "axisLine": {"show": False}, "splitLine": {"show": False}},
    {"type": "value", "axisLabel": {"show": False}, "axisTick": {"show": False},
     "axisLine": {"show": False}, "splitLine": {"show": False}},
]

_PONTEIRO = {
    "type": "line",
    "lineStyle": {"color": "#3C4A59", "width": 1, "type": "dashed"},
    "label": {"show": False},
}


def _serie_temporal(titulo: str, rotulos: list, pecas: list, minutos: list) -> dict:
    """Duas linhas (peças e minutos) sobre os mesmos rótulos de tempo."""
    return {
        **_BASE,
        "grid": {"left": 8, "right": 20, "top": 60, "bottom": 8, "containLabel": True},
        "title": {"text": titulo, "left": "left", "top": 2, "textStyle": _TITULO},
        "tooltip": {**_TOOLTIP, "trigger": "axis", "axisPointer": _PONTEIRO,
                    "formatter": _TOOLTIP_EIXO},
        "legend": {**_BASE["legend"], "data": ["Peças", "Minutos"]},
        "xAxis": {"type": "category", "data": rotulos, "boundaryGap": False,
                  "axisTick": {"show": False},
                  "axisLine": {"lineStyle": {"color": LINHA}},
                  "axisLabel": {"fontSize": 11, "color": MUTED, "hideOverlap": True}},
        "yAxis": _EIXO_Y_OCULTO,
        "series": [
            {"name": "Peças", "type": "line", "smooth": True, "yAxisIndex": 0,
             "showSymbol": False, "symbol": "circle", "symbolSize": 8,
             "lineStyle": {"width": 3, "color": VERDE},
             "itemStyle": {"color": VERDE, "borderColor": SUPERFICIE, "borderWidth": 2},
             "areaStyle": {
                 "opacity": .16,
                 "color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                           "colorStops": [{"offset": 0, "color": VERDE},
                                          {"offset": 1, "color": "rgba(30,158,106,0)"}]},
             },
             "emphasis": {"focus": "series"},
             "data": pecas},
            {"name": "Minutos", "type": "line", "smooth": True, "yAxisIndex": 1,
             "showSymbol": False, "symbol": "circle", "symbolSize": 8,
             "lineStyle": {"width": 2.5, "type": "dashed", "color": AMBAR},
             "itemStyle": {"color": AMBAR, "borderColor": SUPERFICIE, "borderWidth": 2},
             "emphasis": {"focus": "series"},
             "data": minutos},
        ],
    }


def linha_por_dia(df: pd.DataFrame, titulo: str = "Evolução diária") -> dict:
    """Linha dupla (peças e minutos) ao longo dos dias do período filtrado."""
    if df.empty:
        return _sem_dados(titulo)
    return _serie_temporal(
        titulo,
        [d.strftime("%d/%m") for d in df["data"]],
        [round(v) for v in df["qtd_pecas"]],
        [round(v) for v in df["minutos"]],
    )


def linha_por_semana(df: pd.DataFrame, titulo: str = "Total por semana do mês") -> dict:
    """Mesma leitura da diária, agregada por semana já recortada no mês filtrado."""
    if df.empty:
        return _sem_dados(titulo)
    return _serie_temporal(
        titulo,
        df["rotulo"].tolist(),
        [round(v) for v in df["qtd_pecas"]],
        [round(v) for v in df["minutos"]],
    )


# =========================================================================== #
# GRÁFICOS DA ABA DE PREVISÃO
# =========================================================================== #
# Barras, e não linha: na previsão cada categoria é um balde independente (uma MP,
# uma semana, um dia), e a linha sugeriria uma continuidade que não existe entre uma
# MP e a seguinte. A leitura aqui é de comparação de volume, não de tendência.


def _barras_duplas(titulo: str, rotulos: list, pecas: list, minutos: list,
                   *, rodar_rotulo: bool = False) -> dict:
    """Peças e minutos lado a lado sobre os mesmos rótulos.

    Cada série tem seu eixo (peças e minutos diferem em ordem de grandeza) e os
    rótulos do Y ficam ocultos, como no resto do painel: o valor exato vem pela
    tooltip e o gráfico responde "qual é maior", que é a pergunta real.
    """
    eixo_x = {
        "type": "category", "data": rotulos,
        "axisTick": {"show": False},
        "axisLine": {"lineStyle": {"color": LINHA}},
        "axisLabel": {"fontSize": 11, "color": MUTED, "hideOverlap": True},
    }
    if rodar_rotulo:
        # Rótulo de semana ("Semana 3 (13/07 a 19/07)") e de dia são longos e, em
        # barra, nascem sob a coluna: sem inclinação o ECharts esconde um a cada
        # dois para não sobrepor, e o eixo passa a mentir sobre o que está ali.
        eixo_x["axisLabel"] = {**eixo_x["axisLabel"], "rotate": 38,
                               "hideOverlap": False}
    return {
        **_BASE,
        "grid": {"left": 8, "right": 20, "top": 60,
                 "bottom": 24 if rodar_rotulo else 8, "containLabel": True},
        "title": {"text": titulo, "left": "left", "top": 2, "textStyle": _TITULO},
        "tooltip": {**_TOOLTIP, "trigger": "axis",
                    "axisPointer": {"type": "shadow"}, "formatter": _TOOLTIP_EIXO},
        "legend": {**_BASE["legend"], "data": ["Peças", "Minutos"]},
        "xAxis": eixo_x,
        "yAxis": _EIXO_Y_OCULTO,
        "series": [
            {"name": "Peças", "type": "bar", "yAxisIndex": 0, "barMaxWidth": 42,
             "itemStyle": {"color": VERDE, "borderRadius": [6, 6, 0, 0]},
             "emphasis": {"focus": "series"}, "data": pecas},
            {"name": "Minutos", "type": "bar", "yAxisIndex": 1, "barMaxWidth": 42,
             "itemStyle": {"color": AMBAR, "borderRadius": [6, 6, 0, 0]},
             "emphasis": {"focus": "series"}, "data": minutos},
        ],
    }


def barras_por_mp(df: pd.DataFrame,
                  titulo: str = "Distribuição por matéria-prima (MP)") -> dict:
    """Volume previsto por MP. Recebe a saída de `metricas.por_mp`."""
    if df.empty:
        return _sem_dados(titulo)
    return _barras_duplas(
        titulo,
        df["mp"].astype(str).tolist(),
        [round(v) for v in df["qtd_pecas"]],
        [round(v) for v in df["minutos"]],
    )


def barras_por_semana(df: pd.DataFrame,
                      titulo: str = "Distribuição por semana") -> dict:
    """Volume previsto por semana do mês. Recebe a saída de `metricas.por_semana`."""
    if df.empty:
        return _sem_dados(titulo)
    return _barras_duplas(
        titulo,
        df["rotulo"].astype(str).tolist(),
        [round(v) for v in df["qtd_pecas"]],
        [round(v) for v in df["minutos"]],
        rodar_rotulo=True,
    )


def barras_por_dia(df: pd.DataFrame, titulo: str = "Distribuição por dia") -> dict:
    """Volume previsto por dia. Recebe a saída de `metricas.por_dia`."""
    if df.empty:
        return _sem_dados(titulo)
    return _barras_duplas(
        titulo,
        [d.strftime("%d/%m") for d in df["data"]],
        [round(v) for v in df["qtd_pecas"]],
        [round(v) for v in df["minutos"]],
        rodar_rotulo=True,
    )


# =========================================================================== #
# GRÁFICO DA ABA DE METAS
# =========================================================================== #
def relogio_meta(percentual: float, titulo: str, detalhe: str) -> dict:
    """Relógio (gauge) com o quanto da meta já foi alcançado.

    O ponteiro satura em 100% para não sair da escala quando a meta é superada —
    o percentual real continua no texto central.
    """
    pct = max(0.0, min(percentual, 100.0))
    cor = VERDE if percentual >= 100 else (AMBAR if percentual >= 70 else ROSA)
    return {
        "textStyle": _BASE["textStyle"],
        "title": {"text": titulo, "left": "center", "top": 6, "textStyle": _TITULO},
        "series": [{
            "type": "gauge",
            "startAngle": 210, "endAngle": -30,
            "min": 0, "max": 100, "center": ["50%", "62%"], "radius": "78%",
            "progress": {"show": True, "width": 16, "itemStyle": {"color": cor}},
            "axisLine": {"lineStyle": {"width": 16, "color": [[1, "#1E2731"]]}},
            "pointer": {"width": 4, "length": "58%", "itemStyle": {"color": cor}},
            "axisTick": {"show": False},
            "splitLine": {"length": 10, "lineStyle": {"width": 2, "color": "#2E3A47"}},
            "axisLabel": {"distance": 18, "fontSize": 10, "color": MUTED},
            "anchor": {"show": True, "size": 12, "itemStyle": {"color": cor}},
            "title": {"offsetCenter": [0, "36%"], "fontSize": 11, "color": MUTED},
            "detail": {
                "offsetCenter": [0, "-2%"], "fontSize": 24, "fontWeight": "bolder",
                "color": cor, "formatter": f"{percentual:.1f}%",
            },
            "data": [{"value": round(pct, 1), "name": detalhe}],
        }],
    }
