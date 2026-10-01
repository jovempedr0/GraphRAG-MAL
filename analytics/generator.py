"""Pergunta → Cypher → linhas, com validação e autocorreção."""
import time
from dataclasses import dataclass, field

from analytics.cypher import CypherError, prepare_and_run
from analytics.prompt import build_messages, empty_result_message, retry_message

MAX_RETRIES = 2
EMPTY = "0 linhas"


@dataclass
class Attempt:
    raw: str
    error: str | None
    seconds: float


@dataclass
class Answer:
    question: str
    cypher: str | None = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    tokens: int = 0

    @property
    def ok(self):
        return self.cypher is not None


def generate(question, chat, session, schema, max_retries=MAX_RETRIES):
    """Gera, valida e executa. Resultado vazio pede uma revisão (uma vez só): zero linhas pode
    ser a resposta certa, mas costuma ser seta invertida ou filtro com valor inexistente."""
    messages = build_messages(schema.text, question)
    answer = Answer(question)
    empty_hint_sent = False
    for attempt in range(1 + max_retries):
        start = time.perf_counter()
        raw, usage = chat.complete(messages)
        answer.tokens += usage.get("total_tokens", 0)
        try:
            cypher, columns, rows = prepare_and_run(session, raw, schema)
        except CypherError as e:
            answer.attempts.append(Attempt(raw, str(e), time.perf_counter() - start))
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": retry_message(e)}]
            continue
        answer.cypher, answer.columns, answer.rows = cypher, columns, rows
        last = attempt == max_retries
        if rows or empty_hint_sent or last:
            answer.attempts.append(Attempt(raw, None, time.perf_counter() - start))
            break
        answer.attempts.append(Attempt(raw, EMPTY, time.perf_counter() - start))
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": empty_result_message()}]
        empty_hint_sent = True
    return answer
