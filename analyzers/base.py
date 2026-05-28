from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalyzerResult:
    """Base result returned by every analyzer."""
    analyzer: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"analyzer": self.analyzer, **self.raw}
