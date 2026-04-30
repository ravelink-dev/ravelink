"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..player import Player


__all__ = ("PlayerRegistry",)


class PlayerRegistry:
    """Small guild-id keyed registry for active players."""

    def __init__(self) -> None:
        self._players: dict[int, Player] = {}

    def register(self, player: Player) -> None:
        guild = player.guild
        if guild is not None:
            self._players[guild.id] = player

    def unregister(self, guild_id: int) -> Player | None:
        return self._players.pop(int(guild_id), None)

    def get(self, guild_id: int) -> Player | None:
        return self._players.get(int(guild_id))

    def clear(self) -> None:
        self._players.clear()

    def values(self) -> list[Player]:
        return list(self._players.values())

    def __len__(self) -> int:
        return len(self._players)

    def __iter__(self) -> Iterator[Player]:
        return iter(self._players.values())
