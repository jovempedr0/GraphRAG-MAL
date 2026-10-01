"""Carrega o JSON bruto de data/raw no Neo4j (idempotente: tudo via MERGE).

Uso:
    uv run --env-file config/.env python -m ingest.load

Itens recomendados que não estão no top entram como nós "esboço"
(só mal_id e titulo, completo = false). Se depois forem coletados, viram completos.

RECOMMENDS é guardado num sentido só, do menor mal_id para o maior: o MAL
lista o mesmo par nas duas páginas, e nas consultas a direção é ignorada
com (a)-[:RECOMMENDS]-(b).

RELATED_TO (continuações, histórias paralelas...) também fica com uma aresta por par:
(a)-[:RELATED_TO {tipo}]->(b) significa "b é <tipo> de a". Tipos inversos são
normalizados (prequel → sequel invertido) e tipos simétricos vão do menor mal_id
para o maior.
"""

import json
import logging
import os
import re
from pathlib import Path

from neo4j import GraphDatabase

log = logging.getLogger(__name__)

BATCH_SIZE = 100
CREDITS = re.compile(r"\s*(\[Written by [^\]]*\]|\(Source: [^)]*\))\s*$")


def clean_synopsis(text):
    if not text:
        return None
    return CREDITS.sub("", text).strip() or None


def count(d, key):
    # O MAL usa 0 para "desconhecido" (ainda em exibição/publicação)
    return d.get(key) or None


def year(d):
    season_year = (d.get("start_season") or {}).get("year")
    if season_year:
        return season_year
    start = d.get("start_date")
    return int(start[:4]) if start else None


# tipo na página do item → tipo equivalente visto do outro lado
INVERSE_TYPES = {"prequel": "sequel", "parent_story": "side_story", "full_story": "summary"}
SYMMETRIC_TYPES = {"alternative_version", "alternative_setting", "character", "other"}


def related(mal_id, relations):
    out = []
    for r in relations:
        other, tipo = r["node"]["id"], r["relation_type"]
        if tipo in INVERSE_TYPES:
            tipo, saida = INVERSE_TYPES[tipo], False
        elif tipo in SYMMETRIC_TYPES:
            saida = mal_id < other
        else:
            saida = True
        out.append({"mal_id": other, "titulo": r["node"]["title"], "tipo": tipo, "saida": saida})
    return out


def common_row(d):
    return {
        "mal_id": d["id"],
        "props": {
            "titulo": d["title"],
            "titulo_en": (d.get("alternative_titles") or {}).get("en") or None,
            "sinopse": clean_synopsis(d.get("synopsis")),
            "nota": d.get("mean"),
            "rank": d.get("rank"),
            "popularidade": d.get("popularity"),
            "membros": d.get("num_list_users"),
            "tipo": d.get("media_type"),
            "status": d.get("status"),
            "ano": year(d),
        },
        "generos": [g["name"] for g in d.get("genres", [])],
        "recomendacoes": [
            {"mal_id": r["node"]["id"], "titulo": r["node"]["title"], "votos": r["num_recommendations"]}
            for r in d.get("recommendations", [])
        ],
    }


def anime_row(d):
    row = common_row(d)
    row["props"]["episodios"] = count(d, "num_episodes")
    row["props"]["fonte"] = d.get("source")
    row["estudios"] = [{"mal_id": s["id"], "nome": s["name"]} for s in d.get("studios", [])]
    row["relacionados"] = related(d["id"], d.get("related_anime", []))
    return row


def manga_row(d):
    row = common_row(d)
    row["props"]["capitulos"] = count(d, "num_chapters")
    row["props"]["volumes"] = count(d, "num_volumes")
    row["autores"] = [
        {
            "mal_id": a["node"]["id"],
            "nome": " ".join(filter(None, [a["node"].get("first_name"), a["node"].get("last_name")])),
            "papel": a.get("role"),
        }
        for a in d.get("authors", [])
    ]
    row["relacionados"] = related(d["id"], d.get("related_manga", []))
    return row


# Parte comum: nó principal, gêneros e recomendações. {label} é Anime ou Manga.
BASE_QUERY = """
UNWIND $rows AS row
MERGE (n:{label} {{mal_id: row.mal_id}})
SET n += row.props, n.completo = true
WITH n, row
CALL (n, row) {{
  UNWIND row.generos AS nome
  MERGE (g:Genre {{nome: nome}})
  MERGE (n)-[:HAS_GENRE]->(g)
}}
CALL (n, row) {{
  UNWIND row.recomendacoes AS rec
  MERGE (o:{label} {{mal_id: rec.mal_id}})
    ON CREATE SET o.titulo = rec.titulo, o.completo = false
  WITH CASE WHEN n.mal_id < o.mal_id THEN [n, o] ELSE [o, n] END AS par, rec
  WITH par[0] AS origem, par[1] AS destino, rec
  MERGE (origem)-[r:RECOMMENDS]->(destino)
  SET r.votos = rec.votos
}}
CALL (n, row) {{
  UNWIND row.relacionados AS rel
  MERGE (o:{label} {{mal_id: rel.mal_id}})
    ON CREATE SET o.titulo = rel.titulo, o.completo = false
  WITH CASE WHEN rel.saida THEN [n, o] ELSE [o, n] END AS par, rel
  WITH par[0] AS origem, par[1] AS destino, rel
  MERGE (origem)-[:RELATED_TO {{tipo: rel.tipo}}]->(destino)
}}
"""

ANIME_EXTRA = """
UNWIND $rows AS row
MATCH (n:Anime {mal_id: row.mal_id})
UNWIND row.estudios AS e
MERGE (s:Studio {mal_id: e.mal_id}) SET s.nome = e.nome
MERGE (n)-[:PRODUCED_BY]->(s)
"""

MANGA_EXTRA = """
UNWIND $rows AS row
MATCH (n:Manga {mal_id: row.mal_id})
UNWIND row.autores AS a
MERGE (p:Author {mal_id: a.mal_id}) SET p.nome = a.nome
MERGE (n)-[w:WRITTEN_BY]->(p) SET w.papel = a.papel
"""

KINDS = {
    "anime": ("Anime", anime_row, ANIME_EXTRA),
    "manga": ("Manga", manga_row, MANGA_EXTRA),
}


def read_rows(kind, raw_dir="data/raw", state_dir="data/state"):
    _, to_row, _ = KINDS[kind]
    ids = json.loads((Path(state_dir) / f"top_{kind}_ids.json").read_text())
    rows, missing = [], []
    for mal_id in ids:
        path = Path(raw_dir) / kind / f"{mal_id}.json"
        if path.exists():
            rows.append(to_row(json.loads(path.read_text())))
        else:
            missing.append(mal_id)
    if missing:
        log.warning("%s: %d ids sem JSON em cache (rode o fetch de novo): %s", kind, len(missing), missing[:10])
    return rows


def load(driver, kind, rows):
    label, _, extra = KINDS[kind]
    base = BASE_QUERY.format(label=label)
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        driver.execute_query(base, rows=batch)
        driver.execute_query(extra, rows=batch)
    log.info("%s: %d itens carregados", kind, len(rows))


COUNTS = """
CALL () { MATCH (n) RETURN labels(n)[0] AS tipo, count(*) AS total
          UNION ALL
          MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS total }
RETURN tipo, total ORDER BY tipo
"""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        driver.verify_connectivity()
        for kind in KINDS:
            load(driver, kind, read_rows(kind))
        records, _, _ = driver.execute_query(COUNTS)
        for r in records:
            log.info("  %-12s %6d", r["tipo"], r["total"])


if __name__ == "__main__":
    main()
