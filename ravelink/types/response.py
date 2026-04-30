"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from typing import Literal, TypedDict

from typing_extensions import Never, NotRequired

from .filters import FilterPayload
from .state import PlayerState
from .stats import CPUStats, FrameStats, MemoryStats
from .tracks import PlaylistPayload, TrackPayload


class ErrorResponse(TypedDict):
    timestamp: int
    status: int
    error: str
    trace: NotRequired[str]
    message: str
    path: str


class LoadedErrorPayload(TypedDict):
    message: str
    severity: str
    cause: str


class VoiceStateResponse(TypedDict, total=False):
    token: str
    endpoint: str | None
    sessionId: str
    channelId: str | None


class PlayerResponse(TypedDict):
    guildId: str
    track: NotRequired[TrackPayload]
    volume: int
    paused: bool
    state: PlayerState
    voice: VoiceStateResponse
    filters: FilterPayload


class UpdateResponse(TypedDict):
    resuming: bool
    timeout: int


class TrackLoadedResponse(TypedDict):
    loadType: Literal["track"]
    data: TrackPayload


class PlaylistLoadedResponse(TypedDict):
    loadType: Literal["playlist"]
    data: PlaylistPayload


class SearchLoadedResponse(TypedDict):
    loadType: Literal["search"]
    data: list[TrackPayload]


class EmptyLoadedResponse(TypedDict):
    loadType: Literal["empty"]
    data: dict[Never, Never]


class ErrorLoadedResponse(TypedDict):
    loadType: Literal["error"]
    data: LoadedErrorPayload


class VersionPayload(TypedDict):
    semver: str
    major: int
    minor: int
    patch: int
    preRelease: NotRequired[str]
    build: NotRequired[str]


class GitPayload(TypedDict):
    branch: str
    commit: str
    commitTime: int


class PluginPayload(TypedDict):
    name: str
    version: str


RoutePlannerStatusResponse = TypedDict(
    "RoutePlannerStatusResponse",
    {"class": str | None, "details": dict[str, object] | None},
)


class InfoResponse(TypedDict):
    version: VersionPayload
    buildTime: int
    git: GitPayload
    jvm: str
    lavaplayer: str
    sourceManagers: list[str]
    filters: list[str]
    plugins: list[PluginPayload]


class StatsResponse(TypedDict):
    players: int
    playingPlayers: int
    uptime: int
    memory: MemoryStats
    cpu: CPUStats
    frameStats: NotRequired[FrameStats]




