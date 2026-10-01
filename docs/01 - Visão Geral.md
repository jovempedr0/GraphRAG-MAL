---
tags: [projeto, graphrag, arquitetura]
---

# Visão Geral

Voltar: [[00 - Índice GraphRAG Anime]]

## Objetivo de aprendizado
- Ingestão de dados com rate limiting e retry
- Modelagem em grafo (Neo4j + Cypher)
- Embeddings e busca vetorial
- Text-to-Cypher com validação e autocorreção (analytics do grafo)
- Agente com tool use (loop agêntico)
- Avaliar o ganho do grafo sobre RAG puramente vetorial

## Fluxo

```
MyAnimeList (API oficial v2)
        │  ingestão (Python, rate limit, retry)  → [[02 - Ingestão de Dados]]
        ▼
   Neo4j (grafo + índice vetorial)               → [[03 - Modelo do Grafo]]
        ▲
        │  pergunta → Cypher validado → analytics
   Gerador de Cypher (gpt-oss-20b local)         → [[07 - Gerador de Cypher]]
        ▲
        │  ferramentas (busca semântica, vizinhança, consulta_cypher)
   Agente (tool use, local ou Claude)            → [[04 - Agente GraphRAG]]
        ▲
        │
     Usuário (CLI ou chat)
```

## Stack
| Camada | Escolha | Motivo |
|---|---|---|
| Linguagem | Python | ecossistema de dados e SDKs |
| Banco | Neo4j (Docker local) | Cypher, índice vetorial nativo, muitos tutoriais |
| Fonte | API MAL v2 | oficial, só Client ID, recomendações no detalhe |
| Gerador de Cypher | gpt-oss-20b via oMLX (local) | acertou 14/15 na avaliação, ~7 s por pergunta; ver [[07 - Gerador de Cypher]] |
| Agente | tool use com backend trocável: gpt-oss-20b (oMLX) ou Claude | loop próprio, bom para aprender; comparar local × nuvem na avaliação |
| Embeddings | BGE-M3 via oMLX (local) | multilíngue, grátis, offline; ver [[04 - Agente GraphRAG]] |

## Estrutura de pastas prevista
```
anime-graphrag/
├── docker-compose.yml
├── schema/            # constraints e índices Cypher
├── ingest/            # cliente MAL, loaders
├── analytics/         # gerador de Cypher (schema, validação, CLI)
├── agent/             # ferramentas e loop do agente
└── eval/              # perguntas de teste e comparações
```
