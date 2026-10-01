"""Coleta os nós esboço (fora do top) que já estão no grafo: a fronteira do crawl.

Uso:
    uv run --env-file config/.env python -m ingest.crawl anime [--limit 300] [--min-recomendacoes 2]
    uv run --env-file config/.env python -m ingest.load      # depois, para carregar

Os esboços vêm das recomendações e relações dos itens do top. Os mais conectados
são coletados primeiro. Os ids coletados ficam em data/state/crawl_<kind>_ids.json,
que o loader lê junto com o top. Um passo só: os esboços criados pelos itens
coletados agora ficam para uma próxima rodada.
"""

import argparse
import json
import logging
import os
from pathlib import Path

from neo4j import GraphDatabase

from ingest.fetch import fetch_details
from ingest.mal import MalClient

log = logging.getLogger(__name__)

LABELS = {"anime": "Anime", "manga": "Manga"}

FRONTIER = """
MATCH (n:{label} {{completo: false}})
WHERE COUNT {{ (n)-[:RECOMMENDS]-() }} >= $min_rec
RETURN n.mal_id AS mal_id
ORDER BY COUNT {{ (n)-[:RECOMMENDS|RELATED_TO]-() }} DESC, n.mal_id
"""


def frontier_ids(driver, kind, limit=None, min_rec=0):
    records, _, _ = driver.execute_query(FRONTIER.format(label=LABELS[kind]), min_rec=min_rec)
    ids = [r["mal_id"] for r in records]
    return ids[:limit] if limit else ids


def save_crawled(state_dir, kind, ids):
    """Acrescenta os ids ao estado sem perder os de rodadas anteriores."""
    path = Path(state_dir) / f"crawl_{kind}_ids.json"
    previous = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(list(dict.fromkeys(previous + ids))))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=list(LABELS))
    parser.add_argument("--limit", type=int, help="quantos esboços coletar (os mais conectados)")
    parser.add_argument("--min-recomendacoes", type=int, default=0,
                        help="só esboços com pelo menos N recomendações (deixa de fora OVAs e especiais "
                             "que só aparecem por relação)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        ids = frontier_ids(driver, args.kind, args.limit, args.min_recomendacoes)
    log.info("%s: %d esboços na fronteira", args.kind, len(ids))

    state_dir = Path("data/state")
    failures = fetch_details(MalClient(), args.kind, ids, state_dir / f"failed_crawl_{args.kind}.json")
    failed = {int(f["path"].rsplit("/", 1)[1]) for f in failures}
    save_crawled(state_dir, args.kind, [i for i in ids if i not in failed])


if __name__ == "__main__":
    main()
