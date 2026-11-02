import time

import pytest

from engine.event import RoundConfig, rank_for_cut, run_event
from engine.games import PRISONERS_DILEMMA
from engine.match import play_match
from engine.sandbox import load_bot, run_safe_round_robin, validate_code
from engine.sandbox import test_submission as check_submission
from engine.strategies import (
    BUILT_IN_BOTS,
    always_cooperate,
    always_defect,
    random_bot,
    tit_for_tat,
)
from engine.tournament import run_round_robin


def test_tit_for_tat_vs_always_defect():
    result = play_match(tit_for_tat, always_defect, PRISONERS_DILEMMA, turns=10)
    assert (result["score1"], result["score2"]) == (9, 14)


def test_always_cooperate_vs_always_defect():
    result = play_match(always_cooperate, always_defect, PRISONERS_DILEMMA, turns=10)
    assert (result["score1"], result["score2"]) == (0, 50)


def test_round_robin_one_entry_per_bot():
    result = run_round_robin(BUILT_IN_BOTS, PRISONERS_DILEMMA, turns=20, repetitions=2)
    names = [row["name"] for row in result["leaderboard"]]
    assert sorted(names) == sorted(BUILT_IN_BOTS)


def test_seed_makes_random_bot_repeatable():
    first = play_match(random_bot, tit_for_tat, PRISONERS_DILEMMA, turns=50, seed=42)
    second = play_match(random_bot, tit_for_tat, PRISONERS_DILEMMA, turns=50, seed=42)
    assert first["history1"] == second["history1"]
    assert first["history2"] == second["history2"]


def test_self_play_scores():
    bots = {"tit_for_tat": tit_for_tat, "always_defect": always_defect}
    result = run_round_robin(bots, PRISONERS_DILEMMA, turns=200, repetitions=1)
    assert result["matrix"]["tit_for_tat"]["tit_for_tat"] == 600
    assert result["matrix"]["always_defect"]["always_defect"] == 200


# --- Seeds ------------------------------------------------------------------

def test_round_robin_seed_is_repeatable():
    first = run_round_robin(BUILT_IN_BOTS, PRISONERS_DILEMMA, turns=50, repetitions=2, seed=7)
    second = run_round_robin(BUILT_IN_BOTS, PRISONERS_DILEMMA, turns=50, repetitions=2, seed=7)
    assert first == second


# --- Sandbox ----------------------------------------------------------------

COPYCAT = """
import random

def strategy(my_history, opp_history):
    return opp_history[-1] if opp_history else "C"
"""

BAD_MOVE = """
def strategy(my_history, opp_history):
    return "X"
"""

INFINITE_LOOP = """
def strategy(my_history, opp_history):
    while True:
        pass
"""

# Cooperates only while its counter matches its own history, so shared
# state between two copies would make it defect.
STATEFUL = """
count = 0

def strategy(my_history, opp_history):
    global count
    count += 1
    return "C" if count == len(my_history) + 1 else "D"
"""


def test_valid_bot_loads_and_plays():
    assert validate_code(COPYCAT) == []
    bot = load_bot(COPYCAT)
    result = play_match(bot, always_defect, PRISONERS_DILEMMA, turns=10)
    assert (result["score1"], result["score2"]) == (9, 14)


def test_import_os_rejected():
    errors = validate_code("import os\n\ndef strategy(my_history, opp_history):\n    return 'C'\n")
    assert any("os" in e for e in errors)
    with pytest.raises(ValueError):
        load_bot("import os\n\ndef strategy(my_history, opp_history):\n    return 'C'\n")


def test_bad_move_forfeits_and_is_disqualified():
    result = run_safe_round_robin({"bad": BAD_MOVE, "copycat": COPYCAT}, False,
                                  PRISONERS_DILEMMA, turns=10, repetitions=1)
    assert result["disqualified"] == ["bad"]
    assert [row["name"] for row in result["leaderboard"]] == ["copycat"]
    assert result["matrix"] == {"copycat": {"copycat": 30}}  # only self-play left
    assert {f["bot"] for f in result["forfeits"]} == {"bad"}
    assert "'X'" in result["forfeits"][0]["reason"]


def test_infinite_loop_forfeits_and_tournament_finishes():
    start = time.monotonic()
    result = run_safe_round_robin({"loop": INFINITE_LOOP}, True,
                                  PRISONERS_DILEMMA, turns=20, repetitions=1)
    assert result["disqualified"] == ["loop"]
    assert len(result["leaderboard"]) == len(BUILT_IN_BOTS)
    loop_forfeits = [f for f in result["forfeits"] if f["bot"] == "loop"]
    assert len(loop_forfeits) == len(BUILT_IN_BOTS) + 1  # every opponent plus itself
    assert all("timed out" in f["reason"] for f in loop_forfeits)
    # Remaining bots are scored only on each other (8 opponents each)
    tft = next(row for row in result["leaderboard"] if row["name"] == "tit_for_tat")
    assert tft["wins"] + tft["losses"] + tft["draws"] == len(BUILT_IN_BOTS) - 1
    assert time.monotonic() - start < 20


def test_stateful_bot_has_independent_state_in_self_play():
    result = run_safe_round_robin({"stateful": STATEFUL}, False,
                                  PRISONERS_DILEMMA, turns=50, repetitions=1)
    assert result["matrix"]["stateful"]["stateful"] == 150  # cooperated every turn
    assert result["forfeits"] == []


