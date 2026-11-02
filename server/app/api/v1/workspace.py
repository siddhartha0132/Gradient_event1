"""What a team uses while building: submissions, live validation, practice matches, fair play reports."""

import random
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.core.errors import ApiError
from app.db.models import FairplayEvent, Team
from app.db.session import log_event
from app.schemas.api import (
    AgentIn,
    BuiltInBot,
    FairplayBatch,
    FairplayOut,
    Ok,
    PracticeOut,
    PracticeRequest,
    SubmissionDetail,
    SubmissionOut,
    ValidateOut,
)
from app.services import submissions
from app.services.catalog import GAMES, built_in_bots
from engine.sandbox import play_safe_match
from engine.strategies import BUILT_IN_BOTS

from ..deps import CurrentTeam, CurrentUser, Session, TeamUser

router = APIRouter()


@router.post("/submissions", response_model=SubmissionOut, status_code=202, tags=["submissions"])
async def submit(body: AgentIn, user: TeamUser, team: CurrentTeam, session: Session,
                 idempotency_key: Annotated[str | None, Header()] = None):
    """Store a new version and queue its check. The result arrives as a submission.result event.

    Block rules are checked immediately (422 BLOCK_RULES); the server compiles the modules itself.
    """
    layouts = [m.layout for m in body.modules]
    return await submissions.create_submission(session, user, team, body.hand_code, layouts, idempotency_key)


@router.get("/submissions", response_model=list[SubmissionOut], tags=["submissions"])
async def history(team: CurrentTeam, session: Session):
    return await submissions.list_submissions(session, team.id)


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail, tags=["submissions"])
async def get_submission(submission_id: str, user: CurrentUser, session: Session):
    return await submissions.get_submission(session, submission_id, user)


@router.post("/practice/validate", response_model=ValidateOut, tags=["practice"])
async def validate(body: AgentIn, _: CurrentUser, session: Session):
    """Build the agent under the current round's block rules: errors for the editor, and the
    Python generated from each block module for the preview."""
    return await submissions.validate(session, body.hand_code, [m.layout for m in body.modules])


@router.get("/practice/bots", response_model=list[BuiltInBot], tags=["practice"])
async def bots(_: CurrentUser):
    return built_in_bots()


@router.post("/practice/simulate", response_model=PracticeOut, tags=["practice"])
async def simulate(body: PracticeRequest, _: CurrentUser, session: Session):
    """Play a practice match in the sandbox against a built-in bot, or against a copy of yourself."""
    if body.game not in GAMES:
        raise ApiError(404, "UNKNOWN_GAME", "No such game")
    if body.opponent != "self" and body.opponent not in BUILT_IN_BOTS:
        raise ApiError(404, "UNKNOWN_BOT", "No such built-in bot")
    build = await submissions.validate(session, body.hand_code, [m.layout for m in body.modules])
    if build.errors:
        raise ApiError(422, "CODE_INVALID", build.errors[0].message,
                       {"errors": [e.model_dump() for e in build.errors]})
    code = build.assembled
    opponent = "copy" if body.opponent == "self" else body.opponent
    codes = {"you": code, opponent: code if body.opponent == "self" else body.opponent}
    result = await run_in_threadpool(play_safe_match, "you", opponent, codes, GAMES[body.game], body.turns,
                                     body.noise, random.randrange(2**32))
    forfeit = result["forfeit"]
    return PracticeOut(
        score=result["score1"], opponent_score=result["score2"],
        my_moves="".join(result["history1"]), opponent_moves="".join(result["history2"]),
        forfeit=forfeit and f"{'Your bot' if forfeit['side'] == 0 else body.opponent} {forfeit['reason']}")


@router.post("/fairplay/events", response_model=Ok, tags=["fairplay"])
async def report(body: FairplayBatch, team: CurrentTeam, session: Session):
    """Batched reports from the client. They are signals for invigilators, not proof."""
    for e in body.events:
        row = FairplayEvent(team_id=team.id, kind=e.kind, detail=e.detail, client_ts=e.client_ts)
        session.add(row)
        await session.flush()
        flag = FairplayOut(id=row.id, team_id=team.id, team_name=team.name, kind=row.kind, detail=row.detail,
                           client_ts=row.client_ts, server_ts=row.server_ts)
        log_event(session, "fairplay.flag", {"flag": flag.model_dump()}, audience="organisers")
    await session.commit()
    return Ok()


async def fairplay_rows(session, limit: int = 200) -> list[FairplayOut]:
    rows = (await session.execute(
        select(FairplayEvent, Team.name).join(Team, Team.id == FairplayEvent.team_id)
        .order_by(FairplayEvent.server_ts.desc()).limit(limit))).all()
    return [FairplayOut(id=e.id, team_id=e.team_id, team_name=name, kind=e.kind, detail=e.detail,
                        client_ts=e.client_ts, server_ts=e.server_ts) for e, name in rows]
