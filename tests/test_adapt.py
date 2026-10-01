from ingest.adapt import adaptations, match, build_index, norm_title, reverse_search


def anime(id, title, source="manga", ja=None, en=None, sequels=()):
    return {"id": id, "title": title, "source": source,
            "alternative_titles": {"ja": ja, "en": en},
            "related_anime": [{"node": {"id": s}, "relation_type": "sequel"} for s in sequels]}


def manga(id, title, media_type="manga", ja=None, en=None):
    return {"id": id, "title": title, "media_type": media_type, "alternative_titles": {"ja": ja, "en": en}}


def test_norm_title_strips_season_and_punctuation():
    assert norm_title("Shingeki no Kyojin Season 2") == norm_title("Shingeki no Kyojin")
    assert norm_title("Haikyuu!! 2nd Season") == "haikyuu"
    assert norm_title("進撃の巨人 第2期") == norm_title("進撃の巨人")
    assert norm_title("Ｍｏｎｓｔｅｒ") == "monster"


def test_match_by_japanese_title():
    mangas = {10: manga(10, "Sousou no Frieren", ja="葬送のフリーレン")}
    a = anime(1, "Frieren: Beyond Journey's End", ja="葬送のフリーレン")
    assert match(a, build_index(mangas), mangas) == 10


def test_source_type_decides_between_candidates():
    mangas = {10: manga(10, "Kusuriya no Hitorigoto", "light_novel"),
              11: manga(11, "Kusuriya no Hitorigoto", "manga")}
    index = build_index(mangas)
    assert match(anime(1, "Kusuriya no Hitorigoto", "light_novel"), index, mangas) == 10
    assert match(anime(2, "Kusuriya no Hitorigoto", "manga"), index, mangas) == 11


def test_incompatible_or_original_source_is_not_matched():
    mangas = {10: manga(10, "Steins;Gate", "manga")}
    index = build_index(mangas)
    assert match(anime(1, "Steins;Gate", "visual_novel"), index, mangas) is None
    assert match(anime(2, "Steins;Gate", "original"), index, mangas) is None


def test_sequel_chain_inherits_adaptation():
    mangas = {10: manga(10, "Gintama")}
    animes = {1: anime(1, "Gintama", sequels=[2]),
              2: anime(2, "Gintama: Enchousen", sequels=[3]),
              3: anime(3, "Gintama: The Final")}
    result = adaptations(animes, mangas)
    assert result == {1: (10, "titulo"), 2: (10, "sequencia"), 3: (10, "sequencia")}


def test_chain_does_not_cross_different_sources():
    mangas = {10: manga(10, "X")}
    animes = {1: anime(1, "X", sequels=[2]), 2: anime(2, "X Movie", source="original")}
    assert 2 not in adaptations(animes, mangas)


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get(self, path, params):
        self.calls.append(params["q"])
        return {"data": [{"node": n} for n in self.results.get(params["q"], [])]}


def test_reverse_search_only_for_unadapted_and_compatible():
    mangas = {10: manga(10, "Vagabond", ja="バガボンド"), 11: manga(11, "Monster")}
    client = FakeClient({"Vagabond": [{"id": 5, "title": "Vagabond Movie", "source": "original",
                                       "alternative_titles": {"ja": "バガボンド"}},
                                      {"id": 6, "title": "Bagabondo", "source": "manga",
                                       "alternative_titles": {"ja": "バガボンド"}}]})
    found = reverse_search(client, mangas, adapted_mangas={11}, top_manga_ids=[10, 11])
    assert found == [6]
    assert client.calls == ["Vagabond"]
