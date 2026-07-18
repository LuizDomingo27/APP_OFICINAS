"""Regras de leitura e agregação — nada de Streamlit aqui, só pandas puro.

Responsabilidades:
    PERÍODOS   -> meses disponíveis e as semanas de um mês (recortadas no mês)
    FILTRO     -> aplica mês/semana/MP/oficina sobre o fato
    MÉTRICAS   -> totais, médias (dia/semana/mês) e variação vs. período anterior
    AGREGAÇÕES -> séries prontas para os gráficos (por oficina, por MP, por dia)

Cards e gráficos são calculados a partir do mesmo DataFrame filtrado, então nunca
divergem entre si.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.engine import Engine

from . import config
from .db import database

MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


# =========================================================================== #
# LEITURA
# =========================================================================== #
def carregar_fato(engine: Engine, fonte: str) -> pd.DataFrame:
    """Lê uma tabela de fato inteira, com as datas já como datetime."""
    tabela = config.FONTES[fonte]["tabela"]
    campos = config.campos_da_fonte(fonte)
    df = database.read_sql(f"SELECT {', '.join(campos)} FROM {tabela}", engine)
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    if "deadline" in df.columns:
        df["deadline"] = pd.to_datetime(df["deadline"], errors="coerce")
    df["qtd_pecas"] = pd.to_numeric(df["qtd_pecas"], errors="coerce").fillna(0.0)
    df["minutos"] = pd.to_numeric(df["minutos"], errors="coerce").fillna(0.0)
    return df


# =========================================================================== #
# PERÍODOS
# =========================================================================== #
def rotulo_mes(ano: int, mes: int) -> str:
    return f"{MESES_PT[mes - 1].capitalize()}/{ano}"


def meses_disponiveis(df: pd.DataFrame) -> list:
    """(ano, mes) presentes no fato, do mais recente para o mais antigo."""
    datas = df["data"].dropna()
    if datas.empty:
        return []
    return sorted({(int(d.year), int(d.month)) for d in datas}, reverse=True)


@dataclass(frozen=True)
class Semana:
    """Uma semana do mês, já recortada nos limites do próprio mês."""

    numero: int
    inicio: date
    fim: date

    @property
    def rotulo(self) -> str:
        return (f"Semana {self.numero} "
                f"({self.inicio.strftime('%d/%m')} a {self.fim.strftime('%d/%m')})")


def semanas_do_mes(ano: int, mes: int) -> list:
    """Semanas (segunda a domingo) que tocam o mês, recortadas nos limites dele.

    O corte no mês é o que atende o pedido do time: filtrando julho, a primeira
    semana começa em 01/07 e a última termina em 31/07 — sem invadir junho ou agosto.
    """
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    semanas: list = []
    cursor, numero = primeiro, 1
    while cursor <= ultimo:
        fim_semana = cursor + timedelta(days=6 - cursor.weekday())
        semanas.append(Semana(numero, cursor, min(fim_semana, ultimo)))
        cursor = fim_semana + timedelta(days=1)
        numero += 1
    return semanas


def periodo_anterior(inicio: date, fim: date) -> tuple:
    """Período imediatamente anterior ao intervalo dado.

    Quando o intervalo é um mês calendário inteiro, o anterior é o **mês anterior
    inteiro** — comparar julho (31 dias) com "os 31 dias antes de julho" jogaria
    o dia 31 de maio dentro da base de comparação e distorceria a variação.
    Para qualquer outro recorte (uma semana, por exemplo), usa a mesma duração.
    """
    ultimo_dia = calendar.monthrange(inicio.year, inicio.month)[1]
    if inicio.day == 1 and fim.day == ultimo_dia and inicio.month == fim.month:
        fim_ant = inicio - timedelta(days=1)
        return date(fim_ant.year, fim_ant.month, 1), fim_ant
    duracao = (fim - inicio).days + 1
    novo_fim = inicio - timedelta(days=1)
    return novo_fim - timedelta(days=duracao - 1), novo_fim


# =========================================================================== #
# FILTRO
# =========================================================================== #
def filtrar(df: pd.DataFrame, inicio: date | None = None, fim: date | None = None,
            mps: list | None = None, oficinas: list | None = None) -> pd.DataFrame:
    """Recorta o fato por intervalo, MPs e oficinas (lista vazia = sem restrição)."""
    out = df
    if inicio is not None:
        out = out[out["data"] >= pd.Timestamp(inicio)]
    if fim is not None:
        out = out[out["data"] <= pd.Timestamp(fim)]
    if mps:
        out = out[out["mp"].isin(mps)]
    if oficinas:
        out = out[out["oficina"].isin(oficinas)]
    return out.copy()


# =========================================================================== #
# MÉTRICAS
# =========================================================================== #
@dataclass
class Media:
    """Média do período atual com a variação percentual contra o anterior."""

    atual: float = 0.0
    anterior: float = 0.0

    @property
    def variacao(self) -> float | None:
        """Variação %; None quando não há base anterior (evita divisão por zero)."""
        if not self.anterior:
            return None
        return (self.atual - self.anterior) / self.anterior * 100


@dataclass
class Metricas:
    total_pecas: float = 0.0
    total_minutos: float = 0.0
    linhas: int = 0
    oficinas: int = 0
    medias: dict = field(default_factory=dict)  # {"dia_pecas": Media, ...}


def _media_por(df: pd.DataFrame, coluna: str, chave: str) -> float:
    """Total / número de períodos COM movimento (dia, semana ou mês).

    Dividir só pelos períodos com movimento evita que fim de semana e feriado
    puxem a média para baixo e produzam um número que o time não reconhece.
    """
    d = df.dropna(subset=["data"])
    if d.empty:
        return 0.0
    if chave == "dia":
        periodos = d["data"].dt.date
    elif chave == "semana":
        periodos = d["data"].dt.to_period("W")
    else:
        periodos = d["data"].dt.to_period("M")
    n = periodos.nunique()
    return float(d[coluna].sum() / n) if n else 0.0


def calcular_metricas(atual: pd.DataFrame, anterior: pd.DataFrame) -> Metricas:
    """Totais do período atual + as 3 médias, cada uma comparada com o anterior."""
    medias = {
        f"{chave}_{rotulo}": Media(_media_por(atual, coluna, chave),
                                   _media_por(anterior, coluna, chave))
        for chave in ("dia", "semana", "mes")
        for rotulo, coluna in (("pecas", "qtd_pecas"), ("minutos", "minutos"))
    }
    return Metricas(
        total_pecas=float(atual["qtd_pecas"].sum()),
        total_minutos=float(atual["minutos"].sum()),
        linhas=len(atual),
        oficinas=int(atual["oficina"].nunique()),
        medias=medias,
    )


# =========================================================================== #
# AGREGAÇÕES PARA OS GRÁFICOS
# =========================================================================== #
def por_oficina(df: pd.DataFrame, limite: int = 15) -> pd.DataFrame:
    """Total de peças e minutos por oficina, do maior para o menor."""
    if df.empty:
        return pd.DataFrame(columns=["oficina", "qtd_pecas", "minutos"])
    agg = (df.groupby("oficina", as_index=False)[["qtd_pecas", "minutos"]].sum()
             .sort_values("qtd_pecas", ascending=False))
    return agg.head(limite).reset_index(drop=True)


def por_mp(df: pd.DataFrame) -> pd.DataFrame:
    """Total de peças e minutos por granularidade de MP."""
    if df.empty:
        return pd.DataFrame(columns=["mp", "qtd_pecas", "minutos"])
    return (df.groupby("mp", as_index=False)[["qtd_pecas", "minutos"]].sum()
              .sort_values("qtd_pecas", ascending=False).reset_index(drop=True))


def por_dia(df: pd.DataFrame) -> pd.DataFrame:
    """Série diária (linha de evolução dentro do período filtrado)."""
    d = df.dropna(subset=["data"])
    if d.empty:
        return pd.DataFrame(columns=["data", "qtd_pecas", "minutos"])
    agg = (d.assign(dia=d["data"].dt.date)
             .groupby("dia", as_index=False)[["qtd_pecas", "minutos"]].sum()
             .rename(columns={"dia": "data"}))
    return agg.sort_values("data").reset_index(drop=True)


def por_semana(df: pd.DataFrame, semanas: list) -> pd.DataFrame:
    """Total por semana do mês, usando exatamente os recortes de `semanas_do_mes`."""
    linhas = [
        {
            "semana": f"S{s.numero}",
            "rotulo": s.rotulo,
            "qtd_pecas": float(filtrar(df, s.inicio, s.fim)["qtd_pecas"].sum()),
            "minutos": float(filtrar(df, s.inicio, s.fim)["minutos"].sum()),
        }
        for s in semanas
    ]
    return pd.DataFrame(linhas)


# =========================================================================== #
# ACOMPANHAMENTO — O QUE HÁ PARA RECEBER
# =========================================================================== #
# A base de Acompanhamento não é um histórico como Recebimento e Envios: cada
# linha é uma ordem **ainda em aberto**, já enviada e ainda não recebida. Por isso
# aqui não se mede média nem variação contra o período anterior — mede-se saldo,
# prazo e tempo de espera.


def classificar_prazo(df: pd.DataFrame, hoje: date | None = None,
                      janela: int | None = None) -> pd.DataFrame:
    """Acrescenta `dias_prazo`, `dias_aberto` e `status` a cada ordem em aberto.

    `dias_prazo` é negativo quando o prazo já venceu — a leitura "-12" cai melhor
    para o time do que "12 dias de atraso" numa coluna que também mostra futuro.
    Ordem sem prazo válido fica em "Sem prazo" em vez de virar atraso: a ausência
    do dado é problema de cadastro, não de oficina.
    """
    hoje = hoje or date.today()
    janela = config.PRAZO_ALERTA_DIAS if janela is None else janela
    out = df.copy()
    if out.empty:
        for coluna in ("dias_prazo", "dias_aberto"):
            out[coluna] = pd.Series(dtype="float")
        out["status"] = pd.Series(dtype="object")
        return out

    agora = pd.Timestamp(hoje)
    prazo = out["deadline"] if "deadline" in out.columns else pd.Series(pd.NaT, index=out.index)
    out["dias_prazo"] = (prazo - agora).dt.days
    out["dias_aberto"] = (agora - out["data"]).dt.days

    out["status"] = config.STATUS_SEM_PRAZO
    tem_prazo = out["dias_prazo"].notna()
    out.loc[tem_prazo & (out["dias_prazo"] < 0), "status"] = config.STATUS_ATRASADO
    out.loc[tem_prazo & out["dias_prazo"].between(0, janela), "status"] = \
        config.STATUS_VENCE_BREVE
    out.loc[tem_prazo & (out["dias_prazo"] > janela), "status"] = config.STATUS_NO_PRAZO
    return out


@dataclass
class Pendencia:
    """A oficina que mais chama atenção num recorte, com o número que a elegeu."""

    oficina: str = "—"
    dias: int = 0


@dataclass
class ResumoAReceber:
    """Saldo em aberto do Acompanhamento, já classificado por prazo."""

    ordens: int = 0
    pecas: float = 0.0
    minutos: float = 0.0
    oficinas: int = 0
    por_status: dict = field(default_factory=dict)   # {status: {"ordens", "pecas", ...}}
    espera_mais_longa: Pendencia = field(default_factory=Pendencia)
    maior_atraso: Pendencia = field(default_factory=Pendencia)


def _pendencia_por(df: pd.DataFrame, coluna: str, maior: bool = True) -> Pendencia:
    """Linha de maior (ou menor) valor numa coluna, como {oficina, dias}."""
    validos = df[df[coluna].notna()]
    if validos.empty:
        return Pendencia()
    linha = validos.loc[validos[coluna].idxmax() if maior else validos[coluna].idxmin()]
    return Pendencia(oficina=str(linha["oficina"]), dias=int(abs(linha[coluna])))


def resumo_a_receber(df: pd.DataFrame) -> ResumoAReceber:
    """Consolida o saldo em aberto. Espera um df já passado por `classificar_prazo`."""
    if df.empty:
        return ResumoAReceber(
            por_status={s: {"ordens": 0, "pecas": 0.0, "minutos": 0.0}
                        for s in config.STATUS_PRAZO}
        )

    por_status = {}
    for status in config.STATUS_PRAZO:
        recorte = df[df["status"] == status]
        por_status[status] = {
            "ordens": len(recorte),
            "pecas": float(recorte["qtd_pecas"].sum()),
            "minutos": float(recorte["minutos"].sum()),
        }

    atrasadas = df[df["status"] == config.STATUS_ATRASADO]
    return ResumoAReceber(
        ordens=len(df),
        pecas=float(df["qtd_pecas"].sum()),
        minutos=float(df["minutos"].sum()),
        oficinas=int(df["oficina"].nunique()),
        por_status=por_status,
        espera_mais_longa=_pendencia_por(df, "dias_aberto"),
        # O maior atraso é o prazo mais negativo, daí buscarmos o mínimo.
        maior_atraso=_pendencia_por(atrasadas, "dias_prazo", maior=False),
    )


# =========================================================================== #
# FLUXO POR MATÉRIA-PRIMA — O QUE SAIU x O QUE VOLTOU
# =========================================================================== #
# Mede o acumulado histórico: tudo que foi enviado de cada MP contra tudo que foi
# recebido, e a diferença que segue em produção. É leitura diferente do saldo do
# Acompanhamento (a lista declarada de ordens em aberto) e os dois números não
# batem — ver o comentário em `fluxo_por_mp`.

COLUNAS_FLUXO_MP = [
    "mp", "enviado_pecas", "recebido_pecas", "progresso_pecas", "pct_concluido",
    "enviado_minutos", "recebido_minutos", "ordens_abertas", "recebido_sem_envio",
]


def _mapa_om_para_mp(envios: pd.DataFrame) -> pd.Series:
    """{ordem mestre: MP declarada no envio}.

    A MP de uma ordem pode mudar entre sair e voltar — 80 ordens saíram como JEANS
    e retornaram classificadas como ECOBAGS. Agregar cada base pela sua própria MP
    produziria uma MP com recebimento sem envio nenhum e diferença negativa, que é
    ruído de reclassificação, não produção. Por isso a MP do envio manda: é a
    classificação de origem, a mesma que o time usou para despachar.

    Ordem com mais de uma MP no envio (2 casos na base) fica com a primeira: são
    raras demais para justificar uma regra de desempate que ninguém conseguiria
    conferir na planilha.
    """
    validos = envios.dropna(subset=["om"])
    if validos.empty:
        return pd.Series(dtype="object")
    return validos.drop_duplicates("om").set_index("om")["mp"]


def fluxo_por_mp(envios: pd.DataFrame, recebimento: pd.DataFrame,
                 acompanhamento: pd.DataFrame | None = None, *,
                 envios_referencia: pd.DataFrame | None = None) -> pd.DataFrame:
    """Enviado x recebido x em progresso, por matéria-prima.

    O recebimento é reatribuído à MP do envio da mesma ordem (ver `_mapa_om_para_mp`).
    Recebimento cuja ordem não existe em Envios mantém a própria MP e é somado
    também em `recebido_sem_envio` — é o que explica um "em progresso" negativo sem
    esconder a linha: o histórico de Envios começa depois do de Recebimento, então
    parte do que voltou saiu antes de existir registro de envio.

    `envios_referencia` é a base de onde sai o mapa ordem->MP, e existe para quando
    `envios` vem recortado por período. Uma ordem que saiu em maio e voltou em junho
    tem envio — ele só está fora da janela filtrada. Montar o mapa com o `envios`
    recortado a marcaria como "recebido sem envio" e encheria a coluna do que é
    efeito do filtro, não do dado. Passe aqui a base sem recorte de data; sem isso,
    o padrão é o próprio `envios`, que é o certo quando não há filtro nenhum.

    ATENÇÃO ao comparar com os cards de saldo do Acompanhamento na mesma aba: são
    medidas diferentes e vão divergir. Aqui é o acumulado de duas bases com janelas
    distintas; lá é a lista de ordens que a origem declara em aberto agora.
    """
    if envios.empty and recebimento.empty:
        return pd.DataFrame(columns=COLUNAS_FLUXO_MP)

    mapa = _mapa_om_para_mp(envios if envios_referencia is None
                            else envios_referencia)
    receb = recebimento.copy()
    receb["mp_origem"] = (receb["om"].map(mapa) if not mapa.empty
                          else pd.Series(index=receb.index, dtype="object"))
    receb["sem_envio"] = receb["mp_origem"].isna()
    receb["mp_final"] = receb["mp_origem"].fillna(receb["mp"])

    enviado = envios.groupby("mp")[["qtd_pecas", "minutos"]].sum()
    recebido = receb.groupby("mp_final")[["qtd_pecas", "minutos"]].sum()
    orfas = receb[receb["sem_envio"]].groupby("mp_final")["qtd_pecas"].sum()

    out = pd.DataFrame({
        "enviado_pecas": enviado["qtd_pecas"],
        "enviado_minutos": enviado["minutos"],
        "recebido_pecas": recebido["qtd_pecas"],
        "recebido_minutos": recebido["minutos"],
        "recebido_sem_envio": orfas,
    }).fillna(0.0)

    out["progresso_pecas"] = out["enviado_pecas"] - out["recebido_pecas"]
    # Percentual só faz sentido havendo envio: sem denominador a conta seria
    # infinita e apareceria como um número absurdo na tela.
    out["pct_concluido"] = (out["recebido_pecas"] / out["enviado_pecas"] * 100).where(
        out["enviado_pecas"] > 0)

    out["ordens_abertas"] = 0
    if acompanhamento is not None and not acompanhamento.empty:
        aberto = acompanhamento.copy()
        aberto["mp_final"] = (aberto["om"].map(mapa).fillna(aberto["mp"])
                              if not mapa.empty else aberto["mp"])
        contagem = aberto.groupby("mp_final").size()
        out["ordens_abertas"] = contagem.reindex(out.index).fillna(0).astype(int)

    return (out.reset_index().rename(columns={"index": "mp", "mp_final": "mp"})
               .sort_values("enviado_pecas", ascending=False)
               .reset_index(drop=True)[COLUNAS_FLUXO_MP])


@dataclass
class TotaisFluxoMP:
    """Rodapé da tabela de fluxo — o consolidado de todas as MPs."""

    enviado: float = 0.0
    recebido: float = 0.0
    progresso: float = 0.0
    sem_envio: float = 0.0

    @property
    def pct_concluido(self) -> float | None:
        return (self.recebido / self.enviado * 100) if self.enviado else None


def totais_fluxo_mp(df: pd.DataFrame) -> TotaisFluxoMP:
    if df.empty:
        return TotaisFluxoMP()
    return TotaisFluxoMP(
        enviado=float(df["enviado_pecas"].sum()),
        recebido=float(df["recebido_pecas"].sum()),
        progresso=float(df["progresso_pecas"].sum()),
        sem_envio=float(df["recebido_sem_envio"].sum()),
    )


def por_oficina_a_receber(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por oficina com o que ela deve entregar, pior caso primeiro.

    Ordena por ordens atrasadas e depois por tempo de espera: quem está devendo há
    mais tempo aparece no topo, que é como o time cobra na prática.
    """
    colunas = ["oficina", "ordens", "atrasadas", "qtd_pecas", "minutos",
               "envio_mais_antigo", "dias_aberto", "prazo_mais_proximo"]
    if df.empty:
        return pd.DataFrame(columns=colunas)

    agg = df.groupby("oficina", as_index=False).agg(
        ordens=("om", "size"),
        atrasadas=("status", lambda s: int((s == config.STATUS_ATRASADO).sum())),
        qtd_pecas=("qtd_pecas", "sum"),
        minutos=("minutos", "sum"),
        envio_mais_antigo=("data", "min"),
        dias_aberto=("dias_aberto", "max"),
        prazo_mais_proximo=("deadline", "min"),
    )
    return (agg.sort_values(["atrasadas", "dias_aberto"], ascending=False)
               .reset_index(drop=True)[colunas])
