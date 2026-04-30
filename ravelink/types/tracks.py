"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from typing import Any, TypedDict

from typing_extensions import NotRequired


class TrackInfoPayload(TypedDict):
    identifier: str
    isSeekable: bool
    author: str
    length: int
    isStream: bool
    position: int
    title: str
    uri: NotRequired[str]
    artworkUrl: NotRequired[str]
    isrc: NotRequired[str]
    sourceName: str


class PlaylistInfoPayload(TypedDict):
    name: str
    selectedTrack: int


class TrackPayload(TypedDict):
    encoded: str
    info: TrackInfoPayload
    pluginInfo: dict[Any, Any]
    userData: dict[str, Any]


class PlaylistPayload(TypedDict):
    info: PlaylistInfoPayload
    tracks: list[TrackPayload]
    pluginInfo: dict[Any, Any]




