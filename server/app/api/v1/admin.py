"""Organiser controls: windows, rounds, review, penalties and fair play."""

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.errors import not_found
from app.db.models import FairplayEvent, Match, Submission, Team, User
from app.schemas.api import (
    AdminTeamRow,
    BlockRulesModel,
    FairplayOut,
    Ok,
    PenaltyIn,
    PenaltyOut,
    ReviewOut,
    WindowExtend,
    WindowOpen,
)
from app.services import accounts, rounds

from ..deps import Organiser, Session
from .workspace import fairplay_rows

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/rounds/{round_id}/window/open", response_model=Ok)
async def open_window(round_id: str, body: WindowOpen, _: Organiser, session: Session):
    await rounds.open_window(session, await rounds.get_round(session, round_id), body.minutes)
    return Ok()


@router.put("/rounds/{round_id}/rules", response_model=Ok)
async def update_rules(round_id: str, body: BlockRulesModel, _: Organiser, session: Session):
    """Set how many block modules, how many blocks per module and which block categories teams may use."""
    await rounds.update_rules(session, await rounds.get_round(session, round_id), body)
    return Ok()


@router.post("/rounds/{round_id}/window/extend", response_model=Ok)
async def extend_window(round_id: str, body: WindowExtend, _: Organiser, session: Session):
    await rounds.extend_window(session, await rounds.get_round(session, round_id), body.minutes)
    return Ok()


@router.post("/rounds/{round_id}/window/pause", response_model=Ok)
async def pause_window(round_id: str, _: Organiser, session: Session):
    await rounds.pause_window(session, await rounds.get_round(session, round_id))
    return Ok()


@router.post("/rounds/{round_id}/window/resume", response_model=Ok)
async def resume_window(round_id: str, _: Organiser, session: Session):
    await rounds.resume_window(session, await rounds.get_round(session, round_id))
    return Ok()


@router.post("/rounds/{round_id}/window/close", response_model=Ok)
async def close_window(round_id: str, _: Organiser, session: Session):
    await rounds.close_window(session, await rounds.get_round(session, round_id))
    return Ok()


@router.post("/rounds/{round_id}/start", response_model=Ok)
async def start_round(round_id: str, _: Organiser, session: Session):
    await rounds.start_round(session, await rounds.get_round(session, round_id))
    return Ok()


@router.get("/rounds/{round_id}/review", response_model=ReviewOut)
async def review(round_id: str, _: Organiser, session: Session):
    return await rounds.review(session, await rounds.get_round(session, round_id))


@router.post("/rounds/{round_id}/approve", response_model=Ok)
async def approve(round_id: str, user: Organiser, session: Session):
    await rounds.approve(session, await rounds.get_round(session, round_id), user.id)
    return Ok()


@router.post("/matches/{match_id}/retry", response_model=Ok)
async def retry_match(match_id: str, _: Organiser, session: Session):
    match = await session.get(Match, match_id)
    if match is None:
        raise not_found("Match")
    await rounds.retry_failed_match(session, match)
    return Ok()


@router.post("/matches/{match_id}/reverify", response_model=Ok)
async def reverify(match_id: str, _: Organiser, session: Session):
    match = await session.get(Match, match_id)
    if match is None:
        raise not_found("Match")
    await rounds.rerun_verification(session, match)
    return Ok()


@router.post("/teams/{team_id}/penalties", response_model=PenaltyOut)
async def penalise(team_id: str, body: PenaltyIn, user: Organiser, session: Session):
    r = await rounds.get_round(session, body.round_id)
    p = await rounds.issue_penalty(session, team_id, r, body.points, body.reason, user.id)
    return PenaltyOut(id=p.id, team_id=p.team_id, round_id=p.round_id, points=p.points, reason=p.reason,
                      created_at=p.created_at)


@router.post("/teams/{team_id}/revoke-sessions", response_model=Ok)
async def revoke_sessions(team_id: str, _: Organiser, session: Session):
    """Revoke every refresh token of a team, e.g. if its credentials leaked."""
    await accounts.revoke_team_sessions(session, team_id)
    return Ok()


@router.get("/teams", response_model=list[AdminTeamRow])
async def teams(_: Organiser, session: Session):
    flags = dict((await session.execute(
        select(FairplayEvent.team_id, func.count()).group_by(FairplayEvent.team_id))).all())
    out = []
    for team in await session.scalars(select(Team).order_by(Team.name)):
        latest = await session.scalar(
            select(Submission).where(Submission.team_id == team.id).order_by(Submission.version.desc()).limit(1))
        accepted = await session.scalar(
            select(func.max(Submission.version)).where(Submission.team_id == team.id,
                                                       Submission.status == "accepted"))
        usernames = (await session.scalars(select(User.username).where(User.team_id == team.id))).all()
        out.append(AdminTeamRow(
            team=accounts.team_out(team), usernames=list(usernames), latest_submission_id=latest and latest.id,
            latest_version=latest and latest.version, latest_status=latest and latest.status,
            accepted_version=accepted, fairplay_flags=flags.get(team.id, 0)))
    return out


@router.get("/fairplay", response_model=list[FairplayOut])
async def fairplay(_: Organiser, session: Session):
    return await fairplay_rows(session)
