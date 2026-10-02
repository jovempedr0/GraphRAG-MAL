"""Interface web local: chat com o agente, analytics em Cypher, exploração do grafo e avaliações.

    uv run --env-file config/.env uvicorn ui.server:app --port 8765
    → http://localhost:8765
"""
import json
import logging
import os
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
from pydantic import BaseModel

from agent.__main__ import log_run
from agent.backends import AnthropicBackend, OmlxBackend
from agent.loop import Agent
from agent.tools import Tools
from analytics.cypher import CypherError, prepare_and_run
from analytics.generator import generate
from analytics.llm import ChatClient
from analytics.schema import build_schema
from ingest.embeddings import EmbeddingClient

STATIC = Path(__file__).parent / "static"
EVAL_DIR = Path("data/eval")
STATE_DIR = Path("data/state")
MAX_ROWS = 500

state = {}
conversations = {}  # id -> {"agent": Agent, "lock": Lock, "backend": str}


@asynccontextmanager
async def lifespan(app):
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    state["driver"] = driver
    with driver.session() as s:
        state["schema"] = build_schema(s)
    state["embedder"] = EmbeddingClient.from_env()
    state["cypher_chat"] = ChatClient.from_env()
    yield
    driver.close()


app = FastAPI(title="GraphRAG Anime", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def as_json(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False, default=str), status_code=status,
                    media_type="application/json")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# --- status ------------------------------------------------------------------------

@app.get("/api/status")
def status():
    with state["driver"].session() as s:
        nodes = s.run("""
            MATCH (n) WHERE n:Anime OR n:Manga
            RETURN labels(n)[0] AS label, count(*) AS total,
                   sum(CASE WHEN n.top THEN 1 ELSE 0 END) AS top,
                   sum(CASE WHEN n.completo THEN 1 ELSE 0 END) AS completos
            ORDER BY label""").data()
        rels = s.run("MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS total ORDER BY tipo").data()
    crawl = {}
    for kind in ("anime", "manga"):
        path = STATE_DIR / f"crawl_{kind}_ids.json"
        crawl[kind] = len(json.loads(path.read_text())) if path.exists() else 0
    try:
        resp = httpx.get(f"{os.environ['OMLX_BASE_URL']}/models", timeout=5,
                         headers={"Authorization": f"Bearer {os.environ['OMLX_API_KEY']}"})
        models = [m["id"] for m in resp.json()["data"]]
    except Exception as e:  # o oMLX pode estar fechado; a página só avisa
        models = {"erro": str(e)}
    return as_json({"nos": nodes, "relacoes": rels, "crawl_coletados": crawl, "modelos_omlx": models,
                    "cypher_model": os.environ.get("CYPHER_MODEL"),
                    "agent_backend": os.environ.get("AGENT_BACKEND", "omlx"),
                    "anthropic_configurado": bool(os.environ.get("ANTHROPIC_API_KEY"))})


# --- chat --------------------------------------------------------------------------

class ChatIn(BaseModel):
    mensagem: str
    conversa: str | None = None
    backend: str = "omlx"


def new_agent(backend_name):
    backend = AnthropicBackend.from_env() if backend_name == "anthropic" else OmlxBackend.from_env()
    tools = Tools(None, state["embedder"], state["cypher_chat"], state["schema"])
    return Agent(backend, tools)


