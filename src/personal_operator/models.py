from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class BlockStatus(StrEnum):
    PLANNED = "PLANNED"
    WAITING_START = "WAITING_START"
    ACTIVE = "ACTIVE"
    WRAPUP = "WRAPUP"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class DayMode(StrEnum):
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"
    RECOVERY = "RECOVERY"


class ProposalAction(StrEnum):
    ADD_BLOCK = "ADD_BLOCK"
    CANCEL_BLOCK = "CANCEL_BLOCK"
    RESCHEDULE_BLOCK = "RESCHEDULE_BLOCK"
    SUSPEND_DAY = "SUSPEND_DAY"


@dataclass(frozen=True)
class ScheduleChangeProposal:
    """Untrusted interpretation; execute only after the caller confirms it."""

    action: ProposalAction
    arguments: dict[str, Any]
    confirmed: bool = False


@dataclass(frozen=True)
class ActivityStats:
    planned: int
    completed: int
    skipped: int
    cancelled: int
    total_actual_minutes: float
    average_actual_duration: float | None
    average_start_delay: float | None


@dataclass(frozen=True)
class EndWorkflow:
    """Extension point; prompts/answer processing deliberately live outside core."""

    category: str
    prompt: str = "[END_OF_BLOCK_PROMPT_PLACEHOLDER]"

