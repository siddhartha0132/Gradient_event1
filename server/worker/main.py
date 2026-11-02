"""Worker process: claims jobs from the queue and runs agents in the sandbox.

Run with:  uv run python -m worker.main

Delivery is at least once: a job is claimed with a lease, and if the worker dies
before finishing, the lease expires and another worker reclaims it. Results are
written with a conditional update on the match's state, so a job that runs twice
changes nothing the second time. After too many attempts a job is dead and the
organisers see it in review.
"""

import multiprocessing
import os
import signal
import socket
import time

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.models import Match, MatchMoves, Round, RoundEntry, Submission, Verification
from app.db.session import create_tables, log_event, sync_sessions
from app.services.catalog import GAMES
from app.services.rounds import match_out
from app.services.submissions import submission_out
from engine.sandbox import play_recorded_match, test_submission

log = structlog.get_logger()

IDLE_POLL = 0.1

CLAIM = text("""
UPDATE jobs SET status = 'running', worker_id = :worker, attempts = attempts + 1, leased_until = :lease
WHERE id = (
    SELECT id FROM jobs
    WHERE (status = 'queued' OR (status = 'running' AND leased_until < :now))
      AND (exclude_worker IS NULL OR exclude_worker != :worker OR created_at < :exclusive_cutoff)
    ORDER BY priority, id
    LIMIT 1
)
RETURNING id, kind, ref_id, attempts
""")


def claim(session: Session, worker_id: str):
    settings = get_settings()
    now = time.time()
    row = session.execute(CLAIM, {
        "worker": worker_id, "now": now, "lease": now + settings.job_lease_seconds,
        "exclusive_cutoff": now - settings.verify_exclusive_seconds,
    }).first()
    session.commit()
    return row


def ack(session: Session, job_id: int, status: str = "done", error: str | None = None) -> None:
    session.execute(text("UPDATE jobs SET status = :s, error = :e, leased_until = NULL WHERE id = :id"),
                    {"s": status, "e": error, "id": job_id})


# --- Handlers: each writes its result and acks the job in one transaction ----

def handle_test(session: Session, submission_id: str, worker_id: str) -> None:
    s = session.get(Submission, submission_id)
    if s.status == "checking":
        result = test_submission(s.code)
        updated = session.execute(
            update(Submission).where(Submission.id == s.id, Submission.status == "checking")
            .values(status="accepted" if result["ok"] else "rejected", errors=result["errors"],
                    test_results=result.get("results", []), checked_at=time.time()))
        if updated.rowcount == 1:
            session.refresh(s)
            log_event(session, "submission.result", {"submission": submission_out(s).model_dump()},
                      audience=f"team:{s.team_id}")


def _play(session: Session, match: Match) -> dict:
    r = session.get(Round, match.round_id)
    codes = dict(session.execute(
        select(RoundEntry.team_id, Submission.code).join(Submission, Submission.id == RoundEntry.submission_id)
        .where(RoundEntry.round_id == r.id, RoundEntry.team_id.in_((match.team_a, match.team_b)))).all())
    return play_recorded_match(match.team_a, match.team_b, codes[match.team_a], codes[match.team_b],
                               GAMES[r.game], r.actual_turns or r.turns, r.noise, r.seed, match.repetition)


def handle_match(session: Session, match_id: str, worker_id: str) -> None:
    match = session.get(Match, match_id)
    if match.status != "queued":
        return  # already written by an earlier attempt
    result = _play(session, match)
    forfeit = result["forfeit"]
    updated = session.execute(
        update(Match).where(Match.id == match.id, Match.status == "queued").values(
            status="done", score_a=result["score1"], score_b=result["score2"],
            forfeit_side=forfeit and forfeit["side"], forfeit_reason=forfeit and forfeit["reason"],
            worker_id=worker_id, finished_at=time.time()))
    if updated.rowcount != 1:
        return
    moves_a, moves_b = "".join(result["history1"]), "".join(result["history2"])
    session.merge(MatchMoves(match_id=match.id, moves_a=moves_a, moves_b=moves_b))
    session.refresh(match)
    log_event(session, "match.done", {"match": match_out(match).model_dump(),
                                      "moves_a": moves_a, "moves_b": moves_b})


def handle_verify(session: Session, verification_id: str, worker_id: str) -> None:
    check = session.get(Verification, verification_id)
    if check.status != "queued":
        return
    match = session.get(Match, check.match_id)
    result = _play(session, match)
    session.execute(
        update(Verification).where(Verification.id == check.id, Verification.status == "queued").values(
            status="done", worker_id=worker_id, score_a=result["score1"], score_b=result["score2"],
            matches_original=(result["score1"], result["score2"]) == (match.score_a, match.score_b)))


HANDLERS = {"test": handle_test, "match": handle_match, "verify": handle_verify}


def give_up(session: Session, kind: str, ref_id: str, reason: str) -> None:
    """A job ran out of attempts: record the failure where organisers will see it."""
    if kind == "test":
        updated = session.execute(
            update(Submission).where(Submission.id == ref_id, Submission.status == "checking")
            .values(status="rejected", errors=[f"Could not be checked: {reason}"], checked_at=time.time()))
        if updated.rowcount:
            s = session.get(Submission, ref_id)
            log_event(session, "submission.result", {"submission": submission_out(s).model_dump()},
                      audience=f"team:{s.team_id}")
    elif kind == "match":
        session.execute(update(Match).where(Match.id == ref_id, Match.status == "queued")
                        .values(status="failed", forfeit_reason=reason))
        log_event(session, "job.dead", {"kind": kind, "ref_id": ref_id, "reason": reason}, audience="organisers")
    elif kind == "verify":
        session.execute(update(Verification).where(Verification.id == ref_id, Verification.status == "queued")
                        .values(status="failed"))
        log_event(session, "job.dead", {"kind": kind, "ref_id": ref_id, "reason": reason}, audience="organisers")


def process_one(session: Session, worker_id: str) -> bool:
    """Claim and run one job. Returns False when the queue is empty."""
    job = claim(session, worker_id)
    if job is None:
        return False
    if job.attempts > get_settings().max_job_attempts:
        give_up(session, job.kind, job.ref_id, f"failed {job.attempts - 1} times")
        ack(session, job.id, "dead")
        session.commit()
        log.warning("job.dead", job=job.id, kind=job.kind)
        return True
    started = time.monotonic()
    try:
        HANDLERS[job.kind](session, job.ref_id, worker_id)
        ack(session, job.id)
        session.commit()
    except Exception as e:
        # Leave the job leased: it is retried when the lease expires, up to the attempt limit
        session.rollback()
        log.exception("job.failed", job=job.id, kind=job.kind)
        session.execute(text("UPDATE jobs SET error = :e WHERE id = :id"), {"e": repr(e), "id": job.id})
        session.commit()
        return True
    log.info("job.done", job=job.id, kind=job.kind, seconds=round(time.monotonic() - started, 3))
    return True


def main() -> None:
    configure_logging()
    # A fork server keeps sandbox process start-up fast while every match still gets its own process
    multiprocessing.set_start_method("forkserver", force=True)
    multiprocessing.set_forkserver_preload(["engine.sandbox"])
    create_tables()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker.started", worker=worker_id)
    with sync_sessions()() as session:
        while not stopping:
            if not process_one(session, worker_id):
                time.sleep(IDLE_POLL)
    log.info("worker.stopped", worker=worker_id)


if __name__ == "__main__":
    main()
