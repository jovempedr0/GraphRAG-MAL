# GraphRAG de Animes e Mangás

🇺🇸 [English version](README.md)

Um agente que recomenda e explica animes e mangás consultando um **grafo de conhecimento** montado a partir do MyAnimeList. Projeto de estudo de programação agêntica: ingestão de dados, modelagem em grafo, text-to-Cypher e um agente com tool use, rodando com **modelos locais** num Mac.

> [!IMPORTANT]
> **Os prompts são parte do sistema avaliado.** O prompt do agente, o do gerador, os exemplos e as convenções do schema foram ajustados medindo contra os conjuntos de avaliação, e mudanças pequenas no prompt já alteraram os resultados (veja *Avaliação*). Traduzir para outro idioma ou reescrever os prompts exige **rodar as duas avaliações de novo** antes de confiar nos números deste README.

```
"Me indica algo parecido com Monster, mas mais curto"
   → expandir_vizinhanca("Monster")   recomendações dos usuários, com votos e episódios
   → resposta: Psycho-Pass (22 ep.), Pluto (8 ep.)…, citando os números do grafo
```

## Como funciona

```
API do MyAnimeList (v2)
   │  ingest/   coleta com rate limit, retry e cache em disco; crawl da fronteira
   ▼
Neo4j  ── grafo: Anime, Manga, Genre, Studio, Author
   │       RECOMMENDS (com votos), RELATED_TO (sequências...), ADAPTED_FROM, ...
   │       + índice vetorial com embeddings das sinopses
   ▲
   │  analytics/  pergunta → Cypher validado → tabela
   │  agent/      loop de tool use com 3 ferramentas
   ▼
CLI  ·  interface web (ui/)  ·  avaliação automática (eval/)
```

**As três ferramentas do agente**

| Ferramenta | Para quê |
|---|---|
| `busca_semantica` | assunto, clima ou enredo ("anime sobre luto"); busca vetorial nas sinopses, um resultado por franquia |
| `expandir_vizinhanca` | um título citado: recomendações, obras relacionadas, cadeia de temporadas, segundo grau |
| `consulta_cypher` | filtros, contagens, rankings; gera o Cypher com um LLM, valida e executa |

**O gerador de Cypher** valida cada consulta antes de executar:
- bloqueia escrita e executa só em transação de leitura, com timeout;
- usa `EXPLAIN` para pegar erro de sintaxe e label ou propriedade inexistente;
- compara a consulta com o schema real do banco, para pegar setas invertidas ou propriedade no lugar errado (`o.votos` em vez de `r.votos`);
- confere no banco os valores literais da consulta e sugere os parecidos ("Frieren" → "Sousou no Frieren", "Movie" → "movie").

Quando alguma checagem falha, o erro volta para o modelo corrigir.

Se a pergunta pede algo que o grafo não guarda (bilheteria, personagens, episódios filler), o gerador responde `SEM_DADOS` em vez de escrever uma consulta. Sem essa regra, o gpt-oss chegou a responder uma pergunta sobre bilheteria com `RETURN a.popularidade AS bilheteria`: a posição no ranking de popularidade, numa coluna chamada "bilheteria".

## Stack

