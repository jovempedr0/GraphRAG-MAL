from analytics.values import Literal, extract_literals


def test_inline_node_map():
    cypher = "MATCH (a:Anime {titulo: 'Sousou no Frieren', completo: true}) RETURN a"
    assert extract_literals(cypher) == [Literal("node", "Anime", "titulo", "Sousou no Frieren")]


def test_anonymous_node_map():
    cypher = "MATCH (:Studio {nome: 'MAPPA'})<-[:PRODUCED_BY]-(a) RETURN a"
    assert extract_literals(cypher) == [Literal("node", "Studio", "nome", "MAPPA")]


def test_comparison_uses_label_of_variable():
    cypher = "MATCH (m:Manga {completo: true}) WHERE m.status = 'Ongoing' RETURN count(m)"
    assert extract_literals(cypher) == [Literal("node", "Manga", "status", "Ongoing")]


def test_relationship_map_and_comparison():
    cypher = ("MATCH (a)-[:RELATED_TO {tipo: 'prequel'}]->(b)-[r:RELATED_TO]->(c) "
              "WHERE r.tipo = 'sequel' RETURN c")
    assert extract_literals(cypher) == [
        Literal("rel", "RELATED_TO", "tipo", "prequel"),
        Literal("rel", "RELATED_TO", "tipo", "sequel"),
    ]


def test_in_list():
    cypher = "MATCH (g:Genre) WHERE g.nome IN ['Horror', 'Terror'] RETURN g"
    assert extract_literals(cypher) == [
        Literal("node", "Genre", "nome", "Horror"),
        Literal("node", "Genre", "nome", "Terror"),
    ]


def test_title_with_parentheses_and_quotes():
    cypher = 'MATCH (a:Anime {titulo: "Hunter x Hunter (2011)"}) RETURN a'
    assert extract_literals(cypher) == [Literal("node", "Anime", "titulo", "Hunter x Hunter (2011)")]


def test_unknown_variable_and_non_equality_are_ignored():
    cypher = "MATCH (a) WHERE a.titulo = 'X' AND b.nome CONTAINS 'Y' RETURN a"
    assert extract_literals(cypher) == []


def test_duplicates_are_removed():
    cypher = "MATCH (a:Anime {titulo: 'Monster'}) MATCH (b:Anime {titulo: 'Monster'}) RETURN a, b"
    assert len(extract_literals(cypher)) == 1
