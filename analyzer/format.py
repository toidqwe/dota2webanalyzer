"""Russian-language formatting helpers."""

from __future__ import annotations

NBSP = "\u00a0"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_num(value: float, signed: bool = False) -> str:
    number = int(round(value))
    text = f"{abs(number):,}".replace(",", NBSP)
    if number < 0:
        return "−" + text
    if signed and number > 0:
        return "+" + text
    return text


def fmt_pct(value: float, digits: int = 0) -> str:
    return f"{value:.{digits}f}%"


def fmt_signed(value: float) -> str:
    return fmt_num(value, signed=True)


def plural(number: int, one: str, few: str, many: str) -> str:
    n = abs(int(number))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def hero_possessive(name: str) -> str:
    return name