| Camada | Escolha |
|---|---|
| Linguagem | Python 3.13, [uv](https://docs.astral.sh/uv/) |
| Banco | Neo4j 2026.09 Community + APOC (Docker), índice vetorial nativo |
| Dados | API oficial do MyAnimeList v2 (só Client ID) |
| LLM local | oMLX, servidor local de modelos MLX (API compatível com OpenAI), com **gpt-oss-20b** (`gpt-oss-20b-MXFP4-Q8`) |
| Embeddings | BGE-M3 (`bge-m3-mlx-fp16`) via oMLX |
| LLM na nuvem (opcional) | Claude via SDK `anthropic` (`claude-opus-5-5`) |
| Interface | FastAPI + HTML/JS (Cytoscape.js, Chart.js) |

Testado num MacBook M5 Pro com 24 GB. O gpt-oss-20b ocupa ~12 GB; para ele rodar junto com o Neo4j, o *memory guard* do oMLX precisa estar em `aggressive`. Em `balanced`, o servidor recusa o prompt com HTTP 400 `prefill_memory_exceeded`.

## Instalação

```bash
uv sync
cp config/.env.example config/.env      # preencha MAL_CLIENT_ID, NEO4J_PASSWORD, OMLX_API_KEY
```

- **MAL_CLIENT_ID:** crie em https://myanimelist.net/apiconfig (App Type: *other*).
- **oMLX:** baixe os modelos `gpt-oss-20b-MXFP4-Q8` e `bge-m3-mlx-fp16` (mlx-community, no Hugging Face) para `~/.omlx/models/`.

Subir o Neo4j e criar o schema:

```bash
docker compose --env-file config/.env up -d
docker compose --env-file config/.env exec neo4j sh -c \
  'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" -f /schema/constraints.cypher'
```

## Montando o grafo

Todos os comandos usam `uv run --env-file config/.env`, abreviado abaixo como `$R`.

```bash
R="uv run --env-file config/.env"
$R python -m ingest.fetch anime --limit 500     # top 500 → data/raw (cache; pode reexecutar)
$R python -m ingest.fetch manga --limit 500
$R python -m ingest.load                        # JSON → Neo4j (idempotente, MERGE)
$R python -m ingest.crawl anime --min-recomendacoes 2   # opcional: coleta a fronteira
$R python -m ingest.crawl manga
$R python -m ingest.load
$R python -m ingest.embed                       # embeddings das sinopses + índices vetoriais
$R python -m ingest.adapt --buscar              # ADAPTED_FROM; depois: load e adapt de novo
```

- **`top` e `completo` são coisas diferentes.** `top` marca os 500 do ranking. `completo` diz se o nó tem os detalhes. Obras citadas por recomendações ou relações entram como **esboço** (`completo = false`), só com o título, até serem coletadas pelo `ingest.crawl`.
- **`ADAPTED_FROM` vem de casamento de títulos.** A API do MAL não traz a relação anime → mangá, então o vínculo é feito pelo título japonês, romaji ou inglês. O tipo da fonte desempata os candidatos, e a relação se propaga pela cadeia de sequências.

**Grafo atual (2026-10-01)**, depois de um crawl da fronteira e de uma segunda rodada para os esboços mais conectados:

| | Anime | Mangá |
|---|---|---|
| Com todos os detalhes (`completo`) | 2.954 (500 `top`) | 2.735 (500 `top`) |
| Esboços | 4.312 | 3.594 |

23.757 `RECOMMENDS`, 7.664 `RELATED_TO`, 892 `ADAPTED_FROM`, 2.861 autores, 346 estúdios e 80 gêneros.

## Uso

**Agente no terminal**
```bash
$R python -m agent "Em que ordem eu assisto Attack on Titan?"
$R python -m agent                              # modo conversa
AGENT_BACKEND=anthropic $R python -m agent "…"  # com o Claude (precisa de ANTHROPIC_API_KEY)
```

**Pergunta → Cypher → tabela**
```bash
$R python -m analytics "Qual estúdio tem a maior nota média entre os que têm pelo menos 10 animes no top?"
```

**Interface web**: chat com os passos do agente em tempo real, analytics com Cypher editável, exploração visual do grafo e painel das avaliações.
```bash
$R uvicorn ui.server:app --port 8765            # http://localhost:8765
```
A interface não tem login. Para compartilhar, use um túnel com autenticação, por exemplo `ngrok http 8765 --basic-auth "usuario:senha"`.

Os logs de cada pergunta ficam em `data/logs/` (`agent.jsonl`, `analytics.jsonl`).

## Avaliação

```bash
$R python -m eval.run gpt-oss-20b-MXFP4-Q8 [outro-modelo...] [--perguntas eval/questions_novas.json]
$R python -m eval.agent_run [--only A1,A4]
```

- **Gerador de Cypher** (`eval/questions.json`, `eval/questions_novas.json`): compara o **resultado** com o de uma consulta de referência, e não o texto do Cypher. As linhas são comparadas sem ordem, colunas extras são aceitas e os números têm tolerância.
- **Agente** (`eval/agent_questions.json`): a correção é automática, sem LLM como juiz:
  - usou a ferramenta esperada;
  - citou os títulos que a referência devolve;
  - incluiu os textos obrigatórios;
  - **não citou nenhuma nota que não esteja nos resultados das ferramentas**, o que mede diretamente a alucinação.

  Inclui perguntas sem resposta no grafo e continuações de conversa.

Os resultados ficam em `data/eval/*.jsonl` e aparecem na aba **Avaliação** da interface.

**Resultados atuais (gpt-oss-20b, depois do crawl, 2026-10-01)**

| Avaliação | Resultado | Mediana |
|---|---|---|
| Gerador de Cypher | **24/27** (13/15 no primeiro conjunto, 11/12 no segundo) | ~8 s |
| Agente | **15/15**; ferramenta certa 15/15; **0 respostas com nota sem fonte** | ~10 s |

**O grafo ajuda? Mesmo modelo e mesmas perguntas, com ferramentas diferentes**

| Config | Ferramentas | Passou | Respostas com nota sem fonte |
|---|---|---|---|
| A, só LLM | nenhuma | 1/15 | 12/15 |
| B, RAG vetorial | só `busca_semantica` | 5/15 | 0/15 |
| **C, GraphRAG** | as três | **15/15** | **0/15** |

- **A** sabe o assunto e inventa os números. Inventou a bilheteria do filme de Chainsaw Man com uma fonte falsa, deu a Frieren 12 episódios e nota 8,0 (no grafo: 28 e 9,25) e pôs Berserk entre os mangás "sem anime". Mesmo com 16 mil tokens de saída, o gpt-oss às vezes raciocinou até o limite e não respondeu nada.
- **B** é honesto, mas não acha título pela sinopse ("parecido com Monster" trouxe *Gogo Monster*). Sem as arestas, não responde sobre autor, ordem de temporadas, interseções nem filtros.
- Para rodar: `python -m eval.agent_run --config A|B|C` (A com `--max-tokens 16384`). C usa o prompt do agente sem mudança.

**Comparação de modelos no gerador de Cypher (antes do crawl)**

| Modelo (local, oMLX) | Acertos (27 perguntas) | Mediana |
|---|---|---|
| **gpt-oss-20b** | **26/27** | ~5 s |
| Qwen3-14B | 20/27 | ~3 s |
| Qwen3.6-35B-A3B-REAP-19B ¹ | 8/15 | ~2 s |
| text2cypher Gemma-3-4B (Neo4j) ¹ | 7/15 | ~3 s |

¹ avaliados só nas 15 perguntas antigas.

O que as avaliações ensinaram:
- **Corrigir no código ajudou mais do que mexer no prompt.** As checagens contra o schema e contra os valores do banco fizeram a diferença. Listar os valores categóricos no prompt chegou a **piorar** o gpt-oss.
- **Os resultados oscilam com mudanças pequenas no prompt.** A regra do `SEM_DADOS` corrigiu uma pergunta e quebrou outra: a E16, da cadeia de sequências, é a mais sensível. São rodadas únicas com temperatura 0, e uma pergunta vale de 4 a 7 pontos.
- **Mais dados também mudam as perguntas.** Depois do crawl, algumas referências quebraram: animes que ainda não estrearam, sem nota, foram para o topo da ordenação, e um limiar ficou baixo demais. A lista das 15 recomendações com mais votos deixou de responder "recomendados para X e para Y ao mesmo tempo", e essas perguntas passaram a ir para `consulta_cypher`.

Os detalhes estão em `docs/07 - Gerador de Cypher.md` e `docs/04 - Agente GraphRAG.md`.

## Estrutura

```
ingest/      cliente MAL, coleta, crawl, carga no Neo4j, embeddings, ADAPTED_FROM
schema/      constraints e índices
analytics/   gerador de Cypher: schema, prompt, validação, checagens, comparação de resultados
agent/       backends (oMLX / Claude), ferramentas, loop, CLI
ui/          servidor FastAPI e página web
eval/        perguntas e scripts de avaliação
tests/       pytest (uv run pytest)
docs/        notas do projeto (visão geral, modelo do grafo, roadmap, decisões)
data/        cache da API, estado, logs e resultados (fora do git)
```

## Limitações conhecidas

- Os dados vêm só do top 500 e da vizinhança coletada. Obras fora disso aparecem como esboço, sem nota nem gêneros.
- `ADAPTED_FROM` é heurístico: pode faltar adaptação, e casos raros podem casar errado. "Adaptado de light novel" pode ser respondido pela propriedade `fonte` do anime ou pelo `ADAPTED_FROM`, e os dois dão contagens diferentes (55 contra 42 no top 500).
- A busca vetorial com o BGE-M3 dá scores muito próximos entre si (0,72–0,79). Só a ordem do ranking tem valor.
- Os modelos locais tendem a completar de memória quando falta dado no resultado da ferramenta. O que mais ajudou foi completar o resultado da ferramenta, mais do que reforçar instruções no prompt.
- O backend do Claude tem testes unitários com cliente falso, mas ainda não foi rodado com credencial real.
