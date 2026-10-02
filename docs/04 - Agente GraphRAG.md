---
tags: [projeto, graphrag, agentes, tool-use]
---

# Agente GraphRAG

Voltar: [[00 - Índice GraphRAG Anime]] · Anterior: [[07 - Gerador de Cypher]] · Próxima: [[05 - Roadmap e Avaliação]]

## Ideia
O agente (tool use, em Python) decide qual ferramenta chamar, junta o contexto vindo do grafo e responde. Em vez de um pipeline fixo, o modelo escolhe o caminho.

**Modelo (decisão de 2026-10-01): backend trocável.** `AGENT_BACKEND=omlx|anthropic`, com uma camada fina sobre as duas APIs de tool use. Começa pelo local (**gpt-oss-20b**, o mesmo do gerador de Cypher, então um modelo só na memória). O Claude entra depois como comparação na avaliação ([[05 - Roadmap e Avaliação]]).
- A favor do local: grátis, offline, um modelo só nos 24 GB
- Contra: agentes locais se perdem mais no loop (ferramenta errada, chamadas repetidas) e cada passo leva ~7 s. Por isso o loop precisa de limite de passos e checagem dos argumentos

## Preparação (etapa 5 ✅)
- Modelo: **BGE-M3** (`bge-m3-mlx-fp16`) servido localmente pelo **oMLX** (`/v1/embeddings`, API compatível com OpenAI). 1024 dimensões, multilíngue, licença MIT
- O modelo vem da variável `EMBEDDING_MODEL` em `config/.env`; ao trocar e rodar `ingest.embed` de novo, os embeddings são recalculados (`n.embedding_modelo`)
- Texto embutido: título (+ título em inglês) + gêneros + sinopse
- Índices `anime_embedding_1024` e `manga_embedding_1024` (cosseno); busca com `db.index.vector.queryNodes`
- Testar: `uv run --env-file config/.env python -m ingest.embed --buscar "time de vôlei do ensino médio"`

### Observações dos testes
- Perguntas em PT contra sinopses em EN funcionam bem: "banda de garotas" → Girls Band Cry, Bocchi the Rock!; "luto e perda" → Hotaru no Haka; "vôlei" → Haikyuu!!
- **Scores comprimidos:** o Neo4j devolve `(1 + cos) / 2`, e no BGE-M3 tudo cai entre ~0,72 e 0,79. **Não dá para usar um corte fixo** de relevância; só a ordem do ranking tem valor
- No mini-teste contra o Jina v5 (já instalado no oMLX), o Jina separou melhor o relevante do irrelevante e foi ~10x mais rápido. Vale comparar de novo na avaliação
- **Franquias repetidas:** "vôlei" devolve 5 itens de Haikyuu. A ferramenta `busca_semantica` deve agrupar por franquia via `RELATED_TO`, um exemplo de grafo + vetor trabalhando juntos
- A busca vetorial sozinha às vezes erra o principal: "pirata de borracha" deixa One Piece em 2º, atrás de Kaiji. O reranker multilíngue (`mmarco-mMiniLMv2`, já no cache) pode ajudar

## Ferramentas do agente
| Ferramenta | Função |
|---|---|
| `busca_semantica(texto)` | acha nós de entrada pela similaridade da sinopse |
| `expandir_vizinhanca(id, hops)` | percorre recomendações, gêneros, estúdio, adaptações |
| `consulta_cypher(pergunta)` | perguntas estruturadas (filtros, ranking, agregações, analytics); chama `analytics.generator.generate` de [[07 - Gerador de Cypher]] |

## Loop do agente
```
pergunta → modelo decide ferramenta → executa → resultado volta ao modelo
        → (repete até ter contexto suficiente) → resposta final com justificativa
```

## Implementação v1 (2026-10-01)
```
uv run --env-file config/.env python -m agent "me indica algo parecido com Monster, mas mais curto"
uv run --env-file config/.env python -m agent      # conversa
```
| Arquivo | Papel |
|---|---|
| `agent/backends.py` | `OmlxBackend` (API OpenAI do oMLX) e `AnthropicBackend` (SDK oficial, `claude-opus-5-5`, fallback de recusa `fallbacks: "default"`); cada um guarda o histórico no formato nativo, só por append |
| `agent/tools.py` | as três ferramentas, validação de argumentos, resultado em JSON sem nulos (máx. 10 mil caracteres) |
| `agent/loop.py` | prompt de sistema e loop: até 8 passos, chamadas repetidas não reexecutam, no limite pede a resposta sem ferramentas |
| `agent/__main__.py` | CLI; log de cada pergunta em `data/logs/agent.jsonl` |

