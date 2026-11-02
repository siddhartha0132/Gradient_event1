"""Create the event: rounds, organiser accounts and team accounts.

Run from server/:
    uv run python -m scripts.seed_demo --reset               # 12 empty teams
    uv run python -m scripts.seed_demo --reset --bots        # teams with countries and demo bots

Credentials are printed and written to data/credentials.csv.
"""

import argparse
import csv
import hashlib
import secrets

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.models import JOB_PRIORITY, Job, Round, Submission, Team, User
from app.db.session import create_tables, sync_sessions
from app.services.catalog import GAMES, countries
from engine.event import DEFAULT_EVENT

from .demo_bots import generate_bots

GAME_KEYS = {game.name: key for key, game in GAMES.items()}

TEAM_NAMES = [
    "Red Falcon", "Iron Wolves", "Blue Lantern", "Night Owls", "Silver Bear", "Grey Ghost", "Black Sea",
    "Cold Front", "Northern Star", "Last Signal", "Deep Cover", "Open Skies", "Broken Arrow", "Dead Drop",
    "White Rook", "Glass House", "Paper Moon", "Hollow Point", "Quiet Storm", "Echo Base",
]
DEMO_COUNTRIES = [
    "India", "United States of America", "Russia", "China", "Brazil", "France", "Germany", "Japan",
    "United Kingdom", "Australia", "Canada", "South Africa", "Egypt", "Mexico", "Argentina", "Indonesia",
    "Turkey", "Nigeria", "Kenya", "Norway",
]
# A spread of behaviours, plus one bot that crashes mid-match to show disqualification
DEMO_BOTS = [
    "generous_tft_10", "majority_10", "patience_2", "coop_90", "defect_every_3", "generous_tft_30",
    "majority_3", "crash_zero_div", "coop_50", "defect_every_13", "patience_1", "coop_25",
    "generous_tft_5", "majority_50", "defect_every_5", "patience_4", "coop_75", "majority_5",
    "defect_every_2", "patience_16",
]


# (modules, blocks per module, categories) for each round: the tools change as the war goes on
BLOCK_RULES = [
    (2, 20, ["logic", "history", "math"]),
    (3, 25, ["logic", "history", "math", "chance"]),
    (3, 30, ["logic", "history", "math", "chance"]),
    (1, 12, ["logic", "history"]),
]


def password() -> str:
    return f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--bots", action="store_true", help="claim countries and submit demo bots")
    parser.add_argument("--reset", action="store_true", help="delete the database first")
    args = parser.parse_args()
    if not 1 <= args.teams <= len(TEAM_NAMES):
        parser.error(f"--teams must be between 1 and {len(TEAM_NAMES)}")

    settings = get_settings()
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            settings.database_path.with_name(settings.database_path.name + suffix).unlink(missing_ok=True)
    create_tables()
    codes = {name: code for code, name in countries().items()}
    bots = generate_bots()
    credentials = []

    with sync_sessions()() as session:
        if session.query(Round).count():
            raise SystemExit("The database already has an event. Use --reset to start over.")
        for index, config in enumerate(DEFAULT_EVENT, start=1):
            max_modules, max_blocks, categories = BLOCK_RULES[index - 1]
            session.add(Round(
                index=index, name=config.name, game=GAME_KEYS[config.game.name], turns=config.turns,
                hide_turns=config.hide_turn_count, noise=config.noise, repetitions=config.repetitions,
                keep_fraction=config.keep_fraction, keep_count=config.keep_count,
                max_modules=max_modules, max_blocks=max_blocks, block_categories=categories))

        for username, role in (("admin", "admin"), ("organiser", "organiser"), ("projector", "spectator")):
            pw = password()
            session.add(User(username=username, password_hash=hash_password(pw), role=role))
            credentials.append((username, pw, role, ""))

        for i, name in enumerate(TEAM_NAMES[:args.teams]):
            team = Team(name=name, country_code=codes[DEMO_COUNTRIES[i]] if args.bots else None)
            session.add(team)
            session.flush()
            username, pw = f"team{i + 1:02d}", password()
            session.add(User(username=username, team_id=team.id, password_hash=hash_password(pw), role="team"))
            credentials.append((username, pw, "team", name))
            if args.bots:
                code = bots[DEMO_BOTS[i]]
                submission = Submission(team_id=team.id, version=1, hand_code=code, code=code,
                                        code_sha256=hashlib.sha256(code.encode()).hexdigest())
                session.add(submission)
                session.flush()
                session.add(Job(kind="test", priority=JOB_PRIORITY["test"], ref_id=submission.id))
        session.commit()

    out = settings.database_path.parent / "credentials.csv"
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "password", "role", "team"])
        writer.writerows(credentials)
    print(f"{'username':<12} {'password':<16} {'role':<10} team")
    for row in credentials:
        print(f"{row[0]:<12} {row[1]:<16} {row[2]:<10} {row[3]}")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
