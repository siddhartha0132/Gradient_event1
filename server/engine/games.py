"""Two-player, two-move games defined by payoff tables."""


class Game:
    """A symmetric 2x2 game: payoffs maps (move1, move2) -> (score1, score2)."""

    def __init__(self, name, payoffs):
        self.name = name
        self.payoffs = payoffs

    def score(self, move1, move2):
        return self.payoffs[(move1, move2)]

    def __repr__(self):
        return f"Game({self.name!r})"


PRISONERS_DILEMMA = Game("Prisoner's Dilemma", {
    ("C", "C"): (3, 3),
    ("C", "D"): (0, 5),
    ("D", "C"): (5, 0),
    ("D", "D"): (1, 1),
})

CHICKEN = Game("Chicken", {
    ("C", "C"): (3, 3),
    ("C", "D"): (1, 5),
    ("D", "C"): (5, 1),
    ("D", "D"): (0, 0),
})

STAG_HUNT = Game("Stag Hunt", {
    ("C", "C"): (4, 4),
    ("C", "D"): (0, 3),
    ("D", "C"): (3, 0),
    ("D", "D"): (2, 2),
})