Detalhes das ferramentas:
- `busca_semantica`: um resultado por franquia (agrupa por `RELATED_TO` até 6 saltos; com 3, os filmes de Haikyuu escapavam)
- `expandir_vizinhanca`: resolve o título em romaji ou inglês ("Attack on Titan" → Shingeki no Kyojin) e devolve recomendações, relacionados, a **cadeia de sequências completa** e, com `saltos=2`, o segundo grau. As recomendações vêm cortadas nas 15 com mais votos; quando há mais, o campo `recomendacoes_obs` diz "mostrando as 15 com mais votos de N"
- `consulta_cypher`: chama o gerador da nota 07; recusa SQL/Cypher no argumento (o gpt-oss chegou a mandar `SELECT ... FROM Anime`). Se o gerador responder `SEM_DADOS`, devolve `{"sem_dados": motivo}`

**Primeiros testes com o gpt-oss-20b** (4 perguntas, 8–23 s cada): escolhe bem a ferramenta, mas **completa de memória o que falta no resultado**:
- inventou a ordem das temporadas de Attack on Titan (com anos errados) quando a ferramenta só trazia a sequência direta → a cadeia completa resolveu
- inventou detalhes de enredo e duração → regra no prompt: anos, durações, episódios e enredo só se vierem das ferramentas
- preencheu ano e episódios de nós esboço → os esboços agora vêm com um aviso explícito

Lição: com modelo local, **lacuna no resultado da ferramenta vira alucinação**. Vale mais completar o resultado do que pedir no prompt para não inventar.

O backend do Claude tem teste unitário com cliente falso, mas ainda não rodou de verdade (falta credencial).

**Interface web** (`ui/`, FastAPI): chat que mostra cada passo ao vivo (SSE), aba de analytics com o Cypher editável, explorador do grafo (Cytoscape.js) e painel das avaliações. `uv run --env-file config/.env uvicorn ui.server:app --port 8765`.

## Avaliação do agente (2026-10-01)
`eval/agent_questions.json`, 15 perguntas (A1–A15): recomendação, filtro, semântica, franquia, agregação, fato, multi-hop, sinopse, perguntas sem resposta e uma continuação de conversa (campo `antes`).
```
uv run --env-file config/.env python -m eval.agent_run [--only A1,A4]
```
Correção **automática**, sem LLM como juiz. Uma resposta passa se:
- chamou uma das ferramentas esperadas
- cita a fração mínima dos títulos que a consulta de referência devolve (calculada na hora, então acompanha o grafo)
- contém os textos obrigatórios (`deve_conter`, `deve_conter_algum`)
- **não cita nenhuma nota sem fonte**: decimal da resposta que não aparece em nenhum resultado de ferramenta. É a medida direta de alucinação

**Resultado depois do crawl (gpt-oss-20b): 15/15**, ferramenta certa 15/15, nenhuma nota sem fonte, mediana ~10 s.

### Casos que mudaram o agente
- **Falso negativo da sinopse (uso real, pela interface):** perguntaram o nome do protagonista de Bleach. A ferramenta trouxe a sinopse, que cita Ichigo, mas o agente respondeu que o grafo não tinha personagens, porque o prompt mandava não usar nada fora das ferramentas e ele não contou a sinopse como dado. Regra nova: a sinopse pode ser usada, dizendo que veio dela. Viraram as perguntas A13 (protagonista), A14 (fillers: não há dado) e A15 (continuação: "e o personagem principal do anime?" depois de uma pergunta com erro de digitação, "bleack")
- **Bilheteria (A11):** ver `SEM_DADOS` em [[07 - Gerador de Cypher]]. O gerador chegou a devolver a popularidade numa coluna chamada `bilheteria`; pela `consulta_cypher`, o agente receberia esse número como se fosse bilheteria. Agora recebe `sem_dados` e diz que o grafo não tem a informação
- **Interseção (A7, "recomendado para Death Note e para Code Geass"):** antes do crawl, o agente chamava `expandir_vizinhanca` duas vezes e cruzava as listas. Com o grafo maior, cada título tem dezenas de recomendações, o corte em 15 escondia a maior parte da interseção e a resposta saía incompleta sem aviso. Duas mudanças: o aviso `recomendacoes_obs` no resultado e a orientação no prompt de mandar "o que X e Y têm em comum" para `consulta_cypher`. Agora a A7 acerta 18/18
- **Token do gpt-oss vazando no nome da ferramenta (A10):** numa chamada, o nome veio como `consulta_cypher<|channel|>commentary`, um pedaço do formato *harmony* do gpt-oss que o oMLX não separou. O loop devolveu erro de ferramenta desconhecida e o modelo repetiu a chamada com o nome certo, então a pergunta passou. Agora o `OmlxBackend` corta o nome no `<|` antes de procurar a ferramenta (`tool_name`). Na mesma pergunta, a primeira chamada mandou Cypher com propriedades em inglês (`a.genres`, `a.episodes`), que a ferramenta recusou

