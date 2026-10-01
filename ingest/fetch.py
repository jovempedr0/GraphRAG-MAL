"""Coleta o top N de animes/mangás da API do MAL e grava o JSON bruto em data/raw.

Uso:
    uv run --env-file config/.env python -m ingest.fetch anime --limit 500
    uv run --env-file config/.env python -m ingest.fetch manga --limit 500

Pode ser reexecutado à vontade: o que já está no cache não gera requisição,
e o que falhou da última vez é tentado de novo.
"""

import argparse
import json
import logging
from pathlib import Path

from ingest.mal import MalClient, MalError

log = logging.getLogger(__name__)

RANKING_PAGE_SIZE = 500  # máximo aceito pelo endpoint de ranking

COMMON_FIELDS = [
    "id", "title", "alternative_titles", "synopsis", "mean", "rank", "popularity",
    "num_scoring_users", "num_list_users", "media_type", "status", "genres",
    "start_date", "related_anime", "related_manga", "recommendations",
]
FIELDS = {
    "anime": COMMON_FIELDS + ["num_episodes", "start_season", "source", "studios"],
    "manga": COMMON_FIELDS + ["num_chapters", "num_volumes", "authors{first_name,last_name}", "serialization"],
}


def top_ids(client, kind, limit):
    ids, offset = [], 0
    while len(ids) < limit:
        resp = client.get(
            f"/{kind}/ranking",
            {"ranking_type": "all", "limit": min(RANKING_PAGE_SIZE, limit), "offset": offset},
        )
        ids.extend(item["node"]["id"] for item in resp["data"])
        if not resp.get("paging", {}).get("next"):
            break
        offset += len(resp["data"])
    return list(dict.fromkeys(ids))[:limit]


def fetch_top(client, kind, limit, state_dir="data/state"):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    ids = top_ids(client, kind, limit)
    (state_dir / f"top_{kind}_ids.json").write_text(json.dumps(ids))
    fetch_details(client, kind, ids, state_dir / f"failed_{kind}.json")
    return ids


def fetch_details(client, kind, ids, failed_path):
    """Busca o detalhe de cada id (o cache evita repetir) e grava as falhas em failed_path."""
    fields = ",".join(FIELDS[kind])
    failures = []
    for n, mal_id in enumerate(ids, 1):
        path = f"/{kind}/{mal_id}"
        try:
            client.get(path, {"fields": fields})
        except MalError as e:
            log.error("falhou: %s", e)
            failures.append({"path": path, "status": e.status})
        if n % 25 == 0:
            log.info("%s: %d/%d", kind, n, len(ids))

    Path(failed_path).write_text(json.dumps(failures, indent=2))
    log.info("%s: %d itens, %d falhas", kind, len(ids), len(failures))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["anime", "manga"])
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    fetch_top(MalClient(), args.kind, args.limit)


if __name__ == "__main__":
    main()
