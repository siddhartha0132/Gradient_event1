"""WebSocket gateway.

Every state change is a row in the event log. This process tails the log and
forwards each event to its connected clients, so it does not matter which
process wrote the event (API, scheduler or a worker). A client that reconnects
sends the last seq it saw and receives everything it missed, in order.
"""

import asyncio
import contextlib
import time

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.models import EventLog, User
from app.db.session import async_sessions

log = structlog.get_logger()

TAIL_INTERVAL = 0.1
CLOCK_TICK_INTERVAL = 5.0


def can_see(user: User, audience: str) -> bool:
    if audience == "all":
        return True
    if audience == "organisers":
        return user.role in ("organiser", "admin")
    if audience.startswith("team:"):
        return user.team_id == audience[5:] or user.role in ("organiser", "admin")
    return False


def envelope(e: EventLog) -> dict:
    return {"seq": e.seq, "type": e.type, "ts": e.created_at, "payload": e.payload}


class Gateway:
    def __init__(self) -> None:
        self.events: list[EventLog] = []  # the whole log, in seq order (event scale is small)
        self.changed = asyncio.Condition()
        self._task: asyncio.Task | None = None

    @property
    def head(self) -> int:
        return self.events[-1].seq if self.events else 0

    async def start(self) -> None:
        self.events = []
        self.changed = asyncio.Condition()  # bound to the running event loop
        await self._load_new()
        self._task = asyncio.create_task(self._tail())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _load_new(self) -> bool:
        async with async_sessions()() as session:
            rows = (await session.scalars(
                select(EventLog).where(EventLog.seq > self.head).order_by(EventLog.seq))).all()
        self.events.extend(rows)
        return bool(rows)

    async def _tail(self) -> None:
        while True:
            try:
                if await self._load_new():
                    async with self.changed:
                        self.changed.notify_all()
            except Exception:
                log.exception("gateway.tail_failed")
            await asyncio.sleep(TAIL_INTERVAL)

    def _since(self, seq: int) -> list[EventLog]:
        # Binary search would be faster; a linear scan from the end is fine at event scale
        start = len(self.events)
        while start > 0 and self.events[start - 1].seq > seq:
            start -= 1
        return self.events[start:]

    async def serve(self, websocket: WebSocket, user: User, after: int | None) -> None:
        """Send the hello, replay missed events, then stream live events until the client leaves."""
        cursor = self.head if after is None else min(after, self.head)
        await websocket.send_json({"seq": None, "type": "hello", "ts": time.time(),
                                   "payload": {"head": self.head, "replaying_from": cursor}})

        async def pump() -> None:
            nonlocal cursor
            last_tick = 0.0
            while True:
                for e in self._since(cursor):
                    if can_see(user, e.audience):
                        await websocket.send_json(envelope(e))
                    cursor = e.seq
                now = time.time()
                if now - last_tick >= CLOCK_TICK_INTERVAL:
                    await websocket.send_json({"seq": None, "type": "clock.tick", "ts": now,
                                               "payload": {"server_time": now}})
                    last_tick = now
                async with self.changed:
                    if self.head > cursor:  # arrived while we were sending
                        continue
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self.changed.wait(), timeout=CLOCK_TICK_INTERVAL)

        async def drain() -> None:
            while True:  # we only read to notice the disconnect
                await websocket.receive_text()

        tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                    await t


gateway = Gateway()
