"""Player/team grading: turns raw stats into role-aware 0-100 scores."""

from __future__ import annotations

import math

from .constants import BASE, ROLE_WEIGHTS
from .normalize import Match, Player, clamp


def logistic_grade(actual: float, base: float, *, higher_is_better: bool = True, k: float = 2.0) -> float:
    if base <= 0:
        return 50.0
    if higher_is_better:
        ratio = actual / base
    else:
        ratio = base / max(actual, base * 0.02)
    ratio = max(0.02, min(4.5, ratio))
    return clamp(100.0 / (1.0 + math.exp(-k * (ratio - 1.0))))


def lower_grade(actual: float, base: float, *, k: float = 1.6) -> float:
    """Grade for 'lower is better' metrics: 0 -> 100, baseline -> 50, above -> decays fast."""
    if base <= 0:
        return 50.0
    if actual <= base:
        return clamp(50.0 + 50.0 * (1.0 - actual / base))
    return clamp(50.0 * math.exp(-k * (actual / base - 1.0)))


def bench_quality(player: Player, key: str) -> float | None:
    entry = (player.benchmarks or {}).get(key)
    if not isinstance(entry, dict):
        return None
    pct = entry.get("pct")
    if pct is None:
        return None
    try:
        return clamp(float(pct) * 100.0)
    except (TypeError, ValueError):
        return None


def blend(grade: float, player: Player, key: str, weight: float = 0.3) -> float:
    quality = bench_quality(player, key)
    if quality is None:
        return grade
    return grade * (1 - weight) + quality * weight


def _minutes(match: Match) -> float:
    return max(1.0, match.duration / 60.0)


def _death_total_cost(match: Match, player: Player) -> float:
    return sum(
        d.gold_lost + d.gold_fed + d.time_dead * (player.gpm / 60.0)
        for d in match.deaths
        if d.victim_id == player.id
    )


def _expensive_deaths(match: Match, player: Player) -> int:
    count = 0
    squad_nw = sorted((p.networth for p in match.squad(player.team)), reverse=True)
    for death in match.deaths:
        if death.victim_id != player.id or death.time < 600:
            continue
        nw = player.networth_at(death.time)
        if squad_nw and nw >= squad_nw[1] * 0.95:
            count += 1
    return count


