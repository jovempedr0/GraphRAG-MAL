---
tags: [projeto, graphrag, neo4j, cypher, exercicios]
---

# Consultas Cypher (etapa 4)

Voltar: [[00 - Índice GraphRAG Anime]] · Modelo: [[03 - Modelo do Grafo]] · Próxima: [[07 - Gerador de Cypher]]

Roteiro para aprender Cypher explorando o grafo. Tente escrever cada consulta antes de abrir a solução.
Rode no Neo4j Browser: http://localhost:7474 (usuário `neo4j`, senha em `config/.env`).

> [!tip] Lembretes
> - Use `{completo: true}` quando precisar de nota, gênero ou episódios. Os nós esboço só têm `mal_id` e `titulo`
> - `RECOMMENDS` está guardado num sentido só → consulte sem seta: `-[:RECOMMENDS]-`
> - `episodios`/`capitulos` nulos = desconhecido (ainda em exibição/publicação)

---

## Nível 1: MATCH, WHERE, ORDER BY

### E1. Os 10 animes com maior nota
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})
> RETURN a.titulo, a.nota, a.ano, a.episodios
> ORDER BY a.nota DESC LIMIT 10;
> ```

### E2. Desenhe o schema do grafo
> [!example]- Solução
> ```cypher
> CALL db.schema.visualization();
> ```
> Compare com a tabela de [[03 - Modelo do Grafo]].

---

## Nível 2: agregação

### E3. Quantos animes do top por década, e a nota média de cada uma?
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})
> RETURN (a.ano / 10) * 10 AS decada, count(*) AS n, round(avg(a.nota), 2) AS media
> ORDER BY decada;
> ```

> [!note] O que o resultado mostra
> 2010 e 2020 somam ~80% do top, mas a nota média quase não muda entre as décadas (8,38–8,47). O top 500 é "recente", não "melhor".

### E4. Estúdios com mais animes no top, com a nota média
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})-[:PRODUCED_BY]->(s:Studio)
> RETURN s.nome, count(a) AS n, round(avg(a.nota), 2) AS media
> ORDER BY n DESC LIMIT 10;
> ```
> Madhouse lidera (35), MAPPA e Sunrise têm as maiores médias entre os grandes.

### E5. Pares de gêneros que mais aparecem juntos
Dica: dois `HAS_GENRE` saindo do mesmo anime, e um filtro para não contar (A,B) e (B,A).
> [!example]- Solução
> ```cypher
> MATCH (g1:Genre)<-[:HAS_GENRE]-(a:Anime {completo: true})-[:HAS_GENRE]->(g2:Genre)
> WHERE g1.nome < g2.nome
> RETURN g1.nome, g2.nome, count(a) AS n
> ORDER BY n DESC LIMIT 10;
> ```

### E6. Autores com 3+ mangás no top
> [!example]- Solução
> ```cypher
> MATCH (p:Author)<-[:WRITTEN_BY]-(m:Manga {completo: true})
> WITH p, count(m) AS n, collect(m.titulo)[..3] AS exemplos
> WHERE n >= 3
> RETURN p.nome, n, exemplos ORDER BY n DESC;
> ```
> `WITH` funciona como um "pipe": agrega, e depois filtra o agregado (parecido com `HAVING` no SQL).

---

## Nível 3: o grafo de recomendações

### E7. Quais animes são mais recomendados (maior grau)?
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})
> RETURN a.titulo, COUNT { (a)-[:RECOMMENDS]-() } AS grau
> ORDER BY grau DESC LIMIT 10;
> ```
> Death Note (30), Evangelion (29), Mushishi e Shingeki (27). O máximo é baixo porque o MAL devolve só 10 recomendações por item, e o grau vem das duas pontas.

### E8. Parecido com Monster, mas mais curto (pergunta de teste do agente)
> [!example]- Solução
> ```cypher
> MATCH (:Anime {titulo: 'Monster'})-[r:RECOMMENDS]-(o:Anime {completo: true})
> WHERE o.episodios <= 26
> RETURN o.titulo, o.episodios, o.nota, r.votos
> ORDER BY r.votos DESC;
> ```
> Psycho-Pass (22 ep), Pluto (8), Berserk (25)… Death Note fica de fora por ter 37.

### E9. Dois saltos: recomendações das recomendações de Monster que ele não recomenda direto
Dica: conte por quantos caminhos diferentes cada anime é alcançado.
> [!example]- Solução
> ```cypher
> MATCH (m:Anime {titulo: 'Monster'})-[:RECOMMENDS]-(v)-[r2:RECOMMENDS]-(o:Anime {completo: true})
> WHERE o <> m AND NOT (m)-[:RECOMMENDS]-(o)
> RETURN o.titulo, count(DISTINCT v) AS caminhos, sum(r2.votos) AS forca
> ORDER BY caminhos DESC, forca DESC LIMIT 10;
> ```
> Code Geass aparece por 4 caminhos. **Isso é o que um RAG vetorial puro não consegue fazer**, e é a base da ferramenta `expandir_vizinhanca` ([[04 - Agente GraphRAG]]).

