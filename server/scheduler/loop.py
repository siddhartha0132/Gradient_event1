"""The scheduler owns the event clock: it closes windows, detects when a round's
matches and verifications are done, and moves rounds along.

Only one scheduler acts at a time. Each instance tries to hold a lease row; the
holder renews it every tick, and if it dies the lease expires and another
instance takes over within seconds.
"""

import asyncio
import contextlib
import os
import socket
import time

import structlog
from sqlalchemy import or_, select, update

from app.db.models import Lease, Round
from app.db.session import async_sessions
from app.services import rounds

log = structlog.get_logger()

TICK = 0.5
LEASE_SECONDS = 5.0
HOLDER = f"{socket.gethostname()}-{os.getpid()}"


async def hold_lease(session, name: str = "scheduler") -> bool:
    now = time.time()
    result = await session.execute(
        update(Lease).where(Lease.name == name, or_(Lease.holder == HOLDER, Lease.expires_at < now))
        .values(holder=HOLDER, expires_at=now + LEASE_SECONDS))
    if result.rowcount == 0 and await session.get(Lease, name) is None:
        session.add(Lease(name=name, holder=HOLDER, expires_at=now + LEASE_SECONDS))
        try:
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False
    await session.commit()
    return result.rowcount == 1


async def tick() -> None:
    async with async_sessions()() as session:
        if not await hold_lease(session):
            return
        active = (await session.scalars(
            select(Round).where(Round.status.in_(("open", "running", "verifying"))))).all()
        for r in active:
            moved = (await rounds.lock_if_due(session, r)
                     or await rounds.finish_running_if_done(session, r)
                     or await rounds.finish_verifying_if_done(session, r))
            if moved:
                log.info("scheduler.round_moved", round=r.name, status=r.status)


async def run_forever() -> None:
    log.info("scheduler.started", holder=HOLDER)
    while True:
        try:
            await tick()
        except Exception:
            log.exception("scheduler.tick_failed")
        await asyncio.sleep(TICK)


class SchedulerTask:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(run_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
