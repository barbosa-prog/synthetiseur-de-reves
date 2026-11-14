"""Quantiles empiriques R7 (interpolation linéaire), sans dépendance NumPy."""

import math


def percentile(values, percent):
    values = list(values)
    if (not values or type(percent) not in {int, float} or not 0 <= percent <= 100
            or any(type(v) not in {int, float} or not 0 <= v <= 86_400_000
                   or not math.isfinite(v) for v in values)):
        raise ValueError("Echantillon de latence invalide")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(values):
    values = list(values)
    return dict(n=len(values), p50_ms=round(percentile(values, 50), 6),
                p95_ms=round(percentile(values, 95), 6), min_ms=min(values), max_ms=max(values))
