"""Built-in bots. Each takes (my_history, opp_history) and returns "C" or "D"."""

import random


def always_cooperate(my_history, opp_history):
    """Always cooperates."""
    return "C"


def always_defect(my_history, opp_history):
    """Always defects."""
    return "D"


def random_bot(my_history, opp_history):
    """Cooperates or defects with equal probability."""
    return random.choice(["C", "D"])


def tit_for_tat(my_history, opp_history):
    """Cooperates first, then copies the opponent's last move."""
    return opp_history[-1] if opp_history else "C"


def grudger(my_history, opp_history):
    """Cooperates until the opponent defects once, then defects forever."""
    return "D" if "D" in opp_history else "C"


def tit_for_two_tats(my_history, opp_history):
    """Defects only if the opponent defected in each of the last two rounds."""
    return "D" if opp_history[-2:] == ["D", "D"] else "C"


def alternator(my_history, opp_history):
    """Alternates C, D, C, D, ... starting with C."""
    return "C" if len(my_history) % 2 == 0 else "D"


def suspicious_tit_for_tat(my_history, opp_history):
    """Defects first, then copies the opponent's last move."""
    return opp_history[-1] if opp_history else "D"


def win_stay_lose_shift(my_history, opp_history):
    """Cooperates first; repeats its move if the opponent cooperated, otherwise switches."""
    if not my_history:
        return "C"
    if opp_history[-1] == "C":
        return my_history[-1]
    return "D" if my_history[-1] == "C" else "C"


BUILT_IN_BOTS = {
    "always_cooperate": always_cooperate,
    "always_defect": always_defect,
    "random_bot": random_bot,
    "tit_for_tat": tit_for_tat,
    "grudger": grudger,
    "tit_for_two_tats": tit_for_two_tats,
    "alternator": alternator,
    "suspicious_tit_for_tat": suspicious_tit_for_tat,
    "win_stay_lose_shift": win_stay_lose_shift,
}
