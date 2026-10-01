from ingest.load import anime_row, clean_synopsis, manga_row, related

ANIME = {
    "id": 5114,
    "title": "Fullmetal Alchemist: Brotherhood",
    "alternative_titles": {"en": "Fullmetal Alchemist: Brotherhood", "ja": "鋼の錬金術師"},
    "synopsis": "After a horrific alchemy experiment...\n\n[Written by MAL Rewrite]",
    "mean": 9.11,
    "rank": 1,
    "popularity": 3,
    "num_list_users": 3500000,
    "media_type": "tv",
    "status": "finished_airing",
    "start_date": "2009-04-05",
    "start_season": {"year": 2009, "season": "spring"},
    "num_episodes": 64,
    "source": "manga",
    "genres": [{"id": 1, "name": "Action"}, {"id": 27, "name": "Shounen"}],
    "studios": [{"id": 4, "name": "Bones"}],
    "recommendations": [
        {"node": {"id": 11061, "title": "Hunter x Hunter (2011)"}, "num_recommendations": 78},
    ],
}

MANGA = {
    "id": 1,
    "title": "Monster",
    "alternative_titles": {"en": "Monster"},
    "synopsis": "Kenzou Tenma...\n\n(Source: Viz Media)",
    "mean": 9.16,
    "rank": 5,
    "popularity": 30,
    "num_list_users": 300000,
    "media_type": "manga",
    "status": "finished",
    "start_date": "1994-12-05",
    "num_chapters": 162,
    "num_volumes": 18,
    "genres": [{"id": 8, "name": "Drama"}],
    "authors": [{"node": {"id": 1867, "first_name": "Naoki", "last_name": "Urasawa"}, "role": "Story & Art"}],
    "recommendations": [],
}


def test_anime_row_maps_properties():
    row = anime_row(ANIME)

    assert row["mal_id"] == 5114
    assert row["props"] == {
        "titulo": "Fullmetal Alchemist: Brotherhood",
        "titulo_en": "Fullmetal Alchemist: Brotherhood",
        "sinopse": "After a horrific alchemy experiment...",
        "nota": 9.11,
        "rank": 1,
        "popularidade": 3,
        "membros": 3500000,
        "tipo": "tv",
        "status": "finished_airing",
        "ano": 2009,
        "episodios": 64,
        "fonte": "manga",
    }


def test_anime_row_maps_relationships():
    row = anime_row(ANIME)

    assert row["generos"] == ["Action", "Shounen"]
    assert row["estudios"] == [{"mal_id": 4, "nome": "Bones"}]
    assert row["recomendacoes"] == [{"mal_id": 11061, "titulo": "Hunter x Hunter (2011)", "votos": 78}]


def test_manga_row():
    row = manga_row(MANGA)

    assert row["props"]["capitulos"] == 162
    assert row["props"]["volumes"] == 18
    assert row["props"]["ano"] == 1994
    assert row["props"]["sinopse"] == "Kenzou Tenma..."
    assert row["autores"] == [{"mal_id": 1867, "nome": "Naoki Urasawa", "papel": "Story & Art"}]


def test_missing_optional_fields_become_none():
    row = anime_row({"id": 1, "title": "X"})

    assert row["props"]["nota"] is None
    assert row["props"]["ano"] is None
    assert row["generos"] == []
    assert row["recomendacoes"] == []


def test_year_falls_back_to_start_date():
    row = anime_row({"id": 1, "title": "X", "start_date": "1998"})
    assert row["props"]["ano"] == 1998


def test_clean_synopsis_strips_credits():
    assert clean_synopsis("Texto.\n\n[Written by MAL Rewrite]") == "Texto."
    assert clean_synopsis("Texto.\n\n(Source: Crunchyroll)") == "Texto."
    assert clean_synopsis("Texto (com parênteses) no meio.") == "Texto (com parênteses) no meio."
    assert clean_synopsis(None) is None
    assert clean_synopsis("") is None


def test_zero_counts_mean_unknown():
    assert anime_row({"id": 1, "title": "X", "num_episodes": 0})["props"]["episodios"] is None
    row = manga_row({"id": 1, "title": "X", "num_chapters": 0, "num_volumes": 0})
    assert row["props"]["capitulos"] is None
    assert row["props"]["volumes"] is None


def rel(mal_id, tipo):
    return {"node": {"id": mal_id, "title": f"T{mal_id}"}, "relation_type": tipo}


def test_related_keeps_direct_types_as_outgoing():
    # Na página do 10: "Sequel: 20" → 20 é sequência de 10 → (10)-[sequel]->(20)
    assert related(10, [rel(20, "sequel")]) == [
        {"mal_id": 20, "titulo": "T20", "tipo": "sequel", "saida": True}
    ]


def test_related_flips_inverse_types():
    # "Prequel: 5" na página do 10 → 10 é sequência de 5 → (5)-[sequel]->(10)
    out = related(10, [rel(5, "prequel"), rel(6, "parent_story"), rel(7, "full_story")])
    assert [(r["tipo"], r["saida"]) for r in out] == [
        ("sequel", False), ("side_story", False), ("summary", False)
    ]


def test_related_symmetric_types_point_from_lower_id():
    out = related(10, [rel(5, "alternative_version"), rel(20, "other")])
    assert [(r["mal_id"], r["saida"]) for r in out] == [(5, False), (20, True)]


def test_rows_include_same_kind_relations():
    assert anime_row({"id": 1, "title": "X", "related_anime": [rel(2, "sequel")]})["relacionados"][0]["mal_id"] == 2
    assert manga_row({"id": 1, "title": "X", "related_manga": [rel(3, "spin_off")]})["relacionados"][0]["tipo"] == "spin_off"


def test_read_rows_marks_top_and_includes_crawled(tmp_path):
    import json as _json
    from ingest.load import read_rows
    (tmp_path / "state").mkdir()
    (tmp_path / "raw" / "anime").mkdir(parents=True)
    (tmp_path / "state" / "top_anime_ids.json").write_text("[1]")
    (tmp_path / "state" / "crawl_anime_ids.json").write_text("[2, 1, 3]")
    for i in (1, 2):
        (tmp_path / "raw" / "anime" / f"{i}.json").write_text(_json.dumps({"id": i, "title": f"t{i}"}))
    rows = read_rows("anime", raw_dir=tmp_path / "raw", state_dir=tmp_path / "state")
    assert [(r["mal_id"], r["top"]) for r in rows] == [(1, True), (2, False)]
