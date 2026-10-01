"""Cliente de chat para um servidor compatível com a API da OpenAI (aqui, o oMLX local)."""
import os

import httpx

# Parâmetros extras por modelo. Os Qwen3 pensam por padrão e põem o raciocínio na resposta.
MODEL_OPTIONS = {
    "Qwen3-14B-4bit": {"chat_template_kwargs": {"enable_thinking": False}},
    "Qwen3.6-35B-A3B-OptiQ-4bit-REAP-19B": {"chat_template_kwargs": {"enable_thinking": False}},
}


class ChatClient:
    def __init__(self, base_url, api_key, model, max_tokens=4096, timeout=600.0, transport=None):
        self.model = model
        self.max_tokens = max_tokens
        self.options = MODEL_OPTIONS.get(model, {})
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_env(cls, model=None):
        return cls(
            base_url=os.environ["OMLX_BASE_URL"],
            api_key=os.environ["OMLX_API_KEY"],
            model=model or os.environ["CYPHER_MODEL"],
        )

    def complete(self, messages):
        """Devolve (texto, uso de tokens)."""
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            **self.options,
        }
        resp = self._http.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"].get("content") or "", data.get("usage", {})
