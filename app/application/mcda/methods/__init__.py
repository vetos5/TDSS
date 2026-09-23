"""MCDA ranking methods, each exposing ``run(matrix, weights, **options) -> MethodResult``."""

from app.application.mcda.methods import ahp, promethee, topsis, vikor, wsm
from app.application.mcda.methods.base import MethodResult, rank_scores

__all__ = ["MethodResult", "rank_scores", "ahp", "promethee", "topsis", "vikor", "wsm"]
