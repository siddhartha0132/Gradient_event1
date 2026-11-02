"""Login, token refresh, teams and country claims."""

import time

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.security import create_access_token, create_refresh_token, decode_token, verify_password
from app.db.models import RefreshToken, Team, User
from app.db.session import log_event
from app.schemas.api import Country, TeamOut, TokenPair, UserOut

from .catalog import countries


def team_out(team: Team) -> TeamOut:
    return TeamOut(id=team.id, name=team.name, country_code=team.country_code,
                   eliminated_in=team.eliminated_in)


async def user_out(session: AsyncSession, user: User) -> UserOut:
    team = await session.get(Team, user.team_id) if user.team_id else None
    return UserOut(id=user.id, username=user.username, role=user.role, team=team and team_out(team))


async def _issue_tokens(session: AsyncSession, user: User) -> TokenPair:
    refresh, jti, expires_at = create_refresh_token(user.id)
    session.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires_at))
    await session.commit()
    return TokenPair(access_token=create_access_token(user.id, user.role, user.team_id),
                     refresh_token=refresh, user=await user_out(session, user))


async def login(session: AsyncSession, username: str, password: str) -> TokenPair:
    user = await session.scalar(select(User).where(User.username == username.strip()))
    if user is None or not verify_password(user.password_hash, password):
        raise ApiError(401, "BAD_CREDENTIALS", "Wrong username or password")
    return await _issue_tokens(session, user)


async def refresh(session: AsyncSession, token: str) -> TokenPair:
    """Rotate a refresh token: the old one is revoked and a new pair is issued."""
    payload = decode_token(token, "refresh")
    stored = payload and await session.get(RefreshToken, payload["jti"])
    if not stored or stored.revoked or stored.expires_at < time.time():
        raise ApiError(401, "BAD_REFRESH_TOKEN", "Please log in again")
    stored.revoked = True
    user = await session.get(User, stored.user_id)
    return await _issue_tokens(session, user)


async def revoke_team_sessions(session: AsyncSession, team_id: str) -> None:
    user_ids = select(User.id).where(User.team_id == team_id)
    await session.execute(update(RefreshToken).where(RefreshToken.user_id.in_(user_ids)).values(revoked=True))
    await session.commit()


async def list_countries(session: AsyncSession) -> list[Country]:
    claimed = {t.country_code: t for t in (await session.scalars(
        select(Team).where(Team.country_code.is_not(None)))).all()}
    return [Country(code=code, name=name, team_id=claimed[code].id if code in claimed else None,
                    team_name=claimed[code].name if code in claimed else None)
            for code, name in sorted(countries().items(), key=lambda item: item[1])]


async def claim_country(session: AsyncSession, team: Team, code: str) -> TeamOut:
    if code not in countries():
        raise ApiError(404, "UNKNOWN_COUNTRY", "No such country")
    if team.country_code:
        raise ApiError(409, "ALREADY_CLAIMED", "Your team has already claimed a country")
    team.country_code = code
    try:
        await session.flush()  # the unique constraint decides races between two teams
    except IntegrityError:
        await session.rollback()
        raise ApiError(409, "COUNTRY_TAKEN", "Another team has already claimed this country") from None
    out = team_out(team)
    log_event(session, "team.updated", {"team": out.model_dump()})
    await session.commit()
    return out
