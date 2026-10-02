# Anime & Manga GraphRAG

🇧🇷 [Versão em português](README.pt-BR.md)

An agent that recommends and explains anime and manga by querying a **knowledge graph** built from MyAnimeList. It is a study project in agentic programming: data ingestion, graph modeling, text-to-Cypher and a tool-using agent, all running on **local models** on a Mac.

> [!IMPORTANT]
> **This project is written in Brazilian Portuguese.** The README is in English, but everything else is in Portuguese:
> - the code comments, the web UI and the design notes in `docs/`;
> - the tool names (`busca_semantica`, `consulta_cypher`…) and the graph's property names (`titulo`, `nota`, `episodios`…);
> - the LLM prompts, the evaluation questions and the agent's answers.
>
> **Translating the prompts is not a cosmetic change.** The prompts, the few-shot examples and the schema conventions were tuned by measuring them against the evaluation sets, and small prompt changes have already shifted the results (see *Evaluation*). If you translate them, translate the evaluation questions too and **re-run both evaluations** before trusting the numbers in this README.

```
"Me indica algo parecido com Monster, mas mais curto"   (something like Monster, but shorter)
   → expandir_vizinhanca("Monster")   user recommendations, with vote counts and episodes
   → answer: Psycho-Pass (22 eps.), Pluto (8 eps.)…, quoting the numbers from the graph
```

## How it works

```
MyAnimeList API (v2)
   │  ingest/   rate-limited fetching with retries and a disk cache; frontier crawl
   ▼
Neo4j  ── graph: Anime, Manga, Genre, Studio, Author
   │       RECOMMENDS (with votes), RELATED_TO (sequels...), ADAPTED_FROM, ...
   │       + vector index over synopsis embeddings
   ▲
   │  analytics/  question → validated Cypher → table
   │  agent/      tool-use loop with 3 tools
   ▼
CLI  ·  web UI (ui/)  ·  automatic evaluation (eval/)
```

**The agent's three tools**

| Tool | Purpose |
|---|---|
| `busca_semantica` (semantic search) | topic, mood or plot ("an anime about grief"); vector search over synopses, one result per franchise |
| `expandir_vizinhanca` (expand neighborhood) | a named title: recommendations, related works, full season order, second-degree neighbors |
| `consulta_cypher` (Cypher query) | filters, counts, rankings; an LLM writes the Cypher, which is validated and executed |

**The Cypher generator** validates every query before running it:
- blocks writes and runs only in a read transaction with a timeout;
- uses `EXPLAIN` to catch syntax errors and unknown labels or properties;
- checks the query against the real database schema to catch reversed arrows and properties on the wrong element (`o.votos` instead of `r.votos`);
- looks up the query's literal values in the database and suggests close matches ("Frieren" → "Sousou no Frieren", "Movie" → "movie").

When a check fails, the error goes back to the model so it can fix the query.

