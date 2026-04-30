"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import enum


__all__ = ("LifecycleState",)


class LifecycleState(enum.Enum):
    """Lifecycle state for the high-level Ravelink client facade."""

    CREATED = "created"
    STARTED = "started"
    CLOSING = "closing"
    CLOSED = "closed"
