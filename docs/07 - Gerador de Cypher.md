---
tags: [projeto, graphrag, cypher, text-to-cypher, analytics]
---

# Gerador de Cypher (analytics)

Voltar: [[00 - Índice GraphRAG Anime]] · Anterior: [[06 - Consultas Cypher]] · Próxima: [[04 - Agente GraphRAG]]

## Ideia
Transformar uma pergunta em linguagem natural numa consulta Cypher, executar e devolver **analytics do grafo**: tabela, resumo em texto e, quando fizer sentido, um gráfico.

```
"Qual estúdio tem a melhor nota média com pelo menos 10 animes?"
        │
        ▼
  contexto (schema + convenções + exemplos)  →  gpt-oss-20b (oMLX) gera Cypher
        │
        ▼
  validação (só leitura, checagens do schema, EXPLAIN, LIMIT)  ──erro──►  devolve o erro e tenta de novo
        │ ok
        ▼
  execução (transação de leitura)  →  tabela + resumo (+ gráfico)
```

## Por que é a última etapa antes do chat
- Das ferramentas do agente, `consulta_cypher` é a mais arriscada: ela **gera código que vai ser executado**. Vale testar e medir isolada antes de entrar no loop
- O agente da etapa seguinte usa este gerador como a ferramenta `consulta_cypher` ([[04 - Agente GraphRAG]])
- Os exercícios de [[06 - Consultas Cypher]] já são um conjunto de perguntas com respostas de referência

## Componentes

### 1. Contexto do schema
- **Introspecção automática:** `CALL db.schema.nodeTypeProperties()` e `CALL db.schema.relTypeProperties()` trazem labels, propriedades e tipos. Assim o prompt nunca fica desatualizado em relação ao banco
- **Convenções escritas à mão**, que a introspecção não mostra:
  - filtrar `completo = true` quando a pergunta envolve nota, gênero ou episódios
  - `RECOMMENDS` sem direção: `-[:RECOMMENDS]-`
  - `RELATED_TO`: `(a)-[:RELATED_TO {tipo}]->(b)` = "b é `tipo` de a"
  - `episodios`/`capitulos` nulos = desconhecido
  - `Genre` é chaveado por `nome`
  - "do top" = `{top: true}`, "fora do top" = `{top: false}` (propriedade separada de `completo` desde o crawl)
- **Valores válidos não vão no prompt.** A ideia era listar gêneros e tipos para o modelo não inventar `'Terror'` no lugar de `'Horror'`, mas a lista piorou o gpt-oss (ver *Perguntas novas*). Os valores chegam pela checagem de valores, no retry

### 2. Exemplos (few-shot)
Pares pergunta → Cypher tirados de [[06 - Consultas Cypher]], escolhidos para cobrir agregação, `WITH`, `COUNT {}`, `EXISTS {}`, caminhos de tamanho variável e `shortestPath`.

### 3. Geração
Modelo local **gpt-oss-20b** via oMLX (`CYPHER_MODEL` em `config/.env`), temperatura 0. A resposta é só um bloco ```` ```cypher ````; a ideia inicial de JSON (`cypher`, `explicacao`, `grafico`) foi deixada de lado porque modelos locais erram mais o formato, e a explicação fica para o agente.

A extração (`extract_cypher`) tolera o que os modelos fazem na prática: bloco sem fechamento, ```` ``` ```` na mesma linha e `\n` literais no lugar de quebras de linha.

