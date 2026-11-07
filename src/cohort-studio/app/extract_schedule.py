"""Scheduled extract refresh.

A schedule (Off, Hourly at :MM, Daily at HH:MM, Weekly on a day at HH:MM) is
stored with the extract in ``public._studio_extracts``, together with the IANA
time zone it was set in. ``next_run_at`` is stored in UTC and always computed
from the current time, so a run missed while the app was stopped becomes one
catch-up run, not a backlog.

``Scheduler.tick`` finds due extracts in every Aurora/PostgreSQL resource,
claims each with a conditional UPDATE (only one app process wins) and submits
the normal refresh data job. Schedules run only while the app is running.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import extracts

logger = logging.getLogger(__name__)

RETRY_BUSY = timedelta(minutes=5)
LOST_AFTER = timedelta(minutes=15)
RESOURCE_BACKOFF_S = 600.0
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class ExtractSchedule(BaseModel):
    """When to refresh. ``weekday`` is 0 (Monday) to 6 (Sunday)."""
    model_config = ConfigDict(extra="forbid")
    every: Literal["off", "hourly", "daily", "weekly"]
    minute: int = Field(default=0, ge=0, le=59)
    hour: int | None = Field(default=None, ge=0, le=23)
    weekday: int | None = Field(default=None, ge=0, le=6)
    tz: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("tz")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _fields(self):
        if self.every in ("daily", "weekly") and self.hour is None:
            raise ValueError(f"A {self.every} schedule needs an hour")
        if self.every == "weekly" and self.weekday is None:
            raise ValueError("A weekly schedule needs a weekday")
        if self.every == "hourly" and self.hour is not None:
            raise ValueError("An hourly schedule takes a minute, not an hour")
        if self.every != "weekly" and self.weekday is not None:
            raise ValueError("Only a weekly schedule takes a weekday")
        return self

    def stored(self) -> dict | None:
        if self.every == "off":
            return None
        return self.model_dump(exclude_none=True)


def next_run(schedule: dict, after: datetime) -> datetime:
    """The first run strictly after ``after`` (aware), in UTC."""
    s = ExtractSchedule.model_validate(schedule)
    zone = ZoneInfo(s.tz)
    after = after.astimezone(timezone.utc)
    local = after.astimezone(zone)
    if s.every == "hourly":
        at = local.replace(minute=s.minute, second=0, microsecond=0).astimezone(timezone.utc)
        return at if at > after else at + timedelta(hours=1)

    def at_day(day: date) -> datetime:
        return datetime.combine(day, time(s.hour, s.minute), zone).astimezone(timezone.utc)
    step = 1 if s.every == "daily" else 7
    day = local.date()
    if s.every == "weekly":
        day += timedelta(days=(s.weekday - day.weekday()) % 7)
    while at_day(day) <= after:
        day += timedelta(days=step)
    return at_day(day)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scheduler:
    """Checks due schedules every ``interval`` seconds.

    ``submit(resource_id, table, on_done)`` starts the refresh job and raises
    ``data_jobs.Busy`` when admission refuses it; the job calls
    ``on_done()`` when it ends. ``clock`` and ``tick(now)`` make it testable.
    """

    def __init__(self, submit: Callable, resources: Callable[[], list[str]],
                 clock: Callable[[], datetime] = _utcnow, interval: float = 60.0):
        self.submit = submit
        self.resources = resources
        self.clock = clock
        self.interval = interval
        self.pending: set[tuple[str, str]] = set()
        self.backoff: dict[str, float] = {}
        self.lock = threading.Lock()
        self.task: asyncio.Task | None = None

    def _done(self, key):
        with self.lock:
            self.pending.discard(key)

    def tick(self, now: datetime | None = None) -> list[tuple[str, str, str]]:
        """Submit every due refresh once; returns (resource, table, outcome)."""
        now = now or self.clock()
        outcomes = []
        for resource_id in self.resources():
            if self.backoff.get(resource_id, 0) > _time.monotonic():
                continue
            try:
                rows = extracts.due(resource_id, now)
            except Exception as exc:
                self.backoff[resource_id] = _time.monotonic() + RESOURCE_BACKOFF_S
                logger.warning("Extract schedules: can't read %s (%s); retrying in %d min",
                               resource_id, str(exc).split("\n")[0][:200],
                               RESOURCE_BACKOFF_S // 60)
                continue
            self.backoff.pop(resource_id, None)
            self._recover_lost(resource_id, now)
            for row in rows:
                try:
                    outcomes.append((resource_id, row["table"], self._run_one(resource_id, row, now)))
                except Exception:
                    logger.warning("Extract schedules: could not start %s in %s", row["table"],
                                   resource_id, exc_info=True)
        return outcomes

    def _recover_lost(self, resource_id: str, now: datetime) -> None:
        """A run marked running that no process is doing (the app was killed
        mid-run) is due again now. Recent ones may still be queued elsewhere."""
        try:
            for table, started in extracts.started_before(resource_id, now - LOST_AFTER):
                with self.lock:
                    queued = (resource_id, table) in self.pending
                if not queued:
                    extracts.recover_lost(resource_id, table, started, now)
        except Exception:
            logger.warning("Extract schedules: could not check lost runs in %s", resource_id,
                           exc_info=True)

    def _run_one(self, resource_id: str, row: dict, now: datetime) -> str:
        import data_jobs
        table, key = row["table"], (resource_id, row["table"])
        upcoming = next_run(row["schedule"], now)
        with self.lock:
            busy = key in self.pending
        if busy or extracts.refresh_running(resource_id, table):
            if extracts.claim(resource_id, table, row["next_run_at"], upcoming, now):
                extracts.record_run(resource_id, table, "skipped",
                                    "A refresh was already running.", now)
            return "skipped"
        if not extracts.claim(resource_id, table, row["next_run_at"], upcoming, now):
            return "claimed elsewhere"
        with self.lock:
            self.pending.add(key)
        try:
            self.submit(resource_id, table, lambda: self._done(key))
        except data_jobs.Busy as exc:
            self._done(key)
            extracts.record_run(resource_id, table, "skipped", str(exc), now,
                                retry_at=now + RETRY_BUSY)
            return "busy"
        except Exception as exc:
            self._done(key)
            extracts.record_run(resource_id, table, "failed", str(exc).split("\n")[0][:300], now)
            return "failed"
        return "submitted"

    def recover_pending(self) -> None:
        """After data jobs shut down: jobs cancelled before they started never
        reported back, so make their extracts due again for the next start."""
        with self.lock:
            keys, self.pending = list(self.pending), set()
        now = self.clock()
        for resource_id, table in keys:
            try:
                extracts.record_run(resource_id, table, "failed", "Stopped before it started.",
                                    now, retry_at=now)
            except Exception:
                logger.warning("Could not reschedule %s in %s", table, resource_id, exc_info=True)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                logger.exception("Extract schedule check failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self) -> None:
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def enabled() -> bool:
    return os.environ.get("STUDIO_EXTRACT_SCHEDULER", "on").strip().lower() not in (
        "0", "off", "false", "no")
