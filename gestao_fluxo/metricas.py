"""Regras de leitura e agregação — nada de Streamlit aqui, só pandas puro.

Responsabilidades:
    PERÍODOS   -> meses disponíveis e as semanas de um mês (recortadas no mês)
    FILTRO     -> aplica mês/semana/MP/oficina sobre o fato
    MÉTRICAS   -> totais, médias (dia/semana/mês) e variação vs. período anterior
    AGREGAÇÕES -> séries prontas para os gráficos (por oficina, por MP, por dia)

Totais, gráficos e tabelas saem todos do mesmo DataFrame filtrado, então nunca
divergem entre si. As médias vêm em dois sabores, e a distinção é o coração deste
módulo:

* `calcular_medias_periodo` (diária e semanal) responde "como foi o recorte que
  estou olhando" — acompanha mês, semana, MP e oficina, e compara com o recorte
  equivalente do mês anterior.
* `calcular_media_mensal` responde "qual é o padrão da casa" — sai do histórico
  inteiro e não reage a filtro nenhum. Média mensal do mês filtrado seria o total
  do próprio mês dividido por 1, isto é, o número que o card de total já mostra;
  por isso este card é referência, e o delta dele mede o quanto o mês escolhido
  foge desse padrão.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
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
    # `data` e os extras de data (deadline, envio) chegam em ISO. Converter em
    # bloco evita que uma fonte nova com data extra chegue à tela como texto e só
    # falhe na hora de comparar prazos. Extra de texto (o `estagio` do Status)
    # fica de fora — ver config.CAMPOS_EXTRA_TEXTO.
    for coluna in ("data", *config.extras_data_da_fonte(fonte)):
        df[coluna] = pd.to_datetime(df[coluna], errors="coerce")
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


def _numero_da_semana(inicio: date, fim: date) -> int | None:
    """Número da semana quando o intervalo é exatamente uma semana do mês."""
    if (inicio.year, inicio.month) != (fim.year, fim.month):
        return None
    for s in semanas_do_mes(inicio.year, inicio.month):
        if (s.inicio, s.fim) == (inicio, fim):
            return s.numero
    return None


def periodo_anterior(inicio: date, fim: date) -> tuple:
    """Recorte equivalente do mês anterior — a base de comparação dos deltas.

    Três casos, do mais específico para o mais genérico:

    * **Mês calendário inteiro** -> mês anterior inteiro. Comparar julho (31 dias)
      com "os 31 dias antes de julho" jogaria o dia 31 de maio dentro da base e
      distorceria a variação.
    * **Uma semana do mês** -> a semana de **mesmo número** do mês anterior (S3 de
      julho contra S3 de junho), e não a semana imediatamente anterior: o time
      compara com o mesmo momento do ciclo do mês passado. Se o mês anterior não
      chega àquele número (um mês curto pode ter 5 semanas onde o atual tem 6),
      cai para a última semana dele — sem isso a semana ficaria sem comparação
      nenhuma.
    * **Qualquer outro intervalo** -> mesma duração, imediatamente antes.
    """
    ultimo_dia = calendar.monthrange(inicio.year, inicio.month)[1]
    if inicio.day == 1 and fim.day == ultimo_dia and inicio.month == fim.month:
        fim_ant = inicio - timedelta(days=1)
        return date(fim_ant.year, fim_ant.month, 1), fim_ant

    numero = _numero_da_semana(inicio, fim)
    if numero is not None:
        fim_mes_ant = date(inicio.year, inicio.month, 1) - timedelta(days=1)
        semanas = semanas_do_mes(fim_mes_ant.year, fim_mes_ant.month)
        equivalente = next((s for s in semanas if s.numero == numero), semanas[-1])
        return equivalente.inicio, equivalente.fim

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
    """Média do recorte filtrado + a mesma média no recorte equivalente anterior.

    `atual` é o número que o card mostra e acompanha TODOS os filtros (mês, semana,
    MP, oficina). `anterior` é o mesmo cálculo sobre o recorte devolvido por
    `periodo_anterior`, com os mesmos filtros aplicados — comparar o mês filtrado
    por uma oficina contra o mês anterior inteiro daria um delta sem sentido.
    """

    atual: float = 0.0
    anterior: float = 0.0

    @property
    def variacao(self) -> float | None:
        """Variação %; None quando não há base anterior (evita divisão por zero)."""
        if not self.anterior:
            return None
        return (self.atual - self.anterior) / self.anterior * 100


@dataclass
class MediaReferencia:
    """Média mensal de toda a base + o quanto o mês escolhido foge desse padrão.

    `historica` é o número do card e é imune a qualquer filtro: um parâmetro de
    referência que muda a cada clique de MP ou semana deixa de ser referência.
    `mes` é o total do mês selecionado (média mensal de um mês só = o próprio
    total) e existe apenas para alimentar a variação contra a referência.
    """

    historica: float = 0.0
    mes: float = 0.0

    @property
    def variacao(self) -> float | None:
        """Quanto o mês está acima/abaixo do padrão da base, em %."""
        if not self.historica:
            return None
        return (self.mes - self.historica) / self.historica * 100


@dataclass
class Metricas:
    total_pecas: float = 0.0
    total_minutos: float = 0.0
    linhas: int = 0
    oficinas: int = 0


def _chave_semana_do_mes(datas: pd.Series) -> pd.Series:
    """(ano, mês, nº da semana) de cada data — as MESMAS semanas de `semanas_do_mes`.

    Vetorizado em vez de chamar `semanas_do_mes` por linha, mas a regra é idêntica:
    a semana 1 vai do dia 1 ao primeiro domingo e as seguintes são segunda a
    domingo, recortadas no mês. Usar `to_period("W")` aqui (semana ISO, que
    atravessa a virada do mês) faria a média semanal do card divergir do gráfico
    de semanas, que já usa o recorte do mês.
    """
    dia = datas.dt.day
    primeiro_do_mes = datas - pd.to_timedelta(dia - 1, unit="D")
    dias_da_semana1 = 7 - primeiro_do_mes.dt.weekday
    numero = ((dia - dias_da_semana1 - 1) // 7 + 2).where(dia > dias_da_semana1, 1)
    return datas.dt.year * 10000 + datas.dt.month * 100 + numero


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
        periodos = _chave_semana_do_mes(d["data"])
    else:
        periodos = d["data"].dt.to_period("M")
    n = periodos.nunique()
    return float(d[coluna].sum() / n) if n else 0.0


def calcular_metricas(atual: pd.DataFrame) -> Metricas:
    """Totais do recorte filtrado — estes SIM acompanham semana, MP e oficina."""
    return Metricas(
        total_pecas=float(atual["qtd_pecas"].sum()),
        total_minutos=float(atual["minutos"].sum()),
        linhas=len(atual),
        oficinas=int(atual["oficina"].nunique()),
    )


UNIDADES = (("pecas", "qtd_pecas"), ("minutos", "minutos"))


def calcular_medias_periodo(historico: pd.DataFrame, inicio: date, fim: date,
                            mps: list | None = None,
                            oficinas: list | None = None) -> dict:
    """Médias diária e semanal do recorte filtrado, contra o equivalente anterior.

    Recebe o histórico **inteiro**, nunca um recorte: a função precisa enxergar o
    período anterior, que por definição está fora do que a tela filtrou. Os mesmos
    `mps`/`oficinas` são aplicados aos dois lados para que o delta compare coisas
    comparáveis.

    Chaves: `dia_pecas`, `dia_minutos`, `semana_pecas`, `semana_minutos`. Média
    mensal não vive aqui — ver `calcular_media_mensal`.
    """
    ini_ant, fim_ant = periodo_anterior(inicio, fim)
    atual = filtrar(historico, inicio, fim, mps, oficinas)
    anterior = filtrar(historico, ini_ant, fim_ant, mps, oficinas)
    return {
        f"{chave}_{rotulo}": Media(
            atual=_media_por(atual, coluna, chave),
            anterior=_media_por(anterior, coluna, chave),
        )
        for chave in ("dia", "semana")
        for rotulo, coluna in UNIDADES
    }


def calcular_media_mensal(historico: pd.DataFrame, mes_inicio: date,
                          mes_fim: date) -> dict:
    """Média mensal de toda a base + o quanto o mês escolhido foge dela.

    Não aceita `mps`/`oficinas` de propósito: é o parâmetro de referência do time
    e precisa ser o mesmo número em qualquer combinação de filtros. Chaves:
    `mes_pecas` e `mes_minutos`.
    """
    mes = filtrar(historico, mes_inicio, mes_fim)
    return {
        f"mes_{rotulo}": MediaReferencia(
            historica=_media_por(historico, coluna, "mes"),
            mes=_media_por(mes, coluna, "mes"),
        )
        for rotulo, coluna in UNIDADES
    }


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


COLUNAS_POR_SEMANA = ["semana", "rotulo", "qtd_pecas", "minutos"]


def por_semana(df: pd.DataFrame, semanas: list) -> pd.DataFrame:
    """Total por semana do mês, usando exatamente os recortes de `semanas_do_mes`.

    Uma passada só sobre o fato, em numpy: `searchsorted` acha a semana de cada
    linha e `bincount` soma as duas unidades de uma vez. A versão anterior
    chamava `filtrar` duas vezes por semana (uma por unidade), e `filtrar`
    termina em `.copy()` — eram ~12 varreduras e 12 cópias do fato inteiro para
    produzir 6 linhas, em todo rerun de toda aba que mostra a série semanal.

    A classificação é por busca binária, e não por bins contíguos (`pd.cut`),
    porque a grade pode ter buraco: em "Todo o período" da Previsão as semanas
    vêm dos meses COM movimento, então julho pode ser seguido de setembro. Com
    bins contíguos a faixa de agosto seria somada dentro da primeira semana de
    setembro. Aqui a data cai na última semana que começa antes dela e só conta
    se também couber no fim dessa semana — quem cai no buraco fica de fora, que
    é o comportamento que o gráfico sempre teve.
    """
    base = pd.DataFrame(
        {
            "semana": [f"S{s.numero}" for s in semanas],
            "rotulo": [s.rotulo for s in semanas],
            "qtd_pecas": 0.0,
            "minutos": 0.0,
        },
        columns=COLUNAS_POR_SEMANA,
    )
    if not semanas:
        return base

    d = df.dropna(subset=["data"])
    if d.empty:
        return base

    # A busca binária exige as semanas em ordem de início. Elas chegam ordenadas
    # em todos os usos de hoje, mas `ordem` desfaz a suposição: o resultado volta
    # na ordem em que o chamador pediu, que é a ordem do eixo X do gráfico.
    inicios = np.array([s.inicio for s in semanas], dtype="datetime64[ns]")
    # Fim exclusivo (+1 dia): as semanas são fechadas nas duas pontas no domínio,
    # então o dia final tem que entrar na própria semana, não na seguinte.
    fins = np.array([s.fim for s in semanas], dtype="datetime64[ns]") + np.timedelta64(1, "D")
    ordem = np.argsort(inicios, kind="stable")

    datas = d["data"].to_numpy(dtype="datetime64[ns]")
    posicao = np.searchsorted(inicios[ordem], datas, side="right") - 1
    dentro = posicao >= 0
    dentro[dentro] &= datas[dentro] < fins[ordem][posicao[dentro]]
    if not dentro.any():
        return base

    alvo = ordem[posicao[dentro]]
    n = len(semanas)
    for coluna in ("qtd_pecas", "minutos"):
        base[coluna] = np.bincount(
            alvo, weights=d[coluna].to_numpy(dtype="float64")[dentro], minlength=n)
    return base


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


# =========================================================================== #
# PREVISÃO — O QUE ESTÁ AGENDADO PARA VOLTAR
# =========================================================================== #
# Diferente das abas de análise, aqui não se mede média nem variação: previsão não
# tem período anterior com que se comparar. O que a base responde é "quanto vai
# voltar, quando, e quanto disso já está fora do prazo".
#
# Duas medidas de risco convivem e são contadas separadamente (ver
# config.STATUS_PREV_*). Uma ordem pode estar nas duas ao mesmo tempo, então somá-las
# num total único produziria um número maior que a quantidade real de ordens.


def classificar_previsao(df: pd.DataFrame, hoje: date | None = None) -> pd.DataFrame:
    """Acrescenta `dias_prazo`, `atraso_previsto`, `fura_prazo` e `vencida`.

    `dias_prazo` é quanto falta do prazo até hoje (negativo = já venceu).
    `atraso_previsto` é quantos dias a data prevista de retorno passa do prazo
    (negativo = a previsão cabe dentro do prazo).

    Ordem sem prazo cadastrado não entra em nenhum dos dois riscos: a ausência do
    dado é problema de cadastro, e transformá-la em atraso inventaria um número
    que ninguém consegue conferir na planilha. Mesma regra de `classificar_prazo`.
    """
    hoje = hoje or date.today()
    out = df.copy()
    if out.empty:
        for coluna in ("dias_prazo", "atraso_previsto"):
            out[coluna] = pd.Series(dtype="float")
        for coluna in ("fura_prazo", "vencida"):
            out[coluna] = pd.Series(dtype="bool")
        return out

    agora = pd.Timestamp(hoje)
    vazio = pd.Series(pd.NaT, index=out.index)
    prazo = out["deadline"] if "deadline" in out.columns else vazio
    previsto = out["data"]

    out["dias_prazo"] = (prazo - agora).dt.days
    out["atraso_previsto"] = (previsto - prazo).dt.days
    # Sem prazo, a diferença é NaN e a comparação devolve False — que é exatamente
    # a regra desejada: a linha fica fora dos dois riscos, sem virar atraso.
    out["fura_prazo"] = out["atraso_previsto"] > 0
    out["vencida"] = out["dias_prazo"] < 0
    return out


def _contar_ordens(om: pd.Series) -> int:
    """Ordens distintas no recorte, com cada linha sem OM contando por uma.

    Hoje a origem traz uma ordem mestre por linha, mas contamos as distintas: se a
    planilha passar a quebrar uma ordem em parcelas, o número continua dizendo
    "ordens" e não "linhas". Linha sem ordem cadastrada conta como uma — descartá-la
    sumiria com produção real do total.
    """
    return int(om.nunique()) + int(om.isna().sum())


@dataclass
class ResumoPrevisao:
    """Consolidado da previsão, já classificada por `classificar_previsao`."""

    ordens: int = 0
    pecas: float = 0.0
    minutos: float = 0.0
    oficinas: int = 0
    fura_prazo: int = 0          # previsão de retorno posterior ao prazo
    vencidas: int = 0            # prazo já passou e a ordem não voltou
    pecas_fura_prazo: float = 0.0
    pecas_vencidas: float = 0.0
    sem_prazo: int = 0           # ordens sem DEAD LINE cadastrado


def resumo_previsao(df: pd.DataFrame) -> ResumoPrevisao:
    """Totais da previsão no recorte atual. Espera um df já classificado."""
    if df.empty:
        return ResumoPrevisao()

    fura = df[df["fura_prazo"]]
    vencidas = df[df["vencida"]]
    sem_prazo = (df["deadline"].isna() if "deadline" in df.columns
                 else pd.Series(True, index=df.index))
    return ResumoPrevisao(
        ordens=_contar_ordens(df["om"]),
        pecas=float(df["qtd_pecas"].sum()),
        minutos=float(df["minutos"].sum()),
        oficinas=int(df["oficina"].nunique()),
        fura_prazo=len(fura),
        vencidas=len(vencidas),
        pecas_fura_prazo=float(fura["qtd_pecas"].sum()),
        pecas_vencidas=float(vencidas["qtd_pecas"].sum()),
        sem_prazo=int(sem_prazo.sum()),
    )


COLUNAS_CONSOL_MP = ["mp", "qtd_pecas", "minutos", "ordens"]


def consolidado_por_mp(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por MP: peças, minutos e quantidade de ordens previstas.

    É a mesma leitura do gráfico de MP, só que com o número na tela e mais a
    contagem de ordens — o gráfico responde "qual MP pesa mais", a tabela responde
    "quanto exatamente". Recebe o mesmo DataFrame já filtrado que alimenta cards e
    gráficos, então os totais fecham com os cards por construção.

    A contagem de ordens usa `_contar_ordens`, a mesma regra do card "Total de
    ordens". Somar a coluna pode dar mais que o card: uma ordem com MPs diferentes
    entre as parcelas conta uma vez em cada MP, porque a pergunta aqui é quantas
    ordens tocam aquela matéria-prima.
    """
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_CONSOL_MP)
    agg = df.groupby("mp", as_index=False).agg(
        qtd_pecas=("qtd_pecas", "sum"),
        minutos=("minutos", "sum"),
        ordens=("om", _contar_ordens),
    )
    return (agg.sort_values("qtd_pecas", ascending=False)
               .reset_index(drop=True)[COLUNAS_CONSOL_MP])


