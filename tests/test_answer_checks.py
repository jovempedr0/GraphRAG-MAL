from analytics.answer_checks import decimals, mentions, ungrounded_decimals


def test_mentions_romaji_or_english_ignoring_case_and_punctuation():
    answer = "Recomendo **Grave of the Fireflies** e Psycho‑Pass."
    assert mentions(answer, ["Hotaru no Haka", "Grave of the Fireflies"])
    assert mentions(answer, ["Psycho-Pass"])
    assert not mentions(answer, ["Pluto"])


def test_mentions_needs_whole_words():
    assert not mentions("Monsters Inc.", ["Monster"])
    assert mentions("Veja Monster.", ["Monster"])


def test_decimals_normalized():
    assert decimals("nota 8,62 e 9.10; 74 episódios; 2013") == {"8.62", "9.1"}


def test_decimals_ignore_dates_and_long_numbers():
    assert decimals("2013.10.05 e 1234.5") == set()


def test_ungrounded():
    tool = '{"nota": 8.62, "media": 8.4}'
    assert ungrounded_decimals("Notas 8,62 e 8,40 e 9,05", [tool]) == ["9.05"]


from types import SimpleNamespace

from eval.agent_run import grade


def step(tool, result="{}"):
    return SimpleNamespace(tool=tool, result=result)


def test_grade_passes_with_coverage_and_grounded_numbers():
    q = {"ferramentas": ["expandir_vizinhanca"], "min_esperados": 2}
    expected = [["Psycho-Pass"], ["Pluto"], ["Berserk", "Kenpuu Denki Berserk"]]
    g = grade(q, "Psycho-Pass (8,32) e Pluto.", [step("expandir_vizinhanca", '{"nota": 8.32}')], expected)
    assert g["passou"] and g["cobertura"] == "2/3"


def test_grade_fails_on_ungrounded_number_and_wrong_tool():
    q = {"ferramentas": ["consulta_cypher"]}
    g = grade(q, "Nota 9,99", [step("busca_semantica")], [])
    assert not g["ferramenta_ok"] and g["notas_sem_fonte"] == ["9.99"] and not g["passou"]


def test_grade_fraction_and_must_contain():
    q = {"ferramentas": [], "min_esperados": 0.5, "deve_conter": ["9.25"]}
    g = grade(q, "Frieren tem nota 9,25. Indico A.", [step("x", "9.25")], [["A"], ["B"], ["C"], ["D"]])
    assert not g["cobertura_ok"] and g["minimo"] == 2 and g["conteudo_ok"]


def test_grade_tool_criterion_not_applicable_without_expected_tools():
    # Configuração B (só busca_semantica) numa pergunta que pede consulta_cypher: não reprova pela ferramenta
    q = {"ferramentas": ["consulta_cypher"]}
    g = grade(q, "Não sei.", [step("busca_semantica")], [], available=["busca_semantica"])
    assert g["ferramenta_ok"] is None and g["passou"] and g["conteudo_passou"]


def test_grade_tool_criterion_applies_when_an_expected_tool_is_available():
    q = {"ferramentas": ["consulta_cypher", "busca_semantica"]}
    g = grade(q, "Resposta.", [], [], available=["busca_semantica"])
    assert g["ferramenta_ok"] is False and not g["passou"] and g["conteudo_passou"]


def test_grade_llm_only_numbers_are_ungrounded():
    q = {"ferramentas": ["expandir_vizinhanca"], "deve_conter": ["9.25"]}
    g = grade(q, "Frieren tem nota 9,25.", [], [], available=[])
    assert g["ferramenta_ok"] is None and g["conteudo_ok"] and g["notas_sem_fonte"] == ["9.25"]
    assert not g["passou"]