### 4. Validação (antes de executar)
- Bloquear cláusulas de escrita: `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `LOAD CSV`, procedures `dbms.*` e as de escrita do APOC
- `EXPLAIN` da consulta: pega erro de sintaxe sem executar. As **notificações** do plano (`UnknownLabelWarning`, `UnknownPropertyKeyWarning`, `UnknownRelationshipTypeWarning`) contam como erro, porque indicam schema alucinado
- Forçar `LIMIT` (ex.: 100) quando a consulta não tiver um
- Executar com `session.execute_read` e timeout de transação. Usuário somente leitura não existe na Community; ver [[04 - Agente GraphRAG]]

**Checagens contra o schema** (`analytics/lint.py`), para os erros silenciosos que o `EXPLAIN` não pega, porque a consulta é válida e roda:
- **Seta em `RECOMMENDS`**: corrigida automaticamente (`-[:RECOMMENDS]->` vira `-[:RECOMMENDS]-`), sem gastar uma chamada ao modelo
- **Direção invertida**: compara cada `(nó)-[rel]->(nó)` com os padrões reais do banco, inclusive quando o label da variável foi definido num `MATCH` anterior. Ex.: "a consulta usa `(:Studio)-[:PRODUCED_BY]->(:Anime)`, mas no schema é `(:Anime)-[:PRODUCED_BY]->(:Studio)`"
- **Propriedade no lugar errado**: "`o.votos`: `votos` é propriedade da relação RECOMMENDS, não do nó Anime"
- **Resultado vazio**: pede uma revisão (uma vez só) com a dica de conferir direção e valores; se vier vazio de novo, aceita
- Limite: variáveis sem label em lugar nenhum da consulta não são checadas

**Checagem de valores** (`analytics/values.py`): um valor inexistente não gera erro no Neo4j, a consulta só volta vazia ou conta zero. Cada literal de igualdade (`{titulo: '...'}`, `x.status = '...'`, `x.nome IN [...]`) é procurado no banco; se não existir, o erro traz os parecidos:
- títulos e nomes: busca pelo valor inteiro e depois por palavra, também no `titulo_en`, os mais populares primeiro ("Attack on Titan" → 'Shingeki no Kyojin'; "Frieren" → 'Sousou no Frieren')
- categorias (até 20 valores distintos): lista todos os válidos ('Movie' → 'movie', 'ova', ...)

### 5. Autocorreção
Se a validação ou a execução falhar, a mensagem de erro volta para o modelo, que gera uma nova versão. Máximo de 2 tentativas extras; todas ficam registradas no log.

### 5b. `SEM_DADOS`
Se a pergunta pede algo que o grafo não guarda (bilheteria, orçamento, personagens, episódios fillers), o modelo responde só `SEM_DADOS: <o que falta>` em vez de Cypher. O gerador para ali e devolve `no_data` com o motivo; a CLI, a interface e a ferramenta `consulta_cypher` do agente mostram a mensagem. Há um exemplo few-shot ("orçamento de Steins;Gate").

### 6. Saída
- Tabela com o resultado
- Resumo em linguagem natural, gerado a partir **das linhas retornadas**, não do conhecimento prévio do modelo
- Gráfico simples quando o resultado é uma agregação (categoria × valor, série por ano)
- Sempre mostrar o Cypher gerado: é o que permite conferir e aprender

## Analytics de grafo (além de agregações)
Perguntas que pedem algoritmos de grafo:

| Pergunta | Técnica |
|---|---|
| Quais animes são mais centrais na rede de recomendações? | PageRank sobre `RECOMMENDS` (peso = `votos`) |
| Que "comunidades de gosto" existem? | Louvain sobre `RECOMMENDS` |
| Quais animes são parecidos por gênero? | Node Similarity (Jaccard) sobre `HAS_GENRE` |
| Como dois animes se conectam? | `shortestPath` (Cypher puro) |

**Decisão pendente:** usar o plugin **Graph Data Science** (GDS), que tem versão Community gratuita e entra em `NEO4J_PLUGINS` no compose, ou ficar só no Cypher puro.

Se usar o GDS:
- os algoritmos pesados rodam num **script em lote**, que grava propriedades como `pagerank` e `comunidade` nos nós
- o gerador só **lê** essas propriedades
- assim ele continua 100% leitura

## Perguntas de exemplo
- Qual estúdio tem a maior nota média, com pelo menos 10 animes no top?
- Como a nota média evoluiu por década?
- Quais gêneros mais aparecem juntos?
- Quais autores têm mais obras no top?
- Qual a proporção de animes adaptados de mangá, light novel e originais?
- Quais animes são mais centrais na rede de recomendações?
- Quantas temporadas tem a maior cadeia de sequências?

## Avaliação
- **Conjunto de referência:** `eval/questions.json`, 15 exercícios de [[06 - Consultas Cypher]] (a E2 ficou de fora), reescritos como perguntas sem as dicas
  - perguntas "top N" com empate no corte do `LIMIT` viraram limiares (ex.: "25 ou mais conexões"); a E10 pergunta o tamanho do caminho, porque há 16 menores caminhos diferentes
- **Rodar:** `uv run --env-file config/.env python -m eval.run MODELO [MODELO ...] [--only E1,E8]`; detalhes de cada resposta em `data/eval/`
- **Métricas:**
  - execução sem erro
  - **resultado igual ao da referência**: comparar conjuntos de linhas, ignorando ordem e nomes de colunas, e não o texto do Cypher
  - número de tentativas
  - latência
  - custo
- **Meta inicial:** ≥ 80% de resultados corretos
- **Experimento:** medir o ganho de cada parte do contexto (só schema → + convenções → + exemplos)

## Resultados (2026-10-01)
Modelos locais via oMLX, M5 Pro 24 GB, temperatura 0, uma rodada:

| Modelo | Sem checagens | Com checagens | Mediana |
|---|---|---|---|
| **gpt-oss-20b-MXFP4-Q8** | 14/15 | **14/15 (93%)** | 6,7 s |
| Qwen3-14B-4bit | 9/15 | 11/15 | 3,5 s |
| Qwen3.6-35B-A3B-OptiQ-4bit-REAP-19B | 5/15 | 8/15 | 2,3 s |
| neo4j text-to-cypher-Gemma-3-4B | 4/15 | 7/15 | 3,1 s |

**Escolha: gpt-oss-20b.** Bateu a meta de 80% e acertou de primeira as perguntas difíceis (dois saltos, menor caminho, cadeia de `RELATED_TO`). O único erro (E12) foi de interpretação: tratou "é recomendado?" como filtro em vez de coluna.

O que os erros dos outros modelos ensinaram:
- Os mais comuns são **silenciosos**: seta no `RECOMMENDS`, direção invertida, `votos` no nó. A convenção escrita no prompt não basta; as checagens renderam +8 acertos no total
- **Funções inventadas e sintaxe antiga** (`path()`, `apoc.coll.index`, `size((a)-[...]-())`): o `EXPLAIN` acusa, mas os modelos pequenos não conseguem consertar no retry
- O **text2cypher da Neo4j** (treinado num conjunto genérico) segue pouco as convenções específicas deste grafo
- A **poda REAP** do Qwen3.6 estragou o Cypher (numa resposta, repetiu `-[:RELATED_TO]->()` milhares de vezes)

**Ressalvas:** 15 perguntas só (1 pergunta = 7 pontos), e o prompt foi ajustado olhando o mesmo conjunto. Falta testar com perguntas novas.

**Memória:** o gpt-oss ocupa ~11,7 GB. Com o memory guard do oMLX em `balanced`, o teto dinâmico (~11,5 GB) recusa o prompt (HTTP 400 `prefill_memory_exceeded`); foi preciso mudar para `aggressive`.

## Interface
```
uv run --env-file config/.env python -m analytics "qual estúdio tem a melhor nota média?"
```
Mostra as tentativas que falharam, o Cypher e a tabela. Cada pergunta é registrada em `data/logs/analytics.jsonl` (modelo, pergunta, Cypher, tentativas com erro e tempo). O resumo em texto fica para o agente ([[04 - Agente GraphRAG]]).

## Perguntas novas (2026-10-01)
`eval/questions_novas.json`: 12 perguntas com padrões fora da nota 06 e dos exemplos do prompt (categorias, vizinhos em comum, `spin_off`, série por ano, top 1).

| Modelo | Antigas (15) | Novas, 1ª rodada | Novas, após ajustes | Total após ajustes |
|---|---|---|---|---|
| **gpt-oss-20b** | 14/15 | 6/12 | **12/12** | **26/27 (96%)** |
| Qwen3-14B | 11/15 | 6/12 | 9/12 | 20/27 (74%) |

- A 1ª rodada confirmou que os 93% estavam inflados. Erros: valores categóricos chutados ('Light Novel', 'Ongoing', 'Movie'), nome popular no lugar do título ('Frieren'), filtro inventado (`nota > 8.5` para "do top", contaminação do exemplo do prompt) e nulos primeiro no `ORDER BY DESC`
- Ajustes: checagem de valores, convenções sobre "do top" e nulos, comparação numérica com tolerância (8,635 × 8,64)
- **Achado contraintuitivo:** listar os valores categóricos no prompt (como os gêneros) derrubou o gpt-oss em E15 e E16 (perguntas de caminho), de forma determinística nas 3 repetições. Sem a lista, as duas voltam a passar, e as perguntas de categoria passam na 2ª tentativa, com os valores vindos da checagem. Lição: **contexto a mais no prompt pode piorar**; erro + sugestão no retry custa menos
- **Ressalva:** os ajustes foram feitos olhando os erros das perguntas novas, que agora também estão "contaminadas". Para medir generalização, falta um lote escrito por outra pessoa e guardado sem olhar

## Depois do crawl (2026-10-01)
O grafo passou de ~1.000 para ~13.600 nós de obra (2.954 animes e 2.735 mangás completos) e ganhou `ADAPTED_FROM`. Com os mesmos prompts:

| | Antes do crawl | Depois do crawl |
|---|---|---|
| Antigas (15) | 14/15 | **13/15** (E12, E16) |
| Novas (12) | 12/12 | **11/12** (N3) |
| Total | 26/27 | **24/27 (89%)**, mediana ~8 s |

**Referências que o crawl quebrou** (o erro estava na referência, não no modelo):
- **E1** (maiores notas): animes ainda não lançados, com `nota` nula, passaram a vir primeiro no `ORDER BY DESC`. A referência ganhou `WHERE a.nota IS NOT NULL`
- **E14** (esboços mais conectados): com milhares de nós novos, o limiar ficou baixo demais e a pergunta deixou de separar. Virou "fora do top com 40 ou mais conexões", com `{top: false}`
- A propriedade `top` foi criada para isso: antes, "do top" e "completo" eram a mesma coisa; agora um anime pode estar completo (coletado no crawl) sem estar no top

**Bilheteria → `SEM_DADOS`.** No uso real, "qual foi a bilheteria do filme de Chainsaw Man?" gerou `RETURN a.popularidade AS bilheteria`: a consulta é válida, roda e devolve um número com o nome errado. Nenhuma checagem pega isso, porque o erro é de significado. Daí a regra `SEM_DADOS` (seção 5b).

**Efeito colateral da regra:** acrescentar `SEM_DADOS` ao prompt consertou a bilheteria e derrubou a E16, que vinha passando. Mais um caso de contexto no prompt mexendo em pergunta não relacionada, como a lista de valores categóricos (ver *Perguntas novas*).

**As três falhas:**
- **E12 (Jaccard), erro silencioso novo:** `interSize / unionSize` com dois inteiros é **divisão inteira** no Cypher, então a similaridade dá 0 ou 1 e o filtro `>= 0.5` zera o resultado. O modelo recebeu a dica de resultado vazio e respondeu vazio duas vezes. **Virou checagem no lint:** divisão em que os dois lados são `size()`, `count()`, `length()`, `COUNT {}` ou aliases deles, sem `toFloat`. Na rodada seguinte o modelo recebeu o erro e corrigiu na 2ª tentativa (`toFloat(interSize) / unionSize`); nenhuma resposta correta das avaliações anteriores dispara a checagem. A E12 continua errada, mas agora pelo motivo de antes do crawl: trata "é recomendado junto?" como filtro, não como coluna
- **E16 (cadeia de sequências):** sintaxe inventada nas três tentativas: `-[:RELATED_TO {tipo: 'sequel'}*]->` (o `*` vem antes do mapa), depois as funções `index()` e `node()`, que não existem. O `EXPLAIN` acusa, mas o modelo troca um erro por outro
- **N3 (adaptados de light novel):** usou `ADAPTED_FROM` (42) em vez da propriedade `fonte` (55). As duas leituras são defensáveis; falta uma convenção dizendo qual vale. Adiado

## Código
| Arquivo | Papel |
|---|---|
| `analytics/schema.py` | schema lido do banco + convenções → `Schema` (texto do prompt e conjuntos para as checagens) |
| `analytics/prompt.py` | instruções, 7 exemplos (diferentes das perguntas da avaliação, um deles `SEM_DADOS`), mensagens de retry |
| `analytics/llm.py` | cliente de chat do oMLX; desliga o raciocínio dos Qwen3 |
| `analytics/cypher.py` | extração, bloqueio de escrita, `EXPLAIN`, `LIMIT`, execução de leitura com timeout |
| `analytics/lint.py` | checagens contra o schema |
| `analytics/values.py` | checagem dos valores literais no banco, com sugestões |
| `analytics/generator.py` | laço de geração com retry, revisão de resultado vazio e parada em `SEM_DADOS` |
| `analytics/evaluation.py` | comparação de resultados |

## Questões em aberto
- GDS ou Cypher puro para centralidade e comunidades?
- Gráficos no terminal (ex.: `plotext`) ou exportar HTML? (adiado)
- Quantos exemplos few-shot cabem antes de piorar (ou encarecer) a geração?
- O gerador generaliza? Falta um lote de perguntas guardado sem olhar (as 12 novas já orientaram ajustes)
- Vale um exemplo few-shot de caminho de tamanho variável? Os modelos pequenos erraram as cadeias (E15, E16), e depois do `SEM_DADOS` o gpt-oss também erra a E16. Mas exemplo novo é prompt novo, e prompt novo já derrubou outras perguntas
- `fonte` ou `ADAPTED_FROM` para "adaptado de X" (N3)
