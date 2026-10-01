import json

from ingest.fetch import fetch_top
from ingest.mal import MalError


class FakeClient:
    def __init__(self, ranking, fail=()):
        self.ranking = ranking
        self.fail = set(fail)
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path in self.fail:
            raise MalError(path, 504)
        if path.endswith("/ranking"):
            start, size = params["offset"], params["limit"]
            page = self.ranking[start:start + size]
            has_next = start + size < len(self.ranking)
            return {
                "data": [{"node": {"id": i}} for i in page],
                "paging": {"next": "url"} if has_next else {},
            }
        return {"id": int(path.rsplit("/", 1)[1])}

    def paths(self):
        return [p for p, _ in self.calls]


def test_fetches_top_n_details(tmp_path):
    client = FakeClient([1, 2, 3, 4, 5, 6])

    ids = fetch_top(client, "anime", limit=4, state_dir=tmp_path)

    assert ids == [1, 2, 3, 4]
    assert "/anime/4" in client.paths()
    assert "/anime/5" not in client.paths()
    assert json.loads((tmp_path / "top_anime_ids.json").read_text()) == [1, 2, 3, 4]


def test_requests_kind_specific_fields(tmp_path):
    client = FakeClient([1])

    fetch_top(client, "manga", limit=1, state_dir=tmp_path)

    _, params = client.calls[-1]
    assert "recommendations" in params["fields"]
    assert "authors{first_name,last_name}" in params["fields"]


def test_pages_ranking_beyond_500(tmp_path):
    client = FakeClient(list(range(1, 701)))

    ids = fetch_top(client, "anime", limit=700, state_dir=tmp_path)

    assert ids == list(range(1, 701))
    offsets = [p["offset"] for path, p in client.calls if path.endswith("/ranking")]
    assert offsets == [0, 500]


def test_stops_when_no_next_page(tmp_path):
    client = FakeClient([1, 2])
    assert fetch_top(client, "manga", limit=10, state_dir=tmp_path) == [1, 2]


def test_records_failures_and_continues(tmp_path):
    client = FakeClient([1, 2], fail={"/anime/1"})

    fetch_top(client, "anime", limit=2, state_dir=tmp_path)

    assert "/anime/2" in client.paths()
    failures = json.loads((tmp_path / "failed_anime.json").read_text())
    assert failures == [{"path": "/anime/1", "status": 504}]
