"""Play a single repeated match between two bots."""

import random


def _flip(move):
    return "D" if move == "C" else "C"


def play_match(bot1, bot2, game, turns, noise=0.0, seed=None):
    """Play `turns` rounds of `game`. Each move is flipped with probability `noise`.

    Bots are called as strategy(my_history, opp_history). Histories record the
    moves actually played (after noise), so both bots see the same record.
    A seed makes the whole match repeatable, including bots that use `random`.
    """
    if seed is not None:
        random.seed(seed)  # seeds the global RNG that bots like random_bot use
    rng = random.Random(seed)
    history1, history2 = [], []
    score1 = score2 = 0

    for _ in range(turns):
        # Pass copies so a bot can't tamper with the real histories
        move1 = bot1(list(history1), list(history2))
        move2 = bot2(list(history2), list(history1))

        if noise and rng.random() < noise:
            move1 = _flip(move1)
        if noise and rng.random() < noise:
            move2 = _flip(move2)

        s1, s2 = game.score(move1, move2)
        score1 += s1
        score2 += s2
        history1.append(move1)
        history2.append(move2)

    return {
        "history1": history1,
        "history2": history2,
        "score1": score1,
        "score2": score2,
    }
