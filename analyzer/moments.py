"""Win probability, turning points, phases and comeback detection."""

from __future__ import annotations

import math
from collections import Counter

from .format import fmt_pct, fmt_signed, fmt_time
from .normalize import Match, clamp


def win_probability(match: Match) -> list[float]:
    """Radiant win probability per minute from the gold/XP advantage."""
    probs = []
    for minute, gold in enumerate(match.gold_adv):
        xp = match.xp_adv[minute] if minute < len(match.xp_adv) else 0.0
        scale = 1700.0 + 85.0 * minute
        effective = gold + 0.35 * xp
        p = 100.0 / (1.0 + math.exp(-effective / scale))
        probs.append(round(clamp(p, 2.0, 98.0), 1))
    return probs


def _prob_for(probs: list[float], team: str, minute: int) -> float:
    idx = max(0, min(len(probs) - 1, minute))
    value = probs[idx]
    return value if team == "radiant" else 100.0 - value


def _team_swing(match: Match, team: str, start: int, end: int) -> float:
    a = match.gold_for(team, start)
    b = match.gold_for(team, end)
    return b - a


def _fight_line(fight, radiant_win: bool) -> str:
    winner = fight.winner
    if winner == "draw":
        return f"размен {fight.radiant_deaths}:{fight.dire_deaths}"
    team = "Radiant" if winner == "radiant" else "Dire"
    return f"{team} выигрывает драку {fight.radiant_deaths}:{fight.dire_deaths}"


def _window_events(match: Match, start: int, end: int) -> dict:
    start_s, end_s = start * 60, end * 60
    fights = [f for f in match.fights if start_s <= f.start <= end_s and f.major]
    buildings = [o for o in match.objectives if o.kind == "building" and start_s <= o.time <= end_s]
    roshans = [o for o in match.objectives if o.kind == "roshan" and start_s <= o.time <= end_s]
    aegis = [o for o in match.objectives if o.kind == "aegis" and start_s <= o.time <= end_s]
    deaths = [d for d in match.deaths if start_s <= d.time <= end_s]
    return {
        "fights": fights,
        "buildings": buildings,
        "roshans": roshans,
        "aegis": aegis,
        "deaths": deaths,
    }


def _key_death(match: Match, deaths, team: str):
    candidates = [d for d in deaths if match.player(d.victim_id).team == team]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.gold_lost + d.gold_fed + d.time_dead * 10)


def turning_points(match: Match, probs: list[float], limit: int = 5) -> list[dict]:
    n = len(probs)
    if n < 3:
        return []
    window = 3 if n > 22 else 2
    window = min(window, n - 1)
    candidates = []
    for start in range(1, n - window):
        end = start + window
        delta = probs[end] - probs[start]
        if abs(delta) < 8.5:
            continue
        candidates.append((abs(delta), start, end, delta))
    candidates.sort(reverse=True)
    chosen = []
    for _, start, end, delta in candidates:
        if any(abs(start - c[1]) < 3 for c in chosen):
            continue
        chosen.append((abs(delta), start, end, delta))
        if len(chosen) >= limit:
            break

    points = []
    for _, start, end, delta in sorted(chosen, key=lambda c: c[1]):
        events = _window_events(match, start, end)
        beneficiary = "radiant" if delta > 0 else "dire"
        loser = "dire" if beneficiary == "radiant" else "radiant"
        fight = max(events["fights"], key=lambda f: f.deaths, default=None)
        roshan = events["roshans"][0] if events["roshans"] else None
        building = max(events["buildings"], key=lambda o: 1 if "Бараки" in o.label or o.label == "Трон" else 0, default=None)
        key_death = _key_death(match, events["deaths"], loser)

        parts = []
        kind = "economy"
        benef_word = "Radiant" if beneficiary == "radiant" else "Dire"
        if fight and fight.winner == beneficiary:
            kind = "fight"
            parts.append(_fight_line(fight, match.radiant_win))
            fight_swing = fight.gold_swing if beneficiary == "radiant" else -fight.gold_swing
            parts.append(f"размен золота в драке {fmt_signed(fight_swing)}")
        if roshan and roshan.team == beneficiary:
            kind = "fight" if kind == "fight" else "roshan"
            parts.append(f"{benef_word} забирает Рошана")
            if events["aegis"]:
                owner = events["aegis"][0].player_id
                if owner:
                    parts.append(f"аегис у {match.player(owner).hero_name}")
        if building and building.team == beneficiary:
            kind = "objective" if kind == "economy" else kind
            parts.append(f"{benef_word} сносит {building.label}")
        if key_death:
            victim = match.player(key_death.victim_id)
            parts.append(f"ключевая смерть — {victim.hero_name} ({fmt_signed(-(key_death.gold_lost + key_death.gold_fed))})")
        if not parts:
            swing = _team_swing(match, beneficiary, start, end)
            parts.append(f"экономика {fmt_signed(swing)} без крупных драк")

        gold_swing = _team_swing(match, beneficiary, start, end)
        p_before = _prob_for(probs, beneficiary, start)
        p_after = _prob_for(probs, beneficiary, end)
        event_time = fight.start if fight else roshan.time if roshan else building.time if building else start * 60
        title = {
            "fight": f"Драка на {fmt_time(event_time)}",
            "roshan": f"Рошан на {fmt_time(event_time)}",
            "objective": f"Объект на {fmt_time(event_time)}",
            "economy": f"Перелом на {fmt_time(event_time)}",
        }[kind]
        points.append(
            {
                "minute": start,
                "event_time": int(event_time),
                "end_minute": end,
                "time": fmt_time(event_time),
                "kind": kind,
                "title": title,
                "beneficiary": beneficiary,
                "text": ", ".join(parts) + f". Шансы { 'Radiant' if beneficiary == 'radiant' else 'Dire'} выросли с {p_before:.0f}% до {p_after:.0f}%.",
                "prob_before": round(p_before, 1),
                "prob_after": round(p_after, 1),
                "delta_prob": round(delta, 1),
                "gold_swing": int(gold_swing),
                "key_death": key_death.victim_id if key_death else None,
                "fight_index": fight.index if fight else None,
                "roshan": bool(roshan),
                "building": building.label if building else None,
                "severity": round(abs(delta), 1),
            }
        )
    return points


