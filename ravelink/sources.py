"""Source-prefix helpers shared by search and autoplay."""

from __future__ import annotations

from .enums import TrackSource


__all__ = ("normalize_source_prefix", "source_search_prefixes")


_SOURCE_PREFIXES: dict[TrackSource | str, str] = {
    TrackSource.YouTube: "ytsearch",
    TrackSource.YouTubeMusic: "ytmsearch",
    TrackSource.SoundCloud: "scsearch",
    TrackSource.Spotify: "spsearch",
    TrackSource.AppleMusic: "amsearch",
    TrackSource.Deezer: "dzsearch",
    TrackSource.YandexMusic: "ymsearch",
    "youtube": "ytsearch",
    "yt": "ytsearch",
    "ytsearch": "ytsearch",
    "youtube music": "ytmsearch",
    "ytmusic": "ytmsearch",
    "ytmsearch": "ytmsearch",
    "soundcloud": "scsearch",
    "sc": "scsearch",
    "scsearch": "scsearch",
    "spotify": "spsearch",
    "sp": "spsearch",
    "spsearch": "spsearch",
    "apple": "amsearch",
    "applemusic": "amsearch",
    "apple music": "amsearch",
    "am": "amsearch",
    "amsearch": "amsearch",
    "deezer": "dzsearch",
    "dz": "dzsearch",
    "dzsearch": "dzsearch",
    "yandex": "ymsearch",
    "yandexmusic": "ymsearch",
    "yandex music": "ymsearch",
    "ym": "ymsearch",
    "ymsearch": "ymsearch",
}

_MANAGER_SEARCH_PREFIXES: dict[str, tuple[str, ...]] = {
    "youtube": ("ytmsearch", "ytsearch"),
    "ytmusic": ("ytmsearch",),
    "soundcloud": ("scsearch",),
    "spotify": ("spsearch",),
    "applemusic": ("amsearch",),
    "apple music": ("amsearch",),
    "deezer": ("dzsearch",),
    "yandexmusic": ("ymsearch",),
    "yandex music": ("ymsearch",),
}

_MANAGER_PRIORITY: tuple[str, ...] = (
    "youtube",
    "ytmusic",
    "soundcloud",
    "spotify",
    "applemusic",
    "deezer",
    "yandexmusic",
)


def _normalize_key(source: str) -> str:
    return " ".join(source.strip().lower().removesuffix(":").replace("_", " ").replace("-", " ").split())


def normalize_source_prefix(source: TrackSource | str | None) -> str | None:
    """Return the Lavalink search prefix for a source or prefix-like string."""
    if source is None:
        return None

    if isinstance(source, TrackSource):
        return _SOURCE_PREFIXES[source]

    cleaned = source.strip().removesuffix(":")
    if not cleaned:
        return None

    key = _normalize_key(cleaned)
    compact_key = key.replace(" ", "")
    return _SOURCE_PREFIXES.get(key) or _SOURCE_PREFIXES.get(compact_key) or cleaned


def source_search_prefixes(source_managers: set[str]) -> list[str]:
    """Return known search prefixes supported by a Lavalink node's source managers."""
    prefixes: list[str] = []
    seen: set[str] = set()

    def sort_key(manager: str) -> tuple[int, str]:
        compact_key = _normalize_key(manager).replace(" ", "")
        try:
            return _MANAGER_PRIORITY.index(compact_key), compact_key
        except ValueError:
            return len(_MANAGER_PRIORITY), compact_key

    for manager in sorted(source_managers, key=sort_key):
        key = _normalize_key(manager)
        compact_key = key.replace(" ", "")
        for prefix in (*_MANAGER_SEARCH_PREFIXES.get(key, ()), *_MANAGER_SEARCH_PREFIXES.get(compact_key, ())):
            if prefix in seen:
                continue
            seen.add(prefix)
            prefixes.append(prefix)

    return prefixes
