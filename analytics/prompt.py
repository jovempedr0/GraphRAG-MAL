"""Mensagens para o modelo: instruções, schema e exemplos (few-shot)."""

# Resposta do modelo quando o grafo não tem a informação pedida. Sem isso, o modelo trocava
# o dado por outro com o nome pedido (`a.popularidade AS bilheteria`).
NO_DATA = "SEM_DADOS"

SYSTEM = """\
Você traduz perguntas sobre um grafo de animes e mangás do MyAnimeList (Neo4j) em uma única consulta Cypher de leitura.

Regras:
- Use apenas os labels, relações e propriedades do schema abaixo
- Só leitura: nada de CREATE, MERGE, SET, DELETE, REMOVE ou procedures de escrita
- Dê nomes claros às colunas com AS
- Responda só com a consulta, dentro de um bloco ```cypher```, sem explicação
- Se a pergunta pede uma informação que o schema não tem (bilheteria, orçamento, personagens, episódios), não troque por outra propriedade: responda só `SEM_DADOS: <o que falta>`

{schema}"""

# Pares pergunta → Cypher que cobrem os padrões do grafo. Não repetem as perguntas da avaliação
# (eval/questions.json), senão a avaliação mede memorização.
EXAMPLES = [
    (
        "Quais mangás de romance têm nota acima de 8,5?",
        """MATCH (m:Manga {completo: true})-[:HAS_GENRE]->(:Genre {nome: 'Romance'})
WHERE m.nota > 8.5
RETURN m.titulo AS titulo, m.nota AS nota
ORDER BY nota DESC""",
    ),
    (
        "Quais estúdios têm pelo menos 5 animes com nota acima de 8,5?",
        """MATCH (a:Anime {completo: true})-[:PRODUCED_BY]->(s:Studio)
WHERE a.nota > 8.5
WITH s, count(a) AS n
WHERE n >= 5
RETURN s.nome AS estudio, n
ORDER BY n DESC""",
    ),
    (
        "Quais animes são mais recomendados para quem gostou de Cowboy Bebop?",
        """MATCH (:Anime {titulo: 'Cowboy Bebop'})-[r:RECOMMENDS]-(o:Anime)
RETURN o.titulo AS titulo, r.votos AS votos
ORDER BY votos DESC LIMIT 10""",
    ),
    (
        "Qual é a sequência direta de Gintama?",
        """MATCH (:Anime {titulo: 'Gintama'})-[:RELATED_TO {tipo: 'sequel'}]->(s:Anime)
RETURN s.titulo AS sequencia""",
    ),
    (
        "Quantos mangás do top cada autor escreveu, em média com qual nota? Mostre os 5 com mais mangás.",
        """MATCH (m:Manga {top: true})-[:WRITTEN_BY]->(p:Author)
RETURN p.nome AS autor, count(m) AS n, round(avg(m.nota), 2) AS media
ORDER BY n DESC LIMIT 5""",
    ),
    (
        "Quantos animes de ação do top não têm nenhuma sequência?",
        """MATCH (a:Anime {top: true})-[:HAS_GENRE]->(:Genre {nome: 'Action'})
WHERE NOT EXISTS { (a)-[:RELATED_TO {tipo: 'sequel'}]->() }
RETURN count(a) AS n""",
    ),
    (
        "Qual foi o orçamento de produção de Steins;Gate?",
        f"{NO_DATA}: o grafo não tem orçamento de produção",
    ),
]


def build_messages(schema, question, examples=EXAMPLES):
    messages = [{"role": "system", "content": SYSTEM.format(schema=schema)}]
    for q, answer in examples:
        messages.append({"role": "user", "content": q})
        content = answer if answer.startswith(NO_DATA) else f"```cypher\n{answer}\n```"
        messages.append({"role": "assistant", "content": content})
    messages.append({"role": "user", "content": question})
    return messages


def empty_result_message():
    return ("A consulta rodou, mas devolveu 0 linhas. Confira a direção das relações no schema, "
            "os filtros e se os valores usados (gêneros, títulos, tipos) existem exatamente assim. "
            "Se zero linhas for mesmo a resposta certa, repita a mesma consulta. "
            "Responda só com a consulta, dentro de um bloco ```cypher```.")


def retry_message(error):
    return (f"A consulta falhou: {error}\n"
            "Corrija e responda só com a nova consulta, dentro de um bloco ```cypher```.")
