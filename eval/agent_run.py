"""Avalia o agente com as perguntas de eval/agent_questions.json.

    uv run --env-file config/.env python -m eval.agent_run [--only A1,A4]

O backend vem de AGENT_BACKEND (omlx | anthropic). Cada pergunta roda numa conversa nova.
Critérios (todos automáticos):
- ferramenta: chamou pelo menos uma das ferramentas esperadas (lista vazia: qualquer uma ou nenhuma)
- cobertura: fração dos títulos esperados (calculados por Cypher na hora) citados na resposta
- deve_conter / deve_conter_algum: textos obrigatórios (números comparados com vírgula ou ponto)
- notas sem fonte: decimais da resposta que não aparecem em nenhum resultado de ferramenta

"antes" (opcional): perguntas feitas antes, na mesma conversa, para testar continuações.
"""
import argparse
import json
import logging
import math
import os
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from agent.backends import backend_from_env
from agent.loop import Agent
from agent.tools import Tools
from analytics.answer_checks import mentions, normalize_text, ungrounded_decimals
from analytics.llm import ChatClient
from analytics.schema import build_schema
from ingest.embeddings import EmbeddingClient

QUESTIONS = Path(__file__).parent / "agent_questions.json"
OUT_DIR = Path("data/eval")


def expected_names(session, q):
    if not q.get("esperados"):
        return []
    return [[v for v in row if v] for row in session.run(q["esperados"]).values()]


def contains(answer, text):
    norm = normalize_text(answer)
    variants = {text, text.replace(".", ","), text.replace(",", ".")}
    return any(normalize_text(v) in norm for v in variants)


def grade(q, answer, steps, expected):
    tools_used = {s.tool for s in steps}
    tool_ok = not q["ferramentas"] or bool(tools_used & set(q["ferramentas"]))

    found = [names[0] for names in expected if mentions(answer, names)]
    if expected:
        minimum = q.get("min_esperados", 1)
        needed = math.ceil(minimum * len(expected)) if isinstance(minimum, float) else min(minimum, len(expected))
        coverage_ok = len(found) >= needed
    else:
        needed, coverage_ok = 0, True

    must = all(contains(answer, t) for t in q.get("deve_conter", []))
    any_of = q.get("deve_conter_algum")
    must = must and (not any_of or any(contains(answer, t) for t in any_of))

    ungrounded = ungrounded_decimals(answer, [s.result for s in steps])
    passed = tool_ok and coverage_ok and must and not ungrounded
    return {"passou": passed, "ferramenta_ok": tool_ok, "cobertura": f"{len(found)}/{len(expected)}",
            "cobertura_ok": coverage_ok, "minimo": needed, "conteudo_ok": must,
            "notas_sem_fonte": ungrounded, "ferramentas_usadas": sorted(tools_used),
            "faltaram": [names[0] for names in expected if names[0] not in found]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="ids separados por vírgula, ex.: A1,A4")
    args = parser.parse_args()
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    questions = json.loads(QUESTIONS.read_text())
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only.split(","))]

    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with driver, driver.session() as session:
        schema = build_schema(session)
        embedder, cypher_chat = EmbeddingClient.from_env(), ChatClient.from_env()
        results = []
        model = None
        for q in questions:
            backend = backend_from_env()
            model = backend.model
            agent = Agent(backend, Tools(session, embedder, cypher_chat, schema))
            earlier_steps = []
            for previous in q.get("antes", []):
                earlier_steps += agent.ask(previous).steps
            start = time.perf_counter()
            result = agent.ask(q["pergunta"])
            seconds = time.perf_counter() - start
            # Números podem vir de resultados de ferramenta de turnos anteriores da conversa
            g = grade(q, result.answer, earlier_steps + result.steps, expected_names(session, q))
            if q.get("antes"):
                g["ferramentas_usadas"] = sorted({s.tool for s in result.steps})
            results.append({"id": q["id"], "categoria": q["categoria"], "pergunta": q["pergunta"],
                            **g, "passos": len(result.steps), "segundos": round(seconds, 1),
                            "tokens": result.tokens, "parada": result.stop, "resposta": result.answer,
                            "chamadas": [{"ferramenta": s.tool, "args": s.args, "erro": s.error}
                                         for s in result.steps]})
            mark = "✅" if g["passou"] else "❌"
            detail = [] if g["passou"] else [k for k in ("ferramenta_ok", "cobertura_ok", "conteudo_ok")
                                               if not g[k]] + (["notas_sem_fonte"] if g["notas_sem_fonte"] else [])
            print(f"  {mark} {q['id']:<4} {g['cobertura']:>5} {len(result.steps)} passos "
                  f"{seconds:5.1f}s {' '.join(detail)}", flush=True)

    out = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-agente-{model}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in results))
    n = len(results)
    secs = sorted(r["segundos"] for r in results)
    print(f"\n{model}: {sum(r['passou'] for r in results)}/{n} passaram | ferramenta certa "
          f"{sum(r['ferramenta_ok'] for r in results)}/{n} | com notas sem fonte "
          f"{sum(bool(r['notas_sem_fonte']) for r in results)}/{n} | mediana {secs[n // 2]:.1f}s\n→ {out}")


if __name__ == "__main__":
    main()