@app.post("/api/chat")
def chat(body: ChatIn):
    conv_id = body.conversa or str(uuid.uuid4())
    events = queue.Queue()

    def run():
        try:
            conv = conversations.get(conv_id)
            if conv is None or conv["backend"] != body.backend:
                conv = {"agent": new_agent(body.backend), "lock": threading.Lock(), "backend": body.backend}
                conversations[conv_id] = conv
            agent = conv["agent"]
            with conv["lock"], state["driver"].session() as session:
                agent.tools.session = session
                agent.on_step = lambda st: events.put({
                    "tipo": "passo", "ferramenta": st.tool, "args": st.args, "erro": st.error,
                    "segundos": round(st.seconds, 2), "resultado": st.result[:6000]})
                start = time.perf_counter()
                result = agent.ask(body.mensagem)
                seconds = time.perf_counter() - start
            log_run(agent.backend, body.mensagem, result, seconds)
            events.put({"tipo": "resposta", "texto": result.answer, "parada": result.stop,
                        "segundos": round(seconds, 1), "tokens": result.tokens,
                        "modelo": agent.backend.model})
        except Exception as e:
            events.put({"tipo": "erro", "mensagem": f"{type(e).__name__}: {e}"})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        yield f"data: {json.dumps({'tipo': 'inicio', 'conversa': conv_id})}\n\n"
        while (event := events.get()) is not None:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.delete("/api/chat/{conv_id}")
def end_chat(conv_id: str):
    conversations.pop(conv_id, None)
    return {"ok": True}


# --- analytics ---------------------------------------------------------------------

class PerguntaIn(BaseModel):
    pergunta: str


class CypherIn(BaseModel):
    cypher: str


@app.post("/api/cypher")
def cypher_from_question(body: PerguntaIn):
    start = time.perf_counter()
    with state["driver"].session() as s:
        ans = generate(body.pergunta, state["cypher_chat"], s, state["schema"])
    return as_json({
        "ok": ans.ok, "sem_dados": ans.no_data, "cypher": ans.cypher, "colunas": ans.columns, "linhas": ans.rows[:MAX_ROWS],
        "total_linhas": len(ans.rows), "tokens": ans.tokens, "segundos": round(time.perf_counter() - start, 1),
        "modelo": state["cypher_chat"].model,
        "tentativas": [{"resposta": a.raw, "erro": a.error, "segundos": round(a.seconds, 1)}
                       for a in ans.attempts]})


@app.post("/api/cypher/executar")
def run_cypher(body: CypherIn):
    """Executa um Cypher escrito à mão, com as mesmas proteções (só leitura, checagens, LIMIT)."""
    start = time.perf_counter()
    with state["driver"].session() as s:
        try:
            cypher, columns, rows = prepare_and_run(s, body.cypher, state["schema"])
        except CypherError as e:
            return as_json({"ok": False, "erro": str(e)}, status=400)
    return as_json({"ok": True, "cypher": cypher, "colunas": columns, "linhas": rows[:MAX_ROWS],
                    "total_linhas": len(rows), "segundos": round(time.perf_counter() - start, 2)})


# --- grafo -------------------------------------------------------------------------

LABELS = {"Anime", "Manga", "Studio", "Author"}


@app.get("/api/grafo/busca")
def search(q: str, limite: int = 12):
    with state["driver"].session() as s:
        rows = s.run("""
            CALL () {
              MATCH (n) WHERE (n:Anime OR n:Manga)
                AND (toLower(n.titulo) CONTAINS toLower($q) OR toLower(coalesce(n.titulo_en, '')) CONTAINS toLower($q))
              RETURN labels(n)[0] AS label, n.mal_id AS mal_id, n.titulo AS titulo, n.titulo_en AS titulo_en,
                     n.nota AS nota, n.top AS top, n.completo AS completo, coalesce(n.membros, 0) AS pop
              UNION
              MATCH (n) WHERE (n:Studio OR n:Author) AND toLower(n.nome) CONTAINS toLower($q)
              RETURN labels(n)[0] AS label, n.mal_id AS mal_id, n.nome AS titulo, null AS titulo_en,
                     null AS nota, null AS top, true AS completo, 1000000000 AS pop
            }
            RETURN label, mal_id, titulo, titulo_en, nota, top, completo
            ORDER BY pop DESC LIMIT $limite""", q=q, limite=limite).data()
    return as_json(rows)


NODE_FIELDS = """labels(o)[0] AS label, o.mal_id AS mal_id, coalesce(o.titulo, o.nome) AS titulo,
                 o.nota AS nota, o.top AS top, o.completo AS completo"""


