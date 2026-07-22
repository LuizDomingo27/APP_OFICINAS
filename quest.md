# Verificação: "por que falta 9 dias e não 10?" (página de Metas)

Questão levantada pela equipe de desenvolvimento: o `st.info` no fim da página de
metas mostra **"faltam 9 dia(s) útil(eis)"**, mas contando o dia de hoje deveriam
ser **10**. Abaixo a verificação da lógica.

## Onde encontrar no código (arquivo : linha)

Referências conferidas em 2026-07-20, **após** a correção.

| O quê | Arquivo | Linha(s) |
| --- | --- | --- |
| `st.info` "Para fechar o mês faltam N dia(s) útil(eis)" | `app.py` | 1069-1074 |
| Card "restante(s)" no painel | `app.py` | 981-984 |
| Chamada `metas.montar_plano(...)` | `app.py` | 1045 |
| Cálculo decorridos/restantes (trecho corrigido) | `gestao_fluxo/metas.py` | 146-155 |
| Ritmo necessário por dia (`falta / uteis_restantes`) | `gestao_fluxo/metas.py` | 182 |
| Função `montar_plano(...)` | `gestao_fluxo/metas.py` | 137 |
| Função contadora `dias_uteis(inicio, fim)` | `gestao_fluxo/metas.py` | 73-84 |
| Campos `dias_uteis_decorridos` / `dias_uteis_restantes` (dataclass `PlanoMetas`) | `gestao_fluxo/metas.py` | 119-120 |
| Teste do ritmo/dias restantes | `tests/test_metas.py` | 119-126 |
| Teste "mês encerrado não tem dia restante" | `tests/test_metas.py` | 128-132 |

## Causa

```python
# gestao_fluxo/metas.py:147-148
uteis_decorridos = 0 if hoje < inicio_mes else dias_uteis(inicio_mes, min(hoje, fim_mes))
uteis_restantes = max(uteis_mes - uteis_decorridos, 0)
```

A função `dias_uteis()` conta os **dois extremos de forma inclusiva**
(`while cursor <= fim`). Logo `dias_uteis(inicio_mes, hoje)` **inclui o dia de
hoje** na conta de dias *decorridos*. Como `restantes = mês - decorridos`, o dia
de hoje é subtraído do saldo — por isso dá 9.

## Reprodução (hoje = 2026-07-20, segunda-feira)

| Grandeza                                   | Valor |
|--------------------------------------------|-------|
| Dias úteis do mês                          | 23    |
| Decorridos (`início → hoje`, inclui hoje)  | 14    |
| **Restantes = 23 − 14**                    | **9** |
| De hoje até o fim, inclusive               | 10    |

Ou seja: **hoje é classificado como dia já decorrido, não como dia restante.**
Os 9 são os dias úteis *depois de hoje* até o fim do mês. Os 10 esperados pela
equipe correspondem a "de hoje (inclusive) até o fim do mês".

## É bug ou intencional? (decisão de negócio pendente)

- **Se hoje ainda conta como dia de produção** → a mensagem deveria dizer **10**;
  a linha 147 tem um off-by-one. Correção possível: iniciar os decorridos em
  `hoje + timedelta(days=1)`, ou calcular direto `dias_uteis(hoje, fim_mes)`.
- **Se hoje é considerado "já gasto"** (meta do dia já contabilizada, interessa o
  que sobra a partir de amanhã) → 9 está correto; basta reescrever o texto para
  deixar claro que são os dias restantes *após* hoje.

## Efeito colateral importante

O mesmo `uteis_restantes` alimenta o **ritmo necessário por dia**
(`metas.py:175`): `ritmo = falta / uteis_restantes`. Se hoje deveria contar, o
ritmo está sendo calculado sobre base menor (9 em vez de 10), **inflando** as
peças/minutos exigidos por dia. A escolha entre 9 e 10 afeta também esses números.

## Decisão tomada (2026-07-20)

**Opção 1 escolhida:** hoje ainda conta como dia de produção → o restante inclui
hoje (vira 10). Correção aplicada.

### O que mudou

`gestao_fluxo/metas.py:146-155` — antes, `dias_uteis(inicio_mes, hoje)` contava
hoje como *decorrido* (contagem inclusiva). Agora só os dias **anteriores** a hoje
entram em "decorridos" (`hoje - timedelta(days=1)`), e os dois extremos são
tratados explicitamente para manter `decorridos + restantes = dias_uteis_mes`:

```python
if hoje < inicio_mes:          # mês futuro -> nada decorrido
    uteis_decorridos = 0
elif hoje > fim_mes:           # mês encerrado -> tudo decorrido
    uteis_decorridos = uteis_mes
else:                          # dentro do mês: hoje ainda é dia de produção
    uteis_decorridos = dias_uteis(inicio_mes, hoje - timedelta(days=1))
uteis_restantes = max(uteis_mes - uteis_decorridos, 0)
```

### Efeitos

- `st.info` (`app.py:1070`) passa a mostrar **10** em 20/07/2026.
- **Ritmo necessário por dia** (`metas.py:175`) agora divide pela base correta
  (10 em vez de 9) → peças/minutos exigidos por dia ficam um pouco menores.
- Mês encerrado continua com 0 restantes.

### Testes

- `tests/test_metas.py::test_ritmo_necessario_usa_os_dias_uteis_restantes`
  atualizado (15/07 → 10 decorridos, 13 restantes, ritmo `700/13`).
- Suíte de metas: **16 passed**. `test_mes_ja_encerrado_nao_tem_dia_restante`
  segue em 0.

---

