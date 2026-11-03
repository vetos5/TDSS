"""
Life-cycle cost appraisal of the alternatives (Phase 2 of the professional features).

Each alternative is costed over its design life in present values (DOCUMENTATION.md §3.15):

    agency = construction + Σ maintenance_i·df_i − residual·df_end
    users  = Σ (delay_i · VOT + FI_i · c_FI + PDO_i · c_PDO) · df_i,      df_i = (1 + r)^−i

Construction is spent in year 0 (the year before opening); operation runs from the opening year
(i = 1) to the design year. Against the do-minimum (the feasible alternative with the lowest
agency cost) every other alternative gets incremental cost ΔC = agency − agency_base, benefits
B = users_base − users, NPV = B − ΔC, BCR = B / ΔC and the discounted payback year.

Pure Python: no web types, no I/O. Delay and crash series come from ``engineering.analyse``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.application.engineering import AlternativeEngineering, Study
from app.data.engineering_defaults import (
    CRASH_COST_FI_USD,
    CRASH_COST_PDO_USD,
    SERVICE_LIFE_YEARS,
)

_M = 1e6


@dataclass
class AlternativeEconomics:
    name: str
    feasible: bool
    construction_mln: float
    pv_maintenance: float
    pv_residual: float
    pv_delay: float
    pv_crash: float
    pv_agency: float
    pv_user: float
    pv_total: float
    cumulative_total: list[float]     # discounted cost to date, year 0 … design year (M USD)
    is_base: bool = False
    incremental_cost: float | None = None
    benefits: float | None = None
    npv: float | None = None
    bcr: float | None = None
    dominant: bool = False            # cheaper for the agency and no worse for users than base
    payback_year: int | None = None


@dataclass
class EconomicAppraisal:
    study: Study
    years: list[int]                  # year 0 (construction) … design year
    base: str
    best_lcc: str
    crash_cost_fi: float
    crash_cost_pdo: float
    alternatives: list[AlternativeEconomics]


def _r(x: float, d: int = 3) -> float:
    return round(x, d)


def appraise(
    costs_mln: Mapping[str, float],
    engineering: Sequence[AlternativeEngineering],
    study: Study,
    feasible: set[str] | None = None,
) -> EconomicAppraisal:
    """Life-cycle cost, NPV and BCR of each alternative; *costs_mln* is construction in M USD."""
    r = study.discount_pct / 100.0
    n_ops = study.design_years + 1
    df = [(1.0 + r) ** -i for i in range(n_ops + 1)]
    feasible = set(costs_mln) if feasible is None else feasible
    residual_share = max(0.0, 1.0 - n_ops / SERVICE_LIFE_YEARS)

    flows: dict[str, dict[str, list[float]]] = {}
    rows: list[AlternativeEconomics] = []
    for eng in engineering:
        c0 = costs_mln[eng.name]
        maint = [c0 * study.maintenance_pct / 100.0] * n_ops
        delay = [d * study.value_of_time / _M for d in eng.delay_vehh]
        crash = [
            (fi * CRASH_COST_FI_USD + (n - fi) * CRASH_COST_PDO_USD) / _M
            for n, fi in zip(eng.crashes, eng.fi_crashes, strict=True)
        ]
        pv_m = sum(m * df[i + 1] for i, m in enumerate(maint))
        pv_d = sum(x * df[i + 1] for i, x in enumerate(delay))
        pv_c = sum(x * df[i + 1] for i, x in enumerate(crash))
        pv_res = c0 * residual_share * df[n_ops]
        cumulative = [c0]
        for i in range(n_ops):
            cumulative.append(cumulative[-1] + (maint[i] + delay[i] + crash[i]) * df[i + 1])
        cumulative[-1] -= pv_res
        agency = c0 + pv_m - pv_res
        user = pv_d + pv_c
        user_flow = [a + b for a, b in zip(delay, crash, strict=True)]
        flows[eng.name] = {"maint": maint, "user": user_flow}
        rows.append(AlternativeEconomics(
            name=eng.name,
            feasible=eng.name in feasible,
            construction_mln=_r(c0, 2),
            pv_maintenance=_r(pv_m),
            pv_residual=_r(pv_res),
            pv_delay=_r(pv_d),
            pv_crash=_r(pv_c),
            pv_agency=_r(agency),
            pv_user=_r(user),
            pv_total=_r(agency + user),
            cumulative_total=[_r(x) for x in cumulative],
        ))

    pool = [a for a in rows if a.feasible] or rows
    base = min(pool, key=lambda a: (a.pv_agency, a.name))
    best = min(pool, key=lambda a: (a.pv_total, a.name))
    base.is_base = True
    years = [study.opening_year - 1 + i for i in range(n_ops + 1)]

    for a in rows:
        if a.is_base:
            continue
        dc = a.pv_agency - base.pv_agency
        b = base.pv_user - a.pv_user
        a.incremental_cost = _r(dc)
        a.benefits = _r(b)
        a.npv = _r(b - dc)
        if dc > 0:
            a.bcr = _r(b / dc, 2)
        else:
            a.dominant = b >= 0
        # Discounted payback: extra capital back from the yearly user savings net of the extra
        # maintenance (the residual value is left out, as it only arrives at the end).
        cum = -(a.construction_mln - base.construction_mln)
        if cum >= 0:
            a.payback_year = years[0] if b >= 0 else None
            continue
        fa, fb = flows[a.name], flows[base.name]
        for i in range(n_ops):
            cum += ((fb["user"][i] - fa["user"][i]) - (fa["maint"][i] - fb["maint"][i])) * df[i + 1]
            if cum >= 0:
                a.payback_year = years[i + 1]
                break

    return EconomicAppraisal(
        study=study,
        years=years,
        base=base.name,
        best_lcc=best.name,
        crash_cost_fi=CRASH_COST_FI_USD,
        crash_cost_pdo=CRASH_COST_PDO_USD,
        alternatives=rows,
    )
