"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..node import Node

if TYPE_CHECKING:
    import aiohttp
    import discord


__all__ = ("NodeConfig",)


@dataclass(slots=True)
class NodeConfig:
    """Declarative node configuration used by :class:`ravelink.Client`."""

    identifier: str
    uri: str
    password: str
    region: str | None = None
    secure: bool = False
    session: aiohttp.ClientSession | None = None
    heartbeat: float = 15.0
    retries: int | None = None
    resume_timeout: int = 60
    inactive_player_timeout: int | None = 300
    inactive_channel_tokens: int | None = 3
    request_timeout: float = 15.0
    request_retries: int = 2
    request_concurrency: int = 12

    def normalized_uri(self) -> str:
        value = self.uri.strip().removesuffix("/")
        if "://" in value:
            return value

        scheme = "https" if self.secure else "http"
        return f"{scheme}://{value}"

    def build(self, *, client: discord.Client | None = None) -> Node:
        """Create a concrete :class:`ravelink.Node` from this config."""
        return Node(
            identifier=self.identifier,
            uri=self.normalized_uri(),
            password=self.password,
            session=self.session,
            heartbeat=self.heartbeat,
            retries=self.retries,
            client=client,
            region=self.region,
            resume_timeout=self.resume_timeout,
            inactive_player_timeout=self.inactive_player_timeout,
            inactive_channel_tokens=self.inactive_channel_tokens,
            request_timeout=self.request_timeout,
            request_retries=self.request_retries,
            request_concurrency=self.request_concurrency,
        )