@app.get("/api/grafo/no/{label}/{mal_id}")
def node(label: str, mal_id: int):
    if label not in LABELS:
        raise HTTPException(404, "label desconhecido")
    with state["driver"].session() as s:
        record = s.run(f"MATCH (n:{label} {{mal_id: $id}}) RETURN n", id=mal_id).single()
        if record is None:
            raise HTTPException(404, "nó não encontrado")
        props = {k: v for k, v in dict(record["n"]).items() if not k.startswith("embedding")}
        props["generos"] = s.run(f"MATCH (:{label} {{mal_id: $id}})-[:HAS_GENRE]->(g) RETURN g.nome ORDER BY g.nome",
                                 id=mal_id).value()
        if label in ("Studio", "Author"):
            rel = "PRODUCED_BY" if label == "Studio" else "WRITTEN_BY"
            edges = s.run(f"""
                MATCH (n:{label} {{mal_id: $id}})<-[r:{rel}]-(o)
                RETURN {NODE_FIELDS}, type(r) AS tipo, null AS detalhe, 'entrada' AS sentido
                ORDER BY o.top DESC, o.nota DESC LIMIT 40""", id=mal_id).data()
        else:
            edges = s.run(f"""
                MATCH (n:{label} {{mal_id: $id}})
                CALL (n) {{
                  MATCH (n)-[r:RECOMMENDS]-(o)
                  RETURN o, r, r.votos AS detalhe, 'ambos' AS sentido ORDER BY r.votos DESC LIMIT 20
                  UNION
                  MATCH (n)-[r:RELATED_TO]-(o)
                  RETURN o, r, r.tipo AS detalhe,
                         CASE WHEN startNode(r) = n THEN 'saida' ELSE 'entrada' END AS sentido LIMIT 30
                  UNION
                  MATCH (n)-[r:ADAPTED_FROM|PRODUCED_BY|WRITTEN_BY]-(o)
                  RETURN o, r, coalesce(r.metodo, r.papel) AS detalhe,
                         CASE WHEN startNode(r) = n THEN 'saida' ELSE 'entrada' END AS sentido
                }}
                RETURN {NODE_FIELDS}, type(r) AS tipo, detalhe, sentido""", id=mal_id).data()
    return as_json({"label": label, "props": props, "arestas": edges})


# --- avaliações ----------------------------------------------------------------------

def summarize(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    agent = "-agente-" in path.name
    stamp, rest = path.name[:15], path.stem[16:]
    ok = sum(bool(r.get("passou") if agent else r.get("correto")) for r in rows)
    ids = [r["id"] for r in rows]
    conjunto = ("agente" if agent else
                "novas" if all(i.startswith("N") for i in ids) else
                "antigas" if all(i.startswith("E") for i in ids) else "misto")
    secs = sorted(r.get("segundos", 0) for r in rows) or [0]
    return {"nome": path.name, "tipo": "agente" if agent else "gerador", "conjunto": conjunto,
            "modelo": agent_model(rest) if agent else rest, "quando": stamp, "acertos": ok, "total": len(rows),
            "mediana_s": secs[len(secs) // 2]}


def agent_model(rest):
    """agente-gpt-oss… (GraphRAG, config C) ou agente-A-gpt-oss… / agente-B-… (só LLM, RAG vetorial)."""
    rest = rest.removeprefix("agente-")
    config, _, model = rest.partition("-")
    names = {"A": "só LLM", "B": "RAG vetorial"}
    return f"{model} · {names[config]}" if config in names else rest


@app.get("/api/avaliacoes")
def evaluations():
    files = sorted(EVAL_DIR.glob("*.jsonl"), reverse=True) if EVAL_DIR.exists() else []
    return as_json([summarize(f) for f in files])


@app.get("/api/avaliacoes/{nome}")
def evaluation(nome: str):
    path = EVAL_DIR / nome
    if path.parent != EVAL_DIR or not path.exists():
        raise HTTPException(404, "avaliação não encontrada")
    return as_json({"resumo": summarize(path),
                    "linhas": [json.loads(l) for l in path.read_text().splitlines() if l.strip()]})
