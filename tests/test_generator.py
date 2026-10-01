import pytest

from analytics import generator
from analytics.cypher import CypherError
from analytics.schema import Schema


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        self.calls.append(list(messages))
        return self.replies.pop(0), {"total_tokens": 10}


def fake_run(results):
    """results: por chamada, lista de linhas ou uma mensagem de erro."""
    results = list(results)

    def run(session, raw, schema):
        r = results.pop(0)
        if isinstance(r, str):
            raise CypherError(r)
        return raw, ["c"], r
    return run


@pytest.fixture
def run_with(monkeypatch):
    def setup(results, replies):
        monkeypatch.setattr(generator, "prepare_and_run", fake_run(results))
        chat = FakeChat(replies)
        ans = generator.generate("pergunta", chat, None, Schema(text="schema"))
        return ans, chat
    return setup


def test_first_try_success(run_with):
    ans, chat = run_with([[[1]]], ["q1"])
    assert ans.ok and ans.rows == [[1]]
    assert len(ans.attempts) == 1 and len(chat.calls) == 1


def test_error_is_sent_back_and_retried(run_with):
    ans, chat = run_with(["direção invertida", [[1]]], ["q1", "q2"])
    assert ans.cypher == "q2"
    assert "direção invertida" in chat.calls[1][-1]["content"]


def test_empty_result_asks_for_review_once(run_with):
    ans, chat = run_with([[], [[1]]], ["q1", "q2"])
    assert ans.cypher == "q2" and ans.rows == [[1]]
    assert "0 linhas" in chat.calls[1][-1]["content"]


def test_empty_twice_is_accepted(run_with):
    ans, chat = run_with([[], []], ["q1", "q1"])
    assert ans.ok and ans.rows == []
    assert len(chat.calls) == 2


def test_empty_on_last_attempt_is_accepted(run_with):
    ans, _ = run_with(["erro", "erro", []], ["q1", "q2", "q3"])
    assert ans.ok and ans.cypher == "q3"


def test_gives_up_after_max_retries(run_with):
    ans, chat = run_with(["e1", "e2", "e3"], ["q1", "q2", "q3"])
    assert not ans.ok
    assert len(chat.calls) == 3
