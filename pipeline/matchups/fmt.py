"""Number formatting for template takeaways (the page formats table cells itself).

Rounds half away from zero, like the page's JavaScript toFixed, so a takeaway and its table cell
always show the same digits (Python's own formatting rounds exact halves to even).
"""

import math


def _r(v: float, nd: int) -> float:
    v = round(v, 4 if nd <= 2 else nd)  # the value as stored in the JSON (4 decimals), then half-up
    m = 10**nd
    return math.copysign(math.floor(abs(v) * m + 0.5 + 1e-9) / m, v)


def epa(v) -> str:
    return "n/a" if v is None else f"{_r(v, 2):+.2f}"


def pct(v) -> str:
    return "n/a" if v is None else f"{_r(round(v, 4) * 100, 0):.0f}%"


def dec(v, n: int = 1) -> str:
    return "n/a" if v is None else f"{_r(v, n):.{n}f}"


def rank(r, n) -> str:
    return "unranked" if r is None or not n else f"rank {r} of {n}"


def att(n: int) -> str:
    return f"{n} designed run{'s' if n != 1 else ''}"


def weeks_label(weeks: list[int]) -> str:
    if not weeks:
        return "no games yet"
    return f"week {weeks[0]}" if len(weeks) == 1 else f"weeks {weeks[0]}–{weeks[-1]}"
