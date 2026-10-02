"""Pergunta em linguagem natural → Cypher → tabela.

    uv run --env-file config/.env python -m analytics "qual estúdio tem a melhor nota média?"
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from analytics.generator import generate
from analytics.llm import ChatClient
from analytics.schema import build_schema

LOG = Path("data/logs/analytics.jsonl")


def main():
    question = " ".join(sys.argv[1:])
    if not question:
        sys.exit('uso: python -m analytics "pergunta"')
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    chat = ChatClient.from_env()
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver, driver.session() as session:
        ans = generate(question, chat, session, build_schema(session))

    if ans.no_data:
        print(f"O grafo não tem essa informação: {ans.no_data}")
        return
    for i, a in enumerate(ans.attempts, 1):
        if a.error:
            print(f"tentativa {i} falhou ({a.seconds:.1f}s): {a.error}\n")
    if not ans.ok:
        sys.exit("não consegui gerar uma consulta válida")
    print(ans.cypher, "\n")
    print(" | ".join(ans.columns))
    for row in ans.rows:
        print(" | ".join(str(v) for v in row))

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({
            "quando": datetime.now().isoformat(timespec="seconds"), "modelo": chat.model,
            "pergunta": question, "cypher": ans.cypher, "linhas": len(ans.rows),
            "tentativas": [{"erro": a.error, "segundos": round(a.seconds, 1)} for a in ans.attempts],
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
