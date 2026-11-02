"""Static reference data: games, built-in bots and countries."""

import json
from functools import lru_cache
from pathlib import Path

from app.schemas.api import BuiltInBot, GameInfo
from engine.games import CHICKEN, PRISONERS_DILEMMA, STAG_HUNT, Game
from engine.strategies import BUILT_IN_BOTS

GAMES: dict[str, Game] = {
    "prisoners_dilemma": PRISONERS_DILEMMA,
    "chicken": CHICKEN,
    "stag_hunt": STAG_HUNT,
}


def game_info(key: str) -> GameInfo:
    game = GAMES[key]
    payoffs = {a + b: list(scores) for (a, b), scores in game.payoffs.items()}
    return GameInfo(key=key, name=game.name, payoffs=payoffs)


def built_in_bots() -> list[BuiltInBot]:
    return [BuiltInBot(key=key, description=(fn.__doc__ or "").strip()) for key, fn in BUILT_IN_BOTS.items()]


@lru_cache
def countries() -> dict[str, str]:
    """ISO 3166 numeric code -> name, from the same Natural Earth data the client draws."""
    path = Path(__file__).resolve().parents[1] / "data" / "countries.json"
    return json.loads(path.read_text())
