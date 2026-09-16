from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from personal_operator import BlockStatus, PersonalOperator
from personal_operator.demo import seed_demo


@pytest.fixture
def op(tmp_path):
    operator = PersonalOperator(tmp_path / "test.db", "Europe/Berlin")
    seed_demo(operator)
    return operator


def test_initialization_and_persistence(op):
    with op.db.connect() as con:
        assert con.execute("SELECT value FROM settings WHERE key='timezone'").fetchone()[0] == "Europe/Berlin"
    reopened = PersonalOperator(op.db.path, "Europe/Berlin")
    assert reopened.db.path == op.db.path


def test_template_and_event_materialize_once_as_snapshot(op):
    day = date(2026, 9, 20)  # Sunday
    op.add_event("Doctor", day, "15:00", "15:30", "Doctor")
    first = op.get_day_plan(day)
    assert {b["source"] for b in first["blocks"]} == {"TEMPLATE", "FUTURE_EVENT"}
    assert any(b["title"] == "Doctor" for b in first["blocks"])
    op.add_template_block(day.weekday(), "Late addition", "Test", "21:00", "21:30")
    second = op.get_day_plan(day)
    assert second["id"] == first["id"]
    assert len(second["blocks"]) == len(first["blocks"])
    with op.db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM day_plans WHERE plan_date=?", (day.isoformat(),)).fetchone()[0] == 1


def test_day_change_does_not_change_template(op):
    day = date(2026, 9, 20)
    block = op.get_day_plan(day)["blocks"][0]
    template_start = None
    with op.db.connect() as con:
        template_start = con.execute("SELECT start_time FROM weekly_template_blocks WHERE id=?", (block["source_template_id"],)).fetchone()[0]
    op.reschedule_block(block["id"], datetime(2026,9,20,18,tzinfo=timezone.utc), datetime(2026,9,20,19,tzinfo=timezone.utc))
    with op.db.connect() as con:
        assert con.execute("SELECT start_time FROM weekly_template_blocks WHERE id=?", (block["source_template_id"],)).fetchone()[0] == template_start


def test_start_finish_invalid_transitions_and_stats(op):
    day = date(2026, 9, 21)
    block = op.get_day_plan(day)["blocks"][0]
    planned = datetime.fromisoformat(block["planned_start"])
    op.start_block(block["id"], planned + timedelta(minutes=5))
    op.finish_block(block["id"], planned + timedelta(minutes=35))
    updated = op.get_day_plan(day)["blocks"][0]
    assert updated["status"] == BlockStatus.DONE
    assert updated["actual_start"] and updated["actual_end"]
    with pytest.raises(ValueError): op.start_block(block["id"], planned)
    stats = op.get_activity_stats(block["category"], day, day)
    assert stats.completed == 1
    assert stats.total_actual_minutes == pytest.approx(30, abs=.01)
    assert stats.average_start_delay == pytest.approx(5, abs=.01)


def test_cancel_reschedule_and_interval_validation(op):
    blocks = op.get_day_plan(date(2026,9,22))["blocks"]
    op.cancel_block(blocks[0]["id"])
    with pytest.raises(ValueError): op.finish_block(blocks[0]["id"], datetime.now(timezone.utc))
    start = datetime(2026,9,22,18,tzinfo=timezone.utc)
    op.reschedule_block(blocks[1]["id"], start, start + timedelta(hours=1))
    assert op.get_day_plan(date(2026,9,22))["blocks"][1]["status"] == BlockStatus.RESCHEDULED
    with pytest.raises(ValueError): op.add_event("bad", date(2026,9,22), "12:00", "11:00")


def test_scheduled_events_are_persistent_and_idempotent(op):
    now = datetime.now(timezone.utc)
    first = op.schedule_event(now, "START_REMINDER", idempotency_key="unique-reminder")
    second = op.schedule_event(now, "START_REMINDER", idempotency_key="unique-reminder")
    assert first == second
    assert len(op.get_due_events(now + timedelta(seconds=1))) == 1
    assert op.mark_event_executed(first, now)
    assert not op.mark_event_executed(first, now)
    assert op.get_due_events(now + timedelta(seconds=1)) == []


def test_timezone_sensitive_today_and_current_block(op):
    # 22:45 UTC is already the next calendar day in Berlin (summer time).
    local_day = date(2026, 6, 2)
    op.add_template_block(local_day.weekday(), "Midnight work", "Night", "00:30", "01:30")
    instant = datetime(2026,6,1,22,45,tzinfo=timezone.utc)
    assert op.get_today(instant)["date"] == local_day.isoformat()
    assert op.get_current_block(instant)["title"] == "Midnight work"


def test_suspend_day_cancels_remaining_blocks_and_reminders(op):
    day = date(2026,9,23)
    plan = op.get_day_plan(day)
    block_id = plan["blocks"][0]["id"]
    event_id = op.schedule_event(datetime(2026,9,23,5,tzinfo=timezone.utc), "PREWARN", block_id)
    op.suspend_day(day, datetime(2026,9,23,4,tzinfo=timezone.utc))
    result = op.get_day_plan(day)
    assert result["suspended_at"] is not None
    assert all(b["status"] == BlockStatus.CANCELLED for b in result["blocks"])
    with op.db.connect() as con:
        assert con.execute("SELECT status FROM scheduled_events WHERE id=?", (event_id,)).fetchone()[0] == "CANCELLED"

