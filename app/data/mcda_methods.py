"""Display metadata for the MCDA methods and weighting modes (English / Ukrainian)."""

from __future__ import annotations

from typing import Dict

METHOD_INFO: Dict[str, Dict[str, Dict[str, str]]] = {
    "wsm": {
        "en": {"label": "WSM", "description": "Weighted sum of min-max normalised scores."},
        "uk": {"label": "WSM", "description": "Зважена сума нормалізованих (min-max) оцінок."},
    },
    "topsis": {
        "en": {
            "label": "TOPSIS",
            "description": "Relative closeness to the ideal and distance from the anti-ideal.",
        },
        "uk": {
            "label": "TOPSIS",
            "description": "Відносна близькість до ідеального та віддаленість від антиідеального рішення.",
        },
    },
    "ahp": {
        "en": {
            "label": "AHP",
            "description": "Analytic Hierarchy Process: ratio-scale priorities synthesised with weights.",
        },
        "uk": {
            "label": "МАІ (AHP)",
            "description": "Метод аналізу ієрархій: пріоритети за шкалою відношень, зважені вагами критеріїв.",
        },
    },
    "promethee": {
        "en": {
            "label": "PROMETHEE II",
            "description": "Pairwise outranking; alternatives ranked by net preference flow.",
        },
        "uk": {
            "label": "PROMETHEE II",
            "description": "Попарне переважання; ранжування за чистим потоком переваги.",
        },
    },
    "vikor": {
        "en": {
            "label": "VIKOR",
            "description": "Compromise ranking balancing group utility and individual regret.",
        },
        "uk": {
            "label": "VIKOR",
            "description": "Компромісне ранжування: баланс групової корисності та індивідуального жалю.",
        },
    },
}


def resolve_method_info(method: str, locale: str) -> Dict[str, str]:
    info = METHOD_INFO[method]
    return info.get(locale, info["en"])
