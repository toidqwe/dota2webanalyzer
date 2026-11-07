"""Build the static GitHub Pages demo from the live analyzer."""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")

from analyzer import analyze_match

ROOT = Path(".")
DOCS = ROOT / "docs"
WEB = ROOT / "web"
DATA = ROOT / "data"
CACHE = DATA / "cache"

MATCHES = [9078468447, 9078923915, 9074607307]


def rewrite(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "img" and isinstance(item, str) and item.startswith("/img/"):
                out[key] = item[len("/") :]
            else:
                out[key] = rewrite(item)
        return out
    if isinstance(value, list):
        return [rewrite(item) for item in value]
    return value


def analysis_for(match_id: int) -> dict:
    if match_id == 9078468447:
        raw = json.loads((DATA / "demo_match.json").read_text(encoding="utf-8"))
    else:
        raw = json.loads((CACHE / f"{match_id}.json").read_text(encoding="utf-8"))
    return analyze_match(raw)


def main():
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data" / "matches").mkdir(parents=True, exist_ok=True)
    (DOCS / "img").mkdir(exist_ok=True)

    # Static asset copies.
    for name in ("style.css", "charts.js", "app.js"):
        shutil.copy2(WEB / name, DOCS / name)
    if (DOCS / "img").exists():
        shutil.rmtree(DOCS / "img")
    shutil.copytree(WEB / "img", DOCS / "img")

    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/style.css"', 'href="style.css"')
    html = html.replace('src="/charts.js"', 'src="charts.js"')
    html = html.replace('src="/app.js"', 'src="app.js"')
    html = html.replace(
        '<script src="charts.js"></script>',
        '<script>window.OTA_STATIC = true;</script>\n  <script src="charts.js"></script>',
    )
    api_base = os.environ.get("OTA_API_BASE", "").strip().rstrip("/")
    if api_base:
        html = html.replace(
            '<script>window.OTA_STATIC = true;</script>',
            f'<script>window.OTA_STATIC = true; window.OTA_API_BASE = {json.dumps(api_base)};</script>',
        )
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    analyses = {}
    history = []
    for match_id in MATCHES:
        analysis = rewrite(analysis_for(match_id))
        analyses[match_id] = analysis
        payload = {"ok": True, "analysis": analysis, "cached": True}
        if match_id == 9078468447:
            path = DOCS / "data" / "demo.json"
        else:
            path = DOCS / "data" / "matches" / f"{match_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        match = analysis["match"]
        heroes = [{"name": p["hero"]["name"], "img": p["hero"]["img"]} for p in analysis["players"]]
        history.append(
            {
                "id": match["id"],
                "date": match.get("date"),
                "duration": match.get("duration_label"),
                "score": f"{match['score']['radiant']}:{match['score']['dire']}",
                "winner": match["winner"],
                "winner_word": match["winner_word"],
                "heroes": heroes,
                "ts": 0,
            }
        )
    (DOCS / "data" / "history.json").write_text(
        json.dumps({"ok": True, "items": history}, ensure_ascii=False), encoding="utf-8"
    )
    print("built", DOCS, "matches", len(analyses))


if __name__ == "__main__":
    main()
