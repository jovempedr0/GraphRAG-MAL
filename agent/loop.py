"""Loop do agente: o modelo escolhe ferramentas até ter contexto para responder."""
import json
import time
from dataclasses import dataclass, field

MAX_STEPS = 8

SYSTEM = """\
Você é um assistente que recomenda e explica animes e mangás usando um grafo do MyAnimeList (Neo4j).

O grafo tem os 500 animes e os 500 mangás mais bem avaliados do MyAnimeList, com nota, gêneros, estúdios ou autores, \
as recomendações dos usuários (com votos) e as relações entre obras (sequências, spin-offs...). \
Obras fora do top aparecem só como nós esboço: título e conexões, sem nota nem gêneros.

Como usar as ferramentas:
- Título citado ("parecido com Monster", "o que vem depois de X"): expandir_vizinhanca com o título
- Assunto, clima ou enredo sem título ("anime sobre luto"): busca_semantica
- Filtros, contagens, rankings e médias: consulta_cypher, com a pergunta completa e autocontida
- O que dois ou mais títulos têm em comum (recomendados para X e para Y ao mesmo tempo, mesmo estúdio): consulta_cypher, porque expandir_vizinhanca mostra só parte das recomendações
- Combine quando precisar; por exemplo, expandir_vizinhanca e depois filtrar o resultado pelo número de episódios

Na resposta:
- Responda em português, usando só os dados que as ferramentas devolveram; se elas não trouxerem a informação, diga isso
- Não complete com o que você sabe: anos, durações, episódios, temporadas e detalhes de enredo entram na resposta só se vieram das ferramentas
- A sinopse faz parte desses dados: personagens, cenário e enredo escritos nela (inclusive em resultados anteriores da conversa) podem ser usados; diga que vieram da sinopse
- Cite os títulos e os números que sustentam a resposta (nota, episódios, votos de recomendação)
- Seja direto: uma lista curta com o motivo de cada indicação costuma bastar"""

FINAL_NUDGE = ("Limite de passos atingido. Responda agora com o que já foi encontrado, "
               "sem chamar mais ferramentas, e diga o que ficou faltando.")


@dataclass
class Step:
    tool: str
    args: dict | None
    result: str
    error: bool
    seconds: float


@dataclass
class Result:
    answer: str
    steps: list = field(default_factory=list)
    tokens: int = 0
    stop: str = "end"


class Agent:
    """Conversa com memória: cada pergunta continua o histórico do backend."""

    def __init__(self, backend, tools, max_steps=MAX_STEPS, on_step=None):
        self.backend = backend
        self.tools = tools
        self.max_steps = max_steps
        self.on_step = on_step  # callback(Step), para mostrar o progresso
        backend.start(SYSTEM, list(tools.specs.values()))

    def ask(self, question):
        self.backend.add_user(question)
        result = Result("")
        seen = {}  # chamadas repetidas devolvem o resultado anterior, sem executar de novo
        for _ in range(self.max_steps):
            turn = self.backend.step()
            result.tokens += turn.tokens
            if turn.stop == "refusal":
                result.answer, result.stop = "O modelo recusou responder a esta pergunta.", "refusal"
                return result
            if not turn.calls:
                result.answer, result.stop = turn.text, turn.stop
                return result
            outputs = []
            for call in turn.calls:
                key = (call.name, json.dumps(call.args, sort_keys=True))
                start = time.perf_counter()
                if key in seen:
                    text, is_error = seen[key]
                    text = f"(chamada repetida; mesmo resultado de antes) {text}"
                else:
                    text, is_error = self.tools.call(call.name, call.args)
                    seen[key] = (text, is_error)
                step = Step(call.name, call.args, text, is_error, time.perf_counter() - start)
                result.steps.append(step)
                if self.on_step:
                    self.on_step(step)
                outputs.append((call, text, is_error))
            self.backend.add_tool_results(outputs)

        self.backend.add_user(FINAL_NUDGE)
        turn = self.backend.step(allow_tools=False)
        result.tokens += turn.tokens
        result.answer, result.stop = turn.text, "max_steps"
        return result