def choke_info(match: Match, probs: list[float]) -> dict | None:
    loser = "dire" if match.radiant_win else "radiant"
    series = [_prob_for(probs, loser, i) for i in range(len(probs))]
    peak = max(series)
    if peak < 65:
        return None
    peak_minute = series.index(peak)
    after = series[peak_minute:]
    low_idx = None
    for i, value in enumerate(after):
        if value <= 25:
            low_idx = peak_minute + i
            break
    drop = peak - (series[low_idx] if low_idx is not None else series[-1])
    return {
        "team": loser,
        "peak": round(peak, 1),
        "peak_minute": peak_minute,
        "peak_time": fmt_time(peak_minute * 60),
        "collapse_minute": low_idx if low_idx is not None else len(series) - 1,
        "drop": round(drop, 1),
    }


def phases(match: Match, probs: list[float]) -> list[dict]:
    duration_min = max(1, match.duration // 60)
    if duration_min <= 22:
        bounds = [(0, 10, "Лейнинг"), (10, max(12, duration_min // 2), "Середина"), (max(12, duration_min // 2), duration_min, "Концовка")]
    else:
        bounds = [(0, 10, "Лейнинг"), (10, 25, "Середина"), (25, duration_min, "Лейт")]
    out = []
    for start, end, name in bounds:
        if end <= start:
            continue
        start = min(start, len(match.gold_adv) - 1)
        end = min(end, len(match.gold_adv) - 1)
        gold_start = match.gold_for("radiant", start)
        gold_end = match.gold_for("radiant", end)
        fights = [f for f in match.fights if start * 60 <= f.start <= end * 60 and f.major]
        radiant_fight_wins = sum(1 for f in fights if f.winner == "radiant")
        dire_fight_wins = sum(1 for f in fights if f.winner == "dire")
        objectives = [o for o in match.objectives if start * 60 <= o.time <= end * 60]
        buildings = [o for o in objectives if o.kind == "building"]
        roshans = [o for o in objectives if o.kind == "roshan"]
        p_start = probs[start]
        p_end = probs[end]
        leader = "radiant" if gold_end > 0 else "dire"
        out.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "gold_start": int(gold_start),
                "gold_end": int(gold_end),
                "gold_delta": int(gold_end - gold_start),
                "leader": leader,
                "radiant_fight_wins": radiant_fight_wins,
                "dire_fight_wins": dire_fight_wins,
                "fights": len(fights),
                "buildings": len(buildings),
                "roshans": len(roshans),
                "radiant_prob_start": round(p_start, 1),
                "radiant_prob_end": round(p_end, 1),
                "comment": _phase_comment(match, name, gold_start, gold_end, fights, buildings, roshans),
            }
        )
    return out


def _phase_comment(match, name, gold_start, gold_end, fights, buildings, roshans) -> str:
    diff = gold_end - gold_start
    who = "Radiant" if diff > 0 else "Dire"
    pieces = [f"{who} добавляет {fmt_signed(abs(diff))} золота."]
    if fights:
        rw = sum(1 for f in fights if f.winner == "radiant")
        dw = sum(1 for f in fights if f.winner == "dire")
        pieces.append(f"Драки {rw}:{dw} в пользу Radiant." if rw != dw else f"Драки вничью {rw}:{dw}.")
    if roshans:
        pieces.append(f"Рошанов: {len(roshans)}.")
    if buildings:
        pieces.append(f"Зданий снесено: {len(buildings)}.")
    if not fights and not buildings and not roshans:
        pieces.append("Без крупных событий — команды фармили.")
    return " ".join(pieces)


def team_control(match: Match, probs: list[float]) -> dict:
    minutes = len(probs)
    radiant_minutes = sum(1 for p in probs if p >= 50)
    dire_minutes = minutes - radiant_minutes
    longest_radiant = longest_dire = 0
    cur_r = cur_d = 0
    for p in probs:
        if p > 50:
            cur_r += 1
            cur_d = 0
        elif p < 50:
            cur_d += 1
            cur_r = 0
        longest_radiant = max(longest_radiant, cur_r)
        longest_dire = max(longest_dire, cur_d)
    return {
        "radiant_pct": round(radiant_minutes / max(1, minutes) * 100),
        "dire_pct": round(dire_minutes / max(1, minutes) * 100),
        "longest_radiant": longest_radiant,
        "longest_dire": longest_dire,
    }
