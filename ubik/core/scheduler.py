"""
Tiny in-process scheduler — daily / hourly / interval triggers.

We don't need APScheduler / Celery / Quartz for our cadence. Three
shapes cover everything Ubik schedules:

  • daily_at("09:00", coro)        — once per local day
  • every_minutes(60, coro)        — fixed interval (pulse loop)
  • every_seconds(N, coro)         — for tests
  • once_in(seconds, coro)         — one-shot delay

The Scheduler runs as an asyncio task in the daemon main loop. It's
intentionally simple: each job is a coroutine, scheduler awaits each
job sequentially per cycle (so jobs don't overlap themselves). If you
need parallel execution, schedule them on different timers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

logger = logging.getLogger(__name__)

JobCoro = Callable[[], Awaitable[Any]]


@dataclass(slots=True)
class _Job:
    name: str
    next_fire_at: datetime
    period_seconds: float | None
    """None means daily-at-time (recompute by calendar)."""
    daily_time: time | None
    coro_factory: JobCoro
    """Awaitable factory; we call it on each fire."""

    inflight: bool = False


class Scheduler:
    """Cooperative scheduler for daemon-mode Ubik."""

    def __init__(self) -> None:
        self._jobs: list[_Job] = []
        self._stop = asyncio.Event()

    # ── registration ────────────────────────────────────────────────────

    def daily_at(self, hhmm: str, coro_factory: JobCoro, *, name: str | None = None) -> None:
        """Run `coro_factory()` once per day at local `HH:MM`."""
        try:
            t = datetime.strptime(hhmm, "%H:%M").time()
        except ValueError as e:
            raise ValueError(f"daily_at expects 'HH:MM', got {hhmm!r}") from e

        next_fire = self._next_daily(t)
        self._jobs.append(
            _Job(
                name=name or f"daily@{hhmm}",
                next_fire_at=next_fire,
                period_seconds=None,
                daily_time=t,
                coro_factory=coro_factory,
            )
        )
        logger.info(
            "Scheduler: daily_at %s registered (next fire: %s)", hhmm, next_fire.isoformat()
        )

    def every_minutes(self, n: int, coro_factory: JobCoro, *, name: str | None = None) -> None:
        if n <= 0:
            raise ValueError("every_minutes needs n > 0")
        self._every_seconds(n * 60, coro_factory, name=name or f"every-{n}min")

    def every_seconds(self, n: int, coro_factory: JobCoro, *, name: str | None = None) -> None:
        if n <= 0:
            raise ValueError("every_seconds needs n > 0")
        self._every_seconds(n, coro_factory, name=name or f"every-{n}s")

    def once_in(self, seconds: float, coro_factory: JobCoro, *, name: str | None = None) -> None:
        next_fire = datetime.now() + timedelta(seconds=seconds)
        self._jobs.append(
            _Job(
                name=name or f"once-in-{seconds:.0f}s",
                next_fire_at=next_fire,
                period_seconds=None,
                daily_time=None,
                coro_factory=coro_factory,
            )
        )

    def _every_seconds(self, n: float, coro: JobCoro, *, name: str) -> None:
        next_fire = datetime.now() + timedelta(seconds=n)
        self._jobs.append(
            _Job(
                name=name,
                next_fire_at=next_fire,
                period_seconds=n,
                daily_time=None,
                coro_factory=coro,
            )
        )
        logger.info("Scheduler: %s registered (next fire: %s)", name, next_fire.isoformat())

    # ── runtime ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Loop forever. Cancel by calling `.stop()` or the task itself."""
        try:
            while not self._stop.is_set():
                if not self._jobs:
                    # Wait for stop or 60s, whichever comes first.
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=60)
                    except asyncio.TimeoutError:
                        pass
                    continue

                now = datetime.now()
                next_job = min(self._jobs, key=lambda j: j.next_fire_at)
                wait = (next_job.next_fire_at - now).total_seconds()
                if wait > 0:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        pass
                    if self._stop.is_set():
                        break

                # Fire if time has come
                now = datetime.now()
                if next_job.next_fire_at <= now and not next_job.inflight:
                    await self._fire(next_job)
        except asyncio.CancelledError:
            logger.info("Scheduler cancelled")
            raise

    def stop(self) -> None:
        self._stop.set()

    # ── internals ───────────────────────────────────────────────────────

    async def _fire(self, job: _Job) -> None:
        job.inflight = True
        try:
            logger.info("Scheduler: firing %s", job.name)
            await job.coro_factory()
        except Exception as e:
            logger.error("Scheduler job %s raised: %s", job.name, e, exc_info=True)
        finally:
            job.inflight = False
            # Recompute next_fire_at
            if job.period_seconds is not None:
                job.next_fire_at = datetime.now() + timedelta(seconds=job.period_seconds)
            elif job.daily_time is not None:
                job.next_fire_at = self._next_daily(job.daily_time)
            else:
                # one-shot — drop it
                self._jobs.remove(job)

    @staticmethod
    def _next_daily(t: time) -> datetime:
        """Next occurrence of HH:MM in local time. Today if still in the future, else tomorrow."""
        now = datetime.now()
        today_at = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if today_at > now:
            return today_at
        return today_at + timedelta(days=1)
