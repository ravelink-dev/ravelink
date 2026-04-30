"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from typing import TypedDict


class MemoryStats(TypedDict):
    free: int
    used: int
    allocated: int
    reservable: int


class CPUStats(TypedDict):
    cores: int
    systemLoad: float
    lavalinkLoad: float


class FrameStats(TypedDict):
    sent: int
    nulled: int
    deficit: int




