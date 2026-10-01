import pytest

from analytics.lint import check_schema, fix_undirected
from analytics.schema import Schema

SCHEMA = Schema(
    text="",
    node_props={
        "Anime": {"titulo", "nota", "episodios", "completo"},
        "Manga": {"titulo", "nota", "capitulos", "completo"},
        "Studio": {"nome"},
        "Author": {"nome"},
        "Genre": {"nome"},
    },
    rel_props={"RECOMMENDS": {"votos"}, "RELATED_TO": {"tipo"}, "WRITTEN_BY": {"papel"}},
    patterns={
        ("Anime", "PRODUCED_BY", "Studio"),
        ("Anime", "RECOMMENDS", "Anime"),
        ("Manga", "RECOMMENDS", "Manga"),
        ("Anime", "RELATED_TO", "Anime"),
        ("Manga", "WRITTEN_BY", "Author"),
        ("Anime", "HAS_GENRE", "Genre"),
        ("Manga", "HAS_GENRE", "Genre"),
    },
)


@pytest.mark.parametrize("cypher, expected", [
    ("MATCH (a)-[:RECOMMENDS]->(b) RETURN b", "MATCH (a)-[:RECOMMENDS]-(b) RETURN b"),
    ("MATCH (a)<-[r:RECOMMENDS]-(b) RETURN b", "MATCH (a)-[r:RECOMMENDS]-(b) RETURN b"),
    ("MATCH (a)-[:RECOMMENDS*1..2]->(b) RETURN b", "MATCH (a)-[:RECOMMENDS*1..2]-(b) RETURN b"),
    ("MATCH (a)-[r:RECOMMENDS {votos: 3}]->(b)", "MATCH (a)-[r:RECOMMENDS {votos: 3}]-(b)"),
    ("WHERE NOT EXISTS { (a)-[:RECOMMENDS]->() }", "WHERE NOT EXISTS { (a)-[:RECOMMENDS]-() }"),
])
def test_fix_undirected_removes_arrow(cypher, expected):
    assert fix_undirected(cypher) == expected


@pytest.mark.parametrize("cypher", [
    "MATCH (a)-[:RECOMMENDS]-(b) RETURN b",
    "MATCH (a)-[:RELATED_TO {tipo: 'sequel'}]->(b) RETURN b",
    "MATCH (a)-[:RECOMMENDS|RELATED_TO]->(b) RETURN b",
])
def test_fix_undirected_leaves_other_patterns(cypher):
    assert fix_undirected(cypher) == cypher


def test_correct_query_has_no_problems():
    cypher = """MATCH (a:Anime {completo: true})-[:PRODUCED_BY]->(s:Studio)
MATCH (a)-[r:RECOMMENDS]-(o:Anime)
WHERE a.nota > 8.5 AND r.votos >= 5
RETURN s.nome, o.titulo, count(DISTINCT o) AS n"""
    assert check_schema(cypher, SCHEMA) == []


def test_reversed_direction_with_both_labels():
    problems = check_schema("MATCH (s:Studio)-[:PRODUCED_BY]->(a:Anime) RETURN s.nome", SCHEMA)
    assert len(problems) == 1
    assert "invertida" in problems[0]
    assert "(:Anime)-[:PRODUCED_BY]->(:Studio)" in problems[0]


def test_reversed_direction_with_left_arrow():
    problems = check_schema("MATCH (m:Manga)<-[:WRITTEN_BY]-(p:Author) RETURN p.nome", SCHEMA)
    assert len(problems) == 1


def test_reversed_direction_with_label_from_earlier_pattern():
    cypher = "MATCH (a:Author)\nMATCH (a)-[:WRITTEN_BY]->(m) RETURN m.titulo"
    assert len(check_schema(cypher, SCHEMA)) == 1


def test_chain_is_checked_link_by_link():
    cypher = "MATCH (g:Genre)<-[:HAS_GENRE]-(a:Anime)-[:PRODUCED_BY]->(s:Studio) RETURN g.nome"
    assert check_schema(cypher, SCHEMA) == []


def test_unknown_endpoints_are_not_flagged():
    assert check_schema("MATCH (x)-[:PRODUCED_BY]->(y) RETURN x", SCHEMA) == []


def test_relationship_property_on_node():
    problems = check_schema(
        "MATCH (:Anime {titulo: 'Monster'})-[:RECOMMENDS]-(o:Anime) RETURN o.titulo ORDER BY o.votos",
        SCHEMA,
    )
    assert len(problems) == 1
    assert "`o.votos`" in problems[0]
    assert "RECOMMENDS" in problems[0]


def test_property_of_other_label():
    problems = check_schema("MATCH (a:Anime) RETURN a.capitulos", SCHEMA)
    assert len(problems) == 1
    assert "Anime" in problems[0]


def test_property_on_relationship_variable():
    assert len(check_schema("MATCH (a)-[r:RELATED_TO]->(b) RETURN r.votos", SCHEMA)) == 1


def test_strings_and_numbers_are_ignored():
    cypher = "MATCH (a:Anime {titulo: 'Steins;Gate (a.votos)'}) WHERE a.nota > 8.5 RETURN a.titulo"
    assert check_schema(cypher, SCHEMA) == []


def test_function_namespaces_are_ignored():
    assert check_schema("MATCH (a:Anime) RETURN apoc.coll.sum([a.nota])", SCHEMA) == []
