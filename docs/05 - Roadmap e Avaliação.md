---
tags: [projeto, graphrag, roadmap, avaliacao]
---

# Roadmap e Avaliação

Voltar: [[00 - Índice GraphRAG Anime]]

## Etapas
- [x] 1. Subir Neo4j (docker-compose) e criar constraints → [[03 - Modelo do Grafo]]
- [x] 2. Ingestão do top 500 animes via API MAL, com cache em disco → [[02 - Ingestão de Dados]]
- [ ] 3. Ingestão de mangás ✅ e relação `ADAPTED_FROM` (pendente — API não traz relação anime↔mangá)
- [ ] 4. Consultas Cypher à mão para entender o grafo → [[06 - Consultas Cypher]]
- [x] 5. Embeddings das sinopses + índice vetorial → [[04 - Agente GraphRAG]]
- [ ] 6. Gerador de Cypher para analytics do grafo (pergunta → Cypher validado → tabela/resumo/gráfico) → [[07 - Gerador de Cypher]]
- [ ] 7. Agente com as três ferramentas (`consulta_cypher` reaproveita o gerador da etapa 6) → [[04 - Agente GraphRAG]]
- [ ] 8. Avaliação (abaixo)
- [ ] 9. Expandir o crawl pelas recomendações

## Avaliação (onde está o aprendizado)
Comparar as respostas do agente em três configurações:

| Configuração | O que usa |
|---|---|
| A | só LLM, sem contexto |
| B | RAG vetorial puro (sem arestas) |
| C | GraphRAG completo (vetorial + vizinhança + Cypher) |

Critérios: relevância da recomendação, fatos corretos (nota, gênero), perguntas multi-hop, perguntas de filtro/agregação, custo e latência.

## Registro de decisões
- 2026-10-01: ingestão via API em vez de scraping
- 2026-10-01: Jikan → API oficial MAL v2 (Jikan instável: 504 ao conectar no MAL)
- 2026-10-01: Neo4j como banco de grafo
- 2026-10-01: imagem `neo4j:2026.09-community` + APOC; schema em `schema/constraints.cypher`
- 2026-10-01: `RECOMMENDS` num sentido só; `Genre` chaveado por nome
- 2026-10-01: `RELATED_TO {tipo}` (sequências, histórias paralelas…), uma aresta por par
- 2026-10-01: nova etapa 6, gerador de Cypher para analytics, antes do agente/chat
- 2026-10-01: embeddings com BGE-M3 (`bge-m3-mlx-fp16`) via oMLX local; embedding guardado no próprio nó (sinopses são curtas, não precisa de `Chunk`)
- Pendente: GDS ou Cypher puro para centralidade/comunidades ([[07 - Gerador de Cypher]])
