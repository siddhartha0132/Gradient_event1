"""Validate, load and safely run user-submitted bot code.

The AST checks and restricted builtins block the obvious escapes, and each match
runs in a separate worker process with a time limit. This is not OS-level
isolation: workers still run as the server's user.
"""

import ast
import math
import multiprocessing
import os
import random
import signal
import time
import traceback
from types import ModuleType, SimpleNamespace

from .games import PRISONERS_DILEMMA
from .match import play_match
from .strategies import BUILT_IN_BOTS
from .tournament import match_seed, schedule, summarize

MATCH_TIMEOUT = 2.0   # seconds per match, enforced inside the worker
WATCHDOG_GRACE = 1.0  # extra seconds before the parent kills a stuck worker

ALLOWED_IMPORTS = {"random", "math"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals",
                "locals", "getattr", "setattr", "vars"}
# Attributes that reach module internals (random._os) or frames and code objects
BANNED_ATTR_PREFIXES = ("_", "gi_", "cr_", "ag_", "f_", "tb_", "co_")

SAFE_BUILTINS = {f.__name__: f for f in (
    len, range, min, max, sum, abs, list, dict, set, tuple, enumerate, zip,
    any, all, sorted, reversed, int, float, bool, str,
)}


def _identifiers(node):
    """Names a node defines or binds (function names, args, import aliases, ...)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.alias):
        return [node.name, node.asname or ""]
    if isinstance(node, ast.keyword):
        return [node.arg or ""]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return node.names
    return []


def validate_code(code):
    """Return a list of problems with the bot code. Empty means it is valid."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error on line {e.lineno}: {e.msg}"]

    errors = []
    strategies = [n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "strategy"]
    if not strategies:
        errors.append("Missing a top-level function strategy(my_history, opp_history).")
    else:
        args = strategies[-1].args
        if (len(args.posonlyargs + args.args) != 2 or args.vararg
                or args.kwarg or args.kwonlyargs):
            errors.append("strategy must take exactly 2 arguments: (my_history, opp_history).")

    for node in ast.walk(tree):
        line = f"Line {getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    errors.append(f"{line}: importing '{alias.name}' is not allowed (only random and math).")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS:
                errors.append(f"{line}: importing from '{node.module}' is not allowed (only random and math).")
        elif isinstance(node, (ast.Try, ast.TryStar)):
            # Otherwise a bot could catch the timeout and keep running
            errors.append(f"{line}: try/except is not allowed.")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                errors.append(f"{line}: '{node.id}' is not allowed.")
            elif node.id.startswith("__"):
                errors.append(f"{line}: names starting with '__' are not allowed ('{node.id}').")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_NAMES or node.attr.startswith(BANNED_ATTR_PREFIXES):
                errors.append(f"{line}: attribute '.{node.attr}' is not allowed.")

        for name in _identifiers(node):
            if name.startswith("__"):
                errors.append(f"{line}: names starting with '__' are not allowed ('{name}').")

    return errors


def _module_proxy(module):
    """A fresh copy of a module's public functions and constants, so a bot can't
    tamper with the real module or with another bot's copy."""
    public = {}
    for name in dir(module):
        value = getattr(module, name)
        if name.startswith("_") or name == "main" or isinstance(value, (type, ModuleType)):
            continue
        public[name] = value
    return SimpleNamespace(**public)


def load_bot(code):
    """Validate and exec bot code in a fresh namespace. Returns its strategy function."""
    errors = validate_code(code)
    if errors:
        raise ValueError("Invalid bot code:\n" + "\n".join(errors))

    modules = {"random": _module_proxy(random), "math": _module_proxy(math)}

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in modules:
            raise ImportError(f"importing '{name}' is not allowed")
        return modules[name]

    builtins = dict(SAFE_BUILTINS, print=lambda *args, **kwargs: None,
                    __import__=safe_import)
    namespace = {"__builtins__": builtins, **modules}
    exec(compile(code, "<bot>", "exec"), namespace)

    strategy = namespace.get("strategy")
    if not callable(strategy):
        raise ValueError("strategy is not a function.")
    return strategy


# --- Worker side ----------------------------------------------------------

class MatchTimeout(BaseException):
    """Raised by SIGALRM when a match runs past MATCH_TIMEOUT."""


class BadMove(Exception):
    """A bot returned something other than "C" or "D"."""


# Shared arrays indexed by match: when it started, and which side (0/1) is moving
_started = None
_running = None


def _init_worker(started, running):
    global _started, _running
    _started, _running = started, running
    signal.signal(signal.SIGALRM, _on_alarm)