## A/B/C: o grafo ajuda? (2026-10-01)
Mesmo modelo (gpt-oss-20b), mesmo loop, mesmas 15 perguntas; muda o que o agente pode consultar:
```
uv run --env-file config/.env python -m eval.agent_run --config A --max-tokens 16384
uv run --env-file config/.env python -m eval.agent_run --config B
uv run --env-file config/.env python -m eval.agent_run --config C
```
| Config | Ferramentas | Passou | Cobertura + texto (ignorando notas sem fonte) | Com notas sem fonte | Mediana |
|---|---|---|---|---|---|
| A, só LLM | nenhuma | 1/15 | 6/15 | 12/15 | 18 s |
| B, RAG vetorial | `busca_semantica` | 5/15 | 5/15 | 0/15 | 9 s |
| **C, GraphRAG** | as três | **15/15** | **15/15** | **0/15** | 10 s |

- O prompt de C é o do agente, sem mudança; A e B reaproveitam a introdução e as regras de resposta e trocam só o bloco das ferramentas. Em A e B, pergunta que pede uma ferramenta indisponível não reprova pelo critério de ferramenta
- **A sabe o assunto e inventa os números.** Lembra títulos plausíveis (Psycho-Pass e Erased para Monster; Ichigo em Bleach), mas: bilheteria de Chainsaw Man inventada com **fonte falsa** ("Box Office Mojo, 28/10/2023"); Frieren com 12 episódios e nota 8,0 (no grafo: 28 e 9,25); a mesma nota 8,58 para todas as temporadas de Attack on Titan; Berserk entre os mangás "sem anime"
- **A precisa de mais orçamento de saída.** Com os 4.096 tokens padrão, 5 respostas vieram vazias: o gpt-oss gastou tudo raciocinando. Com `--max-tokens 16384`, 3 voltaram; A10 e A14 seguem vazias, levando ~4 min cada. A tabela usa a rodada com 16k (com 4.096: 0/15)
- **B é honesto e cego para o que não está na sinopse.** Não cita nenhuma nota sem fonte, mas a busca vetorial não acha título: "parecido com Monster" virou *Gogo Monster* e *Love♥Monster*; "Frieren" pegou outra obra (nota 7,36, dita com segurança porque veio da ferramenta). Sem relações, não responde autor, ordem de temporadas, interseções nem filtros. Passou só em assunto, sinopse e perguntas sem resposta
- Ressalva: o conjunto foi escrito para o agente com grafo (as referências saem de Cypher), e é uma rodada só. A diferença é grande demais para ser ruído, mas o número exato de A e B não deve ser lido como absoluto

## Pontos de atenção
- `consulta_cypher`: validar a query antes de rodar e executar em **transação de leitura** (`session.execute_read`), que o servidor rejeita se houver escrita. Usuário somente leitura (RBAC) só existe no Neo4j Enterprise; estamos na Community
- Limitar número de passos e tamanho do contexto retornado por ferramenta
- Pedir ao agente que cite os nós (títulos/IDs) usados na resposta
- Logar cada chamada de ferramenta para depurar e avaliar

## Perguntas de teste
- "Me indica algo parecido com Monster, mas mais curto"
- "Quais mangás bem avaliados não têm adaptação em anime?"
- "Quais animes de terror psicológico têm nota acima de 8 e poucos episódios?"
