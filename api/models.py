from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, HttpUrl


class AnalyzeRequest(BaseModel):
    url: str
    session_count: int = 1
    video_actions: Optional[dict[str, Any]] = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    id: str
    status: str  # pending | running | complete | failed
    url: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class YieldGapDriver(BaseModel):
    factor: str
    their_score: int
    your_score: int
    weight: str


class ReportSummary(BaseModel):
    estimated_yield_gap_drivers: list[YieldGapDriver]


class ImplementationDelta(BaseModel):
    missing_bidders: list[str]
    missing_identity: list[str]
    header_bidding_to_ima: str
    prioritized_actions: list[str]


class Report(BaseModel):
    id: str
    target: str
    captured_at: str
    session_count: int
    session_stats: dict[str, Any]
    summary: ReportSummary
    demand_stack: dict[str, Any]
    identity: dict[str, Any]
    orchestration: dict[str, Any]
    creative: dict[str, Any]
    floor_waterfall: dict[str, Any]
    contextual_signal: dict[str, Any]
    pod_strategy: dict[str, Any]
    floors: dict[str, Any]
    your_implementation_delta: ImplementationDelta
    raw_artifacts: dict[str, Any]
