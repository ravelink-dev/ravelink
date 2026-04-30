"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yarl

from .enums import LoadType, TrackSource
from .exceptions import SearchError
from .sources import normalize_source_prefix
from .tracks import Playable, Playlist, Search

if TYPE_CHECKING:
    from .node import Node


__all__ = ("TrackResult", "SearchResolver")


@dataclass(slots=True)
class TrackResult:
    """Normalized result returned by :meth:`ravelink.Client.search`."""

    load_type: LoadType
    tracks: list[Playable] = field(default_factory=list)
    playlist: Playlist | None = None
    plugin_info: dict[str, Any] = field(default_factory=dict)
    query: str | None = None
    source: str | None = None
    node: Node | None = None

    @property
    def first(self) -> Playable | None:
        """Return the first playable track, if one exists."""
        return self.tracks[0] if self.tracks else None

    def __bool__(self) -> bool:
        return bool(self.tracks)

    def __len__(self) -> int:
        return len(self.tracks)

    def __iter__(self) -> Iterator[Playable]:
        return iter(self.tracks)

    @classmethod
    def empty(cls, *, query: str | None = None, source: str | None = None, node: Node | None = None) -> TrackResult:
        return cls(load_type=LoadType.EMPTY, query=query, source=source, node=node)

    @classmethod
    def from_search(
        cls,
        result: Search,
        *,
        query: str | None = None,
        source: str | None = None,
        node: Node | None = None,
    ) -> TrackResult:
        if isinstance(result, Playlist):
            plugin_info = {
                key: value
                for key, value in {
                    "type": result.type,
                    "url": result.url,
                    "artworkUrl": result.artwork,
                    "author": result.author,
                }.items()
                if value is not None
            }
            return cls(
                load_type=LoadType.PLAYLIST,
                tracks=list(result.tracks),
                playlist=result,
                plugin_info=plugin_info,
                query=query,
                source=source,
                node=node,
            )

        tracks = list(result)
        if not tracks:
            return cls.empty(query=query, source=source, node=node)

        load_type = LoadType.TRACK if len(tracks) == 1 else LoadType.SEARCH
        return cls(load_type=load_type, tracks=tracks, query=query, source=source, node=node)


class SearchResolver:
    """Resolve text queries and URLs into normalized track results."""

    def __init__(self, *, default_source: TrackSource | str | None = "ytmsearch") -> None:
        self.default_source = default_source

    def normalize_query(self, query: str, *, source: TrackSource | str | None = None) -> tuple[str, str | None]:
        cleaned = query.strip()
        if not cleaned:
            raise SearchError("Search query cannot be empty.")

        parsed = yarl.URL(cleaned)
        if parsed.host:
            return cleaned, None

        selected = self.default_source if source is None else source
        prefix = normalize_source_prefix(selected)
        if prefix is None:
            return cleaned, None

        normalized_prefix = prefix.removesuffix(":")
        if ":" in cleaned:
            possible_prefix = cleaned.split(":", 1)[0].strip()
            if possible_prefix and " " not in possible_prefix:
                return cleaned, possible_prefix

        return f"{normalized_prefix}:{cleaned}", normalized_prefix

    async def search(
        self,
        query: str,
        *,
        source: TrackSource | str | None = None,
        node: Node | None = None,
    ) -> TrackResult:
        from .node import Pool

        normalized, normalized_source = self.normalize_query(query, source=source)
        result = await Pool.fetch_tracks(normalized, node=node)
        return TrackResult.from_search(result, query=query, source=normalized_source, node=node)
