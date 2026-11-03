"""
Engineering analysis of each alternative over its design life (Phase 1 of the professional
features): design-year traffic per interchange element and expected crashes.

Traffic (DOCUMENTATION.md §3.13). The peak-hour volume V = AADT · K grows at g per year. The peak
direction carries Q = V · D (converted to pc/h with the heavy-vehicle factor), of which the share
``turning_pct`` turns: T = Q · turn. Each element of an interchange type (``TRAFFIC_ELEMENTS``)
carries share × T or share × Q against its own capacity; the element with the highest V/C is
critical. Delay per element follows the BPR function, and annual delay sums both directions over
the equivalent peak hours.

Safety (§3.14). N_t = R · AADT_t · 365 · 10⁻⁶ · CMF_speed · CMF_congestion, with R the crash
rate per million entering vehicles of the interchange type, split into fatal-and-injury and
PDO crashes.

Pure Python: no web types, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from app.application.traffic_engine import bpr_travel_time, los_grade
from app.data.engineering_defaults import (
    BPR_ALPHA,
    BPR_BETA,
    CMF_CONGESTION_SLOPE,
    CMF_CONGESTION_START,
    CMF_LOOP_PER_20KMH,
    CMF_LOOP_SPEED_THRESHOLD,
    CRASH_RATE_PER_MEV,
    ELEMENT_LABELS,
    FI_SHARE,
    HEAVY_VEHICLE_PCE,
    LANE_CAPACITY_BASE,
    LANE_CAPACITY_MAX,
    LANE_CAPACITY_MIN,
    LANE_CAPACITY_PER_MPH,
    PEAK_HOURS_PER_YEAR,
    STUDY_DEFAULTS,
    TRAFFIC_ELEMENTS,
    VC_CAPACITY,
    VC_LOS_E,
)


class SiteParams(Protocol):
    design_speed: int
    aadt: int
    peak_factor: int
    num_lanes: int
    terrain: str


@dataclass(frozen=True)
class Study:
    """Design-life inputs; defaults from ``STUDY_DEFAULTS``."""

    opening_year: int = int(STUDY_DEFAULTS["opening_year"])
    design_years: int = int(STUDY_DEFAULTS["design_years"])
    growth_pct: float = STUDY_DEFAULTS["growth_pct"]
    directional_split: float = STUDY_DEFAULTS["directional_split"]
    heavy_pct: float = STUDY_DEFAULTS["heavy_pct"]
    turning_pct: float = STUDY_DEFAULTS["turning_pct"]
    discount_pct: float = STUDY_DEFAULTS["discount_pct"]
    value_of_time: float = STUDY_DEFAULTS["value_of_time"]
    maintenance_pct: float = STUDY_DEFAULTS["maintenance_pct"]

    @classmethod
    def of(cls, source: object | None) -> "Study":
        """Build from any object or mapping with (some of) the field names."""
        if source is None:
            return cls()
        get = source.get if isinstance(source, Mapping) else lambda k, d: getattr(source, k, d)
        return cls(**{k: get(k, getattr(cls(), k)) for k in cls.__dataclass_fields__})

    @property
    def years(self) -> list[int]:
        return [self.opening_year + t for t in range(self.design_years + 1)]

    def growth(self, t: int) -> float:
        return (1.0 + self.growth_pct / 100.0) ** t


def lane_capacity(design_speed_kmh: float) -> float:
    """Basic freeway lane capacity (pc/h/ln) at a free-flow speed equal to the design speed."""
    mph = design_speed_kmh / 1.609344
    c = LANE_CAPACITY_BASE + LANE_CAPACITY_PER_MPH * (mph - 50.0)
    return max(LANE_CAPACITY_MIN, min(LANE_CAPACITY_MAX, c))


def heavy_vehicle_factor(heavy_pct: float, terrain: str) -> float:
    """pc per vehicle: 1 + P_T · (E_T − 1)."""
    e_t = HEAVY_VEHICLE_PCE.get(terrain, HEAVY_VEHICLE_PCE["Flat"])
    return 1.0 + heavy_pct / 100.0 * (e_t - 1.0)


@dataclass
class ElementState:
    id: str
    label: str
    kind: str
    capacity_pcph: float
    volume_pcph: float
    vc: float
    los: str
    delay_s: float           # mean delay per vehicle against free flow
    shared: bool = False     # the mainline merge: the same for every alternative of the site


@dataclass
class AlternativeEngineering:
    name: str
    opening: list[ElementState]
    design: list[ElementState]
    critical_element: str
    vc_series: list[float]               # critical V/C per year (the interchange's own elements)
    mainline_vc_series: list[float]      # V/C of the shared mainline merge per year
    delay_vehh: list[float]              # annual delay, both directions
    crashes: list[float]                 # expected crashes per year
    fi_crashes: list[float]              # of which fatal and injury
    year_los_e: int | None               # first year the critical V/C exceeds LOS E's threshold
    year_capacity: int | None            # first year it exceeds capacity
    cmf_speed: float
    notes: list[str] = field(default_factory=list)

    @property
    def crashes_total(self) -> float:
        return sum(self.crashes)

    @property
    def fi_total(self) -> float:
        return sum(self.fi_crashes)

    @property
    def delay_total_vehh(self) -> float:
        return sum(self.delay_vehh)


@dataclass
class EngineeringAnalysis:
    study: Study
    years: list[int]
    peak_hour_veh: float                 # two-way peak-hour volume in the opening year
    peak_direction_pcph: float           # Q in the opening year
    turning_pcph: float                  # T in the opening year
    lane_capacity_pcph: float
    hv_factor: float
    alternatives: list[AlternativeEngineering]


def _element_capacity(el: Mapping, params: SiteParams) -> float:
    if el["capacity"] is None:
        return params.num_lanes * lane_capacity(params.design_speed)
    return float(el["capacity"])


def _element_state(
    el: Mapping, params: SiteParams, q_pcph: float, turn_share: float, locale: str
) -> ElementState:
    base = q_pcph if el["load"] == "mainline" else q_pcph * turn_share
    volume = base * float(el["share"])
    capacity = _element_capacity(el, params)
    vc = volume / capacity
    ffs = float(el["ffs_kmh"] or params.design_speed)
    t0 = float(el["length_km"]) / ffs * 3600.0 + float(el.get("control_s", 0.0))
    congested = bpr_travel_time(t0, volume, capacity, BPR_ALPHA, BPR_BETA)
    delay = congested - t0 + float(el.get("control_s", 0.0))
    en, uk = ELEMENT_LABELS.get(str(el["id"]), (str(el["id"]), str(el["id"])))
    return ElementState(
        id=str(el["id"]),
        label=uk if locale == "uk" else en,
        kind=str(el["kind"]),
        capacity_pcph=round(capacity, 0),
        volume_pcph=round(volume, 0),
        vc=round(vc, 3),
        los=los_grade(vc),
        delay_s=round(delay, 1),
        shared=el["load"] == "mainline",
    )


def _milestone(vc0: float, threshold: float, study: Study) -> int | None:
    """First calendar year in the design life in which vc0 · growth(t) exceeds *threshold*."""
    if vc0 > threshold:
        return study.opening_year
    g = study.growth_pct / 100.0
    if g <= 0 or vc0 <= 0:
        return None
    t = math.log(threshold / vc0) / math.log(1.0 + g)
    year = study.opening_year + math.floor(t) + 1
    return year if year <= study.opening_year + study.design_years else None


def analyse_alternative(
    name: str, params: SiteParams, study: Study, locale: str = "en"
) -> AlternativeEngineering:
    elements = TRAFFIC_ELEMENTS.get(name)
    if not elements:
        raise KeyError(name)
    hv = heavy_vehicle_factor(study.heavy_pct, params.terrain)
    v_peak = params.aadt * params.peak_factor / 100.0
    d = study.directional_split / 100.0
    turn = study.turning_pct / 100.0

    def states(t: int, share: float) -> list[ElementState]:
        q = v_peak * share * hv * study.growth(t)
        return [_element_state(el, params, q, turn, locale) for el in elements]

    opening = states(0, d)
    design = states(study.design_years, d)
    # The critical element is the interchange's own: the shared mainline merge is reported but
    # does not tell the alternatives apart.
    own = [s for s in opening if not s.shared] or opening
    critical = max(own, key=lambda s: s.vc)
    vc0 = critical.vc

    loops = any(el["kind"] == "loop" for el in elements)
    cmf_speed = 1.0
    if loops and params.design_speed > CMF_LOOP_SPEED_THRESHOLD:
        excess = (params.design_speed - CMF_LOOP_SPEED_THRESHOLD) / 20.0
        cmf_speed = 1.0 + CMF_LOOP_PER_20KMH * excess
    rate = CRASH_RATE_PER_MEV.get(name, 0.45)
    fi_share = FI_SHARE.get(name, 0.3)

    vc_series, mainline_series, delay_series, crashes, fi = [], [], [], [], []
    for t in range(study.design_years + 1):
        both = []
        for share in (d, 1.0 - d):
            for s in states(t, share):
                both.append((s, share))
        vc_t = max(s.vc for s, share in both if share == d and (s.shared == critical.shared))
        # Delay in vehicle-hours: pc/h ÷ hv = veh/h; × s/veh ÷ 3600 = veh-h per peak hour.
        delay_t = sum(s.volume_pcph / hv * s.delay_s for s, _ in both) / 3600.0
        cmf_cong = 1.0 + CMF_CONGESTION_SLOPE * max(0.0, vc_t - CMF_CONGESTION_START)
        n = rate * params.aadt * study.growth(t) * 365.0 * 1e-6 * cmf_speed * cmf_cong
        vc_series.append(round(vc_t, 3))
        mainline_series.append(round(max(
            (s.vc for s, share in both if share == d and s.shared), default=0.0), 3))
        delay_series.append(round(delay_t * PEAK_HOURS_PER_YEAR, 1))
        crashes.append(round(n, 3))
        fi.append(round(n * fi_share, 3))

    return AlternativeEngineering(
        name=name,
        opening=opening,
        design=design,
        critical_element=critical.id,
        vc_series=vc_series,
        mainline_vc_series=mainline_series,
        delay_vehh=delay_series,
        crashes=crashes,
        fi_crashes=fi,
        year_los_e=_milestone(vc0, VC_LOS_E, study),
        year_capacity=_milestone(vc0, VC_CAPACITY, study),
        cmf_speed=round(cmf_speed, 3),
    )


def analyse(
    names: Sequence[str], params: SiteParams, study: Study, locale: str = "en"
) -> EngineeringAnalysis:
    """Traffic and safety over the design life for every named alternative."""
    hv = heavy_vehicle_factor(study.heavy_pct, params.terrain)
    v_peak = params.aadt * params.peak_factor / 100.0
    q = v_peak * study.directional_split / 100.0 * hv
    return EngineeringAnalysis(
        study=study,
        years=study.years,
        peak_hour_veh=round(v_peak, 0),
        peak_direction_pcph=round(q, 0),
        turning_pcph=round(q * study.turning_pct / 100.0, 0),
        lane_capacity_pcph=round(lane_capacity(params.design_speed), 0),
        hv_factor=round(hv, 3),
        alternatives=[analyse_alternative(n, params, study, locale) for n in names],
    )
