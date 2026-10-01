"""Cria ADAPTED_FROM (Anime → Manga) casando títulos, já que a API do MAL não traz a relação.

Uso:
    uv run --env-file config/.env python -m ingest.adapt              # só com o que está no cache
    uv run --env-file config/.env python -m ingest.adapt --buscar     # + busca reversa no MAL

Regras:
1. Casa o anime com o mangá pelo título (japonês, romaji ou inglês, normalizados), sem o
   sufixo de temporada ("2nd Season", "第2期"), e só se a fonte do anime for compatível
   com o tipo do mangá (mangá ↔ manga/manhwa/manhua, light novel ↔ light_novel...)
2. Se houver mais de um candidato, fica o do tipo preferido para aquela fonte
3. Anime sem par direto herda o da cadeia de sequências (Season 2 → mangá da Season 1)
4. --buscar: para cada mangá do top ainda sem adaptação, procura no MAL um anime com o
   mesmo título; os encontrados são coletados e entram em data/state/crawl_anime_ids.json.
   Depois: `ingest.load` e outra rodada deste script
"""
import argparse
import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from neo4j import GraphDatabase

log = logging.getLogger(__name__)

# Fonte do anime → tipos de mangá aceitos, do preferido para o menos preferido.
SOURCE_TYPES = {
    "manga": ["manga", "manhwa", "manhua", "one_shot", "doujinshi"],
    "web_manga": ["manga", "manhwa", "manhua", "one_shot"],
    "4_koma_manga": ["manga"],
    "light_novel": ["light_novel", "novel"],
    "novel": ["novel", "light_novel"],
    "web_novel": ["light_novel", "novel"],
}
SEASON_SUFFIX = re.compile(
    r"(\s*(\d+(st|nd|rd|th)\s+season|season\s*\d+|part\s*\d+|第\s*\d+\s*期|\d+期)\s*)+$", re.IGNORECASE)


def norm_title(title):
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title).lower()
    t = SEASON_SUFFIX.sub("", t)
    return re.sub(r"[\W_]+", "", t)


def title_keys(item):
    alt = item.get("alternative_titles") or {}
    names = [item.get("title"), alt.get("ja"), alt.get("en")]
    return {k for k in (norm_title(n) for n in names) if k}


def build_index(mangas):
    index = defaultdict(set)
    for m in mangas.values():
        for key in title_keys(m):
            index[key].add(m["id"])
    return index


def match(anime, index, mangas):
    """mal_id do mangá adaptado, ou None."""
    accepted = SOURCE_TYPES.get(anime.get("source"))
    if not accepted:
        return None
    candidates = set()
    for key in title_keys(anime):
        candidates |= index.get(key, set())
    candidates = [c for c in candidates if mangas[c].get("media_type") in accepted]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (accepted.index(mangas[c]["media_type"]), c))


def sequel_graph(animes):
    """Vizinhos por sequel/prequel nos dois sentidos (a página de um lado pode não listar o outro)."""
    graph = defaultdict(set)
    for a_id, a in animes.items():
        for r in a.get("related_anime") or []:
            if r.get("relation_type") in ("sequel", "prequel"):
                graph[a_id].add(r["node"]["id"])
                graph[r["node"]["id"]].add(a_id)
    return graph


def adaptations(animes, mangas):
    """{anime_id: (manga_id, metodo)} com casamento direto e propagação pela cadeia."""
    index = build_index(mangas)
    result = {a_id: (m_id, "titulo") for a_id, a in animes.items()
              if (m_id := match(a, index, mangas)) is not None}
    graph = sequel_graph(animes)
    changed = True
    while changed:  # espalha pela cadeia até estabilizar
        changed = False
        for a_id, a in animes.items():
            if a_id in result or a.get("source") not in SOURCE_TYPES:
                continue
            for n in sorted(graph[a_id]):
                if n in result and animes.get(n, {}).get("source") == a.get("source"):
                    result[a_id] = (result[n][0], "sequencia")
                    changed = True
                    break
    return result


def read_items(kind, state_dir="data/state", raw_dir="data/raw"):
    ids = []
    for name in (f"top_{kind}_ids.json", f"crawl_{kind}_ids.json"):
        path = Path(state_dir) / name
        if path.exists():
            ids += json.loads(path.read_text())
    items = {}
    for i in dict.fromkeys(ids):
        path = Path(raw_dir) / kind / f"{i}.json"
        if path.exists():
            items[i] = json.loads(path.read_text())
    return items


WRITE = """
UNWIND $rows AS row
MATCH (a:Anime {mal_id: row.anime}), (m:Manga {mal_id: row.manga})
MERGE (a)-[r:ADAPTED_FROM]->(m)
SET r.metodo = row.metodo
"""


def reverse_search(client, mangas, adapted_mangas, top_manga_ids):
    """Para mangás do top sem adaptação conhecida, procura um anime de mesmo título no MAL."""
    found = []
    for m_id in top_manga_ids:
        if m_id in adapted_mangas or m_id not in mangas:
            continue
        m = mangas[m_id]
        keys = title_keys(m)
        resp = client.get("/anime", {"q": m["title"][:64], "limit": 10,
                                     "fields": "alternative_titles,media_type,source"})
        for item in resp.get("data", []):
            node = item["node"]
            if title_keys(node) & keys and m.get("media_type") in SOURCE_TYPES.get(node.get("source"), []):
                found.append(node["id"])
    return list(dict.fromkeys(found))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--buscar", action="store_true", help="busca reversa no MAL (1 req por mangá)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    animes, mangas = read_items("anime"), read_items("manga")
    result = adaptations(animes, mangas)
    by_method = defaultdict(int)
    for _, metodo in result.values():
        by_method[metodo] += 1
    log.info("%d animes com fonte escrita; %d adaptações (%s)",
             sum(a.get("source") in SOURCE_TYPES for a in animes.values()), len(result), dict(by_method))

    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        rows = [{"anime": a, "manga": m, "metodo": metodo} for a, (m, metodo) in result.items()]
        driver.execute_query(WRITE, rows=rows)
        records, _, _ = driver.execute_query("MATCH ()-[r:ADAPTED_FROM]->() RETURN count(r) AS n")
        log.info("ADAPTED_FROM no grafo: %d", records[0]["n"])

    if args.buscar:
        from ingest.crawl import save_crawled
        from ingest.mal import MalClient

        from ingest.fetch import fetch_details

        client = MalClient()
        top_mangas = json.loads(Path("data/state/top_manga_ids.json").read_text())
        adapted = {m for m, _ in result.values()}
        found = [i for i in reverse_search(client, mangas, adapted, top_mangas) if i not in animes]
        log.info("busca reversa: %d animes novos", len(found))
        failures = fetch_details(client, "anime", found, Path("data/state/failed_adapt_anime.json"))
        failed = {int(f["path"].rsplit("/", 1)[1]) for f in failures}
        save_crawled("data/state", "anime", [i for i in found if i not in failed])
        log.info("rode ingest.load e este script de novo (sem --buscar) para criar as arestas")


if __name__ == "__main__":
    main()
