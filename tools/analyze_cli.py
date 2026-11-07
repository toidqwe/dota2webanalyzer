import json
import sys
import urllib.request

sys.path.insert(0, ".")

from analyzer import analyze_match


def load(arg: str) -> dict:
    if arg.isdigit():
        url = f"https://api.opendota.com/api/matches/{arg}"
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    with open(arg, encoding="utf-8") as fh:
        return json.load(fh)


raw = load(sys.argv[1] if len(sys.argv) > 1 else "data/demo_match.json")
data = analyze_match(raw)
out = sys.argv[2] if len(sys.argv) > 2 else "data/analysis_sample.json"
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=1)

v = data["verdict"]
print("MATCH", data["match"]["id"], data["match"]["duration_label"], data["match"]["score"])
print("WINNER", data["match"]["winner_word"])
for line in v["summary"]:
    print("SUMMARY:", line)
print("\nCULPRIT:", v["culprit"]["hero"], v["culprit"]["blame"], v["culprit"]["share"])
for b in v["culprit"]["bullets"]:
    print("  -", b)
print("MVP:", v["mvp"]["hero"], v["mvp"]["credit"])
print("\nPLAYERS:")
for p in sorted(data["players"], key=lambda x: -x["blame"]):
    print(
        f"  {p['team'][:3]} {p['hero']['name'][:18]:18} pos{p['position']} "
        f"KDA {p['kills']}/{p['deaths']}/{p['assists']} GPM {p['gpm']} "
        f"blame {p['blame']:5} share {p['blame_share']:4} grades {p['grades']}"
    )
print("\nMISTAKES:", len(data["mistakes"]))
for m in data["mistakes"][:14]:
    pid = m["player_id"]
    p = next((x for x in data["players"] if x["id"] == pid), None)
    print(f"  [{m['severity']}] {m['time_label']} {p['hero']['name'] if p else 'TEAM'}: {m['title']} | {m['text'][:130]}")
print("\nTURNING POINTS:")
for t in data["turning_points"]:
    print(f"  {t['time']} {t['title']} {t['prob_before']}в†’{t['prob_after']} {t['text'][:150]}")
print("\nLANES:")
for ln in data["lanes"]:
    print(" ", ln["title"], ln["diff"], ln["winner"])

