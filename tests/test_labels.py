import labels


def test_votes_round_trip_and_latest_wins(tmp_path):
    f = tmp_path / "labels.jsonl"
    labels.add("C:/x/a.replay", "nobody_back", 12.34, False, 3, "Nobody back", path=f)
    labels.add("C:/x/a.replay", "nobody_back", 12.34, True, 3, "Nobody back", path=f)     # same event, changed mind
    labels.add("C:/x/a.replay", "goal", 40.0, True, 3, "Goal", path=f)
    rows = labels.load(f)
    assert [(r["kind"], r["right"]) for r in rows] == [("nobody_back", True), ("goal", True)]
    assert rows[0]["replay"] == "a.replay"


def test_load_skips_damaged_lines_and_missing_file(tmp_path):
    f = tmp_path / "labels.jsonl"
    f.write_text("not json\n{\"kind\": 1}\n", encoding="utf-8")
    assert labels.load(f) == []
    assert labels.load(tmp_path / "nope.jsonl") == []


def test_precision_per_kind():
    rows = [{"kind": "k", "right": True}, {"kind": "k", "right": True}, {"kind": "k", "right": False, "at": 1},
            {"kind": "j", "right": False, "at": 2}]
    p = labels.precision(rows)
    assert p["k"]["n"] == 3 and abs(p["k"]["precision"] - 2 / 3) < 1e-9 and len(p["k"]["wrong"]) == 1
    assert p["j"]["precision"] == 0