# Correção: front-end não atualizava sem reboot + insert lento (2026-07-22)

Dois problemas relatados em produção (Streamlit Cloud + Supabase/Postgres):

1. **Ao adicionar novos registros pelo app, o painel não atualizava** — só depois
   de reiniciar o servidor do Streamlit Cloud.
2. **A carga (insert) estava muito lenta** na hora de gravar os registros.

## Problema 1 — Front-end não atualizava sem reboot

### Causa

O cache de dados `_fato` não tinha `ttl`, então **nunca expirava sozinho**. A única
coisa que o limpava era `st.cache_data.clear()` dentro de `_rodar_etl`, que roda só
na sessão que faz a carga. Um painel aberto passivamente noutra aba/dispositivo (ou
outra sessão) não re-executa o script e continuava servindo o dado antigo — até o
reboot, que zera todo o cache do processo.

### Correção 1a — `ttl` no cache (`app.py:66`)

**Antes estava assim:**

```python
# app.py:66
@st.cache_data(show_spinner=False)
def _fato(fonte: str, _versao: int):
    """Fato completo em cache. `_versao` invalida o cache após uma recarga."""
    return metricas.carregar_fato(_engine(), fonte)
```

**Depois ficou assim:**

```python
# app.py:66
@st.cache_data(show_spinner=False, ttl=300)
def _fato(fonte: str, _versao: int):
    """Fato completo em cache. `_versao` invalida o cache após uma recarga.
    ... (ttl=300 é a rede de segurança: qualquer sessão relê o banco sozinha em
    no máximo 5 minutos, sem depender de reiniciar o servidor.)
    """
    return metricas.carregar_fato(_engine(), fonte)
```

### Correção 1b — botão "Atualizar dados agora" (`app.py:216`)

Novo botão no menu **Dados** (`_menu_dados`), logo após "Recarregar da pasta do
projeto". Descarta o cache e relê o banco **na hora**, sem gravar nada — é o
substituto direto do "reboot do servidor".

**Antes estava assim** (não existia o botão):

```python
# app.py:198 (trecho anterior ao acréscimo)
    if st.button("Recarregar da pasta do projeto", use_container_width=True):
        try:
            _rodar_etl()
            st.rerun()
        except GestaoFluxoError as exc:
            st.error(exc.mensagem_usuario)
```

**Depois ficou assim** (botão acrescentado):

```python
# app.py:216
    if st.button("🔄 Atualizar dados agora", use_container_width=True):
        st.cache_data.clear()
        st.session_state["versao_dados"] = _versao_dados() + 1
        st.rerun()
```

| O quê | Arquivo | Linha |
| --- | --- | --- |
| `ttl=300` no cache de dados | `app.py` | 66 |
| Botão "🔄 Atualizar dados agora" | `app.py` | 216-219 |

## Problema 2 — Insert muito lento

### Causa

O insert do Postgres usava `conn.exec_driver_sql(sql, linhas)`, que no psycopg2 vira
`executemany` — **uma ida ao banco por linha**. Contra o Supabase remoto (latência de
rede por round-trip), gravar dezenas de milhares de linhas assim levava minutos.

### Correção — `execute_values` em lote (`gestao_fluxo/db/dialeto.py:191`)

**Antes estava assim:**

```python
# gestao_fluxo/db/dialeto.py (DialetoPostgres.inserir_muitas)
def inserir_muitas(self, conn, tabela, colunas, linhas, *, ignorar_conflito):
    # rowcount do psycopg2 já exclui o que o ON CONFLICT descartou...
    resultado = conn.exec_driver_sql(
        self.sql_insert(tabela, colunas, ignorar_conflito=ignorar_conflito), linhas)
    return max(int(resultado.rowcount or 0), 0)
```

**Depois ficou assim:**

```python
# gestao_fluxo/db/dialeto.py:191 (DialetoPostgres.inserir_muitas)
def inserir_muitas(self, conn, tabela, colunas, linhas, *, ignorar_conflito):
    # execute_values monta UM INSERT com várias linhas por página, em vez do
    # executemany (uma ida ao banco por registro). Minutos -> segundos.
    if not linhas:
        return 0
    from psycopg2.extras import execute_values

    conflito = (f" ON CONFLICT ({', '.join(CONFLITO_IDENTIDADE)}) DO NOTHING"
                if ignorar_conflito else "")
    sql = (f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES %s"
           f"{conflito} RETURNING 1")
    raw = conn.connection.dbapi_connection
    with raw.cursor() as cur:
        gravadas = execute_values(cur, sql, linhas, page_size=1000, fetch=True)
    return len(gravadas)
```

Notas da correção:

- A contagem de linhas novas passa a sair do `RETURNING 1` com `fetch=True` (são
  exatamente as linhas que este comando gravou, já sem o que o `ON CONFLICT`
  descartou) — continua correta sob concorrência e mais confiável que o `rowcount`,
  que sob paginação só reflete a última página.
- `import` local do `psycopg2` para preservar a propriedade de que a suíte de testes
  roda em SQLite sem o driver instalado — este caminho só existe em produção.

| O quê | Arquivo | Linha |
| --- | --- | --- |
| Insert em lote com `execute_values` | `gestao_fluxo/db/dialeto.py` | 191-216 |

## Verificação

- Suíte completa: **142 passed** (caminho SQLite intacto — o insert em lote só roda
  contra o Postgres real).
- `app.py` e `dialeto.py` compilam sem erros (`py_compile`).
- Pendente confirmar na próxima carga real que a velocidade melhorou e que a prévia
  "X novas / Y já existentes" continua batendo.
