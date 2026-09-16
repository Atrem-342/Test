from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core import PersonalOperator


DEMO_WEEK = {
    0: [("Morning planning", "Planning", "07:30", "08:00"), ("Demo focus", "Programming", "09:00", "10:00")],
    1: [("Morning walk", "Wellbeing", "07:30", "08:00"), ("Demo study", "English", "18:00", "19:00")],
    2: [("Morning planning", "Planning", "07:30", "08:00"), ("Demo focus", "Programming", "09:00", "10:00")],
    3: [("Morning walk", "Wellbeing", "07:30", "08:00"), ("Demo training", "Training", "17:00", "18:00")],
    4: [("Weekly review", "Planning", "08:00", "08:30"), ("Demo focus", "Programming", "09:00", "10:00")],
    5: [("Demo household block", "Personal", "10:00", "11:00"), ("Demo reading", "Reading", "20:00", "20:30")],
    6: [("Demo recovery walk", "Wellbeing", "10:00", "11:00"), ("Next week preview", "Planning", "19:00", "19:30")],
}


def seed_demo(operator: PersonalOperator) -> None:
    """Load an explicitly non-personal PLACEHOLDER template, idempotently."""
    with operator.db.connect() as con:
        for weekday, blocks in DEMO_WEEK.items():
            for order, (title, category, start, end) in enumerate(blocks):
                con.execute("""INSERT OR IGNORE INTO weekly_template_blocks
                    (weekday,title,category,start_time,end_time,sort_order)
                    VALUES(?,?,?,?,?,?)""", (weekday,title,category,start,end,order))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Personal Operator core demo")
    parser.add_argument("--db", type=Path, default=Path("personal_operator_demo.db"))
    parser.add_argument("--timezone", default="UTC")
    args = parser.parse_args()
    operator = PersonalOperator(args.db, args.timezone)
    seed_demo(operator)
    target = date.today() + timedelta(days=7)
    operator.add_event("DEMO future appointment", target, "14:00", "14:30", "Appointment")
    plan = operator.get_day_plan(target)
    print("DayPlan:")
    for block in plan["blocks"]:
        print(f"  {block['id']}: {block['planned_start']} {block['title']} [{block['status']}]")
    block = plan["blocks"][0]
    start = datetime.fromisoformat(block["planned_start"])
    operator.start_block(block["id"], start)
    operator.finish_block(block["id"], start + timedelta(minutes=25))
    print("Stats:", operator.get_activity_stats(block["category"], target, target))


if __name__ == "__main__":
    main()

