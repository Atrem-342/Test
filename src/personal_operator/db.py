from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_template_blocks (
  id INTEGER PRIMARY KEY, weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
  title TEXT NOT NULL, category TEXT NOT NULL, start_time TEXT NOT NULL,
  end_time TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
  end_prompt TEXT, UNIQUE(weekday, start_time, title)
);
CREATE TABLE IF NOT EXISTS future_events (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, event_date TEXT NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT, category TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PLANNED', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS day_plans (
  id INTEGER PRIMARY KEY, plan_date TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL DEFAULT 'NORMAL', suspended_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY, day_plan_id INTEGER NOT NULL REFERENCES day_plans(id),
  title TEXT NOT NULL, category TEXT NOT NULL, planned_start TEXT NOT NULL,
  planned_end TEXT, actual_start TEXT, actual_end TEXT,
  status TEXT NOT NULL, snooze_count INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL, source_template_id INTEGER,
  source_event_id INTEGER, notes TEXT, continuation TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(day_plan_id, source_event_id)
);
CREATE INDEX IF NOT EXISTS blocks_plan_time ON blocks(day_plan_id, planned_start);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
  block_id INTEGER REFERENCES blocks(id), day_plan_id INTEGER REFERENCES day_plans(id),
  payload TEXT
);
CREATE TABLE IF NOT EXISTS scheduled_events (
  id INTEGER PRIMARY KEY, execute_at TEXT NOT NULL, event_type TEXT NOT NULL,
  block_id INTEGER REFERENCES blocks(id), payload TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
  executed_at TEXT, last_error TEXT,
  idempotency_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS scheduled_due ON scheduled_events(status, execute_at);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self, timezone: str) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('timezone', ?)",
                (timezone,),
            )