def _on_alarm(signum, frame):
    raise MatchTimeout


def _forfeit(side, turns, reason):
    """Result when `side` forfeits: 0 for them, 3 per turn for the opponent."""
    scores = (0, 3 * turns) if side == 0 else (3 * turns, 0)
    return scores + ((side, reason),)


def _bot_line(error):
    """' (line N)' for the deepest frame of bot code in the traceback, if any."""
    lines = [f.lineno for f in traceback.extract_tb(error.__traceback__) if f.filename == "<bot>"]
    return f" (line {lines[-1]})" if lines else ""


def _load(source):
    """A source is either a built-in bot name or code."""
    return BUILT_IN_BOTS[source] if source in BUILT_IN_BOTS else load_bot(source)


def _play_job(index, sources, game, turns, noise, seed, record=False):
    """Play one match in a worker. Returns (score1, score2, forfeit or None), plus
    (history1, history2) when `record` is set. On a forfeit the histories hold
    every turn completed before it."""
    _started[index] = time.monotonic()
    histories = ([], [])

    def guard(bot, side):
        def move(my_history, opp_history):
            nonlocal histories
            if record and side == 0:
                # Side 0 moves first each turn, so it sees every completed turn
                histories = (list(my_history), list(opp_history))
            _running[index] = side
            m = bot(my_history, opp_history)
            if m not in ("C", "D"):
                raise BadMove(f"returned {m!r} instead of 'C' or 'D'")
            return m
        return move

    signal.setitimer(signal.ITIMER_REAL, MATCH_TIMEOUT)
    try:
        # Load each side separately so self-play gets two independent copies
        bots = []
        for side in (0, 1):
            _running[index] = side
            bots.append(guard(_load(sources[side]), side))
        result = play_match(bots[0], bots[1], game, turns, noise, seed)
        outcome = (result["score1"], result["score2"], None)
        histories = (result["history1"], result["history2"])
    except MatchTimeout:
        outcome = _forfeit(_running[index], turns, f"timed out after {MATCH_TIMEOUT:g}s")
    except BadMove as e:
        outcome = _forfeit(_running[index], turns, str(e))
    except BaseException as e:
        outcome = _forfeit(_running[index], turns, f"raised {type(e).__name__}: {e}{_bot_line(e)}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return outcome + histories if record else outcome


# --- Parent side ----------------------------------------------------------

def _run_in_pool(matches, sources, game, turns, noise, seed, record=False):
    """Play every match in a worker pool. Returns one (score1, score2, forfeit) per match,
    with (history1, history2) appended when `record` is set.

    Workers time themselves out with SIGALRM. As a backstop (e.g. a bot stuck in a
    long C call, which ignores signals), the parent kills the pool when a match runs
    past the deadline, forfeits the bot that was moving, and reruns unfinished matches.
    """
    started = multiprocessing.Array("d", len(matches), lock=False)
    running = multiprocessing.Array("i", len(matches), lock=False)
    outcomes = [None] * len(matches)
    todo = list(range(len(matches)))

    while todo:
        for i in todo:
            started[i] = 0.0
        stuck = []
        workers = min(len(todo), os.cpu_count() or 1)
        with multiprocessing.Pool(workers, initializer=_init_worker, initargs=(started, running)) as pool:
            pending = {}
            for i in todo:
                rep, a, b = matches[i]
                args = (i, (sources[a], sources[b]), game, turns, noise,
                        match_seed(seed, a, b, rep), record)
                pending[i] = pool.apply_async(_play_job, args)

            while pending and not stuck:
                time.sleep(0.01)
                for i in [i for i, r in pending.items() if r.ready()]:
                    outcomes[i] = pending.pop(i).get()
                now = time.monotonic()
                stuck = [i for i in pending
                         if started[i] and now - started[i] > MATCH_TIMEOUT + WATCHDOG_GRACE]
        # Leaving the `with` block terminates the pool, killing stuck workers

        for i in stuck:
            outcomes[i] = _forfeit(running[i], turns, f"timed out after {MATCH_TIMEOUT:g}s (worker killed)")
            if record:
                outcomes[i] += ([], [])
        todo = [i for i in pending if i not in stuck]

    return outcomes


def run_safe_round_robin(bot_codes, include_builtins, game, turns, repetitions=1,
                         noise=0.0, seed=None):
    """Like run_round_robin, but bots are code strings run in worker processes.

    bot_codes maps name -> code, or name -> a built-in bot name. A bot that raises,
    returns a bad move or times out forfeits that match and is disqualified from
    the round: all of its matches are dropped, so every remaining bot is scored
    on the same opponents. Returns the run_round_robin result (remaining bots
    only) plus "forfeits" and "disqualified" lists.
    """
    sources = {name: name for name in BUILT_IN_BOTS} if include_builtins else {}
    sources.update(bot_codes)
    for name, source in sources.items():
        if source not in BUILT_IN_BOTS:
            errors = validate_code(source)
            if errors:
                raise ValueError(f"Bot {name!r} is invalid: " + " ".join(errors))

    names = list(sources)
    matches = schedule(names, repetitions)
    outcomes = _run_in_pool(matches, sources, game, turns, noise, seed)

    results, forfeits = [], []
    for (rep, a, b), (sa, sb, forfeit) in zip(matches, outcomes):
        results.append((a, b, sa, sb))
        if forfeit:
            side, reason = forfeit
            forfeits.append({
                "bot": (a, b)[side],
                "opponent": (b, a)[side],
                "repetition": rep,
                "reason": reason,
            })

    disqualified = {f["bot"] for f in forfeits}
    remaining = [name for name in names if name not in disqualified]
    results = [r for r in results if r[0] not in disqualified and r[1] not in disqualified]

    summary = summarize(remaining, results, turns, repetitions)
    summary["forfeits"] = forfeits
    summary["disqualified"] = [name for name in names if name in disqualified]
    return summary


def play_safe_match(name1, name2, bot_codes, game, turns, noise=0.0, seed=None):
    """Play one match between two bots in the sandbox and keep the full record.

    bot_codes maps name -> code or built-in name, as in run_safe_round_robin.
    The match seed is derived the same way as in a round robin, so the replay
    matches repetition 0 of a tournament run with the same seed.

    Returns {"history1", "history2", "score1", "score2", "forfeit"}, where forfeit
    is None or {"side": 0 or 1, "reason": ...}. On a forfeit the histories stop
    at the last completed turn and the scores are the forfeit scores.
    """
    for name in (name1, name2):
        if bot_codes[name] not in BUILT_IN_BOTS:
            errors = validate_code(bot_codes[name])
            if errors:
                raise ValueError(f"Bot {name!r} is invalid: " + " ".join(errors))

    sources = {name1: bot_codes[name1], name2: bot_codes[name2]}
    [(score1, score2, forfeit, history1, history2)] = _run_in_pool(
        [(0, name1, name2)], sources, game, turns, noise, seed, record=True)
    return {
        "history1": history1,
        "history2": history2,
        "score1": score1,
        "score2": score2,
        "forfeit": None if forfeit is None else {"side": forfeit[0], "reason": forfeit[1]},
    }


def test_submission(code, turns=50):
    """Check an uploaded bot before accepting it: validate, then play it against
    tit_for_tat, always_defect and random_bot in the sandbox.

    Returns {"ok": True, "errors": []} or {"ok": False, "errors": [messages]}.
    """
    errors = validate_code(code)
    if errors:
        return {"ok": False, "errors": errors}

    opponents = ["tit_for_tat", "always_defect", "random_bot"]
    sources = {"submission": code, **{name: name for name in opponents}}
    matches = [(0, "submission", name) for name in opponents]
    outcomes = _run_in_pool(matches, sources, PRISONERS_DILEMMA, turns, 0.0, seed=0)

    errors, results = [], []
    for name, (score, opp_score, forfeit) in zip(opponents, outcomes):
        results.append({"opponent": name, "score": score, "opponent_score": opp_score})
        if forfeit:
            side, reason = forfeit
            who = "Your bot" if side == 0 else name  # built-ins never fail, but be exact
            errors.append(f"Against {name}: {who} {reason}")
    return {"ok": not errors, "errors": errors, "results": results}


def play_recorded_match(name1, name2, source1, source2, game, turns, noise, round_seed, repetition):
    """Play one scheduled match of a round in the sandbox, as a worker job does.

    The match seed is derived from (round_seed, name1, name2, repetition) exactly as
    in a round robin, so the same stored inputs always give the same result.
    Self-play (name1 == name2) uses source1 for both sides.
    """
    sources = {name1: source1, name2: source2} if name1 != name2 else {name1: source1}
    [(score1, score2, forfeit, history1, history2)] = _run_in_pool(
        [(repetition, name1, name2)], sources, game, turns, noise, round_seed, record=True)
    return {
        "history1": history1,
        "history2": history2,
        "score1": score1,
        "score2": score2,
        "forfeit": None if forfeit is None else {"side": forfeit[0], "reason": forfeit[1]},
    }
