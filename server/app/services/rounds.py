"""Round lifecycle: draft -> open -> locked -> running -> verifying -> review -> published.

Every transition is one transaction that first checks the current state with a
conditional UPDATE, so it can never happen twice or out of order.
"""

import math
import random
import time

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.db.models import (
    JOB_PRIORITY,
    Job,
    Match,
    Penalty,
    Round,
    RoundEntry,
    Standing,
    Submission,
    Team,
    Verification,
)
from app.db.session import log_event
from app.schemas.api import (
    BlockRulesModel,
    MatchOut,
    Mismatch,
    PenaltyOut,
    ReviewOut,
    RoundOut,
    StandingOut,
    VerificationReport,
)
from engine.blocks import CATEGORIES, BlockRules, check_rules
from engine.event import rank_for_cut
from engine.tournament import match_seed, schedule, summarize

from .catalog import game_info

VERIFY_SAMPLE = 0.05  # share of matches away from the cut line that are re-run


def rules_for(r: Round | None) -> BlockRules:
    if r is None:
        return BlockRules(max_modules=0, max_blocks=1, categories=[])
    return BlockRules(max_modules=r.max_modules, max_blocks=r.max_blocks,
                      categories=[c for c in r.block_categories if c in CATEGORIES])


def rules_out(rules: BlockRules) -> BlockRulesModel:
    return BlockRulesModel(max_modules=rules.max_modules, max_blocks=rules.max_blocks, categories=rules.categories)


def breaks_rules(submission: Submission, r: Round) -> list[str]:
    """Why a stored submission may not play in this round, e.g. built under looser limits."""
    return [e.message for e in check_rules([m["layout"] for m in submission.modules or []], rules_for(r))]


