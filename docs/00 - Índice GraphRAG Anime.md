---
tags: [projeto, graphrag, agentes, anime]
status: em andamento
criado: 2026-10-01
---

# Projeto: GraphRAG de Animes e Mangás

Projeto de aprendizado em **programação agêntica**: ingerir dados do MyAnimeList, guardar em um banco de grafo e construir um agente com GraphRAG que consome esse grafo.

## Notas
- [[01 - Visão Geral]]
- [[02 - Ingestão de Dados]]
- [[03 - Modelo do Grafo]]
- [[04 - Agente GraphRAG]]
- [[05 - Roadmap e Avaliação]]
- [[06 - Consultas Cypher]]
- [[07 - Gerador de Cypher]]
- [[08 - Arquitetura C4]]

## Origem da ideia
> Faz um RPA no MyAnimeList e salva num banco de grafo com os animes, mangás, com nota e gênero e recomendações. Aí tu faz um agente com graph-rag pra consumir isso aí.

## Decisão principal
Trocar o "RPA" (scraping) por **API oficial do MAL v2** (a Jikan foi testada e estava instável). Detalhes em [[02 - Ingestão de Dados]].