# =========================================================================== #
# STATUS — EM QUE ESTÁGIO DO FLUXO A ORDEM PAROU
# =========================================================================== #
@dataclass
class CoberturaPrevisao:
    """Quanto do que está em aberto já tem data prevista de retorno.

    A conta só existe porque a origem parte a carteira em duas planilhas sem
    interseção: a ordem sai do STATUS no instante em que ganha data prevista e
    passa a viver na PREVISÃO. Somar as duas é, portanto, reconstruir a carteira
    inteira — e a fatia de cada lado responde "de tudo que está fora, quanto
    conseguimos agendar de volta?", que nenhuma das duas telas responde sozinha.
    """

    com_previsao: int = 0
    sem_previsao: int = 0
    pecas_sem_previsao: float = 0.0

    @property
    def total(self) -> int:
        """Ordens em aberto na carteira inteira (as duas bases somadas)."""
        return self.com_previsao + self.sem_previsao

    @property
    def pct_coberto(self) -> float | None:
        """% da carteira com data de retorno; None quando não há carteira."""
        return (self.com_previsao / self.total * 100) if self.total else None

    @property
    def pct_sem_previsao(self) -> float | None:
        return (self.sem_previsao / self.total * 100) if self.total else None


def cobertura_previsao(status: pd.DataFrame,
                       previsao: pd.DataFrame) -> CoberturaPrevisao:
    """Divide a carteira em aberto entre o que tem e o que não tem data de retorno.

    A ordem que aparecer nas DUAS bases é contada uma vez só, do lado de quem tem
    previsão. Pela regra da origem isso não acontece, mas a regra vive fora do
    código: se ela mudar (ou falhar numa exportação), a conta erra para o lado
    conservador — nunca infla o total nem inventa cobertura.
    """
    if status.empty and previsao.empty:
        return CoberturaPrevisao()

    previstas = set(previsao["om"].dropna()) if not previsao.empty else set()
    # `isin` devolve False para OM ausente, então a linha sem ordem cadastrada cai
    # em "sem previsão" — que é onde ela deve estar: não há como agendá-la.
    sem = status[~status["om"].isin(previstas)] if not status.empty else status
    return CoberturaPrevisao(
        com_previsao=_contar_ordens(previsao["om"]) if not previsao.empty else 0,
        sem_previsao=_contar_ordens(sem["om"]) if not sem.empty else 0,
        pecas_sem_previsao=float(sem["qtd_pecas"].sum()) if not sem.empty else 0.0,
    )


COLUNAS_POR_ESTAGIO = ["estagio", "ordens", "qtd_pecas", "minutos"]


def por_estagio(df: pd.DataFrame) -> pd.DataFrame:
    """Ordens, peças e minutos por estágio, do maior volume para o menor.

    A ordenação é por volume e não por uma lista fixa de estágios: o vocabulário
    da origem muda (ver config.ESTAGIOS_CANONICOS), e uma ordem cravada no código
    empurraria um estágio novo para o fim da tela justamente no dia em que ele
    apareceu. A contagem de ordens usa a mesma regra dos cards (`_contar_ordens`).
    """
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_POR_ESTAGIO)
    agg = df.groupby("estagio", as_index=False).agg(
        ordens=("om", _contar_ordens),
        qtd_pecas=("qtd_pecas", "sum"),
        minutos=("minutos", "sum"),
    )
    return (agg.sort_values("qtd_pecas", ascending=False)
               .reset_index(drop=True)[COLUNAS_POR_ESTAGIO])


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
