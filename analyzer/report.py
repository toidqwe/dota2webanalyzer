"""Assemble the final JSON report: verdicts, narratives, tables."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .constants import (
    ATTR_COLOR,
    ATTR_LABEL,
    CATEGORY_LABEL,
    GAME_MODES,
    LANE_LABEL,
    LOBBY_TYPES,
    POSITION_LABEL,
    POSITION_SHORT,
)
from .format import fmt_duration, fmt_num, fmt_pct, fmt_time, plural
from .metrics import lane_stats, player_metrics, team_stats
from .mistakes import detect_mistakes
from .moments import (
    choke_info,
    phases,
    team_control,
    turning_points,
    win_probability,
)
from .normalize import HEROES, Match, Player, clamp, hero_image, safe_int


class AnalysisError(Exception):
    def __init__(self, message: str, status: int = 422, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _team_word(team: str) -> str:
    return "Radiant" if team == "radiant" else "Dire"


RANK_MEDALS = {
    1: "Herald",
    2: "Guardian",
    3: "Crusader",
    4: "Archon",
    5: "Legend",
    6: "Ancient",
    7: "Divine",
    8: "Immortal",
}

# Dota 2 medal boundaries, roughly 770 MMR per medal and 154 per star.
MMR_STEPS = [
    (5420, 8, "Immortal"),
    (4620, 7, "Divine"),
    (3850, 6, "Ancient"),
    (3080, 5, "Legend"),
    (2310, 4, "Archon"),
    (1540, 3, "Crusader"),
    (770, 2, "Guardian"),
    (0, 1, "Herald"),
]


def rank_from_mmr(mmr: float) -> str:
    if not mmr or mmr <= 0:
        return "—"
    for threshold, medal, name in MMR_STEPS:
        if mmr >= threshold:
            if medal == 8:
                return "Immortal"
            star = min(5, int((mmr - threshold) // 154) + 1)
            return f"{name} {star}"
    return "Herald 1"


def rank_label(tier: int, mmr: float | None = None) -> str:
    if mmr:
        label = rank_from_mmr(float(mmr))
        if label != "—":
            return label
    if not tier or tier < 10:
        return "—"
    medal = tier // 10
    stars = tier % 10
    name = RANK_MEDALS.get(medal)
    if not name:
        return "—"
    if medal == 8:
        return name
    return f"{name} {min(5, max(1, stars))}"


def _average_rank(players: list[Player]) -> tuple[str, int, int]:
    tiers = [p.rank_tier for p in players if 10 <= p.rank_tier <= 80]
    mmrs = [p.computed_mmr for p in players if p.computed_mmr]
    avg_tier = round(sum(tiers) / len(tiers)) if tiers else 0
    avg_mmr = round(sum(mmrs) / len(mmrs)) if mmrs else 0
    label = rank_from_mmr(avg_mmr) if avg_mmr else rank_label(avg_tier)
    return label, avg_tier, avg_mmr



def _short_time(seconds: float) -> str:
    return fmt_time(seconds)


def _player_public(match: Match, p: Player, metrics: dict, mistakes: list[dict]) -> dict:
    hero = {
        "id": p.hero_id,
        "key": p.hero_key,
        "name": p.hero_name,
        "img": p.image(),
        "attr": p.attr,
        "attr_label": ATTR_LABEL.get(p.attr, p.attr),
        "attr_color": ATTR_COLOR.get(p.attr, "#d9a441"),
        "attack": p.attack,
        "roles": p.roles,
    }
    m = metrics[p.id]
    p_mistakes = [x for x in mistakes if x["player_id"] == p.id]
    rival = next((r for r in match.squad(match.enemy(p.team)) if r.position == p.position), None)
    rival_info = None
    if rival:
        rival_info = {
            "id": rival.id,
            "hero": rival.hero_name,
            "img": rival.image(),
            "nw_diff": p.networth - rival.networth,
            "gpm_diff": p.gpm - rival.gpm,
            "lh10_diff": p.lh10 - rival.lh10,
            "hd_diff": p.hero_damage - rival.hero_damage,
        }
    kills_by = Counter(d.killer_hero for d in match.deaths if d.victim_id == p.id and d.killer_hero)
    death_rows = []
    for d in sorted([x for x in match.deaths if x.victim_id == p.id], key=lambda x: x.time):
        solo = any(x["type"] == "solo_death" and x["time"] == int(d.time) for x in p_mistakes)
        death_rows.append(
            {
                "time": int(d.time),
                "time_label": fmt_time(d.time),
                "killer": match.player(d.killer_id).hero_name if d.killer_id else (d.killer_hero or "Крипы/здание"),
                "gold_lost": d.gold_lost,
                "gold_fed": d.gold_fed,
                "time_dead": d.time_dead,
                "cost": int(d.gold_lost + d.gold_fed + d.time_dead * (p.gpm / 60.0)),
                "solo": solo,
                "fight": d.fight_index,
            }
        )
    notes = _player_notes(match, p, metrics, kills_by)
    chat_count = sum(1 for c in match.chat if c.get("player_id") == p.id and c.get("time", 0) >= 0)

    def checkpoint(minute: int) -> dict:
        index = min(minute, max(0, len(p.networth_t) - 1))
        return {
            "minute": minute,
            "nw": p.networth_t[index] if p.networth_t else 0,
            "lh": p.lh_t[index] if p.lh_t else 0,
            "xp": p.xp_t[index] if p.xp_t else 0,
        }

    bench = {}
    for key, label in (
        ("gold_per_min", "GPM"),
        ("xp_per_min", "XPM"),
        ("last_hits_per_min", "ЛХ"),
        ("hero_damage_per_min", "Урон"),
        ("tower_damage", "Здания"),
    ):
        entry = (p.benchmarks or {}).get(key)
        if isinstance(entry, dict) and entry.get("pct") is not None:
            bench[key] = {"label": label, "pct": round(float(entry["pct"]) * 100)}

    return {
        "id": p.id,
        "checkpoints": [checkpoint(10), checkpoint(20), checkpoint(30)],
        "benchmarks": bench,
        "account_id": p.account_id,
        "rank": {
            "tier": p.rank_tier,
            "label": rank_label(p.rank_tier, p.computed_mmr),
            "mmr": int(p.computed_mmr) if p.computed_mmr else None,
        },
        "wisdom": p.wisdom_count,
        "conduct": {
            "chat_messages": chat_count,
            "pings": p.pings,
            "leaver": bool(p.leaver_status),
            "index": max(
                0,
                round(100 - min(28, chat_count * 1.5) - min(25, p.pings * 0.7) - (30 if p.leaver_status else 0)),
            ),
        },
        "name": p.name,
        "team": p.team,
        "team_word": _team_word(p.team),
        "position": p.position,
        "position_label": POSITION_LABEL[p.position],
        "position_short": POSITION_SHORT[p.position],
        "lane": LANE_LABEL.get(p.lane_role, "Мид"),
        "hero": hero,
        "kills": p.kills,
        "deaths": p.deaths_count,
        "assists": p.assists,
        "kda": p.kda,
        "kp": round(p.kp * 100),
        "gpm": p.gpm,
        "xpm": p.xpm,
        "lh": p.lh,
        "dn": p.dn,
        "lh10": p.lh10,
        "dn10": p.dn10,
        "networth": p.networth,
        "nw_share": round(p.nw_share * 100, 1),
        "level": p.level,
        "hero_damage": p.hero_damage,
        "hd_min": int(m["hd_min"]),
        "tower_damage": p.tower_damage,
        "hero_healing": p.hero_healing,
        "damage_taken": p.damage_taken,
        "tf_part": round(p.tf_part * 100),
        "stuns": round(p.stuns, 1),
        "obs": p.obs,
        "sen": p.sen,
        "dewards": m["dewards"],
        "stacks": p.camps_stacked,
        "runes": p.rune_pickups,
        "buybacks": p.buybacks,
        "tpscroll": p.tpscroll,
        "roshan_kills": p.roshan_kills,
        "buildings": m["buildings"],
        "items": p.items,
        "neutral_item": p.neutral_item,
        "grades": m["grades"],
        "weighted": m["weighted"],
        "blame": m["blame_raw"],
        "blame_share": m["blame_share"],
        "credit": m["credit"],
        "credit_share": m["credit_share"],
        "death_cost": m["death_cost"],
        "deaths10": m["deaths10"],
        "expensive_deaths": m["expensive_deaths"],
        "fight_share": round(m["fight_share"] * 100),
        "solos": m["solos"],
        "throws": m["throws"],
        "buyback_deaths": m["buyback_deaths"],
        "rival": rival_info,
        "death_log": death_rows,
        "notes": notes,
        "mistake_ids": [x["id"] for x in p_mistakes],
        "mistake_count": len(p_mistakes),
        "lane_eff": round(p.lane_efficiency_pct),
    }


def _player_notes(match: Match, p: Player, metrics: dict, kills_by: Counter) -> list[str]:
    notes = []
    squad = match.squad(p.team)
    if p.hero_damage == max(x.hero_damage for x in squad):
        notes.append("Лучший урон по героям в команде")
    if p.deaths_count == max(x.deaths_count for x in squad) and p.deaths_count >= 5:
        notes.append("Больше всех смертей в команде")
    if p.obs + p.sen == max(x.obs + x.sen for x in squad) and p.position >= 4:
        notes.append("Больше всех вардов в команде")
    if p.camps_stacked == max(x.camps_stacked for x in squad) and p.camps_stacked >= 3:
        notes.append(f"{p.camps_stacked} стаков лагерей")
    if p.position <= 3 and p.networth == max(x.networth for x in squad):
        notes.append("Самый богатый герой матча" if p.networth >= 25000 else "Самый богатый в команде")
    if kills_by:
        killer, count = kills_by.most_common(1)[0]
        if count >= 3:
            notes.append(f"{count} {plural(count, 'смерть', 'смерти', 'смертей')} от {killer}")
    if p.roshan_kills >= 2:
        notes.append(f"Добил Рошана {p.roshan_kills} раза")
    if p.hero_healing >= 8000:
        notes.append(f"{fmt_num(p.hero_healing)} исцеления")
    aegis = [o for o in match.objectives if o.kind == "aegis" and o.player_id == p.id]
    if aegis:
        notes.append("Забирал аегис")
    if p.buybacks >= 2:
        notes.append(f"{p.buybacks} байбека")
    return notes[:5]


def _category_fact(match: Match, p: Player, m: dict, category: str) -> str:
    if category == "economy":
        return (
            f"{p.gpm} GPM и {fmt_num(p.networth)} нетворса "
            f"({m['grades']['economy']:.0f}/100); к 10-й минуте {p.lh10} ЛХ."
        )
    if category == "combat":
        return (
            f"{fmt_num(p.hero_damage)} урона по героям ({int(m['hd_min'])}/мин), "
            f"участие в драках {p.tf_part * 100:.0f}%, KDA {p.kda:.2f}."
        )
    if category == "survival":
        return (
            f"{p.deaths_count} {plural(p.deaths_count, 'смерть', 'смерти', 'смертей')} "
            f"({m['deaths10']:.1f} на 10 минут), "
            f"цена смертей ≈{fmt_num(m['death_cost'])}, из них дорогих — {m['expensive_deaths']}."
        )
    if category == "vision":
        return f"{p.obs} обсов и {p.sen} сентри, {m['dewards']} девардов, {p.camps_stacked} стаков."
    if category == "objectives":
        return (
            f"{fmt_num(p.tower_damage)} урона по зданиям, {m['buildings']} добиваний зданий, "
            f"{p.roshan_kills} Рошанов."
        )
    return (
        f"{m['solos']} {plural(m['solos'], 'смерть', 'смерти', 'смертей')} без размена, "
        f"{m['throws']} {plural(m['throws'], 'смерть', 'смерти', 'смертей')} при преимуществе, "
        f"{m['buyback_deaths']} {plural(m['buyback_deaths'], 'смерть', 'смерти', 'смертей')} после байбека."
    )


def _primary_category(m: dict) -> str:
    grades = m["grades"]
    core = ["survival", "economy", "combat"]
    worst = min(core, key=lambda k: grades[k])
    if grades[worst] >= 60:
        worst = min(grades, key=lambda k: grades[k])
    return worst


def _headline(m: dict, positive: bool = False) -> str:
    grades = m["grades"]
    if positive:
        return CATEGORY_LABEL[max(grades, key=lambda k: grades[k])].lower()
    return CATEGORY_LABEL[_primary_category(m)].lower()


def _key_mistake(mistakes: list[dict]) -> dict | None:
    if not mistakes:
        return None
    return max(mistakes, key=lambda x: (x["severity"], x.get("cost", 0), -x["time"]))


def _team_reasons(match: Match, stats: dict, team: str, lanes: list[dict], won: bool) -> list[dict]:
    enemy = match.enemy(team)
    es = stats[enemy]
    ts = stats[team]
    reasons = []

    fight_w, fight_l = ts["fight_wins"], ts["fight_losses"]
    if fight_w + fight_l > 0:
        tone = "good" if fight_w > fight_l else "bad"
        reasons.append(
            {
                "title": "Драки",
                "text": f"{fight_w}:{fight_l} — {ts['fight_wins']} побед в командных драках.",
                "tone": tone,
            }
        )
    nw_diff = ts["networth"] - es["networth"]
    reasons.append(
        {
            "title": "Экономика",
            "text": f"Разница нетворса к концу: {fmt_num(nw_diff, signed=True)} "
            f"({fmt_num(ts['networth'])} против {fmt_num(es['networth'])}).",
            "tone": "good" if nw_diff > 0 else "bad",
        }
    )
    objective_parts = []
    if ts["roshans"]:
        objective_parts.append(f"{ts['roshans']} {plural(ts['roshans'], 'Рошан', 'Рошана', 'Рошанов')}")
    if ts["towers"]:
        objective_parts.append(f"{ts['towers']} {plural(ts['towers'], 'башня', 'башни', 'башен')}")
    if ts["rax"]:
        objective_parts.append(f"{ts['rax']} {plural(ts['rax'], 'барака', 'барака', 'бараков')}")
    if objective_parts:
        reasons.append({"title": "Объекты", "text": "Забрали: " + ", ".join(objective_parts) + ".", "tone": "good"})
    lost_buildings = [o for o in match.objectives if o.kind == "building" and o.team == enemy]
    if lost_buildings:
        reasons.append(
            {
                "title": "Потери",
                "text": f"Отдали {len(lost_buildings)} {plural(len(lost_buildings), 'здание', 'здания', 'зданий')}, "
                f"включая {ts['towers_lost']} {plural(ts['towers_lost'], 'башню', 'башни', 'башен')}.",
                "tone": "bad",
            }
        )
    if ts["dewards"] != es["dewards"] or ts["obs"] != es["obs"]:
        reasons.append(
            {
                "title": "Вижн",
                "text": f"{ts['obs'] + ts['sen']} вардов против {es['obs'] + es['sen']}, "
                f"девардов {ts['dewards']} против {es['dewards']}.",
                "tone": "good" if ts["obs"] + ts["sen"] >= es["obs"] + es["sen"] else "bad",
            }
        )
    lane_wins = sum(1 for lane in lanes if lane["winner"] == team)
    lane_losses = sum(1 for lane in lanes if lane["winner"] == enemy)
    if lanes:
        reasons.append(
            {
                "title": "Лейнинг",
                "text": f"Выиграли {lane_wins} из {len(lanes)} {plural(len(lanes), 'линии', 'линий', 'линий')}, "
                f"проиграли {lane_losses}.",
                "tone": "good" if lane_wins > lane_losses else "bad",
            }
        )
    reasons.append(
        {
            "title": "Смерти",
            "text": f"Суммарно {ts['deaths']} смертей ({ts['deaths10']} на 10 минут).",
            "tone": "good" if ts["deaths"] < es["deaths"] else "bad",
        }
    )
    if not won:
        reasons.sort(key=lambda r: (r["tone"] != "bad",))
    else:
        reasons.sort(key=lambda r: (r["tone"] != "good",))
    return reasons[:5]


def _draft(match: Match) -> dict:
    picks = []
    bans = []
    active_ids = {p.hero_id for p in match.players}
    seen = set()
    for entry in sorted(match.picks_bans, key=lambda e: e.get("order") or 0):
        hero = HEROES.get(str(entry.get("hero_id")), {})
        hero_key = hero.get("key") or ""
        hero_id = safe_int(entry.get("hero_id"))
        is_pick = bool(entry.get("is_pick")) and hero_id in active_ids
        if is_pick and hero_id in seen:
            continue
        if is_pick:
            seen.add(hero_id)
        item = {
            "order": entry.get("order"),
            "team": "radiant" if entry.get("team") == 0 else "dire",
            "hero": {
                "id": hero.get("id"),
                "key": hero_key,
                "name": hero.get("name") or "?",
                "img": hero_image(hero_key) if hero_key else "",
                "attr": hero.get("attr"),
                "roles": hero.get("roles") or [],
            },
        }
        if is_pick:
            picks.append(item)
        else:
            bans.append(item)
    composition = {}
    for team in ("radiant", "dire"):
        squad = match.squad(team)
        attrs = Counter(p.attr for p in squad)
        roles = Counter(role for p in squad for role in p.roles)
        composition[team] = {
            "attrs": [{"key": k, "label": ATTR_LABEL.get(k, k), "count": v, "color": ATTR_COLOR.get(k, "#d9a441")} for k, v in attrs.items()],
            "melee": sum(1 for p in squad if p.attack == "Melee"),
            "ranged": sum(1 for p in squad if p.attack != "Melee"),
            "disablers": roles.get("Disabler", 0),
            "initiators": roles.get("Initiator", 0),
            "nukers": roles.get("Nuker", 0),
            "durables": roles.get("Durable", 0),
            "pushers": roles.get("Pusher", 0),
            "carries": roles.get("Carry", 0),
        }
    return {"picks": picks, "bans": bans, "composition": composition}


def _objectives_public(match: Match) -> list[dict]:
    rows = []
    for o in match.objectives:
        if o.kind not in ("building", "roshan", "aegis", "firstblood"):
            continue
        player = match.player(o.player_id) if o.player_id else None
        rows.append(
            {
                "time": int(o.time),
                "time_label": fmt_time(o.time),
                "kind": o.kind,
                "team": o.team,
                "label": o.label,
                "lane": o.lane,
                "player": player.hero_name if player else None,
                "player_id": player.id if player else None,
            }
        )
    return rows


def _fights_public(match: Match) -> list[dict]:
    rows = []
    for fight in match.fights:
        if fight.deaths == 0 and not fight.major:
            continue
        entries = [(match.player(e.player_id), e) for e in fight.players]
        mvp_p, mvp_e = max(entries, key=lambda pair: pair[1].damage)
        key_deaths = []
        for death in match.deaths:
            if fight.start - 5 <= death.time <= fight.end + 5:
                key_deaths.append(
                    {
                        "victim": match.player(death.victim_id).hero_name,
                        "victim_id": death.victim_id,
                        "killer": match.player(death.killer_id).hero_name if death.killer_id else "?",
                        "time": int(death.time),
                        "gold": death.gold_lost + death.gold_fed,
                    }
                )
        rows.append(
            {
                "index": fight.index,
                "start": int(fight.start),
                "end": int(fight.end),
                "time": f"{fmt_time(fight.start)}–{fmt_time(fight.end)}",
                "winner": fight.winner,
                "radiant_deaths": fight.radiant_deaths,
                "dire_deaths": fight.dire_deaths,
                "gold_swing": int(fight.gold_swing),
                "damage_radiant": fight.damage_radiant,
                "damage_dire": fight.damage_dire,
                "mvp": {"id": mvp_p.id, "hero": mvp_p.hero_name, "img": mvp_p.image(), "damage": mvp_e.damage},
                "deaths": key_deaths,
                "major": fight.major,
            }
        )
    return rows


def _chat_public(match: Match) -> list[dict]:
    rows = []
    for entry in match.chat:
        if entry.get("time", 0) < 0:
            continue
        if len(rows) >= 400:
            break
        player = match.player(entry["player_id"]) if entry.get("player_id") else None
        time_s = entry.get("time", 0)
        rows.append(
            {
                "time": time_s,
                "time_label": ("−" if time_s < 0 else "") + fmt_time(abs(time_s)),
                "pre_game": time_s < 0,
                "text": entry.get("text", ""),
                "type": entry.get("type", "chat"),
                "player_id": player.id if player else None,
                "team": player.team if player else None,
                "hero": player.hero_name if player else None,
                "name": player.name if player else None,
            }
        )
    return rows


def _wisdom_public(match: Match) -> list[dict]:
    rows = []
    for entry in match.wisdom_runes:
        player = match.player(entry["player_id"]) if entry.get("player_id") else None
        rows.append(
            {
                "time": entry["time"],
                "time_label": fmt_time(entry["time"]),
                "team": entry.get("team") or (player.team if player else None),
                "player_id": player.id if player else None,
                "hero": player.hero_name if player else None,
                "name": player.name if player else None,
            }
        )
    return rows


def _glyphs_public(match: Match) -> list[dict]:
    rows = []
    for entry in match.glyphs:
        player = match.player(entry["player_id"]) if entry.get("player_id") else None
        rows.append(
            {
                "time": entry["time"],
                "time_label": fmt_time(entry["time"]),
                "team": entry.get("team"),
                "player_id": player.id if player else None,
                "hero": player.hero_name if player else None,
            }
        )
    return rows


def _conduct_public(match: Match) -> dict:
    return {
        "pauses": len(match.pauses),
        "reports_available": False,
        "behavior_available": False,
        "note": "Valve не отдаёт историю репортов и behavior score через публичный API. "
        "Ниже — только события этого матча: пинги, сообщения, ливы.",
        "players": [
            {
                "player_id": p.id,
                "hero": p.hero_name,
                "name": p.name,
                "team": p.team,
                "pings": p.pings,
                "chat_messages": sum(
                    1 for c in match.chat if c.get("player_id") == p.id and c.get("time", 0) >= 0
                ),
                "leaver": bool(p.leaver_status),
                "index": max(
                    0,
                    round(
                        100
                        - min(
                            28,
                            sum(
                                1
                                for c in match.chat
                                if c.get("player_id") == p.id and c.get("time", 0) >= 0
                            )
                            * 1.5,
                        )
                        - min(25, p.pings * 0.7)
                        - (30 if p.leaver_status else 0)
                    ),
                ),
            }
            for p in match.players
        ],
    }


def _wards_public(match: Match) -> list[dict]:
    rows = []
    for ward in match.wards:
        player = match.player(ward["player_id"])
        rows.append(
            {
                "time": round(ward["time"], 1),
                "time_label": fmt_time(ward["time"]),
                "x": round(ward["x"], 2),
                "y": round(ward["y"], 2),
                "team": ward["team"],
                "type": ward["type"],
                "player_id": player.id,
                "hero": player.hero_name,
                "duration": round(ward["duration"]) if ward.get("duration") is not None else None,
            }
        )
    return rows


def _fight_map_public(match: Match) -> list[dict]:
    rows = []
    for death in match.fight_deaths:
        victim = match.player(death["player_id"])
        killer = match.player(death["killer_id"]) if death.get("killer_id") else None
        fight = next((f for f in match.fights if f.index == death.get("fight_index")), None)
        rows.append(
            {
                "time": round(death["time"], 1),
                "time_label": fmt_time(death["time"]),
                "x": round(death["x"], 2),
                "y": round(death["y"], 2),
                "team": death["team"],
                "victim": victim.hero_name,
                "victim_id": victim.id,
                "victim_img": victim.image(),
                "killer": killer.hero_name if killer else None,
                "fight_index": death.get("fight_index"),
                "fight_winner": fight.winner if fight else None,
            }
        )
    return rows


def analyze_match(raw: dict) -> dict:
    match = Match(raw)
    if not match.players or not match.players[0].gold_t:
        raise AnalysisError(
            "Матч ещё не распарсен. Сейчас запустим локальный парсер реплея — это займёт пару минут.",
            422,
            code="unparsed",
        )
    probs = win_probability(match)
    match.win_prob = probs
    mistakes, team_mistakes = detect_mistakes(match, probs)
    metrics = player_metrics(match, mistakes)
    points = turning_points(match, probs)
    choke = choke_info(match, probs)
    phase_rows = phases(match, probs)
    control = team_control(match, probs)
    stats = team_stats(match)
    lanes = lane_stats(match)

    players = [_player_public(match, p, metrics, mistakes) for p in sorted(match.players, key=lambda x: (x.team != "radiant", x.position))]

    winner = "radiant" if match.radiant_win else "dire"
    loser = match.enemy(winner)
    winner_squad = match.squad(winner)
    loser_squad = match.squad(loser)
    mvp = max(winner_squad, key=lambda p: metrics[p.id]["credit"])
    culprit = max(loser_squad, key=lambda p: metrics[p.id]["blame_raw"])
    least = min(loser_squad, key=lambda p: metrics[p.id]["blame_raw"])
    main_point = max(points, key=lambda x: x["severity"], default=None)
    if main_point is None and match.gold_adv:
        main_point = {
            "minute": len(match.gold_adv) - 1,
            "time": fmt_time(match.duration),
            "title": "Итог",
            "text": "Матч без резких разворотов — команды шли ровно, исход решила концовка.",
            "prob_before": 50,
            "prob_after": 100 if winner == "radiant" else 0,
            "delta_prob": 0,
            "gold_swing": int(match.gold_adv[-1]),
            "beneficiary": winner,
            "severity": 0,
            "kind": "economy",
            "key_death": None,
        }

    def culprit_card(p: Player) -> dict:
        m = metrics[p.id]
        pm = [x for x in mistakes if x["player_id"] == p.id]
        primary = _headline(m)
        primary_key = _primary_category(m)
        bullets = []
        if p.deaths_count >= 5:
            bullets.append(
                f"{p.deaths_count} {plural(p.deaths_count, 'смерть', 'смерти', 'смертей')} "
                f"({m['deaths10']:.1f} на 10 минут), "
                f"цена смертей ≈{fmt_num(m['death_cost'])}; без размена — {m['solos']}."
            )
        if primary_key in ("objectives", "vision") and p.position <= 3:
            primary_key = "combat"
        primary = CATEGORY_LABEL[primary_key].lower()
        if primary_key != "survival":
            bullets.append(_category_fact(match, p, m, primary_key))
        rival = next((r for r in match.squad(match.enemy(p.team)) if r.position == p.position), None)
        if rival and len(bullets) < 3:
            bullets.append(
                f"Визави {rival.hero_name}: {fmt_num(rival.networth)} нетворса против {fmt_num(p.networth)} "
                f"({fmt_num(p.networth - rival.networth, signed=True)})."
            )
        key = _key_mistake(pm)
        if key and len(bullets) < 3:
            bullets.append(f"Ключевая ошибка: {key['time_label']} — {key['title'].lower()}.")
        if not bullets:
            bullets.append(_category_fact(match, p, m, primary_key))
        return {
            "player_id": p.id,
            "name": p.name,
            "hero": p.hero_name,
            "img": p.image(),
            "position": p.position,
            "position_label": POSITION_LABEL[p.position],
            "blame": m["blame_raw"],
            "share": m["blame_share"],
            "headline": primary + " — главная проблема",
            "bullets": bullets[:3],
            "grades": m["grades"],
            "key_mistake": key,
        }

    mvp_m = metrics[mvp.id]
    best_cats = sorted(mvp_m["grades"], key=lambda k: mvp_m["grades"][k], reverse=True)[:2]
    mvp_card = {
        "player_id": mvp.id,
        "name": mvp.name,
        "hero": mvp.hero_name,
        "img": mvp.image(),
        "position": mvp.position,
        "position_label": POSITION_LABEL[mvp.position],
        "credit": mvp_m["credit"],
        "share": mvp_m["credit_share"],
        "kda": mvp.kda,
        "bullets": [
            f"{' и '.join(CATEGORY_LABEL[c].lower() for c in best_cats)} — сильнейшие стороны "
            f"({mvp_m['grades'][best_cats[0]]:.0f}/100).",
            f"KDA {mvp.kda:.2f}, {fmt_num(mvp.hero_damage)} урона, {mvp_m['fight_share'] * 100:.0f}% урона команды в драках.",
            f"{mvp.obs + mvp.sen} вардов, {mvp.roshan_kills} Рошанов, {fmt_num(mvp.tower_damage)} урона по зданиям."
            if mvp.position >= 4
            else f"{fmt_num(mvp.tower_damage)} урона по зданиям и {mvp.roshan_kills} Рошанов.",
        ][:3],
        "grades": mvp_m["grades"],
    }

    least_m = metrics[least.id]
    best_least = sorted(least_m["grades"], key=lambda k: least_m["grades"][k], reverse=True)[:1]
    least_card = {
        "player_id": least.id,
        "name": least.name,
        "hero": least.hero_name,
        "img": least.image(),
        "blame": least_m["blame_raw"],
        "share": least_m["blame_share"],
        "text": (
            f"Меньше всего претензий: {_category_fact(match, least, least_m, best_least[0]).lower()} "
            f"Индекс вины — {least_m['blame_raw']:.0f}/100."
        ),
    }

    summary = _build_summary(match, control, points, choke, culprit, stats, metrics)
    team_reasons = {
        winner: _team_reasons(match, stats, winner, lanes, True),
        loser: _team_reasons(match, stats, loser, lanes, False),
    }
    winner_name = _team_word(winner)
    loser_name = _team_word(loser)

    quality_players = sum(1 for p in match.players if p.benchmarks)
    quality = {
        "players_with_benchmarks": quality_players,
        "teamfights": len(match.fights),
        "deaths_logged": len(match.deaths),
        "objectives": len([o for o in match.objectives if o.kind in ("building", "roshan")]),
        "notes": [],
    }
    if quality_players < 10:
        quality["notes"].append("Часть игроков без бенчмарков OpenDota — оценка опирается на ролевые нормы.")
    if not match.fights:
        quality["notes"].append("Нет данных о командных драках: анализ боёв ограничен.")

    avg_rank_label, avg_rank_tier, avg_mmr = _average_rank(match.players)
    if match.death_mismatches:
        quality["notes"].append(
            "В логе смертей и в KDA были расхождения — для отчёта используется лог смертей."
        )
    if match.score_adjustments:
        quality["notes"].append(
            f"Убрано {len(match.score_adjustments)} смертей, которых нет в счёте матча — KDA и счёт теперь сходятся."
        )
    if not match.glyphs:
        quality["notes"].append("События глифов не отдаются ни OpenDota, ни реплеем — раздел может быть пустым.")
    if not avg_rank_tier:
        quality["notes"].append("Ранги игроков скрыты или матч нерейтинговый.")
    if not match.chat:
        quality["notes"].append("В реплее нет текстового чата.")

    return {
        "ok": True,
        "match": {
            "id": match.id,
            "start_time": match.start_time,
            "date": _date_label(match.start_time),
            "duration": match.duration,
            "duration_label": fmt_duration(match.duration),
            "game_mode": GAME_MODES.get(match.game_mode, "Матч"),
            "lobby": LOBBY_TYPES.get(match.lobby_type, "Матч"),
            "radiant_win": match.radiant_win,
            "winner": winner,
            "winner_word": winner_name,
            "loser": loser,
            "loser_word": loser_name,
            "score": {"radiant": match.radiant_score, "dire": match.dire_score},
            "first_blood_time": fmt_time(match.first_blood_time) if match.first_blood_time else None,
            "first_blood_team": match.first_blood_team,
            "league_id": match.league_id,
            "patch": match.patch,
            "average_rank": avg_rank_label,
            "average_rank_tier": avg_rank_tier,
            "average_mmr": avg_mmr,
        },
        "teams": {
            "radiant": {"name": "Radiant", "win": match.radiant_win, "stats": stats["radiant"], "player_ids": [p.id for p in match.squad("radiant")]},
            "dire": {"name": "Dire", "win": not match.radiant_win, "stats": stats["dire"], "player_ids": [p.id for p in match.squad("dire")]},
        },
        "players": players,
        "verdict": {
            "culprit": culprit_card(culprit),
            "least": least_card,
            "mvp": mvp_card,
            "main_point": main_point,
            "choke": choke,
            "control": control,
            "summary": summary,
            "team_reasons": team_reasons,
            "scoreline": f"{match.radiant_score}:{match.dire_score}",
        },
        "turning_points": points,
        "mistakes": mistakes,
        "team_mistakes": team_mistakes,
        "chat": _chat_public(match),
        "wisdom_runes": _wisdom_public(match),
        "glyphs": _glyphs_public(match),
        "conduct": _conduct_public(match),
        "wards": _wards_public(match),
        "fight_map": _fight_map_public(match),
        "map_bounds": match.map_bounds,
        "buildings": [
            {
                "team": b["team"],
                "kind": b["kind"],
                "label": b["label"],
                "x": b["x"],
                "y": b["y"],
                "destroyed": b["destroyed"],
            }
            for b in match.buildings
        ],
        "fights": _fights_public(match),
        "objectives": _objectives_public(match),
        "lanes": lanes,
        "phases": phase_rows,
        "draft": _draft(match),
        "timeline": {
            "minutes": list(range(len(match.gold_adv))),
            "gold": [int(v) for v in match.gold_adv],
            "xp": [int(v) for v in match.xp_adv],
            "prob": probs,
        },
        "quality": quality,
        "method": {
            "version": 10,
            "source": "OpenDota parsed replay",
            "probability": "Логистическая модель по преимуществу в золоте и опыте с масштабом, растущим к лейту.",
            "blame": "Взвешенная сумма ролевых оценок (экономика, бой, выживаемость, вижн, объекты, дисциплина) + штраф за ошибки.",
        },
    }


def _date_label(timestamp: int) -> str:
    if not timestamp:
        return "—"
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "—"


def _build_summary(match: Match, control: dict, points: list[dict], choke: dict | None, culprit: Player, stats: dict, metrics: dict) -> list[str]:
    winner = "radiant" if match.radiant_win else "dire"
    loser = match.enemy(winner)
    w_name = _team_word(winner)
    l_name = _team_word(loser)
    ws = stats[winner]
    ls = stats[loser]
    total = ws["kills"] + ls["kills"]
    lines = [
        f"{w_name} забирают игру со счётом {match.radiant_score}:{match.dire_score} "
        f"за {fmt_duration(match.duration)}. Контроль карты: {control[f'{winner}_pct']}% времени, "
        f"пик преимущества {fmt_num(ws['peak_lead'], signed=True)} золота."
    ]
    lines.append(
        f"Драки {ws['fight_wins']}:{ws['fight_losses']} в пользу {w_name}, "
        f"Рошаны {ws['roshans']}:{ls['roshans']}, башни {ws['towers']}:{ls['towers']}. "
        f"К концу матча разница нетворса — {fmt_num(ws['networth'] - ls['networth'], signed=True)}."
    )
    if points:
        strongest = max(points, key=lambda p: p["severity"])
        lines.append(f"Главный перелом — {strongest['time']}: {strongest['text']}")
    if choke:
        lines.append(
            f"{_team_word(choke['team'])} имели {choke['peak']:.0f}% на {choke['peak_time']}, "
            f"но растеряли преимущество: к {fmt_time(choke['collapse_minute'] * 60)} осталось меньше 25%."
        )
    lines.append(
        f"Главный виновник по модели — {culprit.hero_name} ({culprit.name}): "
        f"индекс вины {metrics[culprit.id]['blame_raw']:.0f}/100, доля ответственности "
        f"{metrics[culprit.id]['blame_share']:.0f}%. Подробности — ниже."
    )
    return lines

