"""DNA Playbook hook. The Playbook itself is built later; scoring already works without it."""
from __future__ import annotations

from typing import Optional, Protocol


class PlaybookProvider(Protocol):
    def history_score(self, topic_name: str) -> Optional[float]:
        """0-100 for how well this topic (or similar) has performed for Harshitha, or None if no data."""
        ...


class EmptyPlaybook:
    """Used until the real Playbook exists. None makes scoring redistribute the history weight."""

    def history_score(self, topic_name: str) -> Optional[float]:
        return None