### E10. Menor caminho de Frieren até Monster
> [!example]- Solução
> ```cypher
> MATCH p = shortestPath(
>   (a:Anime {titulo: 'Sousou no Frieren'})-[:RECOMMENDS*..6]-(b:Anime {titulo: 'Monster'}))
> RETURN [n IN nodes(p) | n.titulo] AS caminho;
> ```
> Frieren → Tongari Boushi no Atelier → FMA:B → Rainbow → Monster. Rode sem o `[n IN ...]` para ver o caminho desenhado no Browser.

---

## Nível 4: subconsultas e comparação

### E11. Terror psicológico com nota > 8 e até 13 episódios (pergunta de teste)
Dica: `[(a)-[:HAS_GENRE]->(g) | g.nome]` devolve a lista de gêneros inline.
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})-[:HAS_GENRE]->(:Genre {nome: 'Psychological'})
> WHERE a.nota > 8 AND a.episodios <= 13
> RETURN a.titulo, a.nota, a.episodios, [(a)-[:HAS_GENRE]->(g) | g.nome] AS generos
> ORDER BY a.nota DESC;
> ```
> Exigir `Horror` **e** `Psychological` quase zera o resultado: só há 9 animes de Horror no top 500.

### E12. Gêneros parecidos ≠ recomendação? (similaridade de Jaccard)
Para Monster: os animes com mais gêneros em comum, e se eles são recomendados.
> [!example]- Solução
> ```cypher
> MATCH (m:Anime {titulo: 'Monster'})-[:HAS_GENRE]->(g)<-[:HAS_GENRE]-(o:Anime {completo: true})
> WITH m, o, count(g) AS inter
> WITH m, o, inter,
>      COUNT { (m)-[:HAS_GENRE]->() } + COUNT { (o)-[:HAS_GENRE]->() } - inter AS uniao
> RETURN o.titulo, round(1.0 * inter / uniao, 2) AS jaccard,
>        EXISTS { (m)-[:RECOMMENDS]-(o) } AS recomendado
> ORDER BY jaccard DESC LIMIT 10;
> ```

> [!note] O que o resultado mostra
> Dos 6 mais parecidos por gênero, só 1 é recomendado de fato (Kaiji). As arestas `RECOMMENDS` trazem uma informação que os gêneros não trazem. É um bom argumento para a avaliação A/B/C de [[05 - Roadmap e Avaliação]].

### E13. Animes do top sem nenhuma recomendação
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true})
> WHERE NOT (a)-[:RECOMMENDS]-()
> RETURN count(*) AS n, collect(a.titulo)[..10] AS exemplos;
> ```

> [!warning] Achado
> **81 dos 500** ficam isolados. Quase todos são continuações (Gintama: The Final, Bleach Sennen Kessen-hen…): o MAL só recomenda a primeira temporada. Por isso foi criada a aresta `RELATED_TO`. Veja a E15.

### E14. Quais nós esboço deveriam ser coletados primeiro? (prioridade do crawl)
> [!example]- Solução
> ```cypher
> MATCH (s:Anime {completo: false})
> RETURN s.titulo, COUNT { (s)-[:RECOMMENDS]-() } AS grau
> ORDER BY grau DESC LIMIT 10;
> ```
> Diamond no Ace (13), Devilman Crybaby, Boku no Hero Academia… Esse é o critério natural para a etapa 8.

### E15. Continuações isoladas que chegam às recomendações via `RELATED_TO`
Dica: caminho de tamanho variável `-[:RELATED_TO*1..10]-` dentro de um `EXISTS {}`.
> [!example]- Solução
> ```cypher
> MATCH (a:Anime {completo: true}) WHERE NOT (a)-[:RECOMMENDS]-()
> RETURN count(*) AS sem_rec,
>        count(CASE WHEN EXISTS { (a)-[:RELATED_TO*1..10]-(:Anime)-[:RECOMMENDS]-() } THEN 1 END) AS conectados;
> ```
> 62 dos 81 se conectam. Os 19 restantes (Dr. Stone Science Future, Tunshi Xingkong 2nd Season…) dependem de uma temporada que está fora do top: ela é um nó esboço, sem relações próprias, e a cadeia quebra ali. O crawl da etapa 8 resolve isso.

### E16. Ordem para assistir: a cadeia de sequências de Shingeki no Kyojin
> [!example]- Solução
> ```cypher
> MATCH p = (a:Anime {titulo: 'Shingeki no Kyojin'})-[:RELATED_TO*1..10 {tipo: 'sequel'}]->(b)
> WHERE NOT (b)-[:RELATED_TO {tipo: 'sequel'}]->()
> RETURN [n IN nodes(p) | n.titulo] AS ordem
> ORDER BY length(p) DESC LIMIT 1;
> ```
> Aqui a direção importa: a seta segue "b é sequência de a".

---

## Achados de qualidade de dados
- O MAL usa `0` para episódios/capítulos desconhecidos (6 animes, 151 mangás em publicação) → o loader converte para nulo
- Só 10 recomendações por item → o grau máximo fica perto de 30
- Continuações ficam isoladas no grafo de recomendações (E13) → resolvido em parte com `RELATED_TO` (E15)
- Pouco terror no top 500 (9 animes) → algumas perguntas de teste vão depender do crawl
