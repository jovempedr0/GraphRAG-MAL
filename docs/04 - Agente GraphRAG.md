---
tags: [projeto, graphrag, agentes, tool-use]
---

# Agente GraphRAG

Voltar: [[00 - Índice GraphRAG Anime]] · Anterior: [[07 - Gerador de Cypher]] · Próxima: [[05 - Roadmap e Avaliação]]

## Ideia
O agente (Claude via tool use, em Python) decide qual ferramenta chamar, junta o contexto vindo do grafo e responde. Em vez de um pipeline fixo, o modelo escolhe o caminho.

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
| `consulta_cypher(pergunta)` | perguntas estruturadas (filtros, ranking, agregações, analytics); usa o gerador de [[07 - Gerador de Cypher]] |

## Loop do agente
```
pergunta → modelo decide ferramenta → executa → resultado volta ao modelo
        → (repete até ter contexto suficiente) → resposta final com justificativa
```

## Pontos de atenção
- `consulta_cypher`: validar a query antes de rodar e executar em **transação de leitura** (`session.execute_read`), que o servidor rejeita se houver escrita. Usuário somente leitura (RBAC) só existe no Neo4j Enterprise; estamos na Community
- Limitar número de passos e tamanho do contexto retornado por ferramenta
- Pedir ao agente que cite os nós (títulos/IDs) usados na resposta
- Logar cada chamada de ferramenta para depurar e avaliar

## Perguntas de teste
- "Me indica algo parecido com Monster, mas mais curto"
- "Quais mangás bem avaliados não têm adaptação em anime?"
- "Quais animes de terror psicológico têm nota acima de 8 e poucos episódios?"
