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
| `Anime` | `mal_id`, `titulo`, `titulo_en`, `sinopse`, `nota`, `rank`, `popularidade`, `membros`, `tipo`, `status`, `ano`, `episodios`, `fonte`, `completo`, `top`, `embedding` |
| `Manga` | `mal_id`, `titulo`, `titulo_en`, `sinopse`, `nota`, `rank`, `popularidade`, `membros`, `tipo`, `status`, `ano`, `capitulos`, `volumes`, `completo`, `top`, `embedding` |
| `Genre` | `nome` (chave — o MAL reaproveita ids de gênero entre anime e mangá: 41 = Suspense em anime, Seinen em mangá) |
| `Studio` | `mal_id`, `nome` |
| `Author` | `mal_id`, `nome` |

## Arestas
| Relação | Entre | Propriedades |
|---|---|---|
| `HAS_GENRE` | Anime/Manga → Genre | — |
| `RECOMMENDS` | Anime → Anime, Manga → Manga | `votos` — um sentido só, do menor `mal_id` para o maior; consultar com `-[:RECOMMENDS]-` |
| `ADAPTED_FROM` | Anime → Manga | — criada por casamento de títulos (`ingest/adapt.py`); ver abaixo |
| `PRODUCED_BY` | Anime → Studio | — |
| `WRITTEN_BY` | Manga → Author | `papel` (ex.: Story & Art) |
| `RELATED_TO` | Anime → Anime, Manga → Manga | `tipo` — `(a)-[:RELATED_TO {tipo}]->(b)` = "b é `tipo` de a" |

**Embeddings:** `embedding` (1024 floats) e `embedding_modelo` nos nós completos com sinopse; índices vetoriais `anime_embedding_1024` e `manga_embedding_1024` (cosseno), criados por `ingest/embed.py` (o nome do índice leva a dimensão do modelo).

**Nós esboço:** itens recomendados ou relacionados que ainda não foram coletados entram só com `mal_id` + `titulo` e `completo = false`. São a fronteira do crawl ([[02 - Ingestão de Dados]]). Filtrar com `completo = true` quando precisar de nota/gênero.

**`top` × `completo`:** `top = true` marca os 500 do ranking de cada tipo; `completo = true` diz só que o nó tem os detalhes. Depois do crawl são coisas diferentes: um anime coletado pelo crawl é completo, mas `top = false`. Esboços nascem com `top = false`.

**Grafo atual (2026-10-01):** 7.266 animes (2.954 completos), 6.329 mangás (2.735 completos), 23.757 `RECOMMENDS`, 7.664 `RELATED_TO`, 1.240 `ADAPTED_FROM`, 2.861 autores, 346 estúdios, 80 gêneros.

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
- 2026-10-01: o gerador de Cypher lê o schema do próprio banco (`analytics/schema.py`), então esta nota não precisa ser a fonte da verdade para ele
- 2026-10-01: `ADAPTED_FROM` herdado também por histórias paralelas, recapitulações e versões alternativas (`metodo = 'relacionado'`), depois da cadeia de sequências; `spin_off` fica de fora

**`RELATED_TO`:** o MAL lista cada relação nas duas páginas com tipos inversos. O loader guarda uma aresta por par:
- tipos inversos são normalizados invertendo a seta: `prequel` → `sequel`, `parent_story` → `side_story`, `full_story` → `summary`
- simétricos (`alternative_version`, `alternative_setting`, `character`, `other`) vão do menor `mal_id` para o maior
- os demais (`sequel`, `side_story`, `spin_off`, `summary`, `adaptation`) ficam como estão na página
- exceção conhecida: 9 pares em que o MAL é inconsistente (ex.: `spin_off` de um lado, `parent_story` do outro) ficam com 2 arestas

**`ADAPTED_FROM`:** a API MAL v2 não devolve relações anime↔mangá, então `ingest/adapt.py` casa pelos títulos:
1. título japonês, romaji ou inglês, normalizado e sem sufixo de temporada ("2nd Season", "第2期"), e só se a `fonte` do anime for compatível com o tipo do mangá (mangá ↔ manga/manhwa/manhua, light novel ↔ light_novel/novel)
2. com mais de um candidato, fica o do tipo preferido para aquela fonte
3. anime sem par direto herda o da cadeia de sequências (a Season 2 herda o mangá da Season 1). O grafo de sequências é tratado como simétrico para a herança andar nos dois sentidos
4. quem ainda ficou sem par herda também por `side_story`, `parent_story`, `summary`, `full_story` e `alternative_version` (filmes, OVAs e recapitulações com título próprio, como Violet Evergarden Gaiden). `spin_off`, `alternative_setting` e `character` ficam de fora, porque costumam ser outra obra
5. `--buscar`: para cada mangá do top ainda sem adaptação, procura no MAL um anime com o mesmo título; os achados entram no crawl

Cada aresta guarda como foi criada em `metodo`: `titulo` (702), `sequencia` (190) e `relacionado` (348). A etapa 4 levou o total de 892 para 1.240. No top 500, 45 dos 55 animes com `fonte = 'light_novel'` têm `ADAPTED_FROM`; os outros 10 caem em light novel cadastrada como "X Series", obra original fora do grafo ou cadeia que passa por nós não coletados

## Questões em aberto
- `ADAPTED_FROM` é heurística: faltam adaptações com títulos diferentes, e casos raros podem casar errado
- "Adaptado de light novel" tinha duas respostas: a propriedade `fonte` do anime (55 no top 500) ou `ADAPTED_FROM` (45, só quando a obra original está no grafo). Resolvido com uma convenção no gerador: o tipo da obra original vem de `a.fonte`, e `ADAPTED_FROM` só entra quando a pergunta precisa da obra em si ([[07 - Gerador de Cypher]], N3)