def test_safe_round_robin_seed_is_repeatable():
    bots = {"copycat": COPYCAT, "stateful": STATEFUL}
    first = run_safe_round_robin(bots, True, PRISONERS_DILEMMA, turns=50, repetitions=2, seed=7)
    second = run_safe_round_robin(bots, True, PRISONERS_DILEMMA, turns=50, repetitions=2, seed=7)
    assert first["leaderboard"] == second["leaderboard"]


def test_submission_accepts_good_bot():
    result = check_submission(COPYCAT)
    assert result["ok"] and result["errors"] == []
    assert [r["opponent"] for r in result["results"]] == ["tit_for_tat", "always_defect", "random_bot"]


def test_submission_rejects_bad_bots():
    invalid = check_submission("import os\n\ndef strategy(my_history, opp_history):\n    return 'C'\n")
    assert not invalid["ok"] and "os" in invalid["errors"][0]

    crashing = check_submission("def strategy(my_history, opp_history):\n    return opp_history[0]\n")
    assert not crashing["ok"] and len(crashing["errors"]) == 3
    assert crashing["errors"][0] == (
        "Against tit_for_tat: Your bot raised IndexError: list index out of range (line 2)")

    looping = check_submission(INFINITE_LOOP)
    assert not looping["ok"] and "timed out" in looping["errors"][0]


# --- Event ------------------------------------------------------------------

def make_bots(count):
    """`count` valid bots that cooperate with different probabilities."""
    return {
        f"bot_{i:02d}": (
            "import random\n"
            "def strategy(my_history, opp_history):\n"
            f"    return 'C' if random.random() < {i / count} else 'D'\n"
        )
        for i in range(count)
    }


FOUR_HALVING_ROUNDS = [RoundConfig(f"R{i}", PRISONERS_DILEMMA, 20, repetitions=1) for i in range(4)]


def test_event_halves_16_bots_down_to_one():
    event = run_event(make_bots(16), FOUR_HALVING_ROUNDS, seed=3)
    entrants = [len(r["advanced"]) + len(r["eliminated"]) for r in event["rounds"]]
    assert entrants + [len(event["rounds"][-1]["advanced"])] == [16, 8, 4, 2, 1]
    assert event["champion"] == event["rounds"][-1]["advanced"][0]


def test_disqualified_bots_never_advance():
    bots = make_bots(3)
    bots["bad"] = BAD_MOVE
    rounds = [RoundConfig("Generous cut", PRISONERS_DILEMMA, 20, repetitions=1, keep_count=4)]
    event = run_event(bots, rounds, seed=3)
    first = event["rounds"][0]
    assert first["disqualified"] == ["bad"]
    assert "bad" not in first["advanced"] and "bad" in first["eliminated"]
    assert len(first["advanced"]) == 3


def test_same_seed_same_champion():
    rounds = FOUR_HALVING_ROUNDS[:-1] + [
        RoundConfig("Hidden", PRISONERS_DILEMMA, 20, repetitions=1, keep_count=1, hide_turn_count=True)]
    first = run_event(make_bots(16), rounds, seed=99, include_builtins=True)
    second = run_event(make_bots(16), rounds, seed=99, include_builtins=True)
    assert first["champion"] == second["champion"]
    assert [r["advanced"] for r in first["rounds"]] == [r["advanced"] for r in second["rounds"]]
    assert first["rounds"][-1]["turns"] == second["rounds"][-1]["turns"]
    assert all(name.startswith("bot_") for r in first["rounds"] for name in r["advanced"])


def test_keep_count_overrides_keep_fraction():
    assert RoundConfig("R", PRISONERS_DILEMMA, 10, keep_fraction=0.5).cut_size(5) == 3
    assert RoundConfig("R", PRISONERS_DILEMMA, 10, keep_fraction=0.5, keep_count=2).cut_size(5) == 2


def test_cut_tie_break_head_to_head_then_coin_flip():
    leaderboard = [{"name": n, "total": t} for n, t in
                   [("a", 100), ("b", 100), ("c", 100), ("d", 120), ("e", 90), ("f", 90)]]
    matrix = {
        "a": {"b": 10, "c": 10, "d": 0, "e": 0, "f": 0},
        "b": {"a": 30, "c": 30, "d": 0, "e": 0, "f": 0},  # best head to head among a, b, c
        "c": {"a": 20, "b": 20, "d": 0, "e": 0, "f": 0},
        "d": {"a": 0, "b": 0, "c": 0, "e": 0, "f": 0},
        "e": {"a": 0, "b": 0, "c": 0, "d": 0, "f": 15},  # e and f tie on head to head too
        "f": {"a": 0, "b": 0, "c": 0, "d": 0, "e": 15},
    }
    names = ["a", "b", "c", "d", "e", "f"]
    for seed in range(20):
        assert rank_for_cut(names, leaderboard, matrix, seed)[:4] == ["d", "b", "c", "a"]

    # e vs f is a coin flip: repeatable per seed, and not always submission order
    last_two = {seed: tuple(rank_for_cut(names, leaderboard, matrix, seed)[4:]) for seed in range(20)}
    assert last_two == {seed: tuple(rank_for_cut(names, leaderboard, matrix, seed)[4:]) for seed in range(20)}
    assert set(last_two.values()) == {("e", "f"), ("f", "e")}
