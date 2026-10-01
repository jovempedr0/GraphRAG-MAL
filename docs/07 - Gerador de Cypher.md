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
  contexto (schema + convenções + exemplos)  →  Claude gera Cypher
        │
        ▼
  validação (EXPLAIN, só leitura, LIMIT)  ──erro──►  devolve o erro e tenta de novo
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
- **Valores válidos:** a lista de gêneros (76) e de tipos de `RELATED_TO`, para o modelo não inventar `'Terror'` quando o valor real é `'Horror'`

### 2. Exemplos (few-shot)
Pares pergunta → Cypher tirados de [[06 - Consultas Cypher]], escolhidos para cobrir agregação, `WITH`, `COUNT {}`, `EXISTS {}`, caminhos de tamanho variável e `shortestPath`.

### 3. Geração
Claude com saída estruturada:
```json
{"cypher": "...", "explicacao": "...", "grafico": "barras | linha | nenhum"}
```

### 4. Validação (antes de executar)
- Bloquear cláusulas de escrita: `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `LOAD CSV`, procedures `dbms.*` e as de escrita do APOC
- `EXPLAIN` da consulta: pega erro de sintaxe sem executar. As **notificações** do plano (`UnknownLabelWarning`, `UnknownPropertyKeyWarning`, `UnknownRelationshipTypeWarning`) contam como erro, porque indicam schema alucinado
- Forçar `LIMIT` (ex.: 100) quando a consulta não tiver um
- Executar com `session.execute_read` e timeout de transação. Usuário somente leitura não existe na Community; ver [[04 - Agente GraphRAG]]

### 5. Autocorreção
Se a validação ou a execução falhar, a mensagem de erro volta para o modelo, que gera uma nova versão. Máximo de 2 tentativas extras; todas ficam registradas no log.

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
- **Conjunto de referência:** exercícios de [[06 - Consultas Cypher]] (pergunta + Cypher de referência), num arquivo em `eval/`
- **Métricas:**
  - execução sem erro
  - **resultado igual ao da referência**: comparar conjuntos de linhas, ignorando ordem e nomes de colunas, e não o texto do Cypher
  - número de tentativas
  - latência
  - custo
- **Meta inicial:** ≥ 80% de resultados corretos
- **Experimento:** medir o ganho de cada parte do contexto (só schema → + convenções → + exemplos)

## Interface
```
uv run --env-file config/.env python -m analytics "qual estúdio tem a melhor nota média?"
```
Mostra o Cypher, a tabela e o resumo. Cada pergunta é registrada em `data/logs/` (pergunta, tentativas, Cypher, erros, tempo).

## Questões em aberto
- GDS ou Cypher puro para centralidade e comunidades?
- Gráficos no terminal (ex.: `plotext`) ou exportar HTML?
- Quantos exemplos few-shot cabem antes de piorar (ou encarecer) a geração?