If the question asks for something the graph does not store (box office, characters, filler episodes), the generator answers `SEM_DADOS` ("no data") instead of writing a query. Without this rule, gpt-oss once answered a box-office question with `RETURN a.popularidade AS bilheteria`, which put the popularity rank in a column named "box office".

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.13, [uv](https://docs.astral.sh/uv/) |
| Database | Neo4j 2026.09 Community + APOC (Docker), native vector index |
| Data | Official MyAnimeList API v2 (Client ID only) |
| Local LLM | oMLX, a local MLX model server with an OpenAI-compatible API, running **gpt-oss-20b** (`gpt-oss-20b-MXFP4-Q8`) |
| Embeddings | BGE-M3 (`bge-m3-mlx-fp16`) via oMLX |
| Cloud LLM (optional) | Claude via the `anthropic` SDK (`claude-opus-5-5`) |
| UI | FastAPI + HTML/JS (Cytoscape.js, Chart.js) |

Tested on a MacBook M5 Pro with 24 GB. gpt-oss-20b takes about 12 GB. For it to run next to Neo4j, oMLX's *memory guard* must be set to `aggressive`. On `balanced`, the server rejects the prompt with HTTP 400 `prefill_memory_exceeded`.

## Setup

```bash
uv sync
cp config/.env.example config/.env      # fill in MAL_CLIENT_ID, NEO4J_PASSWORD, OMLX_API_KEY
```

- **MAL_CLIENT_ID:** create one at https://myanimelist.net/apiconfig (App Type: *other*).
- **oMLX:** download `gpt-oss-20b-MXFP4-Q8` and `bge-m3-mlx-fp16` (mlx-community, on Hugging Face) into `~/.omlx/models/`.

Start Neo4j and create the schema:

```bash
docker compose --env-file config/.env up -d
docker compose --env-file config/.env exec neo4j sh -c \
  'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" -f /schema/constraints.cypher'
```

## Building the graph

Every command runs with `uv run --env-file config/.env`, shortened to `$R` below.

```bash
R="uv run --env-file config/.env"
$R python -m ingest.fetch anime --limit 500     # top 500 → data/raw (cached; safe to rerun)
$R python -m ingest.fetch manga --limit 500
$R python -m ingest.load                        # JSON → Neo4j (idempotent, MERGE)
$R python -m ingest.crawl anime --min-recomendacoes 2   # optional: crawl the frontier
$R python -m ingest.crawl manga
$R python -m ingest.load
$R python -m ingest.embed                       # synopsis embeddings + vector indexes
$R python -m ingest.adapt --buscar              # ADAPTED_FROM; then run load and adapt again
```

- **`top` and `completo` mean different things.** `top` marks the 500 ranked items of each kind. `completo` says whether the node has full details. Works that only show up in recommendations or relations are stored as **sketch** nodes (`completo = false`) with just a title, until `ingest.crawl` fetches them.
- **`ADAPTED_FROM` comes from title matching.** The MAL API does not return anime → manga relations, so the link is made by matching Japanese, romaji or English titles. The anime's source type breaks ties between candidates, and the relation is propagated along sequel chains.

**Current graph (2026-10-01)**, after one crawl of the frontier and a second round for the best-connected sketches:

| | Anime | Manga |
|---|---|---|
| With full details (`completo`) | 2,954 (500 `top`) | 2,735 (500 `top`) |
| Sketch nodes | 4,312 | 3,594 |

23,757 `RECOMMENDS`, 7,664 `RELATED_TO`, 892 `ADAPTED_FROM`, 2,861 authors, 346 studios and 80 genres.

## Usage

**Agent in the terminal**
```bash
$R python -m agent "Em que ordem eu assisto Attack on Titan?"
$R python -m agent                              # chat mode
AGENT_BACKEND=anthropic $R python -m agent "…"  # with Claude (needs ANTHROPIC_API_KEY)
```

**Question → Cypher → table**
```bash
$R python -m analytics "Qual estúdio tem a maior nota média entre os que têm pelo menos 10 animes no top?"
```

**Web UI**: chat that shows each agent step live, analytics with editable Cypher, a visual graph explorer and an evaluation dashboard.
```bash
$R uvicorn ui.server:app --port 8765            # http://localhost:8765
```
The UI has no login. To share it, use a tunnel with authentication, e.g. `ngrok http 8765 --basic-auth "user:password"`.

Every question is logged to `data/logs/` (`agent.jsonl`, `analytics.jsonl`).

## Evaluation

```bash
$R python -m eval.run gpt-oss-20b-MXFP4-Q8 [other-model...] [--perguntas eval/questions_novas.json]
$R python -m eval.agent_run [--only A1,A4]
```

- **Cypher generator** (`eval/questions.json`, `eval/questions_novas.json`): compares the **result** with the result of a reference query, not the Cypher text. Rows are compared regardless of order, extra columns are accepted and numbers have a tolerance.
- **Agent** (`eval/agent_questions.json`): graded automatically, with no LLM judge. Each answer is checked for:
  - using an expected tool;
  - mentioning the titles the reference query returns;
  - containing the required text;
  - **quoting no score that is absent from the tool results**, which measures hallucination directly.

  The set also includes questions the graph cannot answer and follow-up questions within a conversation.

Results are written to `data/eval/*.jsonl` and shown in the **Avaliação** tab of the UI.

**Current results (gpt-oss-20b, after the crawl, 2026-10-01)**

| Evaluation | Result | Median |
|---|---|---|
| Cypher generator | **24/27** (13/15 first set, 11/12 second set) | ~8 s |
| Agent | **15/15**; right tool 15/15; **0 answers with an ungrounded score** | ~10 s |

**Does the graph help? Same model, same questions, different tools**

| Config | Tools | Passed | Answers quoting an ungrounded score |
|---|---|---|---|
| A, LLM only | none | 1/15 | 12/15 |
| B, vector RAG | `busca_semantica` only | 5/15 | 0/15 |
| **C, GraphRAG** | all three | **15/15** | **0/15** |

- **A** knows the topic but invents the numbers. It made up a box-office figure for the Chainsaw Man movie and cited a fake source, gave Frieren 12 episodes and an 8.0 score (the graph has 28 and 9.25), and listed Berserk among manga "without an anime". Even with a 16k output budget, gpt-oss sometimes reasoned until the limit and returned nothing.
- **B** stays honest but cannot find titles by synopsis ("similar to Monster" returned *Gogo Monster*). Without the edges, it cannot answer questions about authors, season order, intersections or filters.
- Run with `python -m eval.agent_run --config A|B|C` (A with `--max-tokens 16384`). C uses the agent's prompt unchanged.

**Model comparison for the Cypher generator (before the crawl)**

| Model (local, oMLX) | Correct (27 questions) | Median |
|---|---|---|
| **gpt-oss-20b** | **26/27** | ~5 s |
| Qwen3-14B | 20/27 | ~3 s |
| Qwen3.6-35B-A3B-REAP-19B ¹ | 8/15 | ~2 s |
| Neo4j text2cypher Gemma-3-4B ¹ | 7/15 | ~3 s |

¹ evaluated on the first 15 questions only.

What the evaluations taught:
- **Fixing things in code helped more than the prompt.** The checks against the schema and against database values made the difference. Listing categorical values in the prompt actually made gpt-oss **worse**.
- **Results move with small prompt changes.** Adding the `SEM_DADOS` rule fixed one question and broke another: E16, the sequel chain, is the most sensitive. These are single runs at temperature 0, and one question is worth 4–7 points.
- **More data changes the questions too.** After the crawl, some references broke: unreleased anime without a score sorted first, and a threshold became too low. The agent's top-15 recommendation list could no longer answer "recommended for both X and Y", so those questions now go to `consulta_cypher`.

Details (in Portuguese) are in `docs/07 - Gerador de Cypher.md` and `docs/04 - Agente GraphRAG.md`.

## Layout

```
ingest/      MAL client, fetching, crawl, Neo4j loading, embeddings, ADAPTED_FROM
schema/      constraints and indexes
analytics/   Cypher generator: schema, prompt, validation, checks, result comparison
agent/       backends (oMLX / Claude), tools, loop, CLI
ui/          FastAPI server and web page
eval/        questions and evaluation scripts
tests/       pytest (uv run pytest)
docs/        project notes, in Portuguese (overview, graph model, roadmap, decisions)
data/        API cache, state, logs and results (not in git)
```

## Known limitations

- The data covers only the top 500 and the crawled neighborhood. Anything outside it is a sketch node, with no score or genres.
- `ADAPTED_FROM` is heuristic: some adaptations are missing, and rare cases may be matched wrongly. "Adapted from a light novel" can be answered from the anime's `fonte` property or from `ADAPTED_FROM`, and the two give different counts (55 vs. 42 for the top 500).
- Vector search with BGE-M3 produces very close scores (0.72–0.79). Only the ranking order is meaningful.
- Local models tend to fill gaps from memory when a tool result lacks data. Completing the tool result helped more than adding instructions to the prompt.
- The Claude backend has unit tests with a fake client but has not yet been run with real credentials.
