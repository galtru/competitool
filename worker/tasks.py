"""RQ task definitions — sync wrappers around async analysis pipeline."""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def run_analysis_task(job_id: str, url: str, session_count: int) -> None:
    """Entry point for RQ worker. Runs the full async pipeline synchronously."""
    asyncio.run(_run_pipeline(job_id, url, session_count))


async def _run_pipeline(job_id: str, url: str, session_count: int) -> None:
    from storage.db import JobStore
    from storage.artifacts import ArtifactStore
    from capture.worker import run_capture_session
    from analyzers.prebid import PrebidAnalyzer
    from analyzers.ima import IMAAnalyzer
    from analyzers.identity import IdentityAnalyzer
    from analyzers.vast import VASTAnalyzer
    from analyzers.timing import TimingAnalyzer
    from analyzers.gam_floor_waterfall import GAMFloorWaterfallAnalyzer
    from analyzers.contextual_signal import ContextualSignalAnalyzer
    from report.scorecard import build_scorecard
    from report.delta import build_delta
    from report.renderer import render_report
    from report.aggregator import aggregate_session_stats

    job_store = JobStore()
    artifact_store = ArtifactStore()

    await job_store.update_status(job_id, "running")
    try:
        session_artifacts = []
        for i in range(session_count):
            logger.info("[job %s] Starting session %d/%d", job_id, i + 1, session_count)
            artifacts = await run_capture_session(url, job_id, session_index=i)
            session_artifacts.append(artifacts)
            await artifact_store.save_session(job_id, i, artifacts)

        prebid = PrebidAnalyzer().analyze(session_artifacts)
        ima = IMAAnalyzer().analyze(session_artifacts)
        identity = IdentityAnalyzer().analyze(session_artifacts)
        vast = VASTAnalyzer().analyze(session_artifacts)
        timing = TimingAnalyzer().analyze(session_artifacts)
        floor_waterfall = GAMFloorWaterfallAnalyzer().analyze(session_artifacts)
        contextual = ContextualSignalAnalyzer().analyze(session_artifacts)
        session_stats = aggregate_session_stats(session_artifacts)

        scorecard = build_scorecard(prebid, ima, identity, floor_waterfall, contextual)
        delta = build_delta(prebid, ima, identity)

        report = render_report(
            job_id=job_id,
            url=url,
            session_count=session_count,
            prebid=prebid,
            ima=ima,
            identity=identity,
            vast=vast,
            timing=timing,
            floor_waterfall=floor_waterfall,
            contextual=contextual,
            session_stats=session_stats,
            scorecard=scorecard,
            delta=delta,
            artifact_store=artifact_store,
        )
        await artifact_store.save_report(job_id, report)
        await job_store.update_status(job_id, "complete", report_id=job_id)
        logger.info("[job %s] Complete", job_id)
    except Exception as exc:
        logger.exception("[job %s] Failed: %s", job_id, exc)
        await job_store.update_status(job_id, "failed", error=str(exc))
        raise
