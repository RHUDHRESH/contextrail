"""Domain models (CLAUDE.md §7). Pydantic v2 at every boundary.

The models carry principles, not just shapes:
- P1 relevance is not identity: `Subject.source_id` must look like a system-of-record ID, not a name.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


EmploymentType = Literal["employee", "contractor", "vendor", "customer"]


class Subject(_Model):
    """The person (or customer) a run is about. Fetched by ID from a system of record, never chosen by search."""

    source: Literal["freshservice", "hris", "freshdesk"]
    source_id: str = Field(min_length=1, max_length=64)
    display_name: str
    employment_type: EmploymentType
    role: str | None = None
    team: str | None = None
    seniority: Literal["junior", "mid", "senior", "lead", "principal"] | None = None
    manager_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    sow_repos: list[str] = Field(default_factory=list)

    @field_validator("source_id")
    @classmethod
    def _looks_like_an_id(cls, v: str) -> str:
        # A name ("Anil Kumar") has whitespace; an ID ("W-8841", "50001234") does not. This cannot prove the value
        # came from an exact lookup, but it stops the commonest failure: a display name passed as the subject.
        if any(ch.isspace() for ch in v):
            raise ValueError("source_id must be a system-of-record ID, not a name (P1: relevance is not identity)")
        return v
