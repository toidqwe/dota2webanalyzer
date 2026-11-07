"""Convert a gem-dota ``ParsedMatch`` into the OpenDota-shaped dict the analyzer uses.

The per-minute curves, objectives, draft and teamfights produced by gem match
OpenDota's parser closely; deaths are rebuilt from the combat log and the gold
ledger because gem does not emit OpenDota's ``deaths_log`` directly.
"""

from __future__ import annotations

from collections import defaultdict

from .normalize import ITEMS, xp_to_level

TEAM_MAP = {2: "radiant", 3: "dire"}


def _item_id(name: str | None) -> int | None:
    if not name:
        return None
    key = str(name).replace("item_", "", 1)
    item = ITEMS.get(key)
    return int(item["id"]) if item and item.get("id") is not None else None


def _strip_item(name: str) -> str:
    return str(name or "").replace("item_", "", 1)


def _sum_damage_taken(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        return int(sum(v for v in value.values() if isinstance(v, (int, float))))
    try:
        return int(sum(value.values()))
    except Exception:
        return 0


def _hero_slot(player) -> int:
    # gem player_id is global 0..9; OpenDota uses 0..4 and 128..132.
    return player.player_id if player.team == 2 else 128 + max(0, player.player_id - 5)


def _killer_hero_name(entry) -> str:
    name = entry.attacker_name or entry.damage_source_name or ""
    if "npc_dota_lone_druid_bear" in name:
        return "npc_dota_hero_lone_druid"
    if name.startswith("npc_dota_hero_"):
        return name
    return ""


def _death_rows(parsed, player, hero_names: dict[str, object]) -> list[dict]:
    """Rebuild OpenDota-style deaths_log entries from the combat log."""
    entries = []
    for entry in parsed.combat_log:
        log_type = getattr(entry, "log_type", None)
        if getattr(log_type, "value", None) != "DEATH" or not getattr(entry, "target_is_hero", False):
            continue
        if entry.target_name != player.hero_name:
            continue
        time_s = entry.game_time_s
        if time_s is None:
            time_s = 0.0
        entries.append((float(time_s), entry))
    entries.sort(key=lambda pair: pair[0])
    if not entries:
        return []

    # Respawn time weights, scaled so their sum matches the observed dead time.
    levels = []
    for time_s, _ in entries:
        minute = max(0, min(len(player.xp_t_min) - 1, int(time_s // 60))) if player.xp_t_min else 0
        xp = player.xp_t_min[minute] if player.xp_t_min else 0
        levels.append(xp_to_level(xp))
    weights = [6.0 + max(0, level - 1) * 3.8 for level in levels]
    observed_dead = float(getattr(player, "life_state_dead", 0) or 0)
    scale = (observed_dead / sum(weights)) if observed_dead > 0 and sum(weights) > 0 else 1.0
    scale = max(0.25, min(2.5, scale))

    # Gold lost to death per minute from the cumulative ledger.
    snapshots = []
    ledger = getattr(player, "gold_ledger", None)
    if ledger is not None:
        snapshots = list(getattr(ledger, "per_minute", []) or [])

    def lost_delta(minute: int) -> int:
        if minute + 1 >= len(snapshots):
            return 0
        return max(0, int(snapshots[minute + 1].lost_to_death) - int(snapshots[minute].lost_to_death))

    by_minute: dict[int, list[int]] = defaultdict(list)
    for idx, (time_s, _) in enumerate(entries):
        by_minute[int(time_s // 60)].append(idx)
    losses = [0] * len(entries)
    for minute, indices in by_minute.items():
        delta = lost_delta(minute)
        if not delta:
            continue
        share = delta / len(indices)
        for idx in indices:
            losses[idx] = int(share)

    rows = []
    for idx, (time_s, entry) in enumerate(entries):
        killer = _killer_hero_name(entry)
        level = levels[idx]
        rows.append(
            {
                "time": round(time_s, 1),
                "key": killer,
                "gold_fed": min(900, 200 + 12 * level),
                "gold_lost": losses[idx],
                "time_dead": max(5, round(weights[idx] * scale)),
            }
        )
    return rows


def to_opendota_dict(parsed, meta: dict | None = None) -> dict:
    """Build a payload that ``analyzer.Match`` can consume."""
    meta = meta or {}
    players = []
    ordered = sorted(parsed.players, key=lambda p: (p.team, p.player_id))
    hero_names = {p.hero_name: p for p in ordered}
    kill_logs: dict[int, list[dict]] = defaultdict(list)
    ward_logs: dict[int, dict[str, list[dict]]] = {
        p.player_id: {"obs": [], "sen": [], "obs_left": [], "sen_left": []} for p in ordered
    }
    clock = getattr(parsed, "game_clock", None)
    ehandle = 1
    for ward in getattr(parsed, "wards", []) or []:
        if ward.player_id not in ward_logs or ward.x is None or ward.y is None:
            continue
        try:
            placed = clock.game_time_at(ward.tick) if clock else None
        except (TypeError, ValueError):
            placed = None
        if placed is None:
            continue
        is_obs = ward.ward_type == "observer"
        bucket = ward_logs[ward.player_id]
        log_key = "obs" if is_obs else "sen"
        left_key = "obs_left" if is_obs else "sen_left"
        bucket[log_key].append(
            {
                "time": round(float(placed), 1),
                "x": float(ward.x) / 128.0,
                "y": float(ward.y) / 128.0,
                "ehandle": ehandle,
            }
        )
        end_tick = getattr(ward, "killed_tick", None) or getattr(ward, "expires_tick", None)
        if end_tick:
            try:
                ended = clock.game_time_at(end_tick) if clock else None
            except (TypeError, ValueError):
                ended = None
            if ended is not None:
                bucket[left_key].append(
                    {
                        "time": round(float(ended), 1),
                        "x": float(ward.x) / 128.0,
                        "y": float(ward.y) / 128.0,
                        "ehandle": ehandle,
                    }
                )
        ehandle += 1

    # Build kills from hero deaths, attaching them to the killer.
    death_events = []
    for entry in parsed.combat_log:
        log_type = getattr(entry, "log_type", None)
        if getattr(log_type, "value", None) != "DEATH" or not getattr(entry, "target_is_hero", False):
            continue
        if entry.target_name not in hero_names:
            continue
        killer = _killer_hero_name(entry)
        killer_player = hero_names.get(killer)
        if killer_player is not None:
            kill_logs[killer_player.player_id].append(
                {"time": round(float(entry.game_time_s or 0), 1), "key": entry.target_name}
            )

    for p in ordered:
        items = p.final_items or {}
        item_fields = {}
        for slot in range(6):
            item_fields[f"item_{slot}"] = _item_id(items.get(slot)) or 0
        neutral = _item_id(items.get(16)) or _item_id(items.get(6)) or 0
        purchases = []
        for entry in p.purchase_log or []:
            key = _strip_item(getattr(entry, "value_name", ""))
            if not key:
                continue
            time_s = getattr(entry, "game_time_s", None)
            if time_s is None:
                continue
            purchases.append({"time": round(float(time_s), 1), "key": key})
        buybacks = []
        for entry in p.buyback_log or []:
            time_s = getattr(entry, "game_time_s", None)
            if time_s is None:
                continue
            buybacks.append({"time": round(float(time_s), 1)})
        players.append(
            {
                "player_slot": _hero_slot(p),
                "account_id": getattr(p, "account_id", 0) or 0,
                "hero_id": p.hero_id,
                "personaname": p.player_name or f"Player {p.player_id + 1}",
                "name": p.player_name or "",
                "kills": p.kills,
                "deaths": p.deaths,
                "assists": p.assists,
                "net_worth": p.net_worth,
                "last_hits": p.last_hits,
                "denies": p.denies,
                "gold_per_min": p.gold_per_min,
                "xp_per_min": p.xp_per_min,
                "level": p.level,
                "hero_damage": p.hero_damage,
                "tower_damage": p.tower_damage,
                "hero_healing": p.hero_healing,
                "damage_taken": _sum_damage_taken(p.damage_taken),
                "stuns": p.stuns_dealt,
                "obs_placed": p.obs_placed,
                "sen_placed": p.sen_placed,
                "camps_stacked": p.camps_stacked,
                "rune_pickups": p.rune_pickups,
                "buyback_count": p.buyback_count,
                "purchase_tpscroll": p.purchase_tpscroll,
                "roshans_killed": p.roshan_kills,
                "towers_killed": p.tower_kills,
                "observer_kills": p.observer_kills,
                "sentry_kills": p.sentry_kills,
                "firstblood_claimed": bool(p.firstblood_claimed),
                "teamfight_participation": p.teamfight_participation,
                "lane": p.lane,
                "lane_role": p.lane_role,
                "is_roaming": bool(p.is_roaming),
                "lane_efficiency_pct": p.lane_efficiency_pct,
                "gold_t": list(p.gold_t_min or []),
                "networth_t": list(p.net_worth_t_min or []),
                "lh_t": list(p.lh_t_min or []),
                "dn_t": list(p.dn_t_min or []),
                "xp_t": list(p.xp_t_min or []),
                "deaths_log": _death_rows(parsed, p, hero_names),
                "kills_log": kill_logs.get(p.player_id, []),
                "obs_log": ward_logs.get(p.player_id, {}).get("obs", []),
                "sen_log": ward_logs.get(p.player_id, {}).get("sen", []),
                "obs_left_log": ward_logs.get(p.player_id, {}).get("obs_left", []),
                "sen_left_log": ward_logs.get(p.player_id, {}).get("sen_left", []),
                "buyback_log": buybacks,
                "purchase_log": purchases,
                "item_uses": {_strip_item(k): v for k, v in (p.item_uses or {}).items()},
                "ability_uses": dict(p.ability_uses or {}),
                "item_neutral": neutral,
                "life_state_dead": getattr(p, "life_state_dead", 0),
                "benchmarks": {},
                **item_fields,
            }
        )

    teamfights = []
    for fight in getattr(parsed, "opendota_teamfights", []) or []:
        fight_players = []
        for fp in fight.players:
            fight_players.append(
                {
                    "deaths_pos": getattr(fp, "deaths_pos", {}) or {},
                    "ability_uses": getattr(fp, "ability_uses", {}) or {},
                    "item_uses": getattr(fp, "item_uses", {}) or {},
                    "killed": getattr(fp, "killed", {}) or {},
                    "deaths": getattr(fp, "deaths", 0),
                    "buybacks": getattr(fp, "buybacks", 0),
                    "damage": getattr(fp, "damage", 0),
                    "healing": getattr(fp, "healing", 0),
                    "gold_delta": getattr(fp, "gold_delta", 0),
                    "xp_delta": getattr(fp, "xp_delta", 0),
                }
            )
        teamfights.append(
            {
                "start": fight.start,
                "end": fight.end,
                "last_death": fight.last_death,
                "deaths": fight.deaths,
                "players": fight_players,
            }
        )

    draft = []
    for order, event in enumerate(sorted(getattr(parsed, "draft", []) or [], key=lambda e: e.tick)):
        draft.append(
            {
                "is_pick": bool(event.is_pick),
                "hero_id": event.hero_id,
                "team": 0 if event.team == 2 else 1,
                "order": order,
            }
        )

    objectives = []
    for objective in getattr(parsed, "objectives", []) or []:
        if isinstance(objective, dict):
            objectives.append(objective)

    chat = []
    clock = getattr(parsed, "game_clock", None)
    start_tick = getattr(parsed, "game_start_tick", None) or 0
    for entry in getattr(parsed, "chat", []) or []:
        text = (getattr(entry, "text", "") or "").strip()
        if not text:
            continue
        try:
            time_s = clock.game_time_at(entry.tick) if clock else (entry.tick - start_tick) / 30.0
        except (TypeError, ValueError):
            time_s = None
        if time_s is None:
            continue
        slot = getattr(entry, "player_slot", None)
        if slot is not None and slot >= 5:
            slot = 128 + (slot - 5)
        chat.append({"time": round(float(time_s), 1), "type": "chat", "key": text, "player_slot": slot})

    wisdom = []
    for entry in parsed.combat_log:
        if getattr(getattr(entry, "log_type", None), "value", None) != "PICKUP_RUNE":
            continue
        if getattr(entry, "rune_type", None) != 8:
            continue
        time_s = getattr(entry, "game_time_s", None)
        if time_s is None:
            continue
        slot = getattr(entry, "value", None)
        if slot is None:
            continue
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            continue
        player = next((p for p in ordered if p.player_id == slot), None)
        if player is None:
            continue
        pid = ("r" if player.team == 2 else "d") + str(player.player_id if player.team == 2 else player.player_id - 5)
        wisdom.append({"time": round(float(time_s), 1), "player_id": pid, "team": "radiant" if player.team == 2 else "dire"})

    first_blood = next(
        (o.get("time", 0) for o in objectives if o.get("type") == "CHAT_MESSAGE_FIRSTBLOOD"),
        getattr(parsed, "first_blood_time", 0) or 0,
    )

    return {
        "match_id": parsed.match_id,
        "duration": parsed.duration,
        "radiant_win": parsed.radiant_win,
        "start_time": int(meta.get("start_time") or 0),
        "game_mode": int(meta.get("game_mode") or parsed.game_mode or 0),
        "lobby_type": int(meta.get("lobby_type") or 0),
        "patch": meta.get("patch"),
        "leagueid": parsed.leagueid or 0,
        "radiant_score": parsed.radiant_score,
        "dire_score": parsed.dire_score,
        "first_blood_time": first_blood,
        "pre_game_duration": getattr(parsed, "pre_game_duration", 0) or 0,
        "players": players,
        "teamfights": teamfights,
        "objectives": objectives,
        "picks_bans": draft,
        "radiant_gold_adv": list(parsed.radiant_gold_adv or []),
        "radiant_xp_adv": list(parsed.radiant_xp_adv or []),
        "chat": chat,
        "wisdom_runes": wisdom,
        "glyphs": [],
        "_source": "gem-dota",
    }