def _deaths_ahead(match: Match, player: Player) -> int:
    count = 0
    for death in match.deaths:
        if death.victim_id != player.id:
            continue
        if match.gold_for(player.team, int(death.time // 60)) >= 3000:
            count += 1
    return count


def _building_kills(match: Match, player: Player) -> int:
    return sum(
        1
        for o in match.objectives
        if o.kind == "building" and o.team == player.team and o.player_id == player.id
    )


def _fight_damage(match: Match, player: Player) -> int:
    return sum(
        e.damage
        for fight in match.fights
        for e in fight.players
        if e.player_id == player.id
    )


def player_metrics(match: Match, mistakes: list[dict]) -> dict[str, dict]:
    duration_min = _minutes(match)
    team_death_cost = {
        team: sum(_death_total_cost(match, p) for p in match.squad(team))
        for team in ("radiant", "dire")
    }
    team_fight_damage = {
        team: max(1, sum(_fight_damage(match, p) for p in match.squad(team)))
        for team in ("radiant", "dire")
    }
    by_player: dict[str, list[dict]] = {}
    for mistake in mistakes:
        by_player.setdefault(mistake["player_id"], []).append(mistake)

    result: dict[str, dict] = {}
    for p in match.players:
        pos = p.position
        base = {key: values[pos] for key, values in BASE.items()}
        hd_min = p.hero_damage / duration_min
        deaths10 = p.deaths_count / duration_min * 10
        obs_min = p.obs / duration_min
        sen_min = p.sen / duration_min
        dewards = p.observer_kills + p.sentry_kills
        buildings = _building_kills(match, p)
        fight_damage = _fight_damage(match, p)
        fight_share = fight_damage / team_fight_damage[p.team]

        gpm_g = blend(logistic_grade(p.gpm, base["gpm"], k=1.9), p, "gold_per_min")
        xpm_g = blend(logistic_grade(p.xpm, base["xpm"], k=1.9), p, "xp_per_min")
        lh_g = logistic_grade(p.lh10, base["lh10"], k=2.2)
        deny_g = logistic_grade(p.dn10, base["dn10"], k=1.8)
        share_g = logistic_grade(p.nw_share, base["nw_share"], k=3.2)
        economy = 0.38 * gpm_g + 0.22 * lh_g + 0.15 * xpm_g + 0.17 * share_g + 0.08 * deny_g

        hd_g = blend(logistic_grade(hd_min, base["hd_min"], k=1.8), p, "hero_damage_per_min")
        tf_g = logistic_grade(p.tf_part, base["tf_part"], k=2.4)
        kda_g = logistic_grade(p.kda, base["kda"], k=1.9)
        kp_g = logistic_grade(p.kp, base["kp"], k=2.2)
        combat = 0.40 * hd_g + 0.25 * tf_g + 0.20 * kda_g + 0.15 * kp_g

        deaths_g = lower_grade(deaths10, base["deaths10"], k=1.7)
        death_share = p.deaths_count / max(1, p.team_deaths)
        share_deaths_g = lower_grade(death_share, 0.20, k=1.5)
        cost_share = _death_total_cost(match, p) / max(1.0, team_death_cost[p.team])
        cost_base = {1: 0.26, 2: 0.23, 3: 0.20, 4: 0.16, 5: 0.15}[pos]
        cost_g = lower_grade(cost_share, cost_base, k=1.4)
        expensive = _expensive_deaths(match, p)
        expensive_g = lower_grade(expensive, {1: 1.4, 2: 1.2, 3: 1.1, 4: 0.8, 5: 0.6}[pos], k=1.4)
        survival = 0.62 * deaths_g + 0.16 * share_deaths_g + 0.12 * cost_g + 0.10 * expensive_g

        obs_g = logistic_grade(obs_min, base["obs_min"], k=2.2)
        sen_g = logistic_grade(sen_min, base["sen_min"], k=2.2)
        deward_g = logistic_grade(dewards, base["dewards"], k=1.8)
        stack_g = logistic_grade(p.camps_stacked, base["stacks"], k=1.6)
        if pos <= 2:
            vision = 0.45 * 50.0 + 0.35 * deward_g + 0.20 * stack_g
        elif pos == 3:
            vision = 0.18 * obs_g + 0.14 * sen_g + 0.38 * deward_g + 0.30 * stack_g
        else:
            vision = 0.28 * obs_g + 0.27 * sen_g + 0.27 * deward_g + 0.18 * stack_g

        td_g = blend(logistic_grade(p.tower_damage, base["td"], k=1.7), p, "tower_damage")
        bld_g = logistic_grade(buildings, base["buildings"], k=1.9)
        rosh_g = logistic_grade(p.roshan_kills, base["roshan"], k=2.0)
        objectives = 0.50 * td_g + 0.30 * bld_g + 0.20 * rosh_g

        flags = by_player.get(p.id, [])
        penalty = 0.0
        for mistake in flags:
            if mistake["type"] == "solo_death":
                penalty += 8
            elif mistake["type"] == "throw_death":
                penalty += 12
            elif mistake["type"] == "buyback_death":
                penalty += 6
            elif mistake["type"] == "farm_no_fight":
                penalty += 9
            elif mistake["type"] == "objective_after_death":
                penalty += 2
        discipline = clamp(100.0 - min(45.0, penalty), 15.0, 100.0)

        grades = {
            "economy": economy,
            "combat": combat,
            "survival": survival,
            "vision": vision,
            "objectives": objectives,
            "discipline": discipline,
        }
        weights = ROLE_WEIGHTS[pos]
        weighted = sum(grades[key] * weights[key] for key in grades)

        result[p.id] = {
            "grades": {k: round(v, 1) for k, v in grades.items()},
            "weighted": round(weighted, 1),
            "hd_min": round(hd_min, 1),
            "deaths10": round(deaths10, 2),
            "obs_min": round(obs_min, 3),
            "sen_min": round(sen_min, 3),
            "dewards": dewards,
            "buildings": buildings,
            "fight_damage": fight_damage,
            "fight_share": round(fight_share, 3),
            "death_cost": int(_death_total_cost(match, p)),
            "expensive_deaths": expensive,
            "deaths_ahead": _deaths_ahead(match, p),
            "cost_share": round(cost_share, 3),
            "solos": sum(1 for m in flags if m["type"] == "solo_death"),
            "throws": sum(1 for m in flags if m["type"] == "throw_death"),
            "buyback_deaths": sum(1 for m in flags if m["type"] == "buyback_death"),
            "farm_misses": sum(1 for m in flags if m["type"] == "farm_no_fight"),
        }

    mistakes_by_player = by_player
    result = _add_blame(match, result, mistakes_by_player)
    return result


def _mistake_weight(mistakes: list[dict]) -> float:
    total = 0.0
    for m in mistakes:
        total += m["severity"] * (1.0 + min(m.get("cost", 0), 4000) / 4000.0)
    return total


def _add_blame(match: Match, metrics: dict[str, dict], mistakes_by_player: dict[str, list[dict]]) -> dict[str, dict]:
    for team in ("radiant", "dire"):
        squad = match.squad(team)
        raw = {}
        mscore = {}
        credits = {}
        for p in squad:
            m = metrics[p.id]
            raw[p.id] = max(0.0, 100.0 - m["weighted"])
            mscore[p.id] = _mistake_weight(mistakes_by_player.get(p.id, []))
            credits[p.id] = m["weighted"] + 6.0 * min(1.0, m["fight_share"] / 0.25)
        max_m = max(mscore.values()) or 1.0
        for p in squad:
            expected_deaths = BASE["deaths10"][p.position] * match.duration / 600.0
            extra_deaths = max(0.0, p.deaths_count - expected_deaths)
            death_penalty = min(12.0, extra_deaths * 1.4)
            blame = 0.78 * raw[p.id] + 0.17 * (mscore[p.id] / max_m * 100.0) + death_penalty
            metrics[p.id]["blame_raw"] = round(min(100.0, blame), 1)
        total_blame = sum(metrics[p.id]["blame_raw"] ** 3 for p in squad) or 1.0
        shares = {p.id: metrics[p.id]["blame_raw"] ** 3 / total_blame * 100.0 for p in squad}
        rounded = {pid: round(v, 1) for pid, v in shares.items()}
        diff = round(100.0 - sum(rounded.values()), 1)
        if squad:
            rounded[squad[0].id] = round(rounded[squad[0].id] + diff, 1)
        for p in squad:
            metrics[p.id]["blame_share"] = rounded[p.id]
        total_credit = sum(credits.values()) or 1.0
        for p in squad:
            metrics[p.id]["credit"] = round(credits[p.id], 1)
            metrics[p.id]["credit_share"] = round(credits[p.id] / total_credit * 100.0, 1)
    return metrics


def team_stats(match: Match) -> dict[str, dict]:
    out = {}
    minutes = match.duration / 60.0
    for team in ("radiant", "dire"):
        squad = match.squad(team)
        enemy = match.enemy(team)
        buildings = [o for o in match.objectives if o.kind == "building" and o.team == team]
        towers = sum(1 for o in buildings if o.label.startswith("Т"))
        rax = sum(1 for o in buildings if o.label.startswith("Бараки"))
        roshans = sum(1 for o in match.objectives if o.kind == "roshan" and o.team == team)
        aegis = sum(1 for o in match.objectives if o.kind == "aegis" and o.team == team)
        wins, losses = match.fight_record(team)
        lead_series = [match.gold_for(team, i) for i in range(len(match.gold_adv))]
        peak = max(lead_series) if lead_series else 0
        low = min(lead_series) if lead_series else 0
        control = sum(1 for v in lead_series if v > 0) / max(1, len(lead_series)) * 100
        out[team] = {
            "kills": sum(p.kills for p in squad),
            "deaths": sum(p.deaths_count for p in squad),
            "assists": sum(p.assists for p in squad),
            "towers": towers,
            "rax": rax,
            "towers_lost": sum(1 for o in match.objectives if o.kind == "building" and o.team == enemy and o.label.startswith("Т")),
            "roshans": roshans,
            "aegis": aegis,
            "obs": sum(p.obs for p in squad),
            "sen": sum(p.sen for p in squad),
            "dewards": sum(p.observer_kills + p.sentry_kills for p in squad),
            "stacks": sum(p.camps_stacked for p in squad),
            "networth": sum(p.networth for p in squad),
            "gpm": round(sum(p.gpm for p in squad) / 5),
            "xpm": round(sum(p.xpm for p in squad) / 5),
            "hero_damage": sum(p.hero_damage for p in squad),
            "tower_damage": sum(p.tower_damage for p in squad),
            "healing": sum(p.hero_healing for p in squad),
            "fight_wins": wins,
            "fight_losses": losses,
            "peak_lead": int(peak),
            "max_deficit": int(low),
            "control": round(control),
            "first_blood": match.first_blood_team == team,
            "buybacks": sum(p.buybacks for p in squad),
            "wisdom": sum(p.wisdom_count for p in squad),
            "deaths10": round(sum(p.deaths_count for p in squad) / minutes * 10, 1),
            "gpm_sum": sum(p.gpm for p in squad),
            "duration_min": round(minutes, 1),
        }
    return out


def lane_stats(match: Match) -> list[dict]:
    """Radiant safe vs Dire off, mid vs mid, Radiant off vs Dire safe."""
    lanes = []
    specs = [
        ("Сейф Radiant vs Офф Dire", "radiant", 1, "dire", 3),
        ("Мид", "radiant", 2, "dire", 2),
        ("Офф Radiant vs Сейф Dire", "radiant", 3, "dire", 1),
    ]
    for title, team_a, lane_a, team_b, lane_b in specs:
        a_players = [p for p in match.squad(team_a) if p.lane_role == lane_a]
        b_players = [p for p in match.squad(team_b) if p.lane_role == lane_b]
        if not a_players or not b_players:
            continue
        a_core = min(a_players, key=lambda p: p.position)
        b_core = min(b_players, key=lambda p: p.position)
        a_nw = a_core.networth_at(600)
        b_nw = b_core.networth_at(600)
        diff = a_nw - b_nw
        if diff > 700:
            winner = a_core.team
        elif diff < -700:
            winner = b_core.team
        else:
            winner = "draw"
        lanes.append(
            {
                "title": title,
                "a_team": team_a,
                "b_team": team_b,
                "a_players": [p.id for p in a_players],
                "b_players": [p.id for p in b_players],
                "a_core": a_core.id,
                "b_core": b_core.id,
                "a_nw10": a_nw,
                "b_nw10": b_nw,
                "diff": diff,
                "winner": winner,
                "a_lh10": a_core.lh10,
                "b_lh10": b_core.lh10,
            }
        )
    return lanes
