"""Auth, clock, countries, teams and rounds: everything a logged-in viewer can read."""

import time

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.core.errors import ApiError, not_found
from app.core.settings import get_settings
from app.db.models import Match, MatchMoves, Round, Team
from app.schemas.api import (
    ClaimRequest,
    ClientConfig,
    ClockOut,
    Country,
    LoginRequest,
    MatchOut,
    RefreshRequest,
    ReplayOut,
    RoundOut,
    StandingOut,
    TeamOut,
    TokenPair,
    UserOut,
)
from app.services import accounts, rounds
from app.services.catalog import game_info

from ..deps import CurrentTeam, CurrentUser, Session

router = APIRouter()


@router.post("/auth/login", response_model=TokenPair, tags=["auth"])
async def login(body: LoginRequest, session: Session):
    return await accounts.login(session, body.username, body.password)


@router.post("/auth/refresh", response_model=TokenPair, tags=["auth"])
async def refresh(body: RefreshRequest, session: Session):
    return await accounts.refresh(session, body.refresh_token)


@router.get("/me", response_model=UserOut, tags=["auth"])
async def me(user: CurrentUser, session: Session):
    return await accounts.user_out(session, user)


@router.get("/clock", response_model=ClockOut, tags=["clock"])
async def clock():
    return ClockOut(server_time=time.time())


@router.get("/config", response_model=ClientConfig, tags=["clock"])
async def client_config():
    settings = get_settings()
    return ClientConfig(probe_internet=settings.fairplay_internet_probe, probe_url=settings.fairplay_probe_url)


@router.get("/countries", response_model=list[Country], tags=["teams"])
async def countries(_: CurrentUser, session: Session):
    return await accounts.list_countries(session)


@router.post("/teams/me/country", response_model=TeamOut, tags=["teams"])
async def claim_country(body: ClaimRequest, team: CurrentTeam, session: Session):
    return await accounts.claim_country(session, team, body.code)


@router.get("/teams", response_model=list[TeamOut], tags=["teams"])
async def teams(_: CurrentUser, session: Session):
    return [accounts.team_out(t) for t in await session.scalars(select(Team).order_by(Team.name))]


@router.get("/rounds", response_model=list[RoundOut], tags=["rounds"])
async def list_rounds(_: CurrentUser, session: Session):
    return [await rounds.round_out(session, r) for r in await session.scalars(select(Round).order_by(Round.index))]


@router.get("/rounds/current", response_model=RoundOut | None, tags=["rounds"])
async def current(_: CurrentUser, session: Session):
    r = await rounds.current_round(session)
    return r and await rounds.round_out(session, r)


def _is_staff(user) -> bool:
    return user.role in ("organiser", "admin")


@router.get("/rounds/{round_id}/standings", response_model=list[StandingOut], tags=["rounds"])
async def standings(round_id: str, user: CurrentUser, session: Session):
    r = await rounds.get_round(session, round_id)
    if r.status != "published" and not _is_staff(user):
        raise ApiError(403, "NOT_PUBLISHED", "Standings are shown once organisers approve the round")
    return await rounds.standings_out(session, r)


@router.get("/rounds/{round_id}/matches", response_model=list[MatchOut], tags=["replays"])
async def round_matches(round_id: str, user: CurrentUser, session: Session):
    """All matches of a published round, or only your own while it is still in progress."""
    r = await rounds.get_round(session, round_id)
    query = select(Match).where(Match.round_id == round_id).order_by(Match.repetition, Match.team_a, Match.team_b)
    if r.status != "published" and not _is_staff(user):
        if user.role != "team":
            return []
        query = query.where(or_(Match.team_a == user.team_id, Match.team_b == user.team_id))
    return [rounds.match_out(m) for m in await session.scalars(query)]


@router.get("/matches/{match_id}/replay", response_model=ReplayOut, tags=["replays"])
async def replay(match_id: str, user: CurrentUser, session: Session):
    match = await session.get(Match, match_id)
    if match is None:
        raise not_found("Match")
    r = await session.get(Round, match.round_id)
    own = user.role == "team" and user.team_id in (match.team_a, match.team_b)
    if not (r.status == "published" or own or _is_staff(user)):
        raise not_found("Match")
    moves = await session.get(MatchMoves, match_id)
    if moves is None:
        raise ApiError(409, "NOT_PLAYED", "This match has not been played yet")
    return ReplayOut(match=rounds.match_out(match), game=game_info(r.game),
                     moves_a=moves.moves_a, moves_b=moves.moves_b)
