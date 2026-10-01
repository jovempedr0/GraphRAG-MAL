"""Cliente de embeddings para um servidor compatível com a API da OpenAI (aqui, o oMLX local)."""
import os

import httpx

# Alguns modelos foram treinados com prefixos de tarefa (pergunta vs. documento).
# (prefixo da pergunta, prefixo do documento); modelos fora da lista não usam prefixo.
TASK_PREFIXES = {
    "jina-embeddings-v5-text-small-retrieval-mlx": ("Query: ", "Document: "),
}


class EmbeddingClient:
    def __init__(self, base_url, api_key, model, batch_size=32, timeout=300.0, transport=None):
        self.model = model
        self.batch_size = batch_size
        self.query_prefix, self.doc_prefix = TASK_PREFIXES.get(model, ("", ""))
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_env(cls):
        return cls(
            base_url=os.environ["OMLX_BASE_URL"],
            api_key=os.environ["OMLX_API_KEY"],
            model=os.environ["EMBEDDING_MODEL"],
        )

    def embed_query(self, text):
        return self._embed([self.query_prefix + text])[0]

    def embed_documents(self, texts):
        vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = [self.doc_prefix + t for t in texts[i:i + self.batch_size]]
            vectors.extend(self._embed(batch))
        return vectors

    def _embed(self, texts):
        resp = self._http.post("/embeddings", json={"model": self.model, "input": texts})
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]
