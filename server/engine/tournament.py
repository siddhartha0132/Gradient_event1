"""Round-robin tournament between named bots."""

import hashlib
from itertools import combinations

from .match import play_match


def match_seed(seed, a, b, repetition):
    """Derive a repeatable seed for one match from the tournament seed (None stays None)."""
    if seed is None:
        return None
    key = f"{seed}|{a}|{b}|{repetition}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def schedule(names, repetitions):
    """Every match as (repetition, a, b): each bot vs itself, then every pair."""
    matches = []
    for rep in range(repetitions):
        matches += [(rep, name, name) for name in names]
        matches += [(rep, a, b) for a, b in combinations(names, 2)]
    return matches


def summarize(names, results, turns, repetitions):
    """Build the leaderboard and matrix from (a, b, score_a, score_b) results.

    Self-play (a == b) adds one side's score to the total but does not count
    toward wins, losses or draws.
    """
    stats = {name: {"total": 0, "wins": 0, "losses": 0, "draws": 0, "matches": 0}
             for name in names}
    pair_totals = {a: {b: 0 for b in names} for a in names}

    for a, b, sa, sb in results:
        if a == b:
            stats[a]["total"] += sa
            stats[a]["matches"] += 1
            pair_totals[a][a] += sa
            continue

        stats[a]["total"] += sa
        stats[b]["total"] += sb
        stats[a]["matches"] += 1
        stats[b]["matches"] += 1
        pair_totals[a][b] += sa
        pair_totals[b][a] += sb

        if sa > sb:
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
        elif sb > sa:
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1
        else:
            stats[a]["draws"] += 1
            stats[b]["draws"] += 1

    leaderboard = []
    for name, s in stats.items():
        turns_played = s["matches"] * turns
        leaderboard.append({
            "name": name,
            "total": s["total"],
            "avg_per_turn": s["total"] / turns_played if turns_played else 0.0,
            "wins": s["wins"],
            "losses": s["losses"],
            "draws": s["draws"],
        })
    leaderboard.sort(key=lambda row: row["total"], reverse=True)
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    matrix = {a: {b: total / repetitions for b, total in row.items()}
              for a, row in pair_totals.items()}

    return {"leaderboard": leaderboard, "matrix": matrix}


def run_round_robin(bots, game, turns, repetitions=1, noise=0.0, seed=None):
    """Every pair of bots plays one match per repetition, and each bot also plays
    a copy of itself. A seed makes the whole tournament repeatable.

    Returns:
      leaderboard: list of dicts sorted by total score (highest first)
      matrix: matrix[a][b] = a's average score per match against b (a == b is self-play)
    """
    names = list(bots)
    results = []
    for rep, a, b in schedule(names, repetitions):
        result = play_match(bots[a], bots[b], game, turns, noise, match_seed(seed, a, b, rep))
        results.append((a, b, result["score1"], result["score2"]))
    return summarize(names, results, turns, repetitions)
