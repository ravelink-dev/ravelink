"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from typing import TypedDict

from typing_extensions import NotRequired


class PlayerState(TypedDict):
    time: int
    position: int
    connected: bool
    ping: int


class VoiceState(TypedDict, total=False):
    token: str
    endpoint: str | None
    session_id: str
    channel_id: str


class PlayerVoiceState(TypedDict):
    voice: VoiceState
    channel_id: NotRequired[str]
    track: NotRequired[str]
    position: NotRequired[int]




