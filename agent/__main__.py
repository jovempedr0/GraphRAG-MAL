"""Agente GraphRAG no terminal.

    uv run --env-file config/.env python -m agent "me indica algo parecido com Monster, mas mais curto"
    uv run --env-file config/.env python -m agent          # conversa (linha vazia ou Ctrl-D sai)

AGENT_BACKEND=omlx (padrão) ou anthropic; AGENT_MODEL troca o modelo.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from agent.backends import backend_from_env
from agent.loop import Agent
from agent.tools import Tools
from analytics.llm import ChatClient
from analytics.schema import build_schema
from ingest.embeddings import EmbeddingClient

LOG = Path("data/logs/agent.jsonl")


def show_step(step):
    args = json.dumps(step.args, ensure_ascii=False) if step.args is not None else "(inválidos)"
    status = "ERRO " if step.error else ""
    print(f"  → {step.tool}({args}) {status}[{step.seconds:.1f}s, {len(step.result)} chars]", flush=True)


def log_run(backend, question, result, seconds):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({
            "quando": datetime.now().isoformat(timespec="seconds"),
            "backend": type(backend).__name__, "modelo": backend.model,
            "pergunta": question, "resposta": result.answer, "parada": result.stop,
            "segundos": round(seconds, 1), "tokens": result.tokens,
            "passos": [{"ferramenta": s.tool, "args": s.args, "erro": s.error,
                        "segundos": round(s.seconds, 1), "resultado": s.result[:2000]} for s in result.steps],
        }, ensure_ascii=False) + "\n")


def main():
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    backend = backend_from_env()
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver, driver.session() as session:
        tools = Tools(session, EmbeddingClient.from_env(), ChatClient.from_env(), build_schema(session))
        agent = Agent(backend, tools, on_step=show_step)
        print(f"[{type(backend).__name__}: {backend.model}]")

        questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else None
        while True:
            if questions is not None:
                if not questions:
                    break
                question = questions.pop()
            else:
                try:
                    question = input("\nvocê> ").strip()
                except EOFError:
                    break
                if not question:
                    break
            start = time.perf_counter()
            result = agent.ask(question)
            seconds = time.perf_counter() - start
            print(f"\n{result.answer}\n\n[{seconds:.1f}s, {len(result.steps)} chamadas, parada: {result.stop}]")
            log_run(backend, question, result, seconds)


if __name__ == "__main__":
    main()
