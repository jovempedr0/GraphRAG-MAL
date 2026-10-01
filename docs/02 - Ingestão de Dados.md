---
tags: [projeto, graphrag, ingestao, api]
---

# Ingestão de Dados

Voltar: [[00 - Índice GraphRAG Anime]] · Próxima: [[03 - Modelo do Grafo]]

## Por que não scraping (RPA)
- Raspar o MyAnimeList viola os termos de uso
- Quebra a cada mudança de HTML
- Risco de bloqueio de IP

## Opções

### Jikan (`https://api.jikan.moe/v4`) — descartada
- API REST não oficial, **sem autenticação**
- Limite: ~3 requisições/segundo (e ~60/minuto) → rate limiting + retry com backoff
- Endpoints úteis:
  - `/top/anime`, `/top/manga` (paginado)
  - `/anime/{id}/full` (gêneros, estúdios, relações, nota)
  - `/anime/{id}/recommendations`
  - `/manga/{id}/full`, `/manga/{id}/recommendations`
- **Problema (2026-10-01):** a Jikan é um scraper do MAL por baixo; vários endpoints davam `504 Jikan failed to connect to MyAnimeList` (só funcionava o que já estava no cache dela)

### API oficial MAL v2 (`https://api.myanimelist.net/v2`) — escolhida
- Para dados públicos basta o header `X-MAL-CLIENT-ID` (sem fluxo OAuth); criar em https://myanimelist.net/apiconfig
- Limite não documentado → 1 req/s + retry com backoff
- Endpoints:
  - `/anime/ranking`, `/manga/ranking` (`limit` até 500, `offset`)
  - `/anime/{id}?fields=...` e `/manga/{id}?fields=...` — uma chamada traz gêneros, estúdios/autores, `related_anime`, `related_manga` e `recommendations`
- **Limitações observadas (2026-10-01):**
  - `related_manga` no anime e `related_anime` no mangá vêm **sempre vazios** (só relações do mesmo tipo funcionam) → `ADAPTED_FROM` precisa de outra fonte (ver [[03 - Modelo do Grafo]])
  - `recommendations` traz no máximo 10 itens, com `num_recommendations` (= votos)
  - `genres` já mistura gêneros, temas e demografia (ex.: `Shounen`, `Military`)

### Automação de navegador
- Só se quiser praticar RPA, e apenas em páginas que as APIs não cobrem

## Estratégia
1. Começar com subconjunto: **top 500 animes** + top mangás
2. Para cada item: buscar detalhe com `fields` (já inclui recomendações)
3. Gravar o JSON bruto em disco (cache) antes de ir pro banco → evita refazer chamadas
4. Carregar no Neo4j com `MERGE` (idempotente)
5. Expandir depois pelas recomendações (crawl em largura com limite de profundidade)

## Cuidados
- Respeitar rate limit (fila + sleep)
- Retry com backoff em 429 e 5xx
- Cache local para reexecução barata
- Registrar IDs já processados
