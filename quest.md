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
