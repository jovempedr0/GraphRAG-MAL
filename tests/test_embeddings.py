import json

import httpx

from ingest.embed import embedding_text
from ingest.embeddings import EmbeddingClient


def make_client(model="bge-m3-mlx-fp16", batch_size=2):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        data = [{"index": i, "embedding": [float(len(t)), 0.0]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": data})

    client = EmbeddingClient(
        base_url="http://test/v1",
        api_key="k",
        model=model,
        batch_size=batch_size,
        transport=httpx.MockTransport(handler),
    )
    return client, seen


def test_embed_documents_batches_and_keeps_order():
    client, seen = make_client(batch_size=2)

    vectors = client.embed_documents(["a", "bb", "ccc"])

    assert vectors == [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
    assert [len(b["input"]) for b in seen] == [2, 1]
    assert seen[0]["model"] == "bge-m3-mlx-fp16"


def test_bge_m3_uses_no_prefix():
    client, seen = make_client()

    client.embed_query("pergunta")
    client.embed_documents(["texto"])

    assert seen[0]["input"] == ["pergunta"]
    assert seen[1]["input"] == ["texto"]


def test_jina_uses_task_prefixes():
    client, seen = make_client(model="jina-embeddings-v5-text-small-retrieval-mlx")

    client.embed_query("pergunta")
    client.embed_documents(["texto"])

    assert seen[0]["input"] == ["Query: pergunta"]
    assert seen[1]["input"] == ["Document: texto"]


def test_sorts_response_by_index():
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]})

    client = EmbeddingClient("http://test/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.embed_documents(["a", "b"]) == [[1.0], [2.0]]


def test_embedding_text_combines_title_genres_and_synopsis():
    text = embedding_text({
        "titulo": "Monster",
        "titulo_en": "Monster",
        "generos": ["Drama", "Mystery"],
        "sinopse": "Dr. Tenma...",
    })
    assert text == "Monster\nGêneros: Drama, Mystery\n\nDr. Tenma..."


def test_embedding_text_includes_english_title_when_different():
    text = embedding_text({
        "titulo": "Shingeki no Kyojin",
        "titulo_en": "Attack on Titan",
        "generos": [],
        "sinopse": "Humanity...",
    })
    assert text == "Shingeki no Kyojin (Attack on Titan)\n\nHumanity..."
