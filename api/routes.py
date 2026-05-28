from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.models import AnalyzeRequest, JobResponse, JobStatus, Report
from storage.db import JobStore
from storage.artifacts import ArtifactStore

logger = logging.getLogger(__name__)

router = APIRouter()
job_store = JobStore()
artifact_store = ArtifactStore()

# RQ is optional — requires Redis. Falls back to FastAPI BackgroundTasks.
_queue = None
try:
    import redis as _redis_lib
    from rq import Queue as _RQQueue

    _redis_conn = _redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    _redis_conn.ping()  # fail fast if Redis is not running
    _queue = _RQQueue(connection=_redis_conn)
    logger.info("RQ queue connected — jobs will run in worker processes")
except Exception as _rq_err:
    logger.info("Redis not available (%s) — using in-process BackgroundTasks", _rq_err)


async def _run_analysis_background(job_id: str, url: str, session_count: int) -> None:
    """In-process fallback used when RQ is unavailable."""
    from worker.tasks import _run_pipeline
    await _run_pipeline(job_id, url, session_count)


@router.post("/analyze", response_model=JobResponse, status_code=202)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks) -> JobResponse:
    if request.session_count < 5:
        logger.warning(
            "session_count=%d — scores are unreliable below 5 sessions", request.session_count
        )

    job_id = str(uuid.uuid4())
    await job_store.create(job_id, url=request.url, session_count=request.session_count)

    if _queue is not None:
        from worker.tasks import run_analysis_task
        _queue.enqueue(
            run_analysis_task,
            job_id,
            request.url,
            request.session_count,
            job_timeout=1800,
        )
        msg = "Job queued in RQ worker"
    else:
        background_tasks.add_task(_run_analysis_background, job_id, request.url, request.session_count)
        msg = "Job queued (in-process — start a dedicated worker for production)"

    return JobResponse(job_id=job_id, status="pending", message=msg)


@router.get("/report/{job_id}/status", response_model=JobStatus)
async def get_status(job_id: str) -> JobStatus:
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**job)


@router.get("/report/{job_id}", response_model=Report)
async def get_report(job_id: str) -> Report:
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "complete":
        raise HTTPException(status_code=202, detail=f"Job status: {job['status']}")
    report = await artifact_store.load_report(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return Report(**report)
