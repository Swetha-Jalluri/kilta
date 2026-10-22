"""API request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TurnRequest(BaseModel):
    member_id: str | None = Field(default=None, description="priya or lucia")
    text: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, description="Overrides the member's language")


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    refused: bool = False
    reason: str | None = None
    state: str | None = None
    session_id: str | None = None
    say: str | None = None
    ms: int = 0
    error: str | None = None


class TurnResponse(BaseModel):
    speech: str
    card: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    state: str | None = None
    session_id: str | None = None
    member_id: str | None = None
    language: str = "en"
    model: str | None = None
    fallbacks: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
