"""Multi-round elimination event built on the sandboxed round robin."""

import math
import random
from dataclasses import dataclass

from .games import CHICKEN, PRISONERS_DILEMMA, STAG_HUNT
from .sandbox import run_safe_round_robin
from .strategies import BUILT_IN_BOTS


@dataclass
class RoundConfig:
    name: str
    game: object
    turns: int
    noise: float = 0.0
    repetitions: int = 3
    keep_fraction: float = 0.5  # share of entrants that advance, rounded up (at least 1)
    hide_turn_count: bool = False  # if True, actual turns vary within +/-25% of `turns`
    keep_count: int | None = None  # exact number that advance; overrides keep_fraction

    def cut_size(self, entrants):
        """How many of `entrants` bots advance."""
        if self.keep_count is not None:
            return self.keep_count
        return max(1, math.ceil(entrants * self.keep_fraction))


DEFAULT_EVENT = [
    RoundConfig("Opening Moves", PRISONERS_DILEMMA, 200, noise=0.0, keep_fraction=0.5),
    RoundConfig("Fog of War", PRISONERS_DILEMMA, 200, noise=0.05, keep_fraction=0.5),
    RoundConfig("Brinkmanship", CHICKEN, 200, noise=0.02, keep_count=2),
    RoundConfig("Endgame", STAG_HUNT, 200, noise=0.02, keep_count=1, hide_turn_count=True),
]


def actual_turns(config, seed):
    """Turns to play: exact, or randomized within +/-25% when the count is hidden."""
    if not config.hide_turn_count:
        return config.turns
    rng = random.Random(None if seed is None else f"{seed}|turns")
    return rng.randint(round(config.turns * 0.75), round(config.turns * 1.25))


def rank_for_cut(names, leaderboard, matrix, seed):
    """Order `names` for the cut: by total score, then by average score in
    head-to-head matches among bots tied on total, then by a seeded coin flip.
    """
    totals = {row["name"]: row["total"] for row in leaderboard}
    rng = random.Random(None if seed is None else f"{seed}|tiebreak")
    coin = {name: rng.random() for name in sorted(names)}

    def head_to_head(name):
        rivals = [other for other in names if other != name and totals[other] == totals[name]]
        return sum(matrix[name][other] for other in rivals) / len(rivals) if rivals else 0.0

    return sorted(names, key=lambda name: (-totals[name], -head_to_head(name), coin[name]))


def run_event(bot_codes, rounds=DEFAULT_EVENT, seed=None, include_builtins=False):
    """Run each round on the survivors and cut to the top keep_fraction.

    Built-ins (if included) play every round as background bots: they score
    points but never advance and don't count toward the cut. Disqualified bots
    are eliminated. Returns {"rounds": [...], "champion": name or None}.
    """
    if include_builtins:
        clashes = set(bot_codes) & set(BUILT_IN_BOTS)
        if clashes:
            raise ValueError(f"Bot names clash with built-ins: {sorted(clashes)}")

    survivors = list(bot_codes)
    results = []

    for index, config in enumerate(rounds):
        if not survivors:
            break
        round_seed = None if seed is None else f"{seed}|{index}"
        turns = actual_turns(config, round_seed)
        outcome = run_safe_round_robin(
            {name: bot_codes[name] for name in survivors}, include_builtins,
            config.game, turns, config.repetitions, config.noise, round_seed,
        )

        # Rank only the entrants; disqualified bots are already off the leaderboard
        eligible = [row["name"] for row in outcome["leaderboard"] if row["name"] in survivors]
        ranked = rank_for_cut(eligible, outcome["leaderboard"], outcome["matrix"], round_seed)
        keep = config.cut_size(len(survivors))
        advanced = ranked[:keep]
        # Eliminated in rank order, then disqualified bots
        eliminated = ranked[keep:] + [name for name in survivors if name not in ranked]

        results.append({
            "config": config,
            "turns": turns,
            "leaderboard": outcome["leaderboard"],
            "matrix": outcome["matrix"],
            "forfeits": outcome["forfeits"],
            "disqualified": outcome["disqualified"],
            "advanced": advanced,
            "eliminated": eliminated,
        })
        survivors = advanced

    champion = results[-1]["advanced"][0] if results and results[-1]["advanced"] else None
    return {"rounds": results, "champion": champion}
