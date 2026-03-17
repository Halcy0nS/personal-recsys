"""
Minimal Glicko-2 implementation for pairwise preference evaluation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Tuple


GLICKO2_SCALE = 173.7178
DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOLATILITY = 0.06
DEFAULT_TAU = 0.5
EPSILON = 1e-6


@dataclass
class GlickoRating:
    rating: float = DEFAULT_RATING
    rd: float = DEFAULT_RD
    volatility: float = DEFAULT_VOLATILITY

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def _to_mu(rating: float) -> float:
    return (rating - DEFAULT_RATING) / GLICKO2_SCALE


def _to_phi(rd: float) -> float:
    return rd / GLICKO2_SCALE


def _from_mu(mu: float) -> float:
    return mu * GLICKO2_SCALE + DEFAULT_RATING


def _from_phi(phi: float) -> float:
    return phi * GLICKO2_SCALE


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + (3.0 * (phi ** 2)) / (math.pi ** 2))


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    x = _g(phi_j) * (mu - mu_j)
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)

    z = math.exp(x)
    return z / (1.0 + z)


def _variance(mu: float, opponents: Iterable[Tuple[float, float]]) -> float:
    total = 0.0
    for mu_j, phi_j in opponents:
        expectation = _e(mu, mu_j, phi_j)
        total += (_g(phi_j) ** 2) * expectation * (1.0 - expectation)
    return 1.0 / total


def _delta(mu: float, results: Iterable[Tuple[float, float, float]], variance: float) -> float:
    total = 0.0
    for mu_j, phi_j, score in results:
        total += _g(phi_j) * (score - _e(mu, mu_j, phi_j))
    return variance * total


def _f(x: float, delta: float, phi: float, variance: float, a: float, tau: float) -> float:
    exp_x = math.exp(x)
    numerator = exp_x * ((delta ** 2) - (phi ** 2) - variance - exp_x)
    denominator = 2.0 * ((phi ** 2) + variance + exp_x) ** 2
    return (numerator / denominator) - ((x - a) / (tau ** 2))


def update_rating(
    player: GlickoRating,
    matches: List[Tuple[GlickoRating, float]],
    tau: float = DEFAULT_TAU,
) -> GlickoRating:
    """
    Update one rating from a batch of matches.

    matches: List[(opponent_rating, score)] where score is 1.0 / 0.5 / 0.0.
    """
    if not matches:
        phi = _to_phi(player.rd)
        phi_star = math.sqrt(phi ** 2 + player.volatility ** 2)
        return GlickoRating(
            rating=player.rating,
            rd=_from_phi(phi_star),
            volatility=player.volatility,
        )

    mu = _to_mu(player.rating)
    phi = _to_phi(player.rd)
    opponents = [(_to_mu(opp.rating), _to_phi(opp.rd)) for opp, _ in matches]
    results = [(_to_mu(opp.rating), _to_phi(opp.rd), score) for opp, score in matches]

    variance = _variance(mu, opponents)
    delta = _delta(mu, results, variance)

    a = math.log(player.volatility ** 2)

    if delta ** 2 > (phi ** 2 + variance):
        b = math.log(delta ** 2 - phi ** 2 - variance)
    else:
        k = 1
        while _f(a - (k * tau), delta, phi, variance, a, tau) < 0:
            k += 1
        b = a - (k * tau)

    fa = _f(a, delta, phi, variance, a, tau)
    fb = _f(b, delta, phi, variance, a, tau)

    while abs(b - a) > EPSILON:
        c = a + ((a - b) * fa / (fb - fa))
        fc = _f(c, delta, phi, variance, a, tau)

        if fc * fb < 0:
            a = b
            fa = fb
        else:
            fa /= 2.0

        b = c
        fb = fc

    new_sigma = math.exp(a / 2.0)
    phi_star = math.sqrt(phi ** 2 + new_sigma ** 2)
    new_phi = 1.0 / math.sqrt((1.0 / (phi_star ** 2)) + (1.0 / variance))

    total = 0.0
    for mu_j, phi_j, score in results:
        total += _g(phi_j) * (score - _e(mu, mu_j, phi_j))
    new_mu = mu + (new_phi ** 2) * total

    return GlickoRating(
        rating=_from_mu(new_mu),
        rd=_from_phi(new_phi),
        volatility=new_sigma,
    )


def batch_update(
    current_ratings: Dict[str, GlickoRating],
    match_results: List[Tuple[str, str, float]],
    tau: float = DEFAULT_TAU,
) -> Dict[str, GlickoRating]:
    """
    Update a pool of ratings at once.

    match_results: List[(player_a, player_b, score_for_a)]
    """
    ratings = dict(current_ratings)
    for player_a, player_b, _ in match_results:
        ratings.setdefault(player_a, GlickoRating())
        ratings.setdefault(player_b, GlickoRating())

    per_player_matches: Dict[str, List[Tuple[GlickoRating, float]]] = {
        player_id: [] for player_id in ratings.keys()
    }

    for player_a, player_b, score_a in match_results:
        per_player_matches[player_a].append((ratings[player_b], score_a))
        per_player_matches[player_b].append((ratings[player_a], 1.0 - score_a))

    updated = {}
    for player_id, player_rating in ratings.items():
        updated[player_id] = update_rating(player_rating, per_player_matches[player_id], tau=tau)

    return updated
