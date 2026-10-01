"""Gera embeddings das sinopses e grava no Neo4j, com índice vetorial.

Uso:
    uv run --env-file config/.env python -m ingest.embed
    uv run --env-file config/.env python -m ingest.embed --buscar "médico perseguindo um assassino"

Só processa nós completos com sinopse que ainda não têm embedding do modelo atual
(n.embedding_modelo). Trocar EMBEDDING_MODEL e rodar de novo recalcula tudo.
"""

import argparse
import logging
import os

from neo4j import GraphDatabase

from ingest.embeddings import EmbeddingClient

log = logging.getLogger(__name__)

LABELS = ["Anime", "Manga"]
WRITE_BATCH = 64

PENDING = """
MATCH (n:{label} {{completo: true}})
WHERE n.sinopse IS NOT NULL
  AND (n.embedding IS NULL OR n.embedding_modelo <> $model)
RETURN n.mal_id AS mal_id, n.titulo AS titulo, n.titulo_en AS titulo_en, n.sinopse AS sinopse,
       [(n)-[:HAS_GENRE]->(g) | g.nome] AS generos
"""

WRITE = """
UNWIND $rows AS row
MATCH (n:{label} {{mal_id: row.mal_id}})
CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)
SET n.embedding_modelo = $model
"""

# Dimensão no nome do índice: um modelo com outra dimensão ganha um índice novo
# em vez de conflitar com o antigo.
INDEX = """
CREATE VECTOR INDEX {name} IF NOT EXISTS
FOR (n:{label}) ON n.embedding
OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}
"""

SEARCH = """
CALL db.index.vector.queryNodes($index, $k, $vector) YIELD node, score
RETURN node.titulo AS titulo, node.nota AS nota, round(score, 3) AS score
"""


def index_name(label, dim):
    return f"{label.lower()}_embedding_{dim}"


def embedding_text(node):
    titulo = node["titulo"]
    if node.get("titulo_en") and node["titulo_en"] != titulo:
        titulo += f" ({node['titulo_en']})"
    parts = [titulo]
    if node["generos"]:
        parts.append("Gêneros: " + ", ".join(node["generos"]))
    return "\n".join(parts) + "\n\n" + node["sinopse"]


def embed_label(driver, client, label):
    records, _, _ = driver.execute_query(PENDING.format(label=label), model=client.model)
    if not records:
        log.info("%s: nada pendente", label)
        return None

    nodes = [r.data() for r in records]
    vectors = client.embed_documents([embedding_text(n) for n in nodes])
    rows = [{"mal_id": n["mal_id"], "embedding": v} for n, v in zip(nodes, vectors)]
    for i in range(0, len(rows), WRITE_BATCH):
        driver.execute_query(WRITE.format(label=label), rows=rows[i:i + WRITE_BATCH], model=client.model)

    dim = len(vectors[0])
    driver.execute_query(INDEX.format(name=index_name(label, dim), label=label, dim=dim))
    log.info("%s: %d embeddings (dim %d)", label, len(rows), dim)
    return dim


def search(driver, client, text, label="Anime", k=5):
    vector = client.embed_query(text)
    records, _, _ = driver.execute_query(
        SEARCH, index=index_name(label, len(vector)), k=k, vector=vector
    )
    return [r.data() for r in records]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--buscar", help="testa a busca semântica com este texto")
    parser.add_argument("--label", choices=LABELS, default="Anime")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Avisos de "propriedade não existe" na primeira execução, antes de haver embeddings
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    client = EmbeddingClient.from_env()
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        if args.buscar:
            for r in search(driver, client, args.buscar, args.label):
                print(f"{r['score']:.3f}  {r['titulo']}  (nota {r['nota']})")
            return
        for label in LABELS:
            embed_label(driver, client, label)


if __name__ == "__main__":
    main()
