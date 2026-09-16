from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database
from .models import ActivityStats, BlockStatus, DayMode, ScheduleChangeProposal


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="seconds")


class PersonalOperator:
    """Deterministic application service; suitable for CLI, API, or Hermes tools."""

    def __init__(self, db_path: str | Path, timezone_name: str = "UTC"):
        self.db = Database(db_path)
        self.zone = ZoneInfo(timezone_name)
        self.db.initialize(timezone_name)
        with self.db.connect() as con:
            stored = con.execute("SELECT value FROM settings WHERE key='timezone'").fetchone()[0]
        if stored != timezone_name:
            raise ValueError(f"database timezone is {stored!r}, not {timezone_name!r}")

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _instant(self, day: date, clock: str) -> str:
        parsed = time.fromisoformat(clock)
        return _iso(datetime.combine(day, parsed, self.zone))

    def add_template_block(self, weekday: int, title: str, category: str,
                           start_time: str, end_time: str | None = None,
                           sort_order: int = 0, end_prompt: str | None = None) -> int:
        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be 0..6")
        if end_time and time.fromisoformat(end_time) <= time.fromisoformat(start_time):
            raise ValueError("end_time must be after start_time")
        with self.db.connect() as con:
            cur = con.execute("""INSERT INTO weekly_template_blocks
                (weekday,title,category,start_time,end_time,sort_order,end_prompt)
                VALUES(?,?,?,?,?,?,?)""",
                (weekday, title, category, start_time, end_time, sort_order, end_prompt))
            return cur.lastrowid

    def add_event(self, title: str, event_date: date, start_time: str,
                  end_time: str | None = None, category: str = "Event") -> int:
        if end_time and time.fromisoformat(end_time) <= time.fromisoformat(start_time):
            raise ValueError("event end must be after start")
        now = _iso(self._now())
        with self.db.connect() as con:
            cur = con.execute("""INSERT INTO future_events
                (title,event_date,start_time,end_time,category,created_at)
                VALUES(?,?,?,?,?,?)""", (title, event_date.isoformat(), start_time, end_time, category, now))
            return cur.lastrowid

    def get_day_plan(self, plan_date: date) -> dict[str, Any]:
        """Get or atomically materialize an immutable-from-sources snapshot."""
        now = _iso(self._now())
        with self.db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM day_plans WHERE plan_date=?", (plan_date.isoformat(),)).fetchone()
            if row is None:
                cur = con.execute("INSERT INTO day_plans(plan_date,mode,created_at) VALUES(?,?,?)",
                                  (plan_date.isoformat(), DayMode.NORMAL, now))
                plan_id = cur.lastrowid
                templates = con.execute("SELECT * FROM weekly_template_blocks WHERE weekday=? ORDER BY sort_order,start_time", (plan_date.weekday(),)).fetchall()
                for item in templates:
                    self._insert_block(con, plan_id, item["title"], item["category"],
                                       self._instant(plan_date, item["start_time"]),
                                       self._instant(plan_date, item["end_time"]) if item["end_time"] else None,
                                       "TEMPLATE", now, source_template_id=item["id"])
                events = con.execute("SELECT * FROM future_events WHERE event_date=? AND status='PLANNED' ORDER BY start_time", (plan_date.isoformat(),)).fetchall()
                for item in events:
                    self._insert_block(con, plan_id, item["title"], item["category"],
                                       self._instant(plan_date, item["start_time"]),
                                       self._instant(plan_date, item["end_time"]) if item["end_time"] else None,
                                       "FUTURE_EVENT", now, source_event_id=item["id"])
                row = con.execute("SELECT * FROM day_plans WHERE id=?", (plan_id,)).fetchone()
            blocks = con.execute("SELECT * FROM blocks WHERE day_plan_id=? ORDER BY planned_start,id", (row["id"],)).fetchall()
            return {"id": row["id"], "date": row["plan_date"], "mode": row["mode"],
                    "suspended_at": row["suspended_at"], "blocks": [dict(block) for block in blocks]}

    def _insert_block(self, con: Any, plan_id: int, title: str, category: str,
                      start: str, end: str | None, source: str, now: str,
                      source_template_id: int | None = None, source_event_id: int | None = None) -> int:
        if end and end <= start:
            raise ValueError("planned end must be after start")
        cur = con.execute("""INSERT INTO blocks
            (day_plan_id,title,category,planned_start,planned_end,status,source,
             source_template_id,source_event_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (plan_id,title,category,start,end,BlockStatus.PLANNED,source,
             source_template_id,source_event_id,now,now))
        return cur.lastrowid

    def add_block(self, plan_date: date, title: str, category: str,
                  planned_start: datetime, planned_end: datetime | None = None) -> int:
        plan = self.get_day_plan(plan_date)
        start = _iso(planned_start); end = _iso(planned_end) if planned_end else None
        if planned_start.astimezone(self.zone).date() != plan_date:
            raise ValueError("block start is outside day plan date")
        now = _iso(self._now())
        with self.db.connect() as con:
            return self._insert_block(con, plan["id"], title, category, start, end, "MANUAL", now)

    def get_today(self, now: datetime | None = None) -> dict[str, Any]:
        instant = now or self._now()
        return self.get_day_plan(_utc(instant).astimezone(self.zone).date())

    def get_current_block(self, at: datetime) -> dict[str, Any] | None:
        plan = self.get_today(at); stamp = _iso(at)
        candidates = [b for b in plan["blocks"] if b["status"] not in {BlockStatus.CANCELLED, BlockStatus.SKIPPED, BlockStatus.DONE} and b["planned_start"] <= stamp and (b["planned_end"] is None or stamp < b["planned_end"])]
        return candidates[-1] if candidates else None

    def get_next_block(self, at: datetime) -> dict[str, Any] | None:
        plan = self.get_today(at); stamp = _iso(at)
        return next((b for b in plan["blocks"] if b["planned_start"] > stamp and b["status"] not in {BlockStatus.CANCELLED, BlockStatus.SKIPPED}), None)

    def _transition(self, block_id: int, allowed: set[BlockStatus], target: BlockStatus,
                    field: str | None = None, at: datetime | None = None) -> None:
        now = _iso(at or self._now())
        with self.db.connect() as con:
            block = con.execute("SELECT * FROM blocks WHERE id=?", (block_id,)).fetchone()
            if block is None: raise KeyError(block_id)
            if BlockStatus(block["status"]) not in allowed:
                raise ValueError(f"cannot transition {block['status']} to {target}")
            assignments = "status=?, updated_at=?" + (f", {field}=?" if field else "")
            values: list[Any] = [target, now]
            if field: values.append(now)
            values.append(block_id)
            con.execute(f"UPDATE blocks SET {assignments} WHERE id=?", values)
            self._audit(con, f"BLOCK_{target}", block_id, block["day_plan_id"], now)

    def start_block(self, block_id: int, actual_time: datetime) -> None:
        self._transition(block_id, {BlockStatus.PLANNED, BlockStatus.WAITING_START}, BlockStatus.ACTIVE, "actual_start", actual_time)

    def finish_block(self, block_id: int, actual_time: datetime) -> None:
        with self.db.connect() as con:
            row = con.execute("SELECT actual_start FROM blocks WHERE id=?", (block_id,)).fetchone()
        if row is None: raise KeyError(block_id)
        if row["actual_start"] and _iso(actual_time) < row["actual_start"]:
            raise ValueError("actual end cannot precede actual start")
        self._transition(block_id, {BlockStatus.ACTIVE, BlockStatus.WRAPUP}, BlockStatus.DONE, "actual_end", actual_time)

    def skip_block(self, block_id: int) -> None:
        self._transition(block_id, {BlockStatus.PLANNED, BlockStatus.WAITING_START}, BlockStatus.SKIPPED)

    def cancel_block(self, block_id: int) -> None:
        self._transition(block_id, {BlockStatus.PLANNED, BlockStatus.WAITING_START}, BlockStatus.CANCELLED)
        self._cancel_reminders(block_id)

    def reschedule_block(self, block_id: int, new_start: datetime, new_end: datetime | None) -> None:
        start = _iso(new_start); end = _iso(new_end) if new_end else None
        if end and end <= start: raise ValueError("new end must be after new start")
        now = _iso(self._now())
        with self.db.connect() as con:
            row = con.execute("SELECT * FROM blocks WHERE id=?", (block_id,)).fetchone()
            if row is None: raise KeyError(block_id)
            if BlockStatus(row["status"]) not in {BlockStatus.PLANNED, BlockStatus.WAITING_START}:
                raise ValueError("only unstarted blocks can be rescheduled")
            con.execute("UPDATE blocks SET planned_start=?,planned_end=?,status=?,updated_at=? WHERE id=?",
                        (start,end,BlockStatus.RESCHEDULED,now,block_id))
            self._audit(con,"BLOCK_RESCHEDULED",block_id,row["day_plan_id"],now,{"new_start":start,"new_end":end})

    def suspend_day(self, plan_date: date, at: datetime | None = None) -> None:
        plan = self.get_day_plan(plan_date); now = _iso(at or self._now())
        with self.db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM blocks WHERE day_plan_id=? AND status IN ('PLANNED','WAITING_START')", (plan["id"],))]
            con.execute("UPDATE day_plans SET suspended_at=? WHERE id=?", (now,plan["id"]))
            if ids:
                marks = ",".join("?" for _ in ids)
                con.execute(f"UPDATE blocks SET status='CANCELLED',updated_at=? WHERE id IN ({marks})", [now,*ids])
                con.execute(f"UPDATE scheduled_events SET status='CANCELLED' WHERE status='PENDING' AND block_id IN ({marks})", ids)
            self._audit(con,"DAY_SUSPENDED",None,plan["id"],now)

    def _audit(self, con: Any, event_type: str, block_id: int | None, plan_id: int | None,
               timestamp: str, payload: dict[str, Any] | None = None) -> None:
        con.execute("INSERT INTO audit_events(timestamp,event_type,block_id,day_plan_id,payload) VALUES(?,?,?,?,?)",
                    (timestamp,event_type,block_id,plan_id,json.dumps(payload) if payload else None))

    def get_activity_stats(self, category: str, start_date: date, end_date: date) -> ActivityStats:
        with self.db.connect() as con:
            row = con.execute("""SELECT COUNT(*) planned,
              SUM(status='DONE') completed, SUM(status='SKIPPED') skipped, SUM(status='CANCELLED') cancelled,
              SUM(CASE WHEN actual_start IS NOT NULL AND actual_end IS NOT NULL THEN (julianday(actual_end)-julianday(actual_start))*1440 END) total_minutes,
              AVG(CASE WHEN actual_start IS NOT NULL AND actual_end IS NOT NULL THEN (julianday(actual_end)-julianday(actual_start))*1440 END) avg_duration,
              AVG(CASE WHEN actual_start IS NOT NULL THEN (julianday(actual_start)-julianday(planned_start))*1440 END) avg_delay
              FROM blocks b JOIN day_plans d ON d.id=b.day_plan_id
              WHERE b.category=? AND d.plan_date BETWEEN ? AND ?""",
              (category,start_date.isoformat(),end_date.isoformat())).fetchone()
        return ActivityStats(row["planned"],row["completed"] or 0,row["skipped"] or 0,row["cancelled"] or 0,
                             round(row["total_minutes"] or 0, 3),
                             round(row["avg_duration"],3) if row["avg_duration"] is not None else None,
                             round(row["avg_delay"],3) if row["avg_delay"] is not None else None)

    def schedule_event(self, execute_at: datetime, event_type: str, block_id: int | None = None,
                       payload: dict[str, Any] | None = None, idempotency_key: str | None = None) -> int:
        with self.db.connect() as con:
            try:
                cur = con.execute("INSERT INTO scheduled_events(execute_at,event_type,block_id,payload,idempotency_key) VALUES(?,?,?,?,?)",
                                  (_iso(execute_at),event_type,block_id,json.dumps(payload) if payload else None,idempotency_key))
                return cur.lastrowid
            except sqlite3.IntegrityError:
                if not idempotency_key: raise
                return con.execute("SELECT id FROM scheduled_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()[0]

    def get_due_events(self, now: datetime) -> list[dict[str, Any]]:
        with self.db.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM scheduled_events WHERE status='PENDING' AND execute_at<=? ORDER BY execute_at,id", (_iso(now),))]

    def mark_event_executed(self, event_id: int, at: datetime | None = None) -> bool:
        with self.db.connect() as con:
            cur = con.execute("UPDATE scheduled_events SET status='EXECUTED',executed_at=?,attempts=attempts+1 WHERE id=? AND status='PENDING'", (_iso(at or self._now()),event_id))
            return cur.rowcount == 1

    def mark_event_failed(self, event_id: int, error: str) -> bool:
        with self.db.connect() as con:
            cur = con.execute("UPDATE scheduled_events SET status='FAILED',attempts=attempts+1,last_error=? WHERE id=? AND status='PENDING'", (error,event_id))
            return cur.rowcount == 1

    def _cancel_reminders(self, block_id: int) -> None:
        with self.db.connect() as con:
            con.execute("UPDATE scheduled_events SET status='CANCELLED' WHERE block_id=? AND status='PENDING'", (block_id,))

    def apply_confirmed(self, proposal: ScheduleChangeProposal) -> None:
        if not proposal.confirmed:
            raise PermissionError("schedule change requires confirmation")
        handler = getattr(self, proposal.action.value.lower(), None)
        if handler is None: raise ValueError(f"unsupported action {proposal.action}")
        handler(**proposal.arguments)
