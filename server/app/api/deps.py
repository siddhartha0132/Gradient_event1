"""Request dependencies: database session and the authenticated user."""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, forbidden
from app.core.security import decode_token
from app.db.models import Team, User
from app.db.session import get_session

Session = Annotated[AsyncSession, Depends(get_session)]


async def user_from_token(session: AsyncSession, token: str | None) -> User | None:
    payload = token and decode_token(token, "access")
    return payload and await session.get(User, payload["sub"])


async def current_user(session: Session, authorization: Annotated[str | None, Header()] = None) -> User:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    user = await user_from_token(session, token)
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "Please log in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*roles: str):
    async def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise forbidden()
        return user
    return Depends(check)


async def current_team(session: Session, user: User = require("team")) -> Team:
    team = await session.get(Team, user.team_id)
    if team is None:
        raise forbidden("Your account has no team")
    return team


Organiser = Annotated[User, require("organiser", "admin")]
TeamUser = Annotated[User, require("team")]
CurrentTeam = Annotated[Team, Depends(current_team)]
