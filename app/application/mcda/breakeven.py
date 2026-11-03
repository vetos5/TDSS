"""
Break-even analysis on criterion values (DOCUMENTATION.md §3.16).

Weight sensitivity (``sensitivity.py``) asks how far a *weight* may move before the winner changes.
Break-even asks the same about the *values*: for every alternative that does not win, how good
would one of its criterion values have to be for it to take first place ("Turbine wins if its cost
falls below $38 M")? For the winner, how much worse could one of its values get before it loses
first place?

Each question is one-dimensional: scale a single cell of the decision matrix by a factor *m* and
re-run the method (normalisation included, so every method is handled the same way). A geometric
grid over *m* finds the first factor at which the outcome flips, and bisection refines it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping

import numpy as np

from app.application.mcda.matrix import DecisionMatrix
from app.application.mcda.methods.base import MethodResult

MethodFn = Callable[[DecisionMatrix, np.ndarray], MethodResult]

# Furthest a value is moved: ×20 up or ÷20 down. Beyond that the answer is "not reachable".
MAX_FACTOR = 20.0
GRID_POINTS = 48
BISECTION_STEPS = 30


@dataclass
class BreakEven:
    alternative: str
    criterion: str
    current: float
    value: float | None        # the break-even value, or None if not reachable within the range
    change_pct: float | None   # (value − current) / current · 100
    kind: str                  # "overtake" (a challenger becomes first) | "hold" (winner's margin)
    new_winner: str | None = None   # for "hold": who wins past the break-even value


@dataclass
class BreakEvenAnalysis:
    winner: str
    items: list[BreakEven]


def _winner(fn: MethodFn, matrix: DecisionMatrix, weights: np.ndarray) -> int:
    res = fn(matrix, weights)
    best = np.flatnonzero(res.ranks == 1)
    return int(best[0])


def _with_value(matrix: DecisionMatrix, i: int, j: int, v: float) -> DecisionMatrix:
    values = matrix.values.copy()
    values[i, j] = v
    return replace(matrix, values=values)


def _search(
    flipped: Callable[[float], bool], current: float, improve_up: bool, bounds: tuple[float, float]
) -> float | None:
    """Smallest move of *current* in its direction for which *flipped* holds (None if none)."""
    lo_b, hi_b = bounds
    if current == 0:
        targets = np.linspace(0, hi_b if improve_up else lo_b, GRID_POINTS + 1)[1:]
    else:
        factors = np.geomspace(1.0, MAX_FACTOR, GRID_POINTS + 1)[1:]
        targets = current * factors if improve_up == (current > 0) else current / factors
    targets = np.clip(targets, lo_b, hi_b)
    prev = current
    for x in targets:
        if flipped(float(x)):
            a, b = prev, float(x)
            for _ in range(BISECTION_STEPS):
                mid = (a + b) / 2.0
                if flipped(mid):
                    b = mid
                else:
                    a = mid
            return b
        prev = float(x)
        if x in (lo_b, hi_b):
            break
    return None


def analyse_breakeven(
    matrix: DecisionMatrix,
    weights: np.ndarray,
    fn: MethodFn,
    bounds: Mapping[str, tuple[float, float]] | None = None,
) -> BreakEvenAnalysis:
    """Break-even values of every (alternative, criterion) cell under the method *fn*."""
    bounds = dict(bounds or {})
    names, crits = matrix.alternatives, matrix.criterion_names
    w0 = _winner(fn, matrix, weights)
    items: list[BreakEven] = []
    benefit = matrix.benefit
    for i, name in enumerate(names):
        for j, crit in enumerate(crits):
            current = float(matrix.values[i, j])
            lim = bounds.get(crit, (0.0, float("inf")))
            if i == w0:
                # Worsen the winner's value until someone else ranks first.
                def lost(v: float, i: int = i, j: int = j) -> bool:
                    return _winner(fn, _with_value(matrix, i, j, v), weights) != i

                worse_up = not benefit[j]
                v = _search(lost, current, worse_up, lim)
                new = None if v is None else names[
                    _winner(fn, _with_value(matrix, i, j, v), weights)
                ]
                kind = "hold"
            else:
                def wins(v: float, i: int = i, j: int = j) -> bool:
                    res = fn(_with_value(matrix, i, j, v), weights)
                    return bool(res.ranks[i] == 1)

                v = _search(wins, current, bool(benefit[j]), lim)
                new, kind = None, "overtake"
            change = None if v is None or current == 0 else (v - current) / abs(current) * 100.0
            items.append(BreakEven(
                alternative=name,
                criterion=crit,
                current=current,
                value=None if v is None else float(v),
                change_pct=None if change is None else float(change),
                kind=kind,
                new_winner=new,
            ))
    return BreakEvenAnalysis(winner=names[w0], items=items)
