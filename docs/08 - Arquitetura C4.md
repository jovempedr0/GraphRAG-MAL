---
tags: [projeto, graphrag, arquitetura, c4]
---

# Arquitetura (modelo C4)

🇺🇸 [English version](08%20-%20C4%20Architecture.md)

Voltar: [00 - Índice GraphRAG Anime](00%20-%20%C3%8Dndice%20GraphRAG%20Anime.md) · Ver também: [01 - Visão Geral](01%20-%20Vis%C3%A3o%20Geral.md)

Três níveis do [modelo C4](https://c4model.com): contexto, contêineres e componentes. Os diagramas são Mermaid (flowchart com as cores do C4) porque o `C4Context` do Mermaid ainda é experimental e organiza mal o layout.

Legenda das cores:
- **azul-marinho:** pessoa;
- **azul:** o sistema (nível 1), seus contêineres (nível 2) e componentes (nível 3, azul-claro);
- **amarelo:** armazenamento (Neo4j, arquivos em `data/`);
- **cinza:** sistema externo;
- **linha tracejada:** dependência opcional.

## Nível 1: Contexto

Quem usa o sistema e de quais sistemas externos ele depende.

```mermaid
flowchart TB
    user["👤 <b>Usuário</b><br/>Faz perguntas sobre animes e mangás<br/>(recomendação, ordem de temporadas, rankings)"]
    dev["👤 <b>Desenvolvedor</b><br/>Monta o grafo, roda avaliações<br/>e ajusta prompts"]

    sys["<b>GraphRAG de Animes e Mangás</b><br/>Agente que responde consultando um<br/>grafo de conhecimento do MyAnimeList"]

    mal["<b>API do MyAnimeList v2</b><br/>Rankings, detalhes, recomendações<br/>e relações entre obras"]
    omlx["<b>oMLX</b><br/>Servidor local de modelos MLX,<br/>API compatível com OpenAI<br/>(gpt-oss-20b, BGE-M3)"]
    claude["<b>API da Anthropic</b><br/>Claude como backend opcional<br/>do agente"]
    ngrok["<b>ngrok</b><br/>Túnel com basic auth<br/>para compartilhar a UI"]

    user -- "pergunta pelo navegador ou terminal" --> sys
    dev -- "ingestão, avaliação, testes (run.sh)" --> sys
    sys -- "busca dados [HTTPS, Client ID]" --> mal
    sys -- "chat + tool use, embeddings [HTTP]" --> omlx
    sys -. "chat + tool use, opcional [HTTPS]" .-> claude
    user -. "acesso remoto, opcional" .-> ngrok
    ngrok -. "encaminha [HTTP]" .-> sys

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef system fill:#1168bd,stroke:#0b4884,color:#fff
    classDef external fill:#999,stroke:#6b6b6b,color:#fff
    class user,dev person
    class sys system
    class mal,omlx,claude,ngrok external
```

## Nível 2: Contêineres

Os processos e armazenamentos que formam o sistema. Todos rodam no Mac; só o Neo4j fica em Docker. Para caber na tela, o nível está dividido em dois diagramas: a hora da pergunta e a preparação.

### Hora da pergunta

```mermaid
flowchart LR
    user["👤 <b>Usuário</b>"]

    subgraph sys["GraphRAG de Animes e Mangás"]
        spa["<b>Web UI</b><br/>[HTML/JS]<br/>chat, analytics,<br/>explorador do grafo"]
        api["<b>Servidor web</b><br/>[FastAPI · ui/server.py]<br/>REST + streaming<br/>dos passos do agente"]
        neo4j[("<b>Neo4j + APOC</b><br/>[Docker]<br/>grafo + índices vetoriais")]
        logs[("<b>data/logs/</b><br/>[JSONL]")]
    end

    omlx["<b>oMLX</b><br/>gpt-oss-20b · BGE-M3"]
    claude["<b>API da Anthropic</b>"]

    user -- "navegador" --> spa
    spa -- "/api/*" --> api
    api -- "lê [Bolt]" --> neo4j
    api -- "grava perguntas" --> logs
    api -- "chat, embeddings" --> omlx
    api -. "opcional" .-> claude

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

As **CLIs** (`python -m agent` e `python -m analytics`) fazem o mesmo caminho do servidor web, sem a UI: usam o mesmo núcleo (nível 3), leem o Neo4j, chamam o oMLX (ou o Claude) e gravam em `data/logs/`.

### Preparação

```mermaid
flowchart LR
    dev["👤 <b>Desenvolvedor</b>"]

    subgraph sys["GraphRAG de Animes e Mangás"]
        ingest["<b>Ingestão</b><br/>[Python · ingest/]<br/>fetch → load → crawl<br/>→ embed → adapt"]
        evals["<b>Avaliação</b><br/>[Python · eval/]<br/>gerador de Cypher<br/>e agente"]
        neo4j[("<b>Neo4j + APOC</b><br/>[Docker]")]
        files[("<b>data/</b><br/>raw/ · state/ · eval/")]
    end

    mal["<b>API do MyAnimeList v2</b>"]
    omlx["<b>oMLX</b>"]

    dev -- "./run.sh dados" --> ingest
    dev -- "./run.sh eval" --> evals
    ingest -- "HTTPS, rate limit" --> mal
    ingest -- "MERGE [Bolt]" --> neo4j
    ingest -- "embeddings" --> omlx
    ingest -- "cache e estado" --> files
    evals -- "lê [Bolt]" --> neo4j
    evals -- "chat, embeddings" --> omlx
    evals -- "resultados" --> files

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

O painel de avaliação da Web UI lê os resultados em `data/eval/`.

## Nível 3: Componentes do agente e do gerador de Cypher

O núcleo compartilhado pelo servidor web, pelas CLIs e pela avaliação: os pacotes `agent/` e `analytics/`.

```mermaid
flowchart TB
    caller["<b>Servidor web · CLIs · Avaliação</b>"]

    subgraph agentpkg["agent/"]
        loop["<b>Agent</b><br/>[loop.py]<br/>loop de tool use,<br/>no máx. 8 passos"]
        backends["<b>Backends</b><br/>[backends.py]<br/>oMLX · Anthropic"]
        tools["<b>Tools</b><br/>[tools.py]<br/>busca_semantica<br/>expandir_vizinhanca<br/>consulta_cypher"]
    end

    subgraph analyticspkg["analytics/"]
        generator["<b>Gerador</b><br/>[generator.py]<br/>pergunta → Cypher,<br/>com retentativas"]
        prompt["<b>Prompt e schema</b><br/>[prompt.py, schema.py]<br/>few-shot e convenções"]
        cypher["<b>Validação</b><br/>[cypher.py, lint.py, values.py]<br/>só leitura, EXPLAIN,<br/>schema real, valores próximos"]
    end

    neo4j[("<b>Neo4j</b>")]
    omlx["<b>oMLX</b>"]
    claude["<b>API da Anthropic</b>"]

    caller --> loop
    caller -- "analytics direto" --> generator
    loop --> backends
    loop --> tools
    tools -- "consulta_cypher" --> generator
    generator --> prompt
    generator --> cypher

    backends -- "gpt-oss-20b" --> omlx
    backends -. "opcional" .-> claude
    tools -- "BGE-M3" --> omlx
    generator -- "gpt-oss-20b" --> omlx
    tools -- "vizinhança, vetores" --> neo4j
    cypher -- "EXPLAIN + leitura" --> neo4j
    prompt -- "introspecção" --> neo4j

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

### Observações
- **`consulta_cypher` sempre usa o oMLX.** Mesmo com `AGENT_BACKEND=anthropic`, só o loop do agente vai para o Claude; o gerador de Cypher continua no gpt-oss-20b local (`CYPHER_MODEL`).
- **Um modelo só na memória.** No backend local, agente e gerador usam o mesmo gpt-oss-20b, por isso o oMLX precisa do *memory guard* em `aggressive` para caber ao lado do Neo4j.
- **Escrita só na ingestão.** Servidor web, CLIs e avaliação abrem transações de leitura; apenas `ingest/` escreve no grafo, sempre com `MERGE` (idempotente).
