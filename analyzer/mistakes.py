"""Heuristic mistake detection built on parsed replay events."""

from __future__ import annotations

from .constants import BASE
from .format import fmt_num, fmt_time, plural
from .normalize import Match, Player, clamp


def _death_cost(player: Player, death) -> int:
    return int(death.gold_lost + death.gold_fed + death.time_dead * (player.gpm / 60.0))


def _kills_between(match: Match, team: str, start: float, end: float) -> list[dict]:
    return [k for k in match.kills if k["killer_team"] == team and start <= k["time"] <= end]


def _teammate_deaths(match: Match, player: Player, death, window: float = 25) -> list:
    return [
        d
        for d in match.deaths
        if d.victim_id != player.id
        and match.player(d.victim_id).team == player.team
        and abs(d.time - death.time) <= window
    ]


def _prob_for(probs: list[float], team: str, minute: int) -> float:
    idx = max(0, min(len(probs) - 1, minute))
    value = probs[idx]
    return value if team == "radiant" else 100.0 - value


def _has_item(player: Player, key: str) -> bool:
    return any(item["key"] == key for item in player.items)


def _same_position_enemy(match: Match, player: Player) -> Player | None:
    return next((p for p in match.squad(match.enemy(player.team)) if p.position == player.position), None)


def detect_mistakes(match: Match, probs: list[float]) -> tuple[list[dict], list[dict]]:
    mistakes: list[dict] = []
    counter = 0

    def add(player: Player | None, team: str, time: float, mtype: str, title: str, text: str, severity: int, cost: int = 0):
        nonlocal counter
        counter += 1
        mistakes.append(
            {
                "id": f"m{counter}",
                "player_id": player.id if player else None,
                "team": team,
                "time": int(time),
                "time_label": fmt_time(time),
                "type": mtype,
                "title": title,
                "text": text,
                "severity": int(clamp(severity, 1, 5)),
                "cost": int(cost),
            }
        )

    for p in match.players:
        player_deaths = [d for d in match.deaths if d.victim_id == p.id]
        counts: dict[str, int] = {}
        objective_added = False
        for death in player_deaths:
            minute = int(death.time // 60)
            cost = _death_cost(p, death)
            killer = f" от {match.player(death.killer_id).hero_name}" if death.killer_id else ""
            selected = None
            if p.position <= 3 and not objective_added:
                lost = [
                    o for o in match.objectives
                    if o.kind in ("building", "roshan") and o.team == match.enemy(p.team)
                    and death.time + 8 <= o.time <= death.time + death.time_dead + 40
                ]
                major = [
                    o for o in lost
                    if o.kind == "roshan"
                    or "Бараки" in o.label
                    or "Трон" in o.label
                    or "Т3" in o.label
                    or ("Т2" in o.label and p.position <= 2)
                ]
                if major:
                    selected = major[0]
                    objective_added = True
            if selected:
                severity = 3 if ("Бараки" in selected.label or selected.kind == "roshan" or "Трон" in selected.label) else 2
                add(
                    p, p.team, death.time, "objective_after_death",
                    "Смерть → потеря объекта",
                    f"Пока игрок был мёртв, команда отдала {selected.label} на {fmt_time(selected.time)}. "
                    "Это не обязательно его вина, но тайминги совпадают.",
                    severity, 0,
                )
            # 1. Buyback and die again
            recent_bb = [b for b in p.buyback_log if 0 < death.time - float(b.get("time", 0)) <= 120]
            if recent_bb and counts.get("buyback_death", 0) < 2:
                bb = recent_bb[-1]
                add(
                    p, p.team, death.time, "buyback_death",
                    "Выкупился и снова умер",
                    f"Байбек на {fmt_time(float(bb.get('time', 0)))} — и смерть через {int(death.time - float(bb.get('time', 0)))} секунд{killer}. "
                    f"Потеряно ещё ~{fmt_num(cost)} золота.",
                    4 if death.time > 1800 else 3, cost,
                )
                counts["buyback_death"] = counts.get("buyback_death", 0) + 1
                continue
            # 2. Throw death while ahead
            p_before = _prob_for(probs, p.team, minute)
            p_after = _prob_for(probs, p.team, min(len(probs) - 1, minute + 3))
            lead = match.gold_for(p.team, minute)
            drop = p_before - p_after
            squad_nw = sorted((x.networth for x in match.squad(p.team)), reverse=True)
            top_nw = len(squad_nw) < 2 or p.networth_at(death.time) >= squad_nw[1] * 0.95
            mates15 = _teammate_deaths(match, p, death, 15)
            throw_hit = False
            if death.time >= 720 and counts.get("throw_death", 0) < 2:
                cheap = cost < 1500 and not top_nw
                if not mates15 and p_before >= 65 and drop >= 8 and not (cheap and drop < 18):
                    throw_hit = True
                elif top_nw and lead >= 8000 and drop >= 10:
                    throw_hit = True
            if throw_hit:
                add(
                    p, p.team, death.time, "throw_death",
                    "Смерть при преимуществе",
                    f"Смерть на {fmt_time(death.time)}{killer} при преимуществе {fmt_num(lead, signed=True)} и {p_before:.0f}% шансах. "
                    f"Через 3 минуты шансы команды — {p_after:.0f}% (−{drop:.0f} п.п.). Потеряно ~{fmt_num(cost)} золота.",
                    5 if drop >= 15 or lead >= 10000 else 4, cost,
                )
                counts["throw_death"] = counts.get("throw_death", 0) + 1
                continue
            # 3. Solo / no-trade death
            in_fight = death.fight_index is not None
            mates = _teammate_deaths(match, p, death)
            trades = _kills_between(match, p.team, death.time - 20, death.time + 30)
            if not in_fight and not mates and not trades and counts.get("solo_death", 0) < 4:
                severity = 2
                if cost >= 1200:
                    severity += 1
                if death.time < 480:
                    severity = max(1, severity - 1)
                add(
                    p, p.team, death.time, "solo_death",
                    "Смерть без размена",
                    f"На {fmt_time(death.time)}{killer} умер без размена: союзники не погибли рядом и не забрали ответное убийство. "
                    f"Потеряно ~{fmt_num(cost)} золота и {death.time_dead} сек. игры.",
                    severity, cost,
                )
                counts["solo_death"] = counts.get("solo_death", 0) + 1
        # 5. Farming while the team loses a fight
        farm_flags = 0
        for fight in match.fights:
            if fight.start < 600 or fight.duration < 8:
                continue
            team_deaths = fight.radiant_deaths if p.team == "radiant" else fight.dire_deaths
            if team_deaths < 3 or p.position > 3:
                continue
            entry = next((e for e in fight.players if e.player_id == p.id), None)
            if not entry or entry.damage != 0:
                continue
            dead = any(
                d.victim_id == p.id and fight.start - 10 <= d.time <= fight.end + 10 for d in match.deaths
            )
            if dead:
                continue
            team_obj = [
                o for o in match.objectives
                if o.team == p.team and fight.start - 30 <= o.time <= fight.end + 90
            ]
            if team_obj:
                continue
            team_swing = fight.gold_swing if p.team == "radiant" else -fight.gold_swing
            add(
                p, p.team, fight.start, "farm_no_fight",
                "Драка прошла без участия",
                f"Драка {fmt_time(fight.start)}–{fmt_time(fight.end)}: команда потеряла {team_deaths} "
                f"{plural(team_deaths, 'героя', 'героев', 'героев')}, а {p.hero_name} не нанёс ни единицы урона и остался жив. "
                f"Потери в драке: {fmt_num(team_swing, signed=True)} золота.",
                4 if p.position <= 2 else 3,
                int(abs(team_swing) * 0.5),
            )
            farm_flags += 1
            if farm_flags >= 1:
                break

        # 6. Lost lane
        if p.position <= 3 and match.duration >= 720:
            base_lh = BASE["lh10"][p.position]
            enemy = _same_position_enemy(match, p)
            if p.lh10 < base_lh * 0.55:
                deficit = max(0, (enemy.networth_at(600) - p.networth_at(600)) if enemy else 0)
                add(
                    p, p.team, 600, "low_lane",
                    "Проигранный лейнинг",
                    f"К 10-й минуте {p.lh10} ЛХ / {p.dn10} ДН"
                    + (f" против {enemy.lh10} у {enemy.hero_name}" if enemy else "")
                    + f". Отставание по нетворсу — {fmt_num(deficit)}.",
                    3 if p.lh10 < base_lh * 0.4 else 2,
                    deficit,
                )

        # 7. BKB bought but never used
        if _has_item(p, "black_king_bar") and int(p.item_uses.get("black_king_bar", 0) or 0) == 0 and p.deaths_count >= 4:
            add(
                p, p.team, match.duration - 60, "unused_bkb",
                "BKB без использования",
                f"BKB в инвентаре, но за матч не использован ни разу при {p.deaths_count} смертях.",
                2, 0,
            )

        # 8. Vision gap for supports
        enemies = match.squad(match.enemy(p.team))
        if p.position >= 4 and match.duration >= 20 * 60:
            wards = p.obs + p.sen
            rate = wards / max(1.0, match.duration / 60)
            enemy_supports = [e for e in enemies if e.position >= 4]
            enemy_wards = sum(e.obs + e.sen for e in enemy_supports)
            if rate < 0.45 and enemy_wards > wards * 1.4:
                add(
                    p, p.team, match.duration - 60, "vision_gap",
                    "Провал по вижну",
                    f"{wards} вардов за {int(match.duration / 60)} минут ({rate:.2f}/мин) "
                    f"против {enemy_wards} у саппортов врага.",
                    2, 0,
                )

    # Team-level mistakes
    team_mistakes: list[dict] = []
    for team in ("radiant", "dire"):
        enemy = match.enemy(team)
        rosh_given = sum(1 for o in match.objectives if o.kind == "roshan" and o.team == enemy)
        enemy_buildings = [o for o in match.objectives if o.kind == "building" and o.team == enemy]
        early = [o for o in enemy_buildings if o.time <= 20 * 60]
        losses = 0
        best = 0
        first_loss = None
        last_loss = None
        for fight in match.fights:
            if fight.deaths == 0:
                continue
            if fight.winner == enemy:
                losses += 1
                if losses == 1:
                    first_loss = fight
                last_loss = fight
                best = max(best, losses)
            else:
                losses = 0
        wards = sum(p.obs + p.sen for p in match.squad(team))
        if rosh_given >= 2:
            team_mistakes.append(
                {
                    "team": team,
                    "type": "roshan",
                    "title": f"Отдали {rosh_given} {plural(rosh_given, 'Рошана', 'Рошана', 'Рошанов')}",
                    "text": f"{'Radiant' if team == 'radiant' else 'Dire'} проиграли контроль Рошана: "
                    f"соперник забрал {rosh_given} {plural(rosh_given, 'Рошана', 'Рошана', 'Рошанов')}.",
                    "severity": 3,
                }
            )
        if len(early) >= 4:
            team_mistakes.append(
                {
                    "team": team,
                    "type": "towers",
                    "title": "Ранний обвал башен",
                    "text": f"До 20-й минуты потеряли {len(early)} {plural(len(early), 'здание', 'здания', 'зданий')}.",
                    "severity": 3,
                }
            )
        if best >= 3:
            team_mistakes.append(
                {
                    "team": team,
                    "type": "fight_streak",
                    "title": f"{best} проигранных драк подряд",
                    "text": f"Серия с {fmt_time(first_loss.start)} по {fmt_time(last_loss.end)} "
                    f"({best} {plural(best, 'драка', 'драки', 'драк')}).",
                    "severity": 4,
                }
            )
        enemy_wards = sum(p.obs + p.sen for p in match.squad(enemy))
        if enemy_wards > wards * 1.6 and enemy_wards - wards >= 15:
            team_mistakes.append(
                {
                    "team": team,
                    "type": "vision",
                    "title": "Проигран вижн",
                    "text": f"{wards} вардов против {enemy_wards}: карта была под контролем соперника.",
                    "severity": 2,
                }
            )

    # Keep the feed readable: top 8 per player, overall sorted by severity.
    per_player: dict[str, int] = {}
    kept = []
    for m in sorted(mistakes, key=lambda x: (-x["severity"], x["time"])):
        pid = m["player_id"] or "team"
        if per_player.get(pid, 0) >= 6:
            continue
        per_player[pid] = per_player.get(pid, 0) + 1
        kept.append(m)
    kept.sort(key=lambda x: (-x["severity"], x["time"]))
    return kept[:32], team_mistakes
