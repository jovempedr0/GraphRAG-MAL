---
tags: [projeto, graphrag, arquitetura, c4]
---

# Architecture (C4 model)

🇧🇷 [Versão em português](08%20-%20Arquitetura%20C4.md)

Back: [README](../README.md)

Three levels of the [C4 model](https://c4model.com): context, containers and components. The diagrams are Mermaid flowcharts with the C4 colors, because Mermaid's `C4Context` is still experimental and lays things out poorly.

Tool names (`busca_semantica`…), the `SEM_DADOS` marker and the `data/` folders keep their Portuguese names, as in the code.

Color legend:
- **navy:** person;
- **blue:** the system (level 1), its containers (level 2) and components (level 3, light blue);
- **yellow:** storage (Neo4j, files under `data/`);
- **gray:** external system;
- **dashed line:** optional dependency.

## Level 1: System context

Who uses the system and which external systems it depends on.

```mermaid
flowchart TB
    user["👤 <b>User</b><br/>Asks about anime and manga<br/>(recommendations, watch order, rankings)"]
    dev["👤 <b>Developer</b><br/>Builds the graph, runs evaluations<br/>and tunes prompts"]

    sys["<b>Anime & Manga GraphRAG</b><br/>Agent that answers by querying a<br/>knowledge graph built from MyAnimeList"]

    mal["<b>MyAnimeList API v2</b><br/>Rankings, details, recommendations<br/>and relations between works"]
    omlx["<b>oMLX</b><br/>Local MLX model server,<br/>OpenAI-compatible API<br/>(gpt-oss-20b, BGE-M3)"]
    claude["<b>Anthropic API</b><br/>Claude as an optional<br/>agent backend"]
    ngrok["<b>ngrok</b><br/>Tunnel with basic auth<br/>to share the UI"]

    user -- "asks via browser or terminal" --> sys
    dev -- "ingestion, evaluation, tests (run.sh)" --> sys
    sys -- "fetches data [HTTPS, Client ID]" --> mal
    sys -- "chat + tool use, embeddings [HTTP]" --> omlx
    sys -. "chat + tool use, optional [HTTPS]" .-> claude
    user -. "remote access, optional" .-> ngrok
    ngrok -. "forwards [HTTP]" .-> sys

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef system fill:#1168bd,stroke:#0b4884,color:#fff
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class user,dev person
    class sys system
    class mal,omlx,claude,ngrok external
```

## Level 2: Containers

The processes and stores that make up the system. Everything runs on the Mac; only Neo4j runs in Docker.

```mermaid
flowchart TB
    user["👤 <b>User</b>"]
    dev["👤 <b>Developer</b>"]

    subgraph sys["Anime & Manga GraphRAG"]
        spa["<b>Web UI</b><br/>[HTML/JS, Cytoscape.js, Chart.js]<br/>Chat with live agent steps, analytics,<br/>graph explorer, evaluation dashboard"]
        api["<b>Web server</b><br/>[Python, FastAPI · ui/server.py]<br/>REST + streaming of agent steps"]
        cli["<b>CLIs</b><br/>[Python · python -m agent / analytics]<br/>Agent and question→Cypher in the terminal"]
        ingest["<b>Ingestion pipeline</b><br/>[Python · ingest/]<br/>fetch → load → crawl → embed → adapt"]
        evals["<b>Evaluation</b><br/>[Python · eval/]<br/>Scores the Cypher generator and the agent"]
        neo4j[("<b>Neo4j 2026.09 + APOC</b><br/>[Docker]<br/>Anime/Manga/Genre/Studio/Author graph<br/>+ vector indexes over synopses")]
        files[("<b>data/</b><br/>[JSON/JSONL files]<br/>raw/ API cache · state/ ids and failures<br/>logs/ questions · eval/ results")]
    end

    mal["<b>MyAnimeList API v2</b>"]
    omlx["<b>oMLX</b><br/>gpt-oss-20b · BGE-M3"]
    claude["<b>Anthropic API</b>"]

    user -- "uses [HTTPS/HTTP]" --> spa
    user -- "uses" --> cli
    dev -- "runs" --> ingest
    dev -- "runs" --> evals
    spa -- "calls /api/* [JSON, streaming]" --> api

    api -- "reads [Bolt, read transaction]" --> neo4j
    cli -- "reads [Bolt]" --> neo4j
    evals -- "reads [Bolt]" --> neo4j
    ingest -- "writes with MERGE [Bolt]" --> neo4j

    api -- "chat, embeddings" --> omlx
    cli -- "chat, embeddings" --> omlx
    evals -- "chat, embeddings" --> omlx
    ingest -- "synopsis embeddings" --> omlx
    api -. "optional" .-> claude
    cli -. "optional" .-> claude
    evals -. "optional" .-> claude

    ingest -- "fetches [HTTPS, rate limit, retries]" --> mal
    ingest -- "cache and state" --> files
    api -- "writes logs, reads evaluations" --> files
    cli -- "writes logs" --> files
    evals -- "writes results" --> files

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef store fill:#f5c542,stroke:#b8901f,color:#000
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class user,dev person
    class spa,api,cli,ingest,evals container
    class neo4j,files store
    class mal,omlx,claude external
    style sys fill:none,stroke:#1168bd,stroke-width:2px,stroke-dasharray:5 5
```

## Level 3: Components of the agent and the Cypher generator

The core shared by the web server, the CLIs and the evaluation: the `agent/` and `analytics/` packages.

```mermaid
flowchart TB
    caller["<b>Web server · CLIs · Evaluation</b><br/>(level 2 containers)"]

    subgraph agentpkg["agent/"]
        loop["<b>Agent</b><br/>[agent/loop.py]<br/>Tool-use loop with a step limit;<br/>records every step (Step)"]
        backends["<b>Backends</b><br/>[agent/backends.py]<br/>OmlxBackend · AnthropicBackend<br/>thin layer over both APIs"]
        tools["<b>Tools</b><br/>[agent/tools.py]<br/>busca_semantica · expandir_vizinhanca<br/>· consulta_cypher; validates arguments"]
    end

    subgraph analyticspkg["analytics/"]
        generator["<b>Generator</b><br/>[generator.py]<br/>question → Cypher with retries<br/>or SEM_DADOS (no data)"]
        prompt["<b>Prompt</b><br/>[prompt.py]<br/>few-shot, schema conventions,<br/>error messages for the model"]
        cypher["<b>Validation and execution</b><br/>[cypher.py, lint.py, values.py]<br/>blocks writes, EXPLAIN, arrows and<br/>properties vs. real schema, close values"]
        schema["<b>Schema</b><br/>[schema.py]<br/>Reads labels, relationships and<br/>properties from the database"]
        llm["<b>ChatClient</b><br/>[llm.py]<br/>OpenAI-compatible client"]
    end

    embed["<b>EmbeddingClient</b><br/>[ingest/embeddings.py]"]

    neo4j[("<b>Neo4j</b>")]
    omlx["<b>oMLX</b>"]
    claude["<b>Anthropic API</b>"]

    caller -- "question" --> loop
    caller -- "question (analytics directly)" --> generator
    loop -- "next turn" --> backends
    loop -- "runs tool calls" --> tools
    backends -- "[HTTP]" --> omlx
    backends -. "[HTTPS] optional" .-> claude

    tools -- "busca_semantica: query vector" --> embed
    tools -- "neighborhood, vector search, franchises" --> neo4j
    tools -- "consulta_cypher" --> generator

    generator --> prompt
    prompt -- "uses" --> schema
    generator -- "writes Cypher" --> llm
    generator -- "validates and runs" --> cypher
    cypher -- "EXPLAIN + read with timeout" --> neo4j
    schema -- "introspection" --> neo4j
    llm -- "gpt-oss-20b [HTTP]" --> omlx
    embed -- "BGE-M3 [HTTP]" --> omlx

    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef store fill:#f5c542,stroke:#b8901f,color:#000
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class caller container
    class loop,backends,tools,generator,prompt,cypher,schema,llm,embed component
    class neo4j store
    class omlx,claude external
    style agentpkg fill:none,stroke:#438dd5,stroke-dasharray:5 5
    style analyticspkg fill:none,stroke:#438dd5,stroke-dasharray:5 5
```

### Notes
- **`consulta_cypher` always uses oMLX.** Even with `AGENT_BACKEND=anthropic`, only the agent loop goes to Claude; the Cypher generator stays on the local gpt-oss-20b (`CYPHER_MODEL`).
- **One model in memory.** With the local backend, the agent and the generator share the same gpt-oss-20b, which is why oMLX's *memory guard* must be `aggressive` to fit next to Neo4j.
- **Only ingestion writes.** The web server, CLIs and evaluation open read transactions; only `ingest/` writes to the graph, always with `MERGE` (idempotent).
