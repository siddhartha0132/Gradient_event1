"""Database tables. Times are stored as UTC epoch seconds (float).

The jobs table stands in for Redis Streams in the single-machine demo: workers
claim jobs with a lease, and a job whose lease expires is reclaimed.
"""

import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    country_code: Mapped[str | None] = mapped_column(String(8), unique=True)  # one team per country
    eliminated_in: Mapped[int | None] = mapped_column(Integer)  # round index the team fell in
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"))
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))  # team, organiser, admin, spectator


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Round(Base):
    __tablename__ = "rounds"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    index: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(80))
    game: Mapped[str] = mapped_column(String(32))
    turns: Mapped[int] = mapped_column(Integer)
    hide_turns: Mapped[bool] = mapped_column(Boolean, default=False)
    noise: Mapped[float] = mapped_column(Float, default=0.0)
    repetitions: Mapped[int] = mapped_column(Integer, default=3)
    keep_fraction: Mapped[float] = mapped_column(Float, default=0.5)
    keep_count: Mapped[int | None] = mapped_column(Integer)
    # Block rules for submissions made in this round's window
    max_modules: Mapped[int] = mapped_column(Integer, default=2)
    max_blocks: Mapped[int] = mapped_column(Integer, default=20)
    block_categories: Mapped[list] = mapped_column(JSON, default=lambda: ["logic", "history", "math", "chance"])
    seed: Mapped[str] = mapped_column(String(64), default=lambda: uuid.uuid4().hex)
    # draft, open, locked, running, verifying, review, published
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # Submission window. While paused, paused_remaining holds the seconds left
    opens_at: Mapped[float | None] = mapped_column(Float)
    closes_at: Mapped[float | None] = mapped_column(Float)
    paused_remaining: Mapped[float | None] = mapped_column(Float)
    actual_turns: Mapped[int | None] = mapped_column(Integer)
    locked_at: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[float | None] = mapped_column(Float)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[float | None] = mapped_column(Float)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("team_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    hand_code: Mapped[str] = mapped_column(Text, default="")
    modules: Mapped[list] = mapped_column(JSON, default=list)  # [{name, layout, code, blocks}]
    code: Mapped[str] = mapped_column(Text)  # the assembled code that actually runs
    code_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="checking")  # checking, accepted, rejected
    errors: Mapped[list] = mapped_column(JSON, default=list)
    test_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    checked_at: Mapped[float | None] = mapped_column(Float)


class RoundEntry(Base):
    """Exactly which submission version each team played with in a round."""
    __tablename__ = "round_entries"
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"))


class Match(Base):
    __tablename__ = "matches"
    # This uniqueness is what makes result writes idempotent
    __table_args__ = (UniqueConstraint("round_id", "team_a", "team_b", "repetition"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), index=True)
    team_a: Mapped[str] = mapped_column(String(32))
    team_b: Mapped[str] = mapped_column(String(32))
    repetition: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued, done, failed
    score_a: Mapped[int | None] = mapped_column(Integer)
    score_b: Mapped[int | None] = mapped_column(Integer)
    forfeit_side: Mapped[int | None] = mapped_column(Integer)
    forfeit_reason: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[float | None] = mapped_column(Float)


class MatchMoves(Base):
    __tablename__ = "match_moves"
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    moves_a: Mapped[str] = mapped_column(Text)  # one character per turn, "C" or "D"
    moves_b: Mapped[str] = mapped_column(Text)


class Standing(Base):
    __tablename__ = "standings"
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    penalty: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    avg_per_turn: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int | None] = mapped_column(Integer)
    # advanced, eliminated, disqualified, absent (no accepted submission)
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)


class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued, done, failed
    worker_id: Mapped[str | None] = mapped_column(String(64))
    score_a: Mapped[int | None] = mapped_column(Integer)
    score_b: Mapped[int | None] = mapped_column(Integer)
    matches_original: Mapped[bool | None] = mapped_column(Boolean)


class FairplayEvent(Base):
    __tablename__ = "fairplay_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    client_ts: Mapped[float] = mapped_column(Float)
    server_ts: Mapped[float] = mapped_column(Float, default=time.time)


class Penalty(Base):
    __tablename__ = "penalties"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"))
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    issued_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class EventLog(Base):
    """Append only. In SQLite writes are serialised, so seq order is commit order."""
    __tablename__ = "event_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(48))
    audience: Mapped[str] = mapped_column(String(48))  # all, organisers, team:<id>
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # test, match, verify
    priority: Mapped[int] = mapped_column(Integer)  # lower runs first
    ref_id: Mapped[str] = mapped_column(String(32))  # submission, match or verification id
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued, running, done, dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    exclude_worker: Mapped[str | None] = mapped_column(String(64))
    leased_until: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Lease(Base):
    """Leadership leases, e.g. only one scheduler may act at a time."""
    __tablename__ = "leases"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)


JOB_PRIORITY = {"test": 0, "match": 1, "verify": 2}
