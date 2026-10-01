---
tags: [projeto, graphrag, roadmap, avaliacao]
---

# Roadmap e Avaliação

Voltar: [[00 - Índice GraphRAG Anime]]

## Etapas
- [x] 1. Subir Neo4j (docker-compose) e criar constraints → [[03 - Modelo do Grafo]]
- [x] 2. Ingestão do top 500 animes via API MAL, com cache em disco → [[02 - Ingestão de Dados]]
- [ ] 3. Ingestão de mangás ✅ e relação `ADAPTED_FROM` (pendente — API não traz relação anime↔mangá)
- [ ] 4. Consultas Cypher à mão para entender o grafo (roteiro pronto, 16 exercícios conferidos) → [[06 - Consultas Cypher]]
- [x] 5. Embeddings das sinopses + índice vetorial → [[04 - Agente GraphRAG]]
- [ ] 6. Gerador de Cypher para analytics do grafo (pergunta → Cypher validado → tabela/resumo/gráfico) → [[07 - Gerador de Cypher]]
    - [x] schema do banco + convenções + exemplos, validação, checagens contra o schema, retry, CLI
    - [x] avaliação com 15 perguntas e escolha do modelo (gpt-oss-20b, 14/15)
    - [ ] perguntas novas na avaliação (fora da nota 06), para medir generalização
    - [ ] resumo e gráfico: o resumo fica para o agente; o gráfico foi adiado
- [ ] 7. Agente com as três ferramentas (`consulta_cypher` reaproveita o gerador da etapa 6) → [[04 - Agente GraphRAG]]
- [ ] 8. Avaliação (abaixo)
- [ ] 9. Expandir o crawl pelas recomendações

**Ordem combinada (2026-10-01):** notas → perguntas novas na avaliação do gerador → agente v1 (local) → crawl + `ADAPTED_FROM` → avaliação A/B/C. O crawl vem **antes** da avaliação para ela medir o ganho do grafo, não as lacunas dos dados (só 9 animes de terror no top 500; sem `ADAPTED_FROM`).

## Avaliação (onde está o aprendizado)
Comparar as respostas do agente em três configurações:

| Configuração | O que usa |
|---|---|
| A | só LLM, sem contexto |
| B | RAG vetorial puro (sem arestas) |
| C | GraphRAG completo (vetorial + vizinhança + Cypher) |

Critérios: relevância da recomendação, fatos corretos (nota, gênero), perguntas multi-hop, perguntas de filtro/agregação, custo e latência.

Com o backend trocável do agente, a configuração C roda duas vezes: **modelo local (gpt-oss-20b) × Claude**.

## Registro de decisões
- 2026-10-01: ingestão via API em vez de scraping
- 2026-10-01: Jikan → API oficial MAL v2 (Jikan instável: 504 ao conectar no MAL)
- 2026-10-01: Neo4j como banco de grafo
- 2026-10-01: imagem `neo4j:2026.09-community` + APOC; schema em `schema/constraints.cypher`
- 2026-10-01: `RECOMMENDS` num sentido só; `Genre` chaveado por nome
- 2026-10-01: `RELATED_TO {tipo}` (sequências, histórias paralelas…), uma aresta por par
- 2026-10-01: nova etapa 6, gerador de Cypher para analytics, antes do agente/chat
- 2026-10-01: embeddings com BGE-M3 (`bge-m3-mlx-fp16`) via oMLX local; embedding guardado no próprio nó (sinopses são curtas, não precisa de `Chunk`)
- 2026-10-01: gerador de Cypher com modelo **local** (gpt-oss-20b via oMLX) em vez do Claude: 14/15 na avaliação, contra 11/15 do Qwen3-14B, 8/15 do Qwen3.6-35B-A3B-REAP e 7/15 do text2cypher Gemma-3-4B da Neo4j
- 2026-10-01: avaliação do gerador compara o **resultado** com o da consulta de referência (linhas sem ordem, colunas extras aceitas), não o texto do Cypher
- 2026-10-01: checagens próprias contra o schema (seta em `RECOMMENDS`, direção invertida, propriedade no lugar errado), porque o `EXPLAIN` não pega erros silenciosos
- 2026-10-01: oMLX com memory guard em `aggressive`; em `balanced` o gpt-oss não roda junto com o Neo4j nos 24 GB
- 2026-10-01: agente com backend trocável (`omlx` | `anthropic`), começando pelo local
- Pendente: GDS ou Cypher puro para centralidade/comunidades ([[07 - Gerador de Cypher]])
