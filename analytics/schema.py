"""Contexto do schema para o prompt, lido do próprio banco para nunca ficar desatualizado."""
from collections import defaultdict
from dataclasses import dataclass, field

# O que a introspecção não mostra: semântica das arestas e cuidados com os dados.
CONVENTIONS = """\
- Nós com `completo = false` são esboços: só têm `mal_id` e `titulo`. Filtre `{completo: true}` sempre que a pergunta envolver nota, gênero, estúdio, ano ou episódios
- `top = true` marca os 500 animes e os 500 mangás do ranking do MyAnimeList. "Do top" quer dizer `{top: true}` (não é um corte de nota); "fora do top" é `{top: false}`. Não invente filtros que a pergunta não pede
- `ORDER BY ... DESC` põe os nulos primeiro: ao ordenar por uma propriedade que pode faltar, filtre `IS NOT NULL`
- `RECOMMENDS` está gravada num sentido só e não tem direção de significado: consulte sempre sem seta, `(a)-[r:RECOMMENDS]-(b)`
- `votos` é propriedade da aresta `RECOMMENDS` (`r.votos`), não dos nós
- `RELATED_TO` tem direção: `(a)-[:RELATED_TO {tipo: 'sequel'}]->(b)` significa "b é sequência de a"
- `episodios` e `capitulos` nulos significam desconhecido (ainda em exibição/publicação)
- `Genre` é identificado por `nome`, em inglês. Use só nomes da lista de gêneros abaixo
- `nota` vai de 0 a 10; `ano` é o ano de estreia
- Títulos (`titulo`) estão em romaji, como no MyAnimeList (ex.: 'Shingeki no Kyojin'); `titulo_en` é o título em inglês. Use o título exato; se a pergunta usar um nome popular (ex.: 'Frieren'), a validação devolve os títulos parecidos
- Propriedades categóricas (`fonte`, `status`, `tipo`) usam valores em minúsculas do MyAnimeList (ex.: `tipo = 'movie'`); se o valor não existir, a validação devolve os válidos
- Não retorne a propriedade `embedding` (vetor de 1024 números)"""

SKIP_PROPERTIES = {"embedding", "embedding_modelo"}
# Até esse número de valores distintos, a checagem de valores (values.py) sugere todos.
# Listar esses valores no prompt piorou o gpt-oss em perguntas de caminho (E15, E16).
MAX_CATEGORICAL = 20


@dataclass
class Schema:
    text: str  # vai no prompt
    node_props: dict = field(default_factory=dict)  # label -> {propriedades}
    rel_props: dict = field(default_factory=dict)  # tipo -> {propriedades}
    patterns: set = field(default_factory=set)  # {(label origem, tipo, label destino)}


def build_schema(session):
    nodes = defaultdict(list)
    node_props = defaultdict(set)
    for r in session.run("CALL db.schema.nodeTypeProperties()"):
        label = r["nodeLabels"][0]
        if r["propertyName"]:
            node_props[label].add(r["propertyName"])
        if r["propertyName"] and r["propertyName"] not in SKIP_PROPERTIES:
            tipo = (r["propertyTypes"] or ["?"])[0].replace(" NOT NULL", "")
            nodes[label].append(f"{r['propertyName']}: {tipo}")

    rel_props = defaultdict(list)
    rel_prop_names = {}
    for r in session.run("CALL db.schema.relTypeProperties()"):
        rel_type = r["relType"].strip(":`")
        rel_prop_names.setdefault(rel_type, set())
        if r["propertyName"]:
            tipo = r["propertyTypes"][0].replace(" NOT NULL", "")
            rel_props[rel_type].append(f"{r['propertyName']}: {tipo}")
            rel_prop_names[rel_type].add(r["propertyName"])

    patterns = session.run(
        "MATCH (a)-[r]->(b) RETURN DISTINCT labels(a)[0] AS a, type(r) AS t, labels(b)[0] AS b "
        "ORDER BY t, a"
    ).data()
    genres = session.run("MATCH (g:Genre) RETURN g.nome ORDER BY g.nome").value()
    related = session.run(
        "MATCH ()-[r:RELATED_TO]->() RETURN DISTINCT r.tipo ORDER BY r.tipo"
    ).value()

    lines = ["Nós:"]
    lines += [f"- {label} {{{', '.join(sorted(props))}}}" for label, props in sorted(nodes.items())]
    lines.append("\nRelações:")
    for p in patterns:
        props = rel_props.get(p["t"])
        suffix = f" {{{', '.join(props)}}}" if props else ""
        lines.append(f"- (:{p['a']})-[:{p['t']}{suffix}]->(:{p['b']})")
    lines.append(f"\nValores de RELATED_TO.tipo: {', '.join(related)}")
    lines.append(f"\nGêneros (Genre.nome): {', '.join(genres)}")
    lines.append(f"\nConvenções:\n{CONVENTIONS}")
    return Schema(
        text="\n".join(lines),
        node_props=dict(node_props),
        rel_props=rel_prop_names,
        patterns={(p["a"], p["t"], p["b"]) for p in patterns},
    )

