"""Normalize a raw OpenDota match payload into an analysis-friendly model."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import BASE, LANE_LABEL, POSITION_LABEL

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"

CDN_HERO = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{}.png"
CDN_ITEM = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/{}.png"


def _load_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


HEROES: dict[str, dict] = _load_json(DATA_DIR / "heroes.json", {})
ITEMS: dict[str, dict] = _load_json(DATA_DIR / "items.json", {})
ITEMS_BY_ID: dict[str, dict] = _load_json(DATA_DIR / "items_by_id.json", {})


def hero_image(key: str) -> str:
    local = WEB_DIR / "img" / "heroes" / f"{key}.png"
    if local.exists():
        return f"/img/heroes/{key}.png"
    return CDN_HERO.format(key)


def item_image(key: str) -> str:
    local = WEB_DIR / "img" / "items" / f"{key}.png"
    if local.exists():
        return f"/img/items/{key}.png"
    return CDN_ITEM.format(key)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def xp_to_level(xp: float) -> int:
    from .constants import XP_TABLE

    level = 1
    for idx, threshold in enumerate(XP_TABLE):
        if xp >= threshold:
            level = max(1, idx)
    return min(level, 30)


@dataclass
class Player:
    id: str
    slot: int
    team: str
    idx: int
    name: str
    hero_id: int
    hero_key: str
    hero_name: str
    attr: str
    attack: str
    roles: list[str]
    position: int
    lane_role: int
    is_roaming: bool
    is_radiant: bool
    kills: int
    deaths: int
    assists: int
    kda: float
    gpm: int
    xpm: int
    lh: int
    dn: int
    lh10: int
    dn10: int
    level: int
    networth: int
    hero_damage: int
    tower_damage: int
    hero_healing: int
    damage_taken: int
    tf_part: float
    stuns: float
    obs: int
    sen: int
    observer_kills: int
    sentry_kills: int
    camps_stacked: int
    rune_pickups: int
    buybacks: int
    tpscroll: int
    roshan_kills: int
    towers_killed: int
    firstblood_claimed: bool
    benchmarks: dict
    lane_efficiency_pct: float
    items: list[dict]
    neutral_item: dict | None
    gold_t: list[int]
    xp_t: list[int]
    lh_t: list[int]
    dn_t: list[int]
    networth_t: list[int]
    deaths_log: list[dict]
    kills_log: list[dict]
    buyback_log: list[dict]
    purchase_log: list[dict]
    runes_log: list[dict]
    obs_log: list[dict]
    sen_log: list[dict]
    obs_left_log: list[dict]
    sen_left_log: list[dict]
    item_uses: dict
    ability_uses: dict
    account_id: int = 0
    rank_tier: int = 0
    computed_mmr: float = 0.0
    pings: int = 0
    leaver_status: int = 0
    wisdom_count: int = 0
    deaths_reported: int = 0
    death_cost: float = 0.0
    deaths_count: int = 0
    team_kills: int = 0
    team_deaths: int = 0
    team_nw: int = 0
    nw_share: float = 0.0
    kp: float = 0.0
    lanes: list[str] = field(default_factory=list)

    def networth_at(self, seconds: float) -> int:
        if not self.networth_t:
            return self.networth
        minute = int(max(0, min(len(self.networth_t) - 1, seconds // 60)))
        return self.networth_t[minute]

    def gold_at(self, seconds: float) -> int:
        if not self.gold_t:
            return 0
        minute = int(max(0, min(len(self.gold_t) - 1, seconds // 60)))
        return self.gold_t[minute]

    def level_at(self, seconds: float) -> int:
        if not self.xp_t:
            return self.level
        minute = int(max(0, min(len(self.xp_t) - 1, seconds // 60)))
        return xp_to_level(self.xp_t[minute])

    def image(self) -> str:
        return hero_image(self.hero_key)


@dataclass
class Death:
    time: float
    victim_id: str
    killer_id: str | None
    killer_hero: str
    gold_fed: int
    gold_lost: int
    time_dead: int
    fight_index: int | None = None
    solo: bool = False

    @property
    def cost(self) -> int:
        return int(self.gold_lost + self.gold_fed)


@dataclass
class FightPlayer:
    player_id: str
    damage: int
    healing: int
    deaths: int
    gold_delta: int
    xp_delta: int
    killed: list[str]
    buybacks: int
    death_positions: list[tuple[float, float]]


@dataclass
class Fight:
    index: int
    start: float
    end: float
    radiant_deaths: int
    dire_deaths: int
    winner: str
    gold_swing: float
    damage_radiant: int
    damage_dire: int
    players: list[FightPlayer]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def deaths(self) -> int:
        return self.radiant_deaths + self.dire_deaths

    @property
    def major(self) -> bool:
        return self.deaths >= 2 or (self.damage_radiant + self.damage_dire) >= 3000


@dataclass
class Objective:
    time: float
    kind: str
    team: str | None
    player_id: str | None
    label: str
    lane: str | None = None
    victim_team: str | None = None
    raw_key: str = ""


class Match:
    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise ValueError("Ожидался JSON матча OpenDota")
        self.raw = raw
        self.id = safe_int(raw.get("match_id"))
        self.duration = safe_int(raw.get("duration"))
        self.radiant_win = bool(raw.get("radiant_win"))
        self.start_time = safe_int(raw.get("start_time"))
        self.game_mode = safe_int(raw.get("game_mode"))
        self.lobby_type = safe_int(raw.get("lobby_type"))
        self.league_id = safe_int(raw.get("leagueid"))
        self.radiant_score = safe_int(raw.get("radiant_score"))
        self.dire_score = safe_int(raw.get("dire_score"))
        self.first_blood_time = safe_int(raw.get("first_blood_time"))
        self.patch = raw.get("patch")
        self.region = raw.get("region")
        self.picks_bans = raw.get("picks_bans") or []
        self.players: list[Player] = []
        self.deaths: list[Death] = []
        self.fights: list[Fight] = []
        self.objectives: list[Objective] = []
        self.gold_adv: list[float] = []
        self.xp_adv: list[float] = []
        self.win_prob: list[float] = []
        self.chat: list[dict] = []
        self.wisdom_runes: list[dict] = []
        self.glyphs: list[dict] = []
        self.wards: list[dict] = []
        self.fight_deaths: list[dict] = []
        self.buildings: list[dict] = []
        self.death_mismatches: list[dict] = []
        self.score_adjustments: list[dict] = []
        self.pauses: list = list(raw.get("pauses") or [])
        self._by_id: dict[str, Player] = {}
        self._hero_map: dict[str, Player] = {}

        self._build_players()
        self._build_deaths_and_kills()
        self._reconcile_deaths_with_score()
        self._build_fights()
        self._build_map_data()
        self._build_objectives()
        self._build_buildings()
        self._build_timelines()
        self._build_chat()
        self._build_wisdom_runes()
        self._build_glyphs()
        self._mark_fight_deaths()
        self._team_totals()

    # ------------------------------------------------------------------ players
    def _build_players(self) -> None:
        raw_players = self.raw.get("players") or []
        if not raw_players:
            raise ValueError("В матче нет данных об игроках")
        ordered = sorted(raw_players, key=lambda p: safe_int(p.get("player_slot")))
        has_position_est = any(safe_int(rp.get("position_est")) in (1, 2, 3, 4, 5) for rp in ordered)
        for slot_index, rp in enumerate(ordered):
            slot = safe_int(rp.get("player_slot"))
            is_radiant = slot < 128
            team = "radiant" if is_radiant else "dire"
            idx = slot if is_radiant else slot - 128
            hero_id = safe_int(rp.get("hero_id"))
            hero = HEROES.get(str(hero_id), {})
            hero_key = hero.get("key") or f"hero_{hero_id}"
            position = safe_int(rp.get("position_est"))
            if position not in (1, 2, 3, 4, 5):
                position = self._infer_position(rp, ordered)
            lane_role = safe_int(rp.get("lane_role"))
            if lane_role not in (1, 2, 3):
                lane_role = 1 if position in (1, 5) else 2 if position == 2 else 3
            gold_t = [safe_int(v) for v in (rp.get("gold_t") or [])]
            xp_t = [safe_int(v) for v in (rp.get("xp_t") or [])]
            lh_t = [safe_int(v) for v in (rp.get("lh_t") or [])]
            dn_t = [safe_int(v) for v in (rp.get("dn_t") or [])]
            networth_t = [safe_int(v) for v in (rp.get("networth_t") or [])]
            kills = safe_int(rp.get("kills"))
            deaths = safe_int(rp.get("deaths"))
            assists = safe_int(rp.get("assists"))
            items = []
            for i in range(6):
                item_id = rp.get(f"item_{i}")
                if not item_id:
                    continue
                meta = ITEMS_BY_ID.get(str(item_id))
                if not meta:
                    continue
                items.append(
                    {
                        "key": meta["key"],
                        "name": meta["name"],
                        "cost": meta.get("cost", 0),
                        "img": item_image(meta["key"]),
                    }
                )
            neutral = None
            if rp.get("item_neutral"):
                meta = ITEMS_BY_ID.get(str(rp["item_neutral"]))
                if meta:
                    neutral = {"key": meta["key"], "name": meta["name"], "img": item_image(meta["key"])}
            name = (rp.get("name") or "").strip() or (rp.get("personaname") or "").strip() or f"Player {idx + 1}"
            player = Player(
                id=f"{team[0]}{idx}",
                slot=slot,
                team=team,
                idx=idx,
                name=name,
                hero_id=hero_id,
                hero_key=hero_key,
                hero_name=hero.get("name") or hero_key,
                attr=hero.get("attr") or "all",
                attack=hero.get("attack") or "Melee",
                roles=hero.get("roles") or [],
                position=position,
                lane_role=lane_role,
                is_roaming=bool(rp.get("is_roaming")),
                is_radiant=is_radiant,
                kills=kills,
                deaths=deaths,
                assists=assists,
                kda=round((kills + assists) / max(1, deaths), 2),
                gpm=safe_int(rp.get("gold_per_min")),
                xpm=safe_int(rp.get("xp_per_min")),
                lh=safe_int(rp.get("last_hits")),
                dn=safe_int(rp.get("denies")),
                lh10=lh_t[10] if len(lh_t) > 10 else (lh_t[-1] if lh_t else 0),
                dn10=dn_t[10] if len(dn_t) > 10 else (dn_t[-1] if dn_t else 0),
                level=safe_int(rp.get("level"), 1),
                networth=safe_int(rp.get("net_worth")),
                hero_damage=safe_int(rp.get("hero_damage")),
                tower_damage=safe_int(rp.get("tower_damage")),
                hero_healing=safe_int(rp.get("hero_healing")),
                damage_taken=safe_int(rp.get("damage_taken")),
                tf_part=safe_float(rp.get("teamfight_participation")),
                stuns=safe_float(rp.get("stuns")),
                obs=safe_int(rp.get("obs_placed")),
                sen=safe_int(rp.get("sen_placed")),
                observer_kills=safe_int(rp.get("observer_kills")),
                sentry_kills=safe_int(rp.get("sentry_kills")),
                camps_stacked=safe_int(rp.get("camps_stacked")),
                rune_pickups=safe_int(rp.get("rune_pickups")),
                buybacks=safe_int(rp.get("buyback_count")),
                tpscroll=safe_int(rp.get("purchase_tpscroll")),
                roshan_kills=safe_int(rp.get("roshans_killed")),
                towers_killed=safe_int(rp.get("towers_killed")),
                firstblood_claimed=bool(rp.get("firstblood_claimed")),
                benchmarks=rp.get("benchmarks") or {},
                lane_efficiency_pct=safe_float(rp.get("lane_efficiency_pct")),
                items=items,
                neutral_item=neutral,
                gold_t=gold_t,
                xp_t=xp_t,
                lh_t=lh_t,
                dn_t=dn_t,
                networth_t=networth_t,
                deaths_log=rp.get("deaths_log") or [],
                kills_log=rp.get("kills_log") or [],
                buyback_log=rp.get("buyback_log") or [],
                purchase_log=rp.get("purchase_log") or [],
                runes_log=rp.get("runes_log") or [],
                obs_log=rp.get("obs_log") or [],
                sen_log=rp.get("sen_log") or [],
                obs_left_log=rp.get("obs_left_log") or [],
                sen_left_log=rp.get("sen_left_log") or [],
                item_uses=rp.get("item_uses") or {},
                ability_uses=rp.get("ability_uses") or {},
                account_id=safe_int(rp.get("account_id")),
                rank_tier=safe_int(rp.get("rank_tier")),
                computed_mmr=safe_float(rp.get("computed_mmr")),
                pings=safe_int(rp.get("pings")),
                leaver_status=safe_int(rp.get("leaver_status")),
                deaths_reported=safe_int(rp.get("deaths")),
            )
            player.lanes = [LANE_LABEL.get(lane_role, "Мид")]
            self.players.append(player)
            self._by_id[player.id] = player
            self._hero_map[player.hero_key] = player
        if not has_position_est:
            self._assign_positions()

    def _assign_positions(self) -> None:
        """Assign 1..5 from lanes, ranking players within their own lane."""
        for team in ("radiant", "dire"):
            squad = [p for p in self.players if p.team == team]
            assigned: set[str] = set()

            def take(position: int, candidates: list[Player], lowest: bool = False) -> None:
                available = [p for p in candidates if p.id not in assigned]
                if not available:
                    return
                player = min(available, key=lambda p: p.gpm) if lowest else max(available, key=lambda p: p.gpm)
                player.position = position
                assigned.add(player.id)

            mid = [p for p in squad if p.lane_role == 2]
            safe = [p for p in squad if p.lane_role == 1]
            off = [p for p in squad if p.lane_role == 3]
            take(2, mid)
            take(1, safe)
            take(5, safe, lowest=True)
            take(3, off)
            take(4, off, lowest=True)
            remaining = sorted((p for p in squad if p.id not in assigned), key=lambda p: p.gpm, reverse=True)
            free = [pos for pos in (1, 2, 3, 4, 5) if pos not in {p.position for p in squad if p.id in assigned}]
            for player, position in zip(remaining, free):
                player.position = position
                assigned.add(player.id)

    def _infer_position(self, rp: dict, ordered: list[dict]) -> int:
        lane = safe_int(rp.get("lane_role"))
        gpm = safe_int(rp.get("gold_per_min"))
        same_team = [
            p for p in ordered
            if (safe_int(p.get("player_slot")) < 128) == (safe_int(rp.get("player_slot")) < 128)
        ]
        ranked = sorted(same_team, key=lambda p: safe_int(p.get("gold_per_min")), reverse=True)
        if lane == 2:
            return 2
        if lane == 1:
            return 1 if ranked and safe_int(ranked[0].get("player_slot")) == safe_int(rp.get("player_slot")) else 5
        if lane == 3:
            return 3 if ranked and safe_int(ranked[0].get("player_slot")) == safe_int(rp.get("player_slot")) else 4
        rank = next((i for i, p in enumerate(ranked) if safe_int(p.get("player_slot")) == safe_int(rp.get("player_slot"))), 4)
        return [1, 2, 3, 4, 5][min(rank, 4)]

    # ------------------------------------------------------------------ deaths
    def _build_deaths_and_kills(self) -> None:
        for player in self.players:
            entries = player.deaths_log or []
            if entries:
                for entry in entries:
                    killer_hero = str(entry.get("key") or "").replace("npc_dota_hero_", "")
                    killer = self._hero_map.get(killer_hero)
                    self.deaths.append(
                        Death(
                            time=safe_float(entry.get("time")),
                            victim_id=player.id,
                            killer_id=killer.id if killer else None,
                            killer_hero=killer.hero_name if killer else killer_hero,
                            gold_fed=safe_int(entry.get("gold_fed")),
                            gold_lost=safe_int(entry.get("gold_lost")),
                            time_dead=safe_int(entry.get("time_dead")),
                        )
                    )
            else:
                continue
        # Kills from kills_log (victim hero -> victim player), used for trade detection.
        self.kills: list[dict] = []
        for player in self.players:
            for entry in player.kills_log or []:
                victim_key = str(entry.get("key") or "").replace("npc_dota_hero_", "")
                victim = self._hero_map.get(victim_key)
                self.kills.append(
                    {
                        "time": safe_float(entry.get("time")),
                        "killer_id": player.id,
                        "killer_team": player.team,
                        "victim_id": victim.id if victim else None,
                        "victim_team": victim.team if victim else None,
                    }
                )
        self.kills.sort(key=lambda k: k["time"])
        self.deaths.sort(key=lambda d: d.time)
        # Fallback: deaths_log empty but kills exist
        if not self.deaths and self.kills:
            for kill in self.kills:
                if not kill["victim_id"]:
                    continue
                self.deaths.append(
                    Death(
                        time=kill["time"],
                        victim_id=kill["victim_id"],
                        killer_id=kill["killer_id"],
                        killer_hero=self._by_id[kill["killer_id"]].hero_name,
                        gold_fed=0,
                        gold_lost=0,
                        time_dead=0,
                    )
                )
        for player in self.players:
            logged = sum(1 for d in self.deaths if d.victim_id == player.id)
            if player.deaths_log:
                player.deaths_count = logged
                if logged != player.deaths_reported:
                    self.death_mismatches.append(
                        {"player_id": player.id, "reported": player.deaths_reported, "logged": logged}
                    )
                player.deaths = logged
                player.kda = round((player.kills + player.assists) / max(1, logged), 2)
            else:
                player.deaths_count = player.deaths_reported
            player.death_cost = sum(
                d.gold_lost + d.gold_fed + d.time_dead * (player.gpm / 60.0)
                for d in self.deaths
                if d.victim_id == player.id
            )
        self.first_blood_team: str | None = None
        if self.kills:
            fb = min(self.kills, key=lambda k: k["time"])
            self.first_blood_team = fb["killer_team"] if fb["time"] >= 0 else None

    def _reconcile_deaths_with_score(self) -> None:
        """Keep per-player deaths consistent with the official kill score.

        Some parsers count suicides, post-game deaths or deaths to illusions that
        OpenDota does not put in the score. Trimming the cheapest death of the
        over-counting team keeps KDA, the death table and the scoreline aligned.
        """
        for team in ("radiant", "dire"):
            expected = self.dire_score if team == "radiant" else self.radiant_score
            if expected <= 0:
                continue
            team_deaths = [d for d in self.deaths if self.player(d.victim_id).team == team]
            excess = len(team_deaths) - expected
            if excess <= 0:
                continue
            candidates = sorted(
                team_deaths,
                key=lambda d: (
                    0
                    if self.player(d.victim_id).deaths_count > self.player(d.victim_id).deaths_reported
                    else 1,
                    d.gold_lost != 0,
                    d.gold_lost + d.gold_fed,
                    -d.time,
                ),
            )
            removed = {id(d) for d in candidates[:excess]}
            self.deaths = [d for d in self.deaths if id(d) not in removed]
            for death in candidates[:excess]:
                self.score_adjustments.append(
                    {
                        "player_id": death.victim_id,
                        "time": death.time,
                        "gold_lost": death.gold_lost,
                        "gold_fed": death.gold_fed,
                    }
                )
        for player in self.players:
            logged = sum(1 for d in self.deaths if d.victim_id == player.id)
            if player.deaths_log:
                player.deaths_count = logged
                player.deaths = logged
                player.kda = round((player.kills + player.assists) / max(1, logged), 2)
            player.death_cost = sum(
                d.gold_lost + d.gold_fed + d.time_dead * (player.gpm / 60.0)
                for d in self.deaths
                if d.victim_id == player.id
            )

    # ------------------------------------------------------------------ fights
    def _build_fights(self) -> None:
        order = sorted(self.players, key=lambda p: p.slot)
        for idx, raw_fight in enumerate(self.raw.get("teamfights") or []):
            fp = raw_fight.get("players") or []
            if len(fp) != len(order):
                continue
            entries: list[FightPlayer] = []
            for i, player in enumerate(order):
                entry = fp[i] or {}
                positions = []
                for x, ys in (entry.get("deaths_pos") or {}).items():
                    for y, count in (ys or {}).items():
                        try:
                            positions.extend([(float(x), float(y))] * max(1, safe_int(count, 1)))
                        except (TypeError, ValueError):
                            continue
                entries.append(
                    FightPlayer(
                        player_id=player.id,
                        damage=safe_int(entry.get("damage")),
                        healing=safe_int(entry.get("healing")),
                        deaths=safe_int(entry.get("deaths")),
                        gold_delta=safe_int(entry.get("gold_delta")),
                        xp_delta=safe_int(entry.get("xp_delta")),
                        killed=[str(k).replace("npc_dota_hero_", "") for k in (entry.get("killed") or {})],
                        buybacks=safe_int(entry.get("buybacks")),
                        death_positions=positions,
                    )
                )
            radiant_deaths = sum(e.deaths for e in entries if self._by_id[e.player_id].team == "radiant")
            dire_deaths = sum(e.deaths for e in entries if self._by_id[e.player_id].team == "dire")
            gold_swing = sum(e.gold_delta for e in entries if self._by_id[e.player_id].team == "radiant") - sum(
                e.gold_delta for e in entries if self._by_id[e.player_id].team == "dire"
            )
            if radiant_deaths < dire_deaths:
                winner = "radiant"
            elif dire_deaths < radiant_deaths:
                winner = "dire"
            elif gold_swing > 0:
                winner = "radiant"
            elif gold_swing < 0:
                winner = "dire"
            else:
                winner = "draw"
            self.fights.append(
                Fight(
                    index=idx,
                    start=safe_float(raw_fight.get("start")),
                    end=safe_float(raw_fight.get("end")),
                    radiant_deaths=radiant_deaths,
                    dire_deaths=dire_deaths,
                    winner=winner,
                    gold_swing=gold_swing,
                    damage_radiant=sum(e.damage for e in entries if self._by_id[e.player_id].team == "radiant"),
                    damage_dire=sum(e.damage for e in entries if self._by_id[e.player_id].team == "dire"),
                    players=entries,
                )
            )

    def _build_map_data(self) -> None:
        self.map_bounds = {"min": 64.0, "max": 192.0}
        for player in self.players:
            left = {}
            for log in player.obs_left_log or []:
                left[log.get("ehandle")] = safe_float(log.get("time"))
            for log in player.sen_left_log or []:
                left[log.get("ehandle")] = safe_float(log.get("time"))
            for kind, logs in (("observer", player.obs_log or []), ("sentry", player.sen_log or [])):
                for entry in logs:
                    x, y = entry.get("x"), entry.get("y")
                    if x is None or y is None:
                        continue
                    placed = safe_float(entry.get("time"))
                    end = left.get(entry.get("ehandle"))
                    self.wards.append(
                        {
                            "time": placed,
                            "x": float(x),
                            "y": float(y),
                            "team": player.team,
                            "type": kind,
                            "player_id": player.id,
                            "duration": max(0.0, end - placed) if end else None,
                        }
                    )
        self.wards.sort(key=lambda w: w["time"])

        for fight in self.fights:
            for entry in fight.players:
                player = self.player(entry.player_id)
                if not entry.death_positions:
                    continue
                player_deaths = [
                    d
                    for d in self.deaths
                    if d.victim_id == player.id and fight.start - 5 <= d.time <= fight.end + 5
                ]
                for index, (x, y) in enumerate(entry.death_positions):
                    death = player_deaths[index] if index < len(player_deaths) else None
                    self.fight_deaths.append(
                        {
                            "time": death.time if death else fight.start,
                            "x": float(x),
                            "y": float(y),
                            "team": player.team,
                            "player_id": player.id,
                            "killer_id": death.killer_id if death else None,
                            "fight_index": fight.index,
                        }
                    )
        self.fight_deaths.sort(key=lambda d: d["time"])

    # --------------------------------------------------------------- objectives
    def _build_objectives(self) -> None:
        for raw_obj in self.raw.get("objectives") or []:
            kind_raw = raw_obj.get("type")
            time = safe_float(raw_obj.get("time"))
            if kind_raw == "building_kill":
                key = str(raw_obj.get("key") or "")
                if "badguys" in key:
                    team = "radiant"
                elif "goodguys" in key:
                    team = "dire"
                else:
                    team = None
                victim_team = {"radiant": "dire", "dire": "radiant"}.get(team or "", None)
                player = self._resolve_objective_player(raw_obj)
                label, lane = self._building_label(key)
                self.objectives.append(
                    Objective(
                        time=time,
                        kind="building",
                        team=team,
                        player_id=player.id if player else None,
                        label=label,
                        lane=lane,
                        victim_team=victim_team,
                        raw_key=key,
                    )
                )
            elif kind_raw == "CHAT_MESSAGE_ROSHAN_KILL":
                team = {2: "radiant", 3: "dire"}.get(safe_int(raw_obj.get("team")))
                self.objectives.append(
                    Objective(time=time, kind="roshan", team=team, player_id=None, label="Рошан", raw_key="roshan")
                )
            elif kind_raw == "CHAT_MESSAGE_AEGIS":
                player = self._resolve_player_slot(raw_obj.get("player_slot") or raw_obj.get("slot"))
                self.objectives.append(
                    Objective(
                        time=time,
                        kind="aegis",
                        team=player.team if player else None,
                        player_id=player.id if player else None,
                        label="Аегис",
                        raw_key="aegis",
                    )
                )
            elif kind_raw == "CHAT_MESSAGE_MINIBOSS_KILL":
                team = {2: "radiant", 3: "dire"}.get(safe_int(raw_obj.get("team")))
                self.objectives.append(
                    Objective(time=time, kind="miniboss", team=team, player_id=None, label="Мини-босс", raw_key="miniboss")
                )
            elif kind_raw == "CHAT_MESSAGE_FIRSTBLOOD":
                player = self._resolve_player_slot(raw_obj.get("player_slot") or raw_obj.get("slot"))
                self.objectives.append(
                    Objective(
                        time=time,
                        kind="firstblood",
                        team=player.team if player else None,
                        player_id=player.id if player else None,
                        label="Первая кровь",
                        raw_key="firstblood",
                    )
                )
        self.objectives.sort(key=lambda o: o.time)

    def _resolve_objective_player(self, raw_obj: dict) -> Player | None:
        unit = str(raw_obj.get("unit") or "")
        if "npc_dota_hero_" in unit:
            key = unit.split("npc_dota_hero_")[-1]
            player = self._hero_map.get(key)
            if player:
                return player
        return self._resolve_player_slot(raw_obj.get("player_slot") or raw_obj.get("slot"))

    def _resolve_player_slot(self, slot: Any) -> Player | None:
        if slot is None:
            return None
        try:
            slot_int = int(slot)
        except (TypeError, ValueError):
            return None
        if slot_int >= 128:
            return next((p for p in self.players if p.slot == slot_int), None)
        if 0 <= slot_int < 10:
            ordered = sorted(self.players, key=lambda p: p.slot)
            return ordered[slot_int] if slot_int < len(ordered) else None
        return next((p for p in self.players if p.slot == slot_int), None)

    @staticmethod
    def _building_label(key: str) -> tuple[str, str | None]:
        from .constants import BUILDING_LABELS, LANE_SHORT

        lane = None
        for ln in ("top", "mid", "bot"):
            if key.endswith("_" + ln):
                lane = LANE_SHORT[ln]
                break
        for part, label in BUILDING_LABELS.items():
            if f"_{part}" in key:
                text = label
                if lane and part in ("tower1", "tower2", "tower3"):
                    text = f"{label} {lane}"
                elif lane and "rax" in part:
                    text = f"Бараки · {lane}"
                return text, lane
        return "Здание", lane

    def _build_buildings(self) -> None:
        """Approximate building layout on the minimap (64..192 coordinate space)."""
        layout = {
            "radiant": [
                ("tower", "Т1 топ", 86, 96), ("tower", "Т1 мид", 101, 150), ("tower", "Т1 бот", 140, 178),
                ("tower", "Т2 топ", 75, 118), ("tower", "Т2 мид", 90, 165), ("tower", "Т2 бот", 160, 184),
                ("tower", "Т3 топ", 68, 146), ("tower", "Т3 мид", 78, 178), ("tower", "Т3 бот", 180, 186),
                ("tower", "Т4", 66, 184), ("fort", "Трон", 70, 190),
                ("rax", "Бараки (мили) · топ", 72, 158), ("rax", "Бараки (ренж) · топ", 74, 160),
                ("rax", "Бараки (мили) · мид", 82, 184), ("rax", "Бараки (ренж) · мид", 84, 186),
                ("rax", "Бараки (мили) · бот", 174, 188), ("rax", "Бараки (ренж) · бот", 176, 187),
            ],
            "dire": [
                ("tower", "Т1 топ", 100, 78), ("tower", "Т1 мид", 140, 110), ("tower", "Т1 бот", 178, 146),
                ("tower", "Т2 топ", 122, 70), ("tower", "Т2 мид", 156, 94), ("tower", "Т2 бот", 186, 128),
                ("tower", "Т3 топ", 154, 66), ("tower", "Т3 мид", 174, 82), ("tower", "Т3 бот", 188, 110),
                ("tower", "Т4", 188, 72), ("fort", "Трон", 188, 68),
                ("rax", "Бараки (мили) · топ", 160, 68), ("rax", "Бараки (ренж) · топ", 162, 66),
                ("rax", "Бараки (мили) · мид", 180, 78), ("rax", "Бараки (ренж) · мид", 182, 80),
                ("rax", "Бараки (мили) · бот", 186, 104), ("rax", "Бараки (ренж) · бот", 186, 106),
            ],
        }
        destroyed = {
            (o.victim_team, o.label)
            for o in self.objectives
            if o.kind == "building" and o.label
        }
        for team, entries in layout.items():
            for kind, label, x, y in entries:
                self.buildings.append(
                    {
                        "team": team,
                        "kind": kind,
                        "label": label,
                        "x": float(x),
                        "y": float(y),
                        "destroyed": (team, label) in destroyed,
                    }
                )

    # ----------------------------------------------------------------- timelines
    def _build_timelines(self) -> None:
        minutes = max(1, math.floor(self.duration / 60) + 1)
        gold = [safe_float(v) for v in (self.raw.get("radiant_gold_adv") or [])]
        xp = [safe_float(v) for v in (self.raw.get("radiant_xp_adv") or [])]
        if not gold:
            gold = self._adv_from_players("networth_t", minutes)
        if not xp:
            xp = self._adv_from_players("xp_t", minutes)
        self.gold_adv = self._pad(gold, minutes)
        self.xp_adv = self._pad(xp, minutes)
        self.minutes = minutes

    def _adv_from_players(self, attr: str, minutes: int) -> list[float]:
        values = []
        for minute in range(minutes):
            rad = sum((p.networth_t[minute] if minute < len(p.networth_t) else p.networth) for p in self.players if p.team == "radiant")
            dire = sum((p.networth_t[minute] if minute < len(p.networth_t) else p.networth) for p in self.players if p.team == "dire")
            values.append(rad - dire)
        return values

    @staticmethod
    def _pad(values: list[float], minutes: int) -> list[float]:
        if not values:
            return [0.0] * minutes
        if len(values) < minutes:
            values = values + [values[-1]] * (minutes - len(values))
        return values[:minutes]

    def _build_chat(self) -> None:
        for entry in self.raw.get("chat") or []:
            text = str(entry.get("key") or entry.get("text") or "").strip()
            if not text:
                continue
            slot = entry.get("player_slot")
            if slot is None:
                slot = entry.get("slot")
            try:
                slot = int(slot)
            except (TypeError, ValueError):
                slot = None
            if slot is not None and slot >= 10 and slot < 128:
                slot = 128 + (slot - 10)
            elif slot is not None and slot >= 5 and slot < 10:
                slot = 128 + (slot - 5)
            player = next((p for p in self.players if p.slot == slot), None) if slot is not None else None
            if player is None and slot is not None and 0 <= slot < 5:
                player = next((p for p in self.players if p.slot == slot), None)
            self.chat.append(
                {
                    "time": round(safe_float(entry.get("time")), 1),
                    "player_id": player.id if player else None,
                    "team": player.team if player else None,
                    "text": text,
                    "type": str(entry.get("type") or "chat"),
                }
            )
        self.chat.sort(key=lambda c: c["time"])

    def _build_wisdom_runes(self) -> None:
        explicit = self.raw.get("wisdom_runes") or []
        if explicit:
            for entry in explicit:
                pid = entry.get("player_id")
                player = self._by_id.get(pid) if pid else None
                self.wisdom_runes.append(
                    {
                        "time": round(safe_float(entry.get("time")), 1),
                        "player_id": player.id if player else None,
                        "team": player.team if player else entry.get("team"),
                    }
                )
        else:
            for player in self.players:
                for entry in player.runes_log or []:
                    if safe_int(entry.get("key")) == 8:
                        self.wisdom_runes.append(
                            {"time": round(safe_float(entry.get("time")), 1), "player_id": player.id, "team": player.team}
                        )
        self.wisdom_runes.sort(key=lambda r: r["time"])
        for player in self.players:
            player.wisdom_count = sum(1 for r in self.wisdom_runes if r["player_id"] == player.id)

    def _build_glyphs(self) -> None:
        for entry in self.raw.get("glyphs") or []:
            pid = entry.get("player_id")
            player = self._by_id.get(pid) if pid else None
            self.glyphs.append(
                {
                    "time": round(safe_float(entry.get("time")), 1),
                    "team": player.team if player else entry.get("team"),
                    "player_id": player.id if player else None,
                }
            )
        for objective in self.objectives:
            if "GLYPH" in objective.kind.upper() or "GLYPH" in objective.raw_key.upper():
                self.glyphs.append({"time": objective.time, "team": objective.team, "player_id": objective.player_id})
        self.glyphs.sort(key=lambda g: g["time"])

    def _mark_fight_deaths(self) -> None:
        for death in self.deaths:
            for fight in self.fights:
                if fight.start - 10 <= death.time <= fight.end + 10:
                    death.fight_index = fight.index
                    break

    def _team_totals(self) -> None:
        for team in ("radiant", "dire"):
            squad = [p for p in self.players if p.team == team]
            team_kills = sum(p.kills for p in squad)
            team_deaths = sum(p.deaths_count for p in squad)
            team_nw = sum(p.networth for p in squad)
            for p in squad:
                p.team_kills = team_kills
                p.team_deaths = team_deaths
                p.team_nw = team_nw
                p.nw_share = p.networth / team_nw if team_nw else 0.0
                p.kp = min(1.0, (p.kills + p.assists) / max(1, team_kills))

    # ------------------------------------------------------------------ helpers
    def player(self, pid: str) -> Player:
        return self._by_id[pid]

    def squad(self, team: str) -> list[Player]:
        return [p for p in self.players if p.team == team]

    def enemy(self, team: str) -> str:
        return "dire" if team == "radiant" else "radiant"

    def gold_for(self, team: str, minute: int) -> float:
        idx = max(0, min(len(self.gold_adv) - 1, minute))
        value = self.gold_adv[idx]
        return value if team == "radiant" else -value

    def gold_at(self, seconds: float) -> float:
        idx = max(0, min(len(self.gold_adv) - 1, int(seconds // 60)))
        return self.gold_adv[idx]

    def deaths_of(self, team: str) -> list[Death]:
        ids = {p.id for p in self.squad(team)}
        return [d for d in self.deaths if d.victim_id in ids]

    def fights_in(self, start: float, end: float) -> list[Fight]:
        return [f for f in self.fights if f.start < end and f.end > start]

    def objectives_in(self, start: float, end: float) -> list[Objective]:
        return [o for o in self.objectives if start <= o.time <= end]

    def teamfight_players(self, fight: Fight) -> list[tuple[Player, FightPlayer]]:
        return [(self.player(e.player_id), e) for e in fight.players]

    def fight_record(self, team: str) -> tuple[int, int]:
        wins = sum(1 for f in self.fights if f.winner == team and f.deaths > 0)
        losses = sum(1 for f in self.fights if f.winner != team and f.winner != "draw" and f.deaths > 0)
        return wins, losses
