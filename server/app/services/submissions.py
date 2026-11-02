"""Versioned submissions. Rows are never overwritten once their check completes."""

import hashlib
import time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.db.models import JOB_PRIORITY, IdempotencyKey, Job, Submission, Team, User
from app.schemas.api import (
    CodeError,
    ModuleDetail,
    ModuleOut,
    SubmissionDetail,
    SubmissionOut,
    TestResult,
    ValidateOut,
)
from engine.blocks import Build, build_agent

from .rounds import breaks_rules, current_round, rules_for, rules_out, window_open


def errors_out(build: Build) -> list[CodeError]:
    return [CodeError(message=e.message, line=e.line, module=e.module, kind=e.kind) for e in build.errors]


async def validate(session: AsyncSession, hand_code: str, layouts: list[dict]) -> ValidateOut:
    """Build the agent under the current round's rules: errors, generated module code and the assembled code."""
    rules = rules_for(await current_round(session))
    build = build_agent(hand_code, layouts, rules)
    return ValidateOut(errors=errors_out(build), assembled=build.assembled, rules=rules_out(rules),
                       modules=[m and ModuleOut(name=m.name, code=m.code, blocks=m.blocks) for m in build.by_index])


def submission_out(s: Submission, with_code: bool = False) -> SubmissionOut:
    fields = {"id": s.id, "version": s.version, "status": s.status, "errors": s.errors or [],
              "test_results": [TestResult(**r) for r in s.test_results or []], "code_sha256": s.code_sha256,
              "created_at": s.created_at, "checked_at": s.checked_at, "module_count": len(s.modules or [])}
    if not with_code:
        return SubmissionOut(**fields)
    return SubmissionDetail(**fields, hand_code=s.hand_code or s.code, code=s.code,
                            modules=[ModuleDetail(**m) for m in s.modules or []])


async def create_submission(session: AsyncSession, user: User, team: Team, hand_code: str, layouts: list[dict],
                            idempotency_key: str | None) -> SubmissionOut:
    if idempotency_key:
        stored = await session.get(IdempotencyKey, (idempotency_key, user.id))
        if stored:
            return SubmissionOut(**stored.response)

    if team.eliminated_in is not None:
        raise ApiError(403, "TEAM_ELIMINATED", "Your nation has fallen and can no longer submit")
    r = await current_round(session)
    if r is None or not window_open(r):
        raise ApiError(409, "WINDOW_CLOSED", "The submission window is closed")

    # Block rules are checked here, on the server, because the client cannot be trusted.
    # Problems in the hand-written code are reported by the sandbox test like any other agent.
    build = build_agent(hand_code, layouts, rules_for(r))
    block_errors = [e for e in errors_out(build) if e.kind == "blocks"]
    if block_errors:
        raise ApiError(422, "BLOCK_RULES", "Your block modules break this round's rules",
                       {"errors": [e.model_dump() for e in block_errors]})

    version = (await session.scalar(
        select(func.max(Submission.version)).where(Submission.team_id == team.id)) or 0) + 1
    submission = Submission(
        team_id=team.id, version=version, hand_code=hand_code, code=build.assembled,
        modules=[{"name": m.name, "layout": m.layout, "code": m.code, "blocks": m.blocks} for m in build.modules],
        code_sha256=hashlib.sha256(build.assembled.encode()).hexdigest())
    session.add(submission)
    await session.flush()
    session.add(Job(kind="test", priority=JOB_PRIORITY["test"], ref_id=submission.id))
    out = submission_out(submission)
    if idempotency_key:
        session.add(IdempotencyKey(key=idempotency_key, user_id=user.id, response=out.model_dump()))

    # Re-check the deadline at commit time: the window may have closed while we worked
    await session.refresh(r)
    if not window_open(r, time.time()):
        await session.rollback()
        raise ApiError(409, "WINDOW_CLOSED", "The submission window is closed")
    try:
        await session.commit()
    except IntegrityError:  # two submissions raced for the same version number
        await session.rollback()
        raise ApiError(409, "RETRY", "Please submit again") from None
    return out


async def list_submissions(session: AsyncSession, team_id: str) -> list[SubmissionOut]:
    rows = await session.scalars(
        select(Submission).where(Submission.team_id == team_id).order_by(Submission.version.desc()))
    r = await current_round(session)
    out = []
    for s in rows:
        item = submission_out(s)
        if s.status == "accepted" and r is not None and r.status in ("draft", "open"):
            item.rule_problems = breaks_rules(s, r)
        out.append(item)
    return out


async def get_submission(session: AsyncSession, submission_id: str, user: User) -> SubmissionDetail:
    s = await session.get(Submission, submission_id)
    if s is None or (user.role not in ("organiser", "admin") and s.team_id != user.team_id):
        raise not_found("Submission")
    return submission_out(s, with_code=True)
