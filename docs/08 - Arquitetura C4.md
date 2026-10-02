---
tags: [projeto, graphrag, arquitetura, c4]
---

# Arquitetura (modelo C4)

Voltar: [[00 - Índice GraphRAG Anime]] · Ver também: [[01 - Visão Geral]]

Três níveis do [modelo C4](https://c4model.com): contexto, contêineres e componentes. Os diagramas são Mermaid (flowchart com as cores do C4) porque o `C4Context` do Mermaid ainda é experimental e organiza mal o layout.

Legenda: 🟦 pessoa · 🟦 escuro = sistema/contêiner deste projeto · ⬜ cinza = sistema externo · 🟨 = armazenamento.

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

Os processos e armazenamentos que formam o sistema. Todos rodam no Mac; só o Neo4j fica em Docker.

```mermaid
flowchart TB
    user["👤 <b>Usuário</b>"]
    dev["👤 <b>Desenvolvedor</b>"]

    subgraph sys["GraphRAG de Animes e Mangás"]
        spa["<b>Web UI</b><br/>[HTML/JS, Cytoscape.js, Chart.js]<br/>Chat com passos ao vivo, analytics,<br/>explorador do grafo, painel de avaliação"]
        api["<b>Servidor web</b><br/>[Python, FastAPI · ui/server.py]<br/>REST + streaming dos passos do agente"]
        cli["<b>CLIs</b><br/>[Python · python -m agent / analytics]<br/>Agente e pergunta→Cypher no terminal"]
        ingest["<b>Pipeline de ingestão</b><br/>[Python · ingest/]<br/>fetch → load → crawl → embed → adapt"]
        evals["<b>Avaliação</b><br/>[Python · eval/]<br/>Mede o gerador de Cypher e o agente"]
        neo4j[("<b>Neo4j 2026.09 + APOC</b><br/>[Docker]<br/>Grafo Anime/Manga/Genre/Studio/Author<br/>+ índices vetoriais das sinopses")]
        files[("<b>data/</b><br/>[arquivos JSON/JSONL]<br/>raw/ cache da API · state/ ids e falhas<br/>logs/ perguntas · eval/ resultados")]
    end

    mal["<b>API do MyAnimeList v2</b>"]
    omlx["<b>oMLX</b><br/>gpt-oss-20b · BGE-M3"]
    claude["<b>API da Anthropic</b>"]

    user -- "usa [HTTPS/HTTP]" --> spa
    user -- "usa" --> cli
    dev -- "roda" --> ingest
    dev -- "roda" --> evals
    spa -- "chama /api/* [JSON, streaming]" --> api

    api -- "lê [Bolt, transação de leitura]" --> neo4j
    cli -- "lê [Bolt]" --> neo4j
    evals -- "lê [Bolt]" --> neo4j
    ingest -- "escreve com MERGE [Bolt]" --> neo4j

    api -- "chat, embeddings" --> omlx
    cli -- "chat, embeddings" --> omlx
    evals -- "chat, embeddings" --> omlx
    ingest -- "embeddings das sinopses" --> omlx
    api -. "opcional" .-> claude
    cli -. "opcional" .-> claude
    evals -. "opcional" .-> claude

    ingest -- "busca [HTTPS, rate limit, retries]" --> mal
    ingest -- "cache e estado" --> files
    api -- "grava logs, lê avaliações" --> files
    cli -- "grava logs" --> files
    evals -- "grava resultados" --> files

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

## Nível 3: Componentes do agente e do gerador de Cypher

O núcleo compartilhado pelo servidor web, pelas CLIs e pela avaliação: os pacotes `agent/` e `analytics/`.

```mermaid
flowchart TB
    caller["<b>Servidor web · CLIs · Avaliação</b><br/>(contêineres do nível 2)"]

    subgraph agentpkg["agent/"]
        loop["<b>Agent</b><br/>[agent/loop.py]<br/>Loop de tool use com limite de passos;<br/>registra cada passo (Step)"]
        backends["<b>Backends</b><br/>[agent/backends.py]<br/>OmlxBackend · AnthropicBackend<br/>camada fina sobre as duas APIs"]
        tools["<b>Tools</b><br/>[agent/tools.py]<br/>busca_semantica · expandir_vizinhanca<br/>· consulta_cypher; valida argumentos"]
    end

    subgraph analyticspkg["analytics/"]
        generator["<b>Gerador</b><br/>[generator.py]<br/>pergunta → Cypher com retentativas<br/>ou SEM_DADOS"]
        prompt["<b>Prompt</b><br/>[prompt.py]<br/>few-shot, convenções do schema,<br/>mensagens de erro para o modelo"]
        cypher["<b>Validação e execução</b><br/>[cypher.py, lint.py, values.py]<br/>bloqueia escrita, EXPLAIN, setas e<br/>propriedades vs. schema real, valores próximos"]
        schema["<b>Schema</b><br/>[schema.py]<br/>Lê labels, relações e propriedades<br/>do banco"]
        llm["<b>ChatClient</b><br/>[llm.py]<br/>Cliente OpenAI-compatível"]
    end

    embed["<b>EmbeddingClient</b><br/>[ingest/embeddings.py]"]

    neo4j[("<b>Neo4j</b>")]
    omlx["<b>oMLX</b>"]
    claude["<b>API da Anthropic</b>"]

    caller -- "pergunta" --> loop
    caller -- "pergunta (analytics direto)" --> generator
    loop -- "próximo turno" --> backends
    loop -- "executa chamadas de ferramenta" --> tools
    backends -- "[HTTP]" --> omlx
    backends -. "[HTTPS] opcional" .-> claude

    tools -- "busca_semantica: vetor da pergunta" --> embed
    tools -- "vizinhança, busca vetorial, franquias" --> neo4j
    tools -- "consulta_cypher" --> generator

    generator --> prompt
    prompt -- "usa" --> schema
    generator -- "gera Cypher" --> llm
    generator -- "valida e roda" --> cypher
    cypher -- "EXPLAIN + leitura com timeout" --> neo4j
    schema -- "introspecção" --> neo4j
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

### Observações
- **`consulta_cypher` sempre usa o oMLX.** Mesmo com `AGENT_BACKEND=anthropic`, só o loop do agente vai para o Claude; o gerador de Cypher continua no gpt-oss-20b local (`CYPHER_MODEL`).
- **Um modelo só na memória.** No backend local, agente e gerador usam o mesmo gpt-oss-20b, por isso o oMLX precisa do *memory guard* em `aggressive` para caber ao lado do Neo4j.
- **Escrita só na ingestão.** Servidor web, CLIs e avaliação abrem transações de leitura; apenas `ingest/` escreve no grafo, sempre com `MERGE` (idempotente).
