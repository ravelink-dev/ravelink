"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeAlias, TypedDict


if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from .state import PlayerState
    from .stats import CPUStats, FrameStats, MemoryStats
    from .tracks import TrackPayload


class TrackExceptionPayload(TypedDict):
    message: NotRequired[str]
    severity: str
    cause: str


class ReadyOP(TypedDict):
    op: Literal["ready"]
    resumed: bool
    sessionId: str


class PlayerUpdateOP(TypedDict):
    op: Literal["playerUpdate"]
    guildId: str
    state: PlayerState


class StatsOP(TypedDict):
    op: Literal["stats"]
    players: int
    playingPlayers: int
    uptime: int
    memory: MemoryStats
    cpu: CPUStats
    frameStats: FrameStats


class TrackStartEvent(TypedDict):
    op: Literal["event"]
    guildId: str
    type: Literal["TrackStartEvent"]
    track: TrackPayload


class TrackEndEvent(TypedDict):
    op: Literal["event"]
    guildId: str
    type: Literal["TrackEndEvent"]
    track: TrackPayload
    reason: str


class TrackExceptionEvent(TypedDict):
    op: Literal["event"]
    guildId: str
    type: Literal["TrackExceptionEvent"]
    track: TrackPayload
    exception: TrackExceptionPayload


class TrackStuckEvent(TypedDict):
    op: Literal["event"]
    guildId: str
    type: Literal["TrackStuckEvent"]
    track: TrackPayload
    thresholdMs: int


class WebsocketClosedEvent(TypedDict):
    op: Literal["event"]
    guildId: str
    type: Literal["WebSocketClosedEvent"]
    code: int
    reason: str
    byRemote: bool


WebsocketOP: TypeAlias = (
    ReadyOP
    | PlayerUpdateOP
    | StatsOP
    | TrackStartEvent
    | TrackEndEvent
    | TrackExceptionEvent
    | TrackStuckEvent
    | WebsocketClosedEvent
)




