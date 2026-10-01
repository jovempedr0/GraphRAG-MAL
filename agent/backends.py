"""Backends de tool use: o mesmo loop roda com o modelo local (oMLX) ou com o Claude.

Cada backend guarda o histórico no formato nativo da sua API e só cresce por append.
No Claude isso importa: a resposta inteira (com os blocos de thinking) volta no histórico.
"""
import json
import os
from dataclasses import dataclass, field

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict | None  # None quando o JSON dos argumentos veio inválido
    raw_args: str = ""


@dataclass
class Turn:
    text: str
    calls: list = field(default_factory=list)
    stop: str = "end"  # "end" | "tool_use" | "refusal" | "max_tokens"
    tokens: int = 0


def tool_spec(name, description, parameters):
    """Ferramenta no formato neutro; cada backend converte para o seu."""
    return {"name": name, "description": description, "parameters": parameters}


class OmlxBackend:
    """API compatível com OpenAI (/v1/chat/completions), servida pelo oMLX."""

    def __init__(self, base_url, api_key, model, max_tokens=4096, timeout=600.0, transport=None):
        self.model = model
        self.max_tokens = max_tokens
        self.messages = []
        self.tools = []
        self._http = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"},
                                  timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, model=None):
        return cls(os.environ["OMLX_BASE_URL"], os.environ["OMLX_API_KEY"],
                   model or os.environ.get("AGENT_MODEL") or os.environ["CYPHER_MODEL"])

    def start(self, system, tools):
        self.messages = [{"role": "system", "content": system}]
        self.tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in tools]

    def add_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def step(self, allow_tools=True):
        body = {"model": self.model, "messages": self.messages, "temperature": 0,
                "max_tokens": self.max_tokens, "tools": self.tools,
                "tool_choice": "auto" if allow_tools else "none"}
        resp = self._http.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        raw_calls = msg.get("tool_calls") or []
        assistant = {"role": "assistant", "content": msg.get("content") or ""}
        if raw_calls:
            assistant["tool_calls"] = raw_calls
        self.messages.append(assistant)

        calls = []
        for c in raw_calls:
            raw = c["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
                args = args if isinstance(args, dict) else None
            except json.JSONDecodeError:
                args = None
            calls.append(ToolCall(c["id"], c["function"]["name"], args, raw))
        stop = "tool_use" if calls else ("max_tokens" if choice.get("finish_reason") == "length" else "end")
        return Turn(msg.get("content") or "", calls, stop, data.get("usage", {}).get("total_tokens", 0))

    def add_tool_results(self, results):
        """results: lista de (ToolCall, conteúdo em texto, é_erro)."""
        for call, content, is_error in results:
            self.messages.append({"role": "tool", "tool_call_id": call.id,
                                  "content": f"ERRO: {content}" if is_error else content})


class AnthropicBackend:
    """Claude via SDK oficial (manual loop: o mesmo controle de passos do backend local)."""

    DEFAULT_MODEL = "claude-opus-5-5"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, model=None, effort="medium", max_tokens=16000, client=None):
        if client is None:
            import anthropic  # só carrega o SDK quando este backend é usado
            client = anthropic.Anthropic()
        self.client = client
        self.model = model or self.DEFAULT_MODEL
        self.effort = effort
        self.max_tokens = max_tokens
        self.system = ""
        self.tools = []
        self.messages = []

    @classmethod
    def from_env(cls, model=None):
        return cls(model=model or os.environ.get("AGENT_MODEL") or None,
                   effort=os.environ.get("AGENT_EFFORT", "medium"))

    def start(self, system, tools):
        self.system = system
        self.tools = [{"name": t["name"], "description": t["description"],
                       "input_schema": t["parameters"]} for t in tools]
        self.messages = []

    def add_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def step(self, allow_tools=True):
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            tools=self.tools,
            tool_choice={"type": "auto"} if allow_tools else {"type": "none"},
            messages=self.messages,
            output_config={"effort": self.effort},
            # Recusa dos classificadores de segurança: refaz no modelo recomendado pela Anthropic.
            betas=[self.FALLBACK_BETA],
            fallbacks="default",
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        if response.stop_reason == "refusal":
            return Turn("", [], "refusal", tokens)
        # Resposta inteira no histórico (thinking incluído), sem editar nada depois.
        self.messages.append({"role": "assistant", "content": response.content})
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else None,
                          json.dumps(b.input, ensure_ascii=False))
                 for b in response.content if b.type == "tool_use"]
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens"}.get(response.stop_reason, "end")
        return Turn(text, calls, stop if not calls else "tool_use", tokens)

    def add_tool_results(self, results):
        # Todos os resultados numa única mensagem de usuário (separar desestimula chamadas paralelas).
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
            for call, content, is_error in results]})


def backend_from_env():
    name = os.environ.get("AGENT_BACKEND", "omlx")
    if name == "omlx":
        return OmlxBackend.from_env()
    if name == "anthropic":
        return AnthropicBackend.from_env()
    raise ValueError(f"AGENT_BACKEND desconhecido: {name} (use omlx ou anthropic)")
