import json
from types import SimpleNamespace

import httpx
import pytest

from agent.backends import AnthropicBackend, OmlxBackend, ToolCall, Turn
from agent.loop import FINAL_NUDGE, Agent
from agent.tools import SPECS, ToolError, Tools, to_text, validate

SPEC = {s["name"]: s for s in SPECS}


# --- loop -------------------------------------------------------------------------

class FakeBackend:
    model = "fake"

    def __init__(self, turns):
        self.turns = list(turns)
        self.log = []

    def start(self, system, tools):
        self.log.append(("start", [t["name"] for t in tools]))

    def add_user(self, text):
        self.log.append(("user", text))

    def step(self, allow_tools=True):
        self.log.append(("step", allow_tools))
        return self.turns.pop(0)

    def add_tool_results(self, results):
        self.log.append(("results", [(c.name, text, err) for c, text, err in results]))


class FakeTools:
    specs = SPEC

    def __init__(self):
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        return f"resultado de {name}", False


def call(name, args, id="c1"):
    return ToolCall(id, name, args, json.dumps(args))


def test_answers_directly_without_tools():
    agent = Agent(FakeBackend([Turn("Oi!")]), FakeTools())
    result = agent.ask("oi")
    assert result.answer == "Oi!" and result.steps == []


def test_runs_tool_then_answers():
    backend = FakeBackend([
        Turn("", [call("expandir_vizinhanca", {"titulo": "Monster"})], "tool_use"),
        Turn("Psycho-Pass e Pluto."),
    ])
    tools = FakeTools()
    result = Agent(backend, tools).ask("parecido com Monster")
    assert result.answer == "Psycho-Pass e Pluto."
    assert tools.calls == [("expandir_vizinhanca", {"titulo": "Monster"})]
    assert ("results", [("expandir_vizinhanca", "resultado de expandir_vizinhanca", False)]) in backend.log


def test_repeated_call_is_not_executed_again():
    same = call("consulta_cypher", {"pergunta": "x"})
    backend = FakeBackend([Turn("", [same], "tool_use"), Turn("", [same], "tool_use"), Turn("fim")])
    tools = FakeTools()
    result = Agent(backend, tools).ask("?")
    assert len(tools.calls) == 1
    assert "chamada repetida" in result.steps[1].result


def test_step_limit_forces_final_answer_without_tools():
    turns = [Turn("", [call("busca_semantica", {"texto": str(i)}, id=str(i))], "tool_use") for i in range(3)]
    backend = FakeBackend(turns + [Turn("resposta parcial")])
    result = Agent(backend, FakeTools(), max_steps=3).ask("?")
    assert result.stop == "max_steps" and result.answer == "resposta parcial"
    assert ("user", FINAL_NUDGE) in backend.log
    assert backend.log[-1] == ("step", False)


def test_refusal_stops():
    result = Agent(FakeBackend([Turn("", [], "refusal")]), FakeTools()).ask("?")
    assert result.stop == "refusal"


def test_conversation_keeps_history():
    backend = FakeBackend([Turn("a"), Turn("b")])
    agent = Agent(backend, FakeTools())
    agent.ask("1")
    agent.ask("2")
    assert [x for x in backend.log if x[0] == "start"] == [("start", list(SPEC))]


# --- validação de argumentos -------------------------------------------------------

@pytest.mark.parametrize("name, args", [
    ("busca_semantica", None),
    ("busca_semantica", {}),
    ("busca_semantica", {"texto": "x", "k": 50}),
    ("busca_semantica", {"texto": "x", "k": "5"}),
    ("busca_semantica", {"texto": "x", "tipo": "livro"}),
    ("busca_semantica", {"texto": "x", "extra": 1}),
    ("expandir_vizinhanca", {"titulo": "x", "saltos": 3}),
    ("consulta_cypher", {"pergunta": ""}),
    ("consulta_cypher", {"pergunta": "SELECT titulo FROM Anime"}),
    ("consulta_cypher", {"pergunta": "MATCH (a:Anime) RETURN a"}),
])
def test_invalid_args(name, args):
    with pytest.raises(ToolError):
        validate(SPEC[name], args)


@pytest.mark.parametrize("name, args", [
    ("busca_semantica", {"texto": "luto", "tipo": "manga", "k": 3}),
    ("expandir_vizinhanca", {"titulo": "Monster", "saltos": 2}),
    ("expandir_vizinhanca", {"mal_id": 19}),
    ("consulta_cypher", {"pergunta": "quantos animes?"}),
])
def test_valid_args(name, args):
    validate(SPEC[name], args)


