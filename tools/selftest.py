"""Smoke test for the analysis engine on the bundled demo match."""
import json
import sys

sys.path.insert(0, ".")

from analyzer import analyze_match

raw = json.load(open("data/demo_match.json", encoding="utf-8"))
data = analyze_match(raw)

assert data["ok"] is True
assert data["match"]["id"] == 9078468447
assert len(data["players"]) == 10
assert len(data["timeline"]["prob"]) == len(data["timeline"]["gold"])
assert len(data["turning_points"]) >= 1
assert len(data["mistakes"]) >= 5
assert len(data["fights"]) >= 5

for team in ("radiant", "dire"):
    squad = [p for p in data["players"] if p["team"] == team]
    assert len(squad) == 5
    assert abs(sum(p["blame_share"] for p in squad) - 100) < 0.6
    for p in squad:
        assert 0 <= p["blame"] <= 100
        for grade in p["grades"].values():
            assert 0 <= grade <= 100
        # every referenced death belongs to the player
        assert all(d["time_label"] for d in p["death_log"])
        assert p["deaths"] == len(p["death_log"])

assert all(1 <= m["severity"] <= 5 for m in data["mistakes"])
assert all(m["player_id"] in {p["id"] for p in data["players"]} for m in data["mistakes"] if m["player_id"])
assert len(data["draft"]["picks"]) == 10
assert {p["team"] for p in data["draft"]["picks"]} == {"radiant", "dire"}
assert isinstance(data["chat"], list)
assert isinstance(data["wisdom_runes"], list)
assert isinstance(data["conduct"]["players"], list)
assert data["match"]["average_rank"]

print("OK: demo match analyzed")
print("winner:", data["match"]["winner_word"], data["match"]["score"])
print("culprit:", data["verdict"]["culprit"]["hero"], data["verdict"]["culprit"]["blame"], "%", data["verdict"]["culprit"]["share"])
print("mistakes:", len(data["mistakes"]), "| turning points:", len(data["turning_points"]))
