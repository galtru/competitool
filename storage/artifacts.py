"""Local-disk artifact storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ArtifactStore:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or os.getenv("ARTIFACT_DIR", "./artifacts"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        d = self.base_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def har_path(self, job_id: str, session_index: int) -> str:
        return str(self._job_dir(job_id) / f"session_{session_index:03d}.har")

    def console_path(self, job_id: str, session_index: int) -> str:
        return str(self._job_dir(job_id) / f"session_{session_index:03d}_console.jsonl")

    async def save_session(self, job_id: str, session_index: int, artifacts: dict[str, Any]) -> None:
        d = self._job_dir(job_id)

        # Save HAR
        if artifacts.get("har"):
            with open(d / f"session_{session_index:03d}.har", "w") as f:
                json.dump(artifacts["har"], f)

        # Save console log
        console = artifacts.get("console_log", [])
        if console:
            with open(d / f"session_{session_index:03d}_console.jsonl", "w") as f:
                for line in console:
                    f.write(json.dumps(line) + "\n")

        # Save globals snapshots
        snaps = artifacts.get("globals_snapshots", [])
        if snaps:
            with open(d / f"session_{session_index:03d}_globals.json", "w") as f:
                json.dump(snaps, f, indent=2)

        # Save screenshots
        for name, data in artifacts.get("screenshots", {}).items():
            if data:
                with open(d / f"session_{session_index:03d}_{name}.png", "wb") as f:
                    f.write(data)

        # Save session metadata (without large blobs)
        meta = {k: v for k, v in artifacts.items() if k not in ("har", "screenshots", "console_log", "globals_snapshots", "network_requests")}
        with open(d / f"session_{session_index:03d}_meta.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

    async def save_report(self, job_id: str, report: dict[str, Any]) -> None:
        d = self._job_dir(job_id)
        with open(d / "report.json", "w") as f:
            json.dump(report, f, indent=2, default=str)

    async def load_report(self, job_id: str) -> dict[str, Any] | None:
        report_path = self._job_dir(job_id) / "report.json"
        if not report_path.exists():
            return None
        with open(report_path) as f:
            return json.load(f)