# --- backend oMLX ------------------------------------------------------------------

def test_omlx_backend_round_trip():
    bodies = []
    replies = [
        {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
          "tool_calls": [{"id": "c1", "type": "function",
                          "function": {"name": "consulta_cypher", "arguments": '{"pergunta": "x"}'}}]}}],
         "usage": {"total_tokens": 10}},
        {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "pronto"}}],
         "usage": {"total_tokens": 5}},
    ]

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(bodies) - 1])

    b = OmlxBackend("http://t/v1", "k", "m", transport=httpx.MockTransport(handler))
    b.start("sistema", SPECS)
    b.add_user("pergunta")
    turn = b.step()
    assert turn.stop == "tool_use" and turn.calls[0].args == {"pergunta": "x"}
    b.add_tool_results([(turn.calls[0], "linhas", False)])
    assert b.step().text == "pronto"

    second = bodies[1]
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "tool"]
    assert second["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "linhas"}
    assert second["tools"][0]["function"]["name"] == "busca_semantica"


def test_omlx_invalid_json_args_become_none():
    reply = {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "busca_semantica", "arguments": "{texto: x"}}]}}]}
    b = OmlxBackend("http://t/v1", "k", "m",
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, json=reply)))
    b.start("s", SPECS)
    b.add_user("?")
    assert b.step().calls[0].args is None


# --- backend Claude (cliente falso) --------------------------------------------------

class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def block(type, **kw):
    return SimpleNamespace(type=type, **kw)


def response(content, stop):
    return SimpleNamespace(content=content, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=3, output_tokens=2))


def test_anthropic_backend_round_trip():
    content = [block("thinking", thinking=""), block("text", text="Vou buscar."),
               block("tool_use", id="t1", name="consulta_cypher", input={"pergunta": "x"})]
    client = FakeAnthropic([response(content, "tool_use"),
                            response([block("text", text="pronto")], "end_turn")])
    b = AnthropicBackend(client=client)
    b.start("sistema", SPECS)
    b.add_user("pergunta")
    turn = b.step()
    assert turn.calls[0].args == {"pergunta": "x"} and turn.text == "Vou buscar."
    b.add_tool_results([(turn.calls[0], "linhas", False)])
    assert b.step().text == "pronto"

    req = client.requests[1]
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["tools"][0]["input_schema"]["required"] == ["texto"]
    # resposta inteira (com thinking) volta ao histórico; resultados numa só mensagem
    assert req["messages"][1] == {"role": "assistant", "content": content}
    assert req["messages"][2]["content"][0]["tool_use_id"] == "t1"


def test_anthropic_refusal():
    client = FakeAnthropic([response([], "refusal")])
    b = AnthropicBackend(client=client)
    b.start("s", SPECS)
    b.add_user("?")
    assert b.step().stop == "refusal"


def test_to_text_drops_nulls_and_truncates():
    assert to_text({"a": 1, "b": None, "c": [{"d": None, "e": 2}]}) == '{"a": 1, "c": [{"e": 2}]}'
    assert to_text({"x": "y" * 20000}).endswith("…(cortado)")


def test_omlx_tool_name_drops_leaked_harmony_tokens():
    reply = {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {
            "name": "consulta_cypher<|channel|>commentary", "arguments": "{\"pergunta\": \"x\"}"}}]}}],
        "usage": {"total_tokens": 1}}
    b = OmlxBackend("http://t/v1", "k", "m",
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, json=reply)))
    b.start("s", [])
    b.add_user("q")
    assert b.step().calls[0].name == "consulta_cypher"


def test_omlx_without_tools_omits_tool_fields():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"content": "oi"}}]})
    b = OmlxBackend("http://t/v1", "k", "m", transport=httpx.MockTransport(handler))
    b.start("s", [])
    b.add_user("q")
    assert b.step().text == "oi"
    assert "tools" not in bodies[0] and "tool_choice" not in bodies[0]


def test_tools_subset():
    tools = Tools(None, None, None, None, only=["busca_semantica"])
    assert list(tools.specs) == ["busca_semantica"]
    assert tools.call("consulta_cypher", {"pergunta": "x"}) == ("ferramenta desconhecida: consulta_cypher", True)
