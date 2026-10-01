import pytest

from analytics.cypher import CypherError, check_read_only, ensure_limit, extract_cypher


def test_extract_from_fenced_block():
    text = "Aqui está:\n```cypher\nMATCH (a:Anime)\nRETURN a.titulo;\n```\nPronto."
    assert extract_cypher(text) == "MATCH (a:Anime)\nRETURN a.titulo"


def test_extract_plain_text():
    assert extract_cypher("  MATCH (a) RETURN a;  ") == "MATCH (a) RETURN a"


def test_extract_turns_literal_backslash_n_into_newlines():
    assert extract_cypher("MATCH (a)\\nRETURN a") == "MATCH (a)\nRETURN a"


def test_extract_literal_backslash_n_inside_fenced_block():
    text = "```cypher\nMATCH (a)\\nRETURN a\n```"
    assert extract_cypher(text) == "MATCH (a)\nRETURN a"


@pytest.mark.parametrize("text", [
    "```cypher\nMATCH (a)\nRETURN a",
    "```cypher MATCH (a)\nRETURN a",
    "```\nMATCH (a)\nRETURN a",
])
def test_extract_unclosed_fence(text):
    assert extract_cypher(text) == "MATCH (a)\nRETURN a"


def test_extract_keeps_backslash_n_when_text_already_has_newlines():
    text = "MATCH (a)\nWHERE a.titulo = 'x\\ny'\nRETURN a"
    assert extract_cypher(text) == text


@pytest.mark.parametrize("cypher", [
    "MATCH (a) DETACH DELETE a",
    "CREATE (:Anime {titulo: 'x'})",
    "MATCH (a) SET a.nota = 10",
    "merge (g:Genre {nome: 'x'})",
    "LOAD CSV FROM 'file:///x' AS l RETURN l",
    "CALL dbms.components()",
    "CALL apoc.create.node(['X'], {})",
])
def test_write_queries_are_blocked(cypher):
    with pytest.raises(CypherError):
        check_read_only(cypher)


@pytest.mark.parametrize("cypher", [
    "MATCH (a:Anime) RETURN a.titulo ORDER BY a.nota DESC",
    "MATCH (a:Anime {titulo: 'Set Up'}) RETURN a",
    "MATCH (a:Anime) WHERE a.titulo CONTAINS 'Create' RETURN a.created_at",
    "CALL db.schema.visualization()",
])
def test_read_queries_pass(cypher):
    check_read_only(cypher)


def test_ensure_limit_adds_when_missing():
    assert ensure_limit("MATCH (a) RETURN a", 100) == "MATCH (a) RETURN a\nLIMIT 100"


def test_ensure_limit_keeps_existing():
    assert ensure_limit("MATCH (a) RETURN a LIMIT 5") == "MATCH (a) RETURN a LIMIT 5"
