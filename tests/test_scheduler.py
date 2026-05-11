"""Tests for the in-process Scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from ubik.core.scheduler import Scheduler


@pytest.mark.asyncio
async def test_every_seconds_fires() -> None:
    sched = Scheduler()
    fired = []

    async def job():
        fired.append(datetime.now())

    sched.every_seconds(1, job, name="every-1s-test")

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(2.5)  # allow ~2 fires
    sched.stop()
    await asyncio.wait_for(task, timeout=2)

    assert len(fired) >= 1


@pytest.mark.asyncio
async def test_once_in_fires_once_then_drops() -> None:
    sched = Scheduler()
    fired = []

    async def job():
        fired.append("once")

    sched.once_in(0.3, job, name="one-shot")
    task = asyncio.create_task(sched.run())
    await asyncio.sleep(1.5)
    sched.stop()
    await asyncio.wait_for(task, timeout=2)

    assert fired == ["once"]


@pytest.mark.asyncio
async def test_daily_at_validates_format() -> None:
    sched = Scheduler()
    with pytest.raises(ValueError):
        sched.daily_at("not-a-time", lambda: asyncio.sleep(0))


@pytest.mark.asyncio
async def test_daily_at_schedules_for_today_or_tomorrow() -> None:
    """Smoke — verify next_fire_at is in the future and at the requested time."""
    sched = Scheduler()
    sched.daily_at("23:59", lambda: asyncio.sleep(0))
    job = sched._jobs[0]
    assert job.next_fire_at > datetime.now()
    assert job.daily_time.hour == 23 and job.daily_time.minute == 59


@pytest.mark.asyncio
async def test_failing_job_does_not_kill_scheduler() -> None:
    sched = Scheduler()
    fired = []

    async def good():
        fired.append("good")

    async def bad():
        fired.append("bad")
        raise RuntimeError("boom")

    sched.every_seconds(1, bad, name="bad-1s")
    sched.every_seconds(1, good, name="good-1s")

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(2.5)
    sched.stop()
    await asyncio.wait_for(task, timeout=2)

    assert "bad" in fired
    assert "good" in fired
