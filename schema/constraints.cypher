// Constraints de unicidade (também criam índice sobre mal_id → MERGE rápido e idempotente)
CREATE CONSTRAINT anime_id IF NOT EXISTS FOR (a:Anime) REQUIRE a.mal_id IS UNIQUE;
CREATE CONSTRAINT manga_id IF NOT EXISTS FOR (m:Manga) REQUIRE m.mal_id IS UNIQUE;


// Genre usa o nome como chave: o MAL reaproveita o mesmo id para gêneros diferentes em anime e mangá
// (ex.: 41 = Suspense em anime, Seinen em mangá)
CREATE CONSTRAINT genre_nome IF NOT EXISTS FOR (g:Genre) REQUIRE g.nome IS UNIQUE;
CREATE CONSTRAINT studio_id IF NOT EXISTS FOR (s:Studio) REQUIRE s.mal_id IS UNIQUE;
CREATE CONSTRAINT author_id IF NOT EXISTS FOR (p:Author) REQUIRE p.mal_id IS UNIQUE;


// Índices para filtros frequentes
CREATE INDEX anime_nota IF NOT EXISTS FOR (a:Anime) ON (a.nota);
CREATE INDEX manga_nota IF NOT EXISTS FOR (m:Manga) ON (m.nota);