def window_open(r: Round, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return (r.status == "open" and r.paused_remaining is None
            and r.closes_at is not None and now < r.closes_at)


async def round_out(session: AsyncSession, r: Round) -> RoundOut:
    total = await session.scalar(select(func.count()).where(Match.round_id == r.id)) or 0
    done = await session.scalar(
        select(func.count()).where(Match.round_id == r.id, Match.status.in_(("done", "failed")))) or 0
    return RoundOut(
        id=r.id, index=r.index, name=r.name, game=game_info(r.game),
        turns=None if r.hide_turns else r.turns, hide_turns=r.hide_turns, noise=r.noise,
        repetitions=r.repetitions, keep_fraction=r.keep_fraction, keep_count=r.keep_count,
        block_rules=rules_out(rules_for(r)), status=r.status, opens_at=r.opens_at, closes_at=r.closes_at,
        paused_remaining=r.paused_remaining, window_open=window_open(r),
        matches_total=total, matches_done=done,
    )


async def current_round(session: AsyncSession) -> Round | None:
    """The first round not yet published, or the last round once the event is over."""
    r = await session.scalar(select(Round).where(Round.status != "published").order_by(Round.index))
    return r or await session.scalar(select(Round).order_by(Round.index.desc()))


async def get_round(session: AsyncSession, round_id: str) -> Round:
    r = await session.get(Round, round_id)
    if r is None:
        raise not_found("Round")
    return r


async def _transition(session: AsyncSession, r: Round, expected: tuple[str, ...], **values) -> None:
    """Conditional update: applies only if the round is still in an expected state."""
    name = r.name
    result = await session.execute(
        update(Round).where(Round.id == r.id, Round.status.in_(expected)).values(**values))
    if result.rowcount != 1:
        status = await session.scalar(select(Round.status).where(Round.id == r.id))
        await session.rollback()  # expires r, so nothing may be read from it afterwards
        raise ApiError(409, "INVALID_ROUND_STATE", f"Round '{name}' is {status}, expected {' or '.join(expected)}")
    await session.refresh(r)


async def _announce(session: AsyncSession, r: Round, type_: str = "round.status") -> None:
    log_event(session, type_, {"round": (await round_out(session, r)).model_dump()})


# --- Windows (organiser actions) -------------------------------------------

async def open_window(session: AsyncSession, r: Round, minutes: float) -> None:
    earlier = await session.scalar(
        select(func.count()).where(Round.index < r.index, Round.status != "published"))
    if earlier:
        raise ApiError(409, "EARLIER_ROUND_PENDING", "Publish the earlier rounds first")
    now = time.time()
    await _transition(session, r, ("draft",), status="open", opens_at=now, closes_at=now + minutes * 60,
                      paused_remaining=None)
    await _announce(session, r)
    await _announce(session, r, "window.updated")
    await session.commit()


async def update_rules(session: AsyncSession, r: Round, rules: BlockRulesModel) -> None:
    """Change a round's block rules. Allowed until its window closes."""
    unknown = set(rules.categories) - set(CATEGORIES)
    if unknown:
        raise ApiError(422, "UNKNOWN_CATEGORY", f"Unknown block categories: {', '.join(sorted(unknown))}")
    await _transition(session, r, ("draft", "open"), max_modules=rules.max_modules, max_blocks=rules.max_blocks,
                      block_categories=[c for c in CATEGORIES if c in rules.categories])
    await _announce(session, r, "window.updated")
    await session.commit()


async def extend_window(session: AsyncSession, r: Round, minutes: float) -> None:
    if r.status != "open":
        raise ApiError(409, "INVALID_ROUND_STATE", "The window is not open")
    delta = minutes * 60
    if r.paused_remaining is not None:
        values = {"paused_remaining": max(0.0, r.paused_remaining + delta)}
    else:
        values = {"closes_at": max(time.time(), r.closes_at + delta)}
    await _transition(session, r, ("open",), **values)
    await _announce(session, r, "window.updated")
    await session.commit()


async def pause_window(session: AsyncSession, r: Round) -> None:
    if r.status != "open" or r.paused_remaining is not None:
        raise ApiError(409, "INVALID_ROUND_STATE", "The window is not running")
    await _transition(session, r, ("open",), paused_remaining=max(0.0, r.closes_at - time.time()))
    await _announce(session, r, "window.updated")
    await session.commit()


async def resume_window(session: AsyncSession, r: Round) -> None:
    if r.status != "open" or r.paused_remaining is None:
        raise ApiError(409, "INVALID_ROUND_STATE", "The window is not paused")
    await _transition(session, r, ("open",), closes_at=time.time() + r.paused_remaining,
                      paused_remaining=None)
    await _announce(session, r, "window.updated")
    await session.commit()


async def close_window(session: AsyncSession, r: Round) -> None:
    await _transition(session, r, ("open",), closes_at=time.time(), paused_remaining=None)
    await _announce(session, r, "window.updated")
    await session.commit()


# --- Scheduler steps -------------------------------------------------------

async def lock_if_due(session: AsyncSession, r: Round) -> bool:
    """Close the window and record each live team's latest accepted version.

    Waits while a submission made before the deadline is still being checked, so
    a team that submitted in the last second is not locked out by the test queue.
    """
    now = time.time()
    if r.status != "open" or r.paused_remaining is not None or now < r.closes_at:
        return False
    still_checking = await session.scalar(
        select(func.count()).where(Submission.status == "checking", Submission.created_at <= r.closes_at))
    if still_checking:
        return False

    await _transition(session, r, ("open",), status="locked", locked_at=now)
    live_teams = (await session.scalars(select(Team.id).where(Team.eliminated_in.is_(None)))).all()
    for team_id in live_teams:
        latest = await session.scalar(
            select(Submission).where(Submission.team_id == team_id, Submission.status == "accepted")
            .order_by(Submission.version.desc()).limit(1))
        # The latest accepted version only plays if it keeps to this round's block rules
        if latest and not breaks_rules(latest, r):
            session.add(RoundEntry(round_id=r.id, team_id=team_id, submission_id=latest.id))
    await _announce(session, r)
    await _announce(session, r, "window.updated")
    await session.commit()
    return True


def _actual_turns(r: Round) -> int:
    """The exact count, or a seeded count within +/-25% when the count is hidden."""
    if not r.hide_turns:
        return r.turns
    rng = random.Random(f"{r.seed}|turns")
    return rng.randint(round(r.turns * 0.75), round(r.turns * 1.25))


async def start_round(session: AsyncSession, r: Round) -> None:
    entrants = (await session.scalars(
        select(RoundEntry.team_id).where(RoundEntry.round_id == r.id).order_by(RoundEntry.team_id))).all()
    if not entrants:
        raise ApiError(409, "NO_ENTRANTS", "No team has an accepted submission for this round")
    await _transition(session, r, ("locked",), status="running", started_at=time.time(),
                      actual_turns=_actual_turns(r))
    for rep, a, b in schedule(list(entrants), r.repetitions):
        match = Match(round_id=r.id, team_a=a, team_b=b, repetition=rep)
        session.add(match)
        await session.flush()
        session.add(Job(kind="match", priority=JOB_PRIORITY["match"], ref_id=match.id))
    await _announce(session, r)
    await session.commit()


async def finish_running_if_done(session: AsyncSession, r: Round) -> bool:
    pending = await session.scalar(
        select(func.count()).where(Match.round_id == r.id, Match.status == "queued"))
    if r.status != "running" or pending:
        return False
    await _transition(session, r, ("running",), status="verifying")
    ranked_ids, keep = await compute_standings(session, r)
    await _queue_verifications(session, r, ranked_ids, keep)
    await _announce(session, r)
    await session.commit()
    return True


async def finish_verifying_if_done(session: AsyncSession, r: Round) -> bool:
    pending = await session.scalar(
        select(func.count()).select_from(Verification).join(Match, Match.id == Verification.match_id)
        .where(Match.round_id == r.id, Verification.status == "queued"))
    if r.status != "verifying" or pending:
        return False
    await _transition(session, r, ("verifying",), status="review")
    await _announce(session, r)
    await session.commit()
    return True


async def _queue_verifications(session: AsyncSession, r: Round, ranked_ids: list[str], keep: int) -> None:
    """Re-run every match involving a team within two places of the cut line,
    plus a seeded random sample of the rest, each on a different worker."""
    near_cut = set(ranked_ids[max(0, keep - 2):keep + 2])
    rng = random.Random(f"{r.seed}|verify")
    matches = (await session.scalars(
        select(Match).where(Match.round_id == r.id, Match.status == "done").order_by(Match.id))).all()
    for match in matches:
        if match.team_a in near_cut or match.team_b in near_cut or rng.random() < VERIFY_SAMPLE:
            check = Verification(match_id=match.id)
            session.add(check)
            await session.flush()
            session.add(Job(kind="verify", priority=JOB_PRIORITY["verify"], ref_id=check.id,
                            exclude_worker=match.worker_id))


async def compute_standings(session: AsyncSession, r: Round) -> tuple[list[str], int]:
    """(Re)build the standings for a round. Returns (ranked team ids, cut size).

    Uses the engine's rules: a team that forfeits any match is disqualified and all
    of its matches are dropped, so the others are scored on the same opponents.
    Penalties are subtracted before ranking. Ties break by head to head, then a
    seeded coin flip.
    """
    turns = r.actual_turns or r.turns
    entrants = (await session.scalars(select(RoundEntry.team_id).where(RoundEntry.round_id == r.id))).all()
    matches = (await session.scalars(select(Match).where(Match.round_id == r.id))).all()

    reasons: dict[str, str] = {}
    for m in matches:
        if m.status == "done" and m.forfeit_side is not None:
            reasons.setdefault((m.team_a, m.team_b)[m.forfeit_side], m.forfeit_reason or "forfeited")
    remaining = [t for t in entrants if t not in reasons]
    results = [(m.team_a, m.team_b, m.score_a, m.score_b) for m in matches
               if m.status == "done" and m.team_a in remaining and m.team_b in remaining]
    summary = summarize(remaining, results, turns, r.repetitions)

    penalties = dict((await session.execute(
        select(Penalty.team_id, func.sum(Penalty.points)).where(Penalty.round_id == r.id)
        .group_by(Penalty.team_id))).all())
    rows = {row["name"]: row for row in summary["leaderboard"]}
    leaderboard = [{**row, "total": row["total"] - penalties.get(row["name"], 0)}
                   for row in summary["leaderboard"]]
    ranked = rank_for_cut(remaining, leaderboard, summary["matrix"], r.seed)
    keep = r.keep_count if r.keep_count is not None else max(1, math.ceil(len(entrants) * r.keep_fraction))

    await session.execute(Standing.__table__.delete().where(Standing.round_id == r.id))
    for position, team_id in enumerate(ranked, start=1):
        row = rows[team_id]
        session.add(Standing(
            round_id=r.id, team_id=team_id, total=row["total"] - penalties.get(team_id, 0),
            penalty=penalties.get(team_id, 0), wins=row["wins"], losses=row["losses"], draws=row["draws"],
            avg_per_turn=row["avg_per_turn"], rank=position,
            outcome="advanced" if position <= keep else "eliminated"))
    for team_id, reason in reasons.items():
        session.add(Standing(round_id=r.id, team_id=team_id, outcome="disqualified", reason=reason,
                             penalty=penalties.get(team_id, 0)))
    absent = (await session.scalars(select(Team.id).where(
        Team.eliminated_in.is_(None), Team.id.not_in(entrants)))).all()
    for team_id in absent:
        latest = await session.scalar(
            select(Submission).where(Submission.team_id == team_id, Submission.status == "accepted",
                                     Submission.created_at <= (r.locked_at or time.time()))
            .order_by(Submission.version.desc()).limit(1))
        broken = latest and breaks_rules(latest, r)
        reason = (f"Latest accepted version breaks this round's block rules: {broken[0]}" if broken
                  else "No accepted submission when the window closed")
        session.add(Standing(round_id=r.id, team_id=team_id, outcome="absent", reason=reason))
    await session.flush()
    return ranked, keep


async def standings_out(session: AsyncSession, r: Round) -> list[StandingOut]:
    rows = (await session.execute(
        select(Standing, Team).join(Team, Team.id == Standing.team_id).where(Standing.round_id == r.id)
        .order_by(Standing.rank.is_(None), Standing.rank, Team.name))).all()
    return [StandingOut(
        team_id=s.team_id, team_name=t.name, country_code=t.country_code, total=s.total, penalty=s.penalty,
        wins=s.wins, losses=s.losses, draws=s.draws, avg_per_turn=s.avg_per_turn, rank=s.rank,
        outcome=s.outcome, reason=s.reason) for s, t in rows]


# --- Review and approval ---------------------------------------------------

def match_out(m: Match) -> MatchOut:
    return MatchOut(id=m.id, round_id=m.round_id, team_a=m.team_a, team_b=m.team_b, repetition=m.repetition,
                    status=m.status, score_a=m.score_a, score_b=m.score_b, forfeit_side=m.forfeit_side,
                    forfeit_reason=m.forfeit_reason)


async def review(session: AsyncSession, r: Round) -> ReviewOut:
    checks = (await session.execute(
        select(Verification, Match).join(Match, Match.id == Verification.match_id)
        .where(Match.round_id == r.id))).all()
    mismatches = [Mismatch(match_id=m.id, team_a=m.team_a, team_b=m.team_b,
                           original=[m.score_a, m.score_b], recomputed=[v.score_a, v.score_b])
                  for v, m in checks if v.status == "done" and not v.matches_original]
    failed = (await session.scalars(
        select(Match).where(Match.round_id == r.id, Match.status == "failed"))).all()
    penalties = (await session.scalars(select(Penalty).where(Penalty.round_id == r.id))).all()

    blockers = []
    if r.status != "review":
        blockers.append(f"The round is {r.status}, not in review")
    if mismatches:
        blockers.append(f"{len(mismatches)} verification mismatch(es)")
    if failed:
        blockers.append(f"{len(failed)} match(es) failed to compute")
    failed_checks = sum(1 for v, _ in checks if v.status == "failed")
    if failed_checks:
        blockers.append(f"{failed_checks} verification job(s) failed")
    queued = await session.scalar(
        select(func.count()).where(Match.round_id == r.id, Match.status == "queued")) or 0
    queued += sum(1 for v, _ in checks if v.status == "queued")
    if queued and r.status == "review":
        blockers.append(f"{queued} retried job(s) still running")

    return ReviewOut(
        round=await round_out(session, r),
        standings=await standings_out(session, r),
        verification=VerificationReport(
            total=len(checks), done=sum(1 for v, _ in checks if v.status == "done"), mismatches=mismatches),
        failed_matches=[match_out(m) for m in failed],
        penalties=[PenaltyOut(id=p.id, team_id=p.team_id, round_id=p.round_id, points=p.points,
                              reason=p.reason, created_at=p.created_at) for p in penalties],
        blockers=blockers,
    )


async def approve(session: AsyncSession, r: Round, actor_id: str) -> None:
    report = await review(session, r)
    if report.blockers:
        raise ApiError(409, "ROUND_BLOCKED", "This round cannot be published yet",
                       {"blockers": report.blockers})
    await compute_standings(session, r)
    await _transition(session, r, ("review",), status="published", approved_by=actor_id,
                      approved_at=time.time())
    standings = await standings_out(session, r)
    fallen = [s.team_id for s in standings if s.outcome != "advanced"]
    if fallen:
        await session.execute(update(Team).where(Team.id.in_(fallen)).values(eliminated_in=r.index))
    is_last = not await session.scalar(select(func.count()).where(Round.index > r.index))
    advanced = [s for s in standings if s.outcome == "advanced"]
    champion = advanced[0].team_id if is_last and advanced else None
    log_event(session, "standings.published", {
        "round": (await round_out(session, r)).model_dump(),
        "standings": [s.model_dump() for s in standings],
        "eliminated": fallen,
        "champion": champion,
    })
    await session.commit()


async def issue_penalty(session: AsyncSession, team_id: str, r: Round, points: int, reason: str,
                        actor_id: str) -> Penalty:
    if r.status == "published":
        raise ApiError(409, "INVALID_ROUND_STATE", "This round is already published")
    if await session.get(Team, team_id) is None:
        raise not_found("Team")
    penalty = Penalty(team_id=team_id, round_id=r.id, points=points, reason=reason, issued_by=actor_id)
    session.add(penalty)
    await session.flush()
    if r.status in ("verifying", "review"):
        await compute_standings(session, r)
    log_event(session, "penalty.issued", {"team_id": team_id, "points": points, "reason": reason},
              audience=f"team:{team_id}")
    await session.commit()
    return penalty


async def retry_failed_match(session: AsyncSession, match: Match) -> None:
    """Give a match that ran out of attempts another go (e.g. after fixing a worker)."""
    result = await session.execute(
        update(Match).where(Match.id == match.id, Match.status == "failed").values(status="queued"))
    if result.rowcount != 1:
        raise ApiError(409, "INVALID_MATCH_STATE", "Only failed matches can be retried")
    session.add(Job(kind="match", priority=JOB_PRIORITY["match"], ref_id=match.id))
    await session.commit()


async def rerun_verification(session: AsyncSession, match: Match) -> None:
    """Re-run a match's verification on yet another worker, e.g. after a mismatch."""
    check = await session.scalar(select(Verification).where(Verification.match_id == match.id))
    if check is None:
        raise not_found("Verification")
    previous = check.worker_id
    check.status, check.score_a, check.score_b, check.matches_original = "queued", None, None, None
    session.add(Job(kind="verify", priority=JOB_PRIORITY["verify"], ref_id=check.id,
                    exclude_worker=previous or match.worker_id))
    await session.commit()


def match_seed_for(r: Round, m: Match) -> int:
    return match_seed(r.seed, m.team_a, m.team_b, m.repetition)
