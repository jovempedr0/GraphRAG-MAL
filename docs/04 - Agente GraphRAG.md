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
- `expandir_vizinhanca`: resolve o título em romaji ou inglês ("Attack on Titan" → Shingeki no Kyojin) e devolve recomendações, relacionados, a **cadeia de sequências completa** e, com `saltos=2`, o segundo grau
- `consulta_cypher`: chama o gerador da nota 07; recusa SQL/Cypher no argumento (o gpt-oss chegou a mandar `SELECT ... FROM Anime`)

**Primeiros testes com o gpt-oss-20b** (4 perguntas, 8–23 s cada): escolhe bem a ferramenta, mas **completa de memória o que falta no resultado**:
- inventou a ordem das temporadas de Attack on Titan (com anos errados) quando a ferramenta só trazia a sequência direta → a cadeia completa resolveu
- inventou detalhes de enredo e duração → regra no prompt: anos, durações, episódios e enredo só se vierem das ferramentas
- preencheu ano e episódios de nós esboço → os esboços agora vêm com um aviso explícito

Lição: com modelo local, **lacuna no resultado da ferramenta vira alucinação**. Vale mais completar o resultado do que pedir no prompt para não inventar.

O backend do Claude tem teste unitário com cliente falso, mas ainda não rodou de verdade (falta credencial).

## Pontos de atenção
- `consulta_cypher`: validar a query antes de rodar e executar em **transação de leitura** (`session.execute_read`), que o servidor rejeita se houver escrita. Usuário somente leitura (RBAC) só existe no Neo4j Enterprise; estamos na Community
- Limitar número de passos e tamanho do contexto retornado por ferramenta
- Pedir ao agente que cite os nós (títulos/IDs) usados na resposta
- Logar cada chamada de ferramenta para depurar e avaliar

## Perguntas de teste
- "Me indica algo parecido com Monster, mas mais curto"
- "Quais mangás bem avaliados não têm adaptação em anime?"
- "Quais animes de terror psicológico têm nota acima de 8 e poucos episódios?"
