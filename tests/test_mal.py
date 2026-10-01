import httpx
import pytest

from ingest.mal import MalClient, MalError


class FakeClock:
    """Relógio controlado: sleep só avança o tempo, sem esperar de verdade."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(tmp_path, handler, **kwargs):
    clock = FakeClock()
    client = MalClient(
        client_id="test",
        cache_dir=tmp_path,
        transport=httpx.MockTransport(handler),
        clock=clock.time,
        sleep=clock.sleep,
        **kwargs,
    )
    return client, clock


def test_get_returns_json_and_writes_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json={"data": {"mal_id": 19}})

    client, _ = make_client(tmp_path, handler)

    assert client.get("/anime/19/full") == {"data": {"mal_id": 19}}
    assert (tmp_path / "anime" / "19" / "full.json").exists()

    # Segunda chamada vem do cache, sem requisição
    assert client.get("/anime/19/full") == {"data": {"mal_id": 19}}
    assert len(calls) == 1


def test_cache_key_includes_params(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"page": request.url.params["page"]})

    client, _ = make_client(tmp_path, handler)

    assert client.get("/top/anime", {"page": 1}) == {"page": "1"}
    assert client.get("/top/anime", {"page": 2}) == {"page": "2"}
    assert (tmp_path / "top" / "anime" / "page=1.json").exists()


def test_rate_limit_spaces_requests(tmp_path):
    client, clock = make_client(
        tmp_path, lambda r: httpx.Response(200, json={}), min_interval=1.0
    )

    client.get("/a")
    client.get("/b")
    client.get("/c")

    assert clock.sleeps == [1.0, 1.0]


@pytest.mark.parametrize("status", [307, 429, 500, 503, 504])
def test_retries_transient_errors_with_backoff(tmp_path, status):
    responses = iter([httpx.Response(status), httpx.Response(status), httpx.Response(200, json={"ok": True})])
    client, clock = make_client(
        tmp_path, lambda r: next(responses), min_interval=0, backoff_base=2.0
    )

    assert client.get("/x") == {"ok": True}
    assert clock.sleeps == [2.0, 4.0]


def test_respects_retry_after_header(tmp_path):
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})])
    client, clock = make_client(tmp_path, lambda r: next(responses), min_interval=0)

    client.get("/x")
    assert clock.sleeps == [7.0]


def test_gives_up_after_max_retries_and_does_not_cache(tmp_path):
    client, _ = make_client(
        tmp_path, lambda r: httpx.Response(504), min_interval=0, max_retries=3
    )

    with pytest.raises(MalError) as exc:
        client.get("/anime/1")
    assert exc.value.status == 504
    assert not (tmp_path / "anime" / "1.json").exists()


def test_does_not_retry_404(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    client, _ = make_client(tmp_path, handler, min_interval=0)

    with pytest.raises(MalError) as exc:
        client.get("/anime/999999/full")
    assert exc.value.status == 404
    assert len(calls) == 1


def test_retries_network_errors(tmp_path):
    attempts = iter([httpx.ConnectError("boom"), None])

    def handler(request):
        err = next(attempts)
        if err:
            raise err
        return httpx.Response(200, json={"ok": True})

    client, _ = make_client(tmp_path, handler, min_interval=0)
    assert client.get("/x") == {"ok": True}


def test_sends_client_id_header(tmp_path):
    seen = {}

    def handler(request):
        seen["id"] = request.headers.get("X-MAL-CLIENT-ID")
        return httpx.Response(200, json={})

    client, _ = make_client(tmp_path, handler)
    client.get("/anime/19")
    assert seen["id"] == "test"


def test_fields_param_is_sent_but_not_in_cache_name(tmp_path):
    seen = {}

    def handler(request):
        seen["fields"] = request.url.params.get("fields")
        return httpx.Response(200, json={})

    client, _ = make_client(tmp_path, handler)
    client.get("/anime/19", {"fields": "mean,genres"})
    assert seen["fields"] == "mean,genres"
    assert (tmp_path / "anime" / "19.json").exists()


def test_requires_client_id(tmp_path, monkeypatch):
    monkeypatch.delenv("MAL_CLIENT_ID", raising=False)
    with pytest.raises(ValueError):
        MalClient(cache_dir=tmp_path)


def test_forbidden_is_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, json={"error": "forbidden"})

    client, _ = make_client(tmp_path, handler, min_interval=0)
    with pytest.raises(MalError) as exc:
        client.get("/anime/19")
    assert exc.value.status == 403
    assert len(calls) == 1
