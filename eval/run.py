"""Avalia o gerador de Cypher com as perguntas de eval/questions.json.

    uv run --env-file config/.env python -m eval.run MODELO [MODELO ...] [--only E1,E8]
        [--perguntas eval/questions_novas.json]

Para cada modelo: gera o Cypher (com validação e retry), executa, compara com a referência
e grava os detalhes em data/eval/<data>-<modelo>.jsonl.
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from analytics.evaluation import same_result
from analytics.generator import generate
from analytics.llm import ChatClient
from analytics.schema import build_schema

QUESTIONS = Path(__file__).parent / "questions.json"
OUT_DIR = Path("data/eval")


def evaluate(model, questions, session, schema, reference):
    chat = ChatClient.from_env(model)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{stamp}-{model}.jsonl"
    results = []
    with out.open("w") as f:
        for q in questions:
            start = time.perf_counter()
            ans = generate(q["pergunta"], chat, session, schema)
            seconds = time.perf_counter() - start
            correct = ans.ok and same_result(reference[q["id"]], ans.rows)
            res = {
                "id": q["id"], "pergunta": q["pergunta"], "correto": correct, "executou": ans.ok,
                "tentativas": len(ans.attempts), "segundos": round(seconds, 1), "tokens": ans.tokens,
                "cypher": ans.cypher, "linhas": ans.rows[:20],
                "erros": [a.error for a in ans.attempts if a.error],
                "respostas": [a.raw for a in ans.attempts],
            }
            f.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
            f.flush()
            results.append(res)
            mark = "✅" if correct else ("⚠️ " if ans.ok else "❌")
            print(f"  {mark} {q['id']:<4} {len(ans.attempts)} tent. {seconds:5.1f}s", flush=True)
    return results, out


def summary_line(model, results):
    n = len(results)
    ok = sum(r["correto"] for r in results)
    ran = sum(r["executou"] for r in results)
    first = sum(r["correto"] and r["tentativas"] == 1 for r in results)
    secs = sorted(r["segundos"] for r in results)
    return (f"| {model} | {ok}/{n} ({ok / n:.0%}) | {first} | {ran}/{n} | "
            f"{sum(r['tentativas'] for r in results) / n:.1f} | {secs[n // 2]:.1f}s | {sum(secs):.0f}s |")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+")
    parser.add_argument("--only", help="ids separados por vírgula, ex.: E1,E8")
    parser.add_argument("--perguntas", type=Path, default=QUESTIONS, help="arquivo de perguntas")
    args = parser.parse_args()
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    questions = json.loads(args.perguntas.read_text())
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver, driver.session() as session:
        schema = build_schema(session)
        reference = {q["id"]: session.run(q["cypher"]).values() for q in questions}
        lines = []
        for model in args.models:
            print(f"\n== {model}", flush=True)
            results, out = evaluate(model, questions, session, schema, reference)
            print(f"  → {out}")
            lines.append(summary_line(model, results))

    print("\n| Modelo | Corretas | De primeira | Executou | Tentativas (média) | Mediana | Total |")
    print("|---|---|---|---|---|---|---|")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
