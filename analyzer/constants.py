"""Static tables and labels used by the analysis engine."""

from __future__ import annotations

POSITION_LABEL = {
    1: "Керри",
    2: "Мидер",
    3: "Оффлейнер",
    4: "Роумер",
    5: "Фулл-саппорт",
}

POSITION_SHORT = {1: "Поз. 1", 2: "Поз. 2", 3: "Поз. 3", 4: "Поз. 4", 5: "Поз. 5"}

LANE_LABEL = {1: "Сейф", 2: "Мид", 3: "Офф"}

ATTR_LABEL = {"str": "Сила", "agi": "Ловкость", "int": "Интеллект", "all": "Универсал"}

ATTR_COLOR = {"str": "#e2564f", "agi": "#4fbf73", "int": "#4ea3e0", "all": "#d9a441"}

GAME_MODES = {
    0: "Unknown",
    1: "All Pick",
    2: "Captains Mode",
    3: "Random Draft",
    4: "Single Draft",
    5: "All Random",
    6: "Intro",
    7: "Diretide",
    8: "Reverse Captains Mode",
    9: "Greeviling",
    10: "Tutorial",
    11: "Mid Only",
    12: "Least Played",
    13: "Limited Heroes",
    14: "Compendium",
    15: "Custom",
    16: "Captains Draft",
    17: "Balanced Draft",
    18: "Ability Draft",
    19: "Event",
    20: "All Random Deathmatch",
    21: "1v1 Mid",
    22: "All Pick",
    23: "Turbo",
    24: "Mutation",
    25: "Ranked All Pick",
}

LOBBY_TYPES = {
    0: "Обычный матч",
    1: "Тренировка",
    2: "Турнир",
    3: "Турнир",
    4: "Co-op",
    5: "Team Match",
    6: "Рейтинг",
    7: "Рейтинг (соло)",
    8: "1v1 Mid",
    9: "Battle Cup",
    10: "Event",
    11: "Ranked All Pick",
    12: "Ranked Captains Mode",
}

# Hero-relative benchmarks percentiles (OpenDota) that are "higher = better".
BENCH_HIGHER_IS_BETTER = {
    "gold_per_min",
    "xp_per_min",
    "last_hits_per_min",
    "denies_per_min",
    "hero_damage_per_min",
    "tower_damage",
    "deaths_per_min",  # OpenDota inverts this one: higher pct = fewer deaths
}

# Expected values for a ~40 minute game at a high skill level, by position.
BASE = {
    "gpm": {1: 580, 2: 540, 3: 450, 4: 360, 5: 300},
    "xpm": {1: 640, 2: 660, 3: 560, 4: 480, 5: 420},
    "lh10": {1: 50, 2: 47, 3: 37, 4: 15, 5: 7},
    "dn10": {1: 9, 2: 8, 3: 6, 4: 4, 5: 3},
    "hd_min": {1: 620, 2: 760, 3: 620, 4: 500, 5: 380},
    "td": {1: 7200, 2: 6000, 3: 5200, 4: 3600, 5: 3000},
    "tf_part": {1: 0.55, 2: 0.60, 3: 0.58, 4: 0.54, 5: 0.52},
    "kda": {1: 3.5, 2: 3.3, 3: 2.7, 4: 2.3, 5: 2.1},
    "deaths10": {1: 1.5, 2: 1.6, 3: 1.8, 4: 1.9, 5: 2.0},
    "kp": {1: 0.58, 2: 0.62, 3: 0.62, 4: 0.66, 5: 0.66},
    "obs_min": {1: 0.03, 2: 0.05, 3: 0.12, 4: 0.32, 5: 0.40},
    "sen_min": {1: 0.02, 2: 0.04, 3: 0.12, 4: 0.45, 5: 0.55},
    "dewards": {1: 0.5, 2: 0.8, 3: 1.5, 4: 7.0, 5: 7.0},
    "stacks": {1: 0.6, 2: 0.6, 3: 1.2, 4: 3.0, 5: 3.0},
    "nw_share": {1: 0.28, 2: 0.24, 3: 0.21, 4: 0.15, 5: 0.12},
    "roshan": {1: 0.8, 2: 0.8, 3: 0.7, 4: 0.5, 5: 0.4},
    "buildings": {1: 1.8, 2: 1.5, 3: 1.4, 4: 1.0, 5: 0.8},
    "runes": {1: 6, 2: 8, 3: 8, 4: 10, 5: 10},
}

# How much each category counts toward the "blame / credit" index.
ROLE_WEIGHTS = {
    1: {"economy": 0.30, "combat": 0.22, "survival": 0.20, "vision": 0.04, "objectives": 0.14, "discipline": 0.10},
    2: {"economy": 0.27, "combat": 0.24, "survival": 0.19, "vision": 0.05, "objectives": 0.13, "discipline": 0.12},
    3: {"economy": 0.21, "combat": 0.21, "survival": 0.22, "vision": 0.07, "objectives": 0.15, "discipline": 0.14},
    4: {"economy": 0.16, "combat": 0.20, "survival": 0.19, "vision": 0.20, "objectives": 0.11, "discipline": 0.14},
    5: {"economy": 0.14, "combat": 0.18, "survival": 0.18, "vision": 0.27, "objectives": 0.09, "discipline": 0.14},
}

CATEGORY_LABEL = {
    "economy": "Экономика",
    "combat": "Бой",
    "survival": "Выживаемость",
    "vision": "Вижн",
    "objectives": "Объекты",
    "discipline": "Дисциплина",
}

CATEGORY_SHORT = {
    "economy": "Эко",
    "combat": "Бой",
    "survival": "Жив",
    "vision": "Вижн",
    "objectives": "Объекты",
    "discipline": "Дисц.",
}

# Approximate cumulative XP required to reach level N (index = level).
XP_TABLE = [
    0, 0, 240, 640, 1160, 1760, 2440, 3200, 4000, 4900, 5900,
    7000, 8300, 9700, 11200, 12900, 14700, 16700, 18900, 21300, 23900,
    26700, 29700, 32900, 36300, 39900, 43700, 47700, 51900, 56300, 60900,
]

BUILDING_LABELS = {
    "tower1": "Т1",
    "tower2": "Т2",
    "tower3": "Т3",
    "tower4": "Т4",
    "melee_rax": "Бараки (мили)",
    "range_rax": "Бараки (ренж)",
    "fort": "Трон",
}

LANE_SHORT = {"mid": "мид", "top": "топ", "bot": "бот"}

MISTAKE_SEVERITY = {
    1: "мелочь",
    2: "заметно",
    3: "серьёзно",
    4: "критично",
    5: "решающе",
}

TEAM_LABEL = {"radiant": "Radiant", "dire": "Dire"}
