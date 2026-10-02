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

The processes and stores that make up the system. Everything runs on the Mac; only Neo4j runs in Docker. To fit on screen, this level is split into two diagrams: question time and preparation.

### Question time

```mermaid
flowchart LR
    user["👤 <b>User</b>"]

    subgraph sys["Anime & Manga GraphRAG"]
        spa["<b>Web UI</b><br/>[HTML/JS]<br/>chat, analytics,<br/>graph explorer"]
        api["<b>Web server</b><br/>[FastAPI · ui/server.py]<br/>REST + streaming<br/>of agent steps"]
        neo4j[("<b>Neo4j + APOC</b><br/>[Docker]<br/>graph + vector indexes")]
        logs[("<b>data/logs/</b><br/>[JSONL]")]
    end

    omlx["<b>oMLX</b><br/>gpt-oss-20b · BGE-M3"]
    claude["<b>Anthropic API</b>"]

    user -- "browser" --> spa
    spa -- "/api/*" --> api
    api -- "reads [Bolt]" --> neo4j
    api -- "logs questions" --> logs
    api -- "chat, embeddings" --> omlx
    api -. "optional" .-> claude

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef store fill:#f5c542,stroke:#b8901f,color:#000
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class user person
    class spa,api container
    class neo4j,logs store
    class omlx,claude external
    style sys fill:none,stroke:#1168bd,stroke-width:2px,stroke-dasharray:5 5
```

The **CLIs** (`python -m agent` and `python -m analytics`) take the same path as the web server, without the UI: they use the same core (level 3), read Neo4j, call oMLX (or Claude) and write to `data/logs/`.

### Preparation

```mermaid
flowchart LR
    dev["👤 <b>Developer</b>"]

    subgraph sys["Anime & Manga GraphRAG"]
        ingest["<b>Ingestion</b><br/>[Python · ingest/]<br/>fetch → load → crawl<br/>→ embed → adapt"]
        evals["<b>Evaluation</b><br/>[Python · eval/]<br/>Cypher generator<br/>and agent"]
        neo4j[("<b>Neo4j + APOC</b><br/>[Docker]")]
        files[("<b>data/</b><br/>raw/ · state/ · eval/")]
    end

    mal["<b>MyAnimeList API v2</b>"]
    omlx["<b>oMLX</b>"]

    dev -- "./run.sh dados" --> ingest
    dev -- "./run.sh eval" --> evals
    ingest -- "HTTPS, rate limit" --> mal
    ingest -- "MERGE [Bolt]" --> neo4j
    ingest -- "embeddings" --> omlx
    ingest -- "cache and state" --> files
    evals -- "reads [Bolt]" --> neo4j
    evals -- "chat, embeddings" --> omlx
    evals -- "results" --> files

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef store fill:#f5c542,stroke:#b8901f,color:#000
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class dev person
    class ingest,evals container
    class neo4j,files store
    class mal,omlx external
    style sys fill:none,stroke:#1168bd,stroke-width:2px,stroke-dasharray:5 5
```

The Web UI's evaluation dashboard reads the results in `data/eval/`.

## Level 3: Components of the agent and the Cypher generator

The core shared by the web server, the CLIs and the evaluation: the `agent/` and `analytics/` packages.

```mermaid
flowchart TB
    caller["<b>Web server · CLIs · Evaluation</b>"]

    subgraph agentpkg["agent/"]
        loop["<b>Agent</b><br/>[loop.py]<br/>tool-use loop,<br/>at most 8 steps"]
        backends["<b>Backends</b><br/>[backends.py]<br/>oMLX · Anthropic"]
        tools["<b>Tools</b><br/>[tools.py]<br/>busca_semantica<br/>expandir_vizinhanca<br/>consulta_cypher"]
    end

    subgraph analyticspkg["analytics/"]
        generator["<b>Generator</b><br/>[generator.py]<br/>question → Cypher,<br/>with retries"]
        prompt["<b>Prompt and schema</b><br/>[prompt.py, schema.py]<br/>few-shot and conventions"]
        cypher["<b>Validation</b><br/>[cypher.py, lint.py, values.py]<br/>read-only, EXPLAIN,<br/>real schema, close values"]
    end

    neo4j[("<b>Neo4j</b>")]
    omlx["<b>oMLX</b>"]
    claude["<b>Anthropic API</b>"]

    caller --> loop
    caller -- "analytics directly" --> generator
    loop --> backends
    loop --> tools
    tools -- "consulta_cypher" --> generator
    generator --> prompt
    generator --> cypher

    backends -- "gpt-oss-20b" --> omlx
    backends -. "optional" .-> claude
    tools -- "BGE-M3" --> omlx
    generator -- "gpt-oss-20b" --> omlx
    tools -- "neighborhood, vectors" --> neo4j
    cypher -- "EXPLAIN + read" --> neo4j
    prompt -- "introspection" --> neo4j

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef store fill:#f5c542,stroke:#b8901f,color:#000
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class caller container
    class loop,backends,tools,generator,prompt,cypher component
    class neo4j store
    class omlx,claude external
    style agentpkg fill:none,stroke:#438dd5,stroke-dasharray:5 5
    style analyticspkg fill:none,stroke:#438dd5,stroke-dasharray:5 5
```

### Notes
- **`consulta_cypher` always uses oMLX.** Even with `AGENT_BACKEND=anthropic`, only the agent loop goes to Claude; the Cypher generator stays on the local gpt-oss-20b (`CYPHER_MODEL`).
- **One model in memory.** With the local backend, the agent and the generator share the same gpt-oss-20b, which is why oMLX's *memory guard* must be `aggressive` to fit next to Neo4j.
- **Only ingestion writes.** The web server, CLIs and evaluation open read transactions; only `ingest/` writes to the graph, always with `MERGE` (idempotent).
