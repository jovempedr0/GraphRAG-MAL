---
tags: [projeto, graphrag, neo4j, cypher]
---

# Modelo do Grafo

Voltar: [[00 - Índice GraphRAG Anime]] · Anterior: [[02 - Ingestão de Dados]] · Próxima: [[04 - Agente GraphRAG]]

## Banco
**Neo4j** em Docker local, com índice vetorial nativo.

## Nós
| Label | Propriedades principais |
|---|---|
| `Anime` | `mal_id`, `titulo`, `titulo_en`, `sinopse`, `nota`, `rank`, `popularidade`, `membros`, `tipo`, `status`, `ano`, `episodios`, `fonte`, `completo`, `embedding` |
| `Manga` | `mal_id`, `titulo`, `titulo_en`, `sinopse`, `nota`, `rank`, `popularidade`, `membros`, `tipo`, `status`, `ano`, `capitulos`, `volumes`, `completo`, `embedding` |
| `Genre` | `nome` (chave — o MAL reaproveita ids de gênero entre anime e mangá: 41 = Suspense em anime, Seinen em mangá) |
| `Studio` | `mal_id`, `nome` |
| `Author` | `mal_id`, `nome` |

## Arestas
| Relação | Entre | Propriedades |
|---|---|---|
| `HAS_GENRE` | Anime/Manga → Genre | — |
| `RECOMMENDS` | Anime → Anime, Manga → Manga | `votos` — um sentido só, do menor `mal_id` para o maior; consultar com `-[:RECOMMENDS]-` |
| `ADAPTED_FROM` | Anime → Manga | — |
| `PRODUCED_BY` | Anime → Studio | — |
| `WRITTEN_BY` | Manga → Author | `papel` (ex.: Story & Art) |
| `RELATED_TO` | Anime → Anime, Manga → Manga | `tipo` — `(a)-[:RELATED_TO {tipo}]->(b)` = "b é `tipo` de a" |

**Embeddings:** `embedding` (1024 floats) e `embedding_modelo` nos nós completos com sinopse; índices vetoriais `anime_embedding_1024` e `manga_embedding_1024` (cosseno), criados por `ingest/embed.py` (o nome do índice leva a dimensão do modelo).

**Nós esboço:** itens recomendados fora do top entram só com `mal_id` + `titulo` e `completo = false` (fronteira para o crawl da etapa 8). Filtrar com `completo = true` quando precisar de nota/gênero.

## Constraints e índices
Em `schema/constraints.cypher` (unicidade em `mal_id` para Anime/Manga/Studio/Author, `nome` para Genre; índices em `nota`).

## Consultas para treinar à mão
```cypher
// Top 10 seinen com nota > 8
MATCH (a:Anime)-[:HAS_GENRE]->(:Genre {nome: 'Seinen'})
WHERE a.nota > 8
RETURN a.titulo, a.nota ORDER BY a.nota DESC LIMIT 10;

// Mangás bem avaliados sem adaptação em anime
MATCH (m:Manga)
WHERE m.nota > 8 AND NOT EXISTS { (:Anime)-[:ADAPTED_FROM]->(m) }
RETURN m.titulo, m.nota ORDER BY m.nota DESC LIMIT 20;
```

## Decisões
- 2026-10-01: `RECOMMENDS` num sentido só (menor → maior `mal_id`)
- 2026-10-01: `RELATED_TO {tipo}` normalizado, uma aresta por par

**`RELATED_TO`:** o MAL lista cada relação nas duas páginas com tipos inversos. O loader guarda uma aresta por par:
- tipos inversos são normalizados invertendo a seta: `prequel` → `sequel`, `parent_story` → `side_story`, `full_story` → `summary`
- simétricos (`alternative_version`, `alternative_setting`, `character`, `other`) vão do menor `mal_id` para o maior
- os demais (`sequel`, `side_story`, `spin_off`, `summary`, `adaptation`) ficam como estão na página
- exceção conhecida: 9 pares em que o MAL é inconsistente (ex.: `spin_off` de um lado, `parent_story` do outro) ficam com 2 arestas

## Questões em aberto
- `ADAPTED_FROM`: a API MAL v2 não devolve relações anime↔mangá. Opções: campo `source` do anime (diz que veio de mangá, mas não de qual) + casar por título/autor; ou buscar só as relações na Jikan (`/anime/{id}/relations`) quando ela estiver estável
