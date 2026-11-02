"""Stress test the sandbox: 40 bots, Prisoner's Dilemma, 200 turns, 3 repetitions.

Run from backend/:  python -m scripts.stress
"""

import time

from engine.games import PRISONERS_DILEMMA
from engine.sandbox import run_safe_round_robin, validate_code


def generate_bots():
    bots = {}
    # 7 probabilistic cooperators
    for p in (0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9):
        bots[f"coop_{int(p * 100)}"] = (
            "import random\n"
            "def strategy(my_history, opp_history):\n"
            f"    return 'C' if random.random() < {p} else 'D'\n"
        )
    # 6 generous tit-for-tats (forgive a defection with probability g)
    for g in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5):
        bots[f"generous_tft_{int(g * 100)}"] = (
            "import random\n"
            "def strategy(my_history, opp_history):\n"
            "    if not opp_history or opp_history[-1] == 'C':\n"
            "        return 'C'\n"
            f"    return 'C' if random.random() < {g} else 'D'\n"
        )
    # 5 periodic defectors
    for k in (2, 3, 5, 8, 13):
        bots[f"defect_every_{k}"] = (
            "def strategy(my_history, opp_history):\n"
            f"    return 'D' if len(my_history) % {k} == {k - 1} else 'C'\n"
        )
    # 5 majority-rule bots looking at the last n moves
    for n in (3, 5, 10, 20, 50):
        bots[f"majority_{n}"] = (
            "def strategy(my_history, opp_history):\n"
            f"    recent = opp_history[-{n}:]\n"
            "    return 'D' if recent.count('D') > len(recent) / 2 else 'C'\n"
        )
    # 5 stateful bots that turn hostile after t total opponent defections
    for t in (1, 2, 4, 8, 16):
        bots[f"patience_{t}"] = (
            "strikes = 0\n"
            "def strategy(my_history, opp_history):\n"
            "    global strikes\n"
            "    if opp_history and opp_history[-1] == 'D':\n"
            "        strikes += 1\n"
            f"    return 'D' if strikes >= {t} else 'C'\n"
        )
    # 2 crashing bots and 1 infinite loop bot
    bots["crash_zero_div"] = (
        "def strategy(my_history, opp_history):\n"
        "    if len(my_history) == 50:\n"
        "        return 1 / 0\n"
        "    return 'C'\n"
    )
    bots["crash_index"] = (
        "def strategy(my_history, opp_history):\n"
        "    return opp_history[0]  # IndexError on the first turn\n"
    )
    bots["infinite_loop"] = (
        "def strategy(my_history, opp_history):\n"
        "    while len(my_history) >= 100:\n"
        "        pass\n"
        "    return 'C'\n"
    )
    return bots


if __name__ == "__main__":
    bots = generate_bots()
    assert len(bots) == 31 and all(validate_code(c) == [] for c in bots.values())

    start = time.monotonic()
    result = run_safe_round_robin(bots, True, PRISONERS_DILEMMA, turns=200, repetitions=3, seed=2026)
    elapsed = time.monotonic() - start

    total = len(result["leaderboard"]) + len(result["disqualified"])
    print(f"Bots: {total}, matches: {(total * (total - 1) // 2 + total) * 3}, total time: {elapsed:.1f}s\n")
    print(f"Disqualified: {', '.join(result['disqualified'])}\n")
    print("Top 10:")
    for row in result["leaderboard"][:10]:
        print(f"  {row['rank']:>2}. {row['name']:<20} {row['total']:>7}  {row['avg_per_turn']:.3f}/turn")

    forfeits = result["forfeits"]
    print(f"\nForfeits: {len(forfeits)}")
    by_bot = {}
    for f in forfeits:
        by_bot.setdefault((f["bot"], f["reason"]), []).append(f)
    for (bot, reason), items in sorted(by_bot.items()):
        print(f"  {bot:<15} x{len(items):<4} {reason}")
