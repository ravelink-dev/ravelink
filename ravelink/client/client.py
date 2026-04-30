"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..balancers import BaseBalancer, resolve_balancer
from ..enums import TrackSource
from ..exceptions import NodeUnavailableError
from ..node import Node, Pool
from ..player import Player
from ..search import SearchResolver, TrackResult
from .config import NodeConfig
from .lifecycle import LifecycleState
from .registry import PlayerRegistry

if TYPE_CHECKING:
    import discord


__all__ = ("Client",)


class Client:
    """High-level Ravelink runtime facade.

    This class keeps the legacy-compatible :class:`ravelink.Pool` and
    :class:`ravelink.Player` internals, but exposes a smaller Python-first API
    for bots that want a single music runtime object.
    """

    def __init__(
        self,
        *,
        bot: discord.Client,
        nodes: Iterable[NodeConfig | Node],
        strategy: str | BaseBalancer | None = "latency_weighted",
        balancer: BaseBalancer | None = None,
        cache_capacity: int | None = None,
        default_source: TrackSource | str | None = "ytmsearch",
        player_cls: type[Player] = Player,
    ) -> None:
        self.bot = bot
        self.node_configs = list(nodes)
        self.cache_capacity = cache_capacity
        self.player_cls = player_cls
        self.players = PlayerRegistry()
        self.resolver = SearchResolver(default_source=default_source)
        self._balancer = balancer or resolve_balancer(strategy)
        self._state = LifecycleState.CREATED

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def node_pool(self) -> type[Pool]:
        return Pool

    @property
    def nodes(self) -> dict[str, Node]:
        return Pool.nodes

    def set_balancer(self, balancer: BaseBalancer | str) -> None:
        self._balancer = resolve_balancer(balancer)

    def add_source_resolver(self, resolver: SearchResolver) -> None:
        self.resolver = resolver

    async def start(self) -> dict[str, Node]:
        """Connect configured nodes and make this runtime ready for work."""
        concrete_nodes = [
            node.build(client=self.bot) if isinstance(node, NodeConfig) else node
            for node in self.node_configs
        ]
        self._state = LifecycleState.STARTED
        return await Pool.connect(nodes=concrete_nodes, client=self.bot, cache_capacity=self.cache_capacity)

    async def close(self) -> None:
        """Close every connected node and clear runtime registries."""
        self._state = LifecycleState.CLOSING
        await Pool.close()
        self.players.clear()
        self._state = LifecycleState.CLOSED

    def select_node(
        self,
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        return self._balancer.select_node(
            list(Pool.nodes.values()),
            guild_id=guild_id,
            region=region,
            exclude=exclude,
        )

    async def search(
        self,
        query: str,
        *,
        source: TrackSource | str | None = None,
        region: str | None = None,
        node: Node | None = None,
    ) -> TrackResult:
        """Search/load tracks through the selected node and return a normalized result."""
        selected = node or self.select_node(region=region)
        return await self.resolver.search(query, source=source, node=selected)

    async def connect(
        self,
        guild: discord.Guild,
        *,
        channel: discord.VoiceChannel | discord.StageChannel,
        region: str | None = None,
        node: Node | None = None,
        timeout: float = 10.0,
        reconnect: bool = True,
        self_deaf: bool = True,
        self_mute: bool = False,
    ) -> Player:
        """Connect or move a guild player to a voice channel."""
        current = self.get_player(guild.id)
        if current is not None and current.connected:
            if getattr(current.channel, "id", None) != channel.id:
                await current.move_to(channel, timeout=timeout, self_deaf=self_deaf, self_mute=self_mute)
            self.players.register(current)
            return current

        selected = node or self.select_node(guild_id=guild.id, region=region)
        player = await channel.connect(
            cls=self.player_cls,
            timeout=timeout,
            reconnect=reconnect,
            self_deaf=self_deaf,
            self_mute=self_mute,
            nodes=[selected],
        )
        self.players.register(player)
        return player

    def get_player(self, guild_id: int) -> Player | None:
        """Return a player by guild id, including players registered directly through Discord.py."""
        player = self.players.get(guild_id)
        if player is not None:
            return player

        for node in Pool.nodes.values():
            player = node.get_player(int(guild_id))
            if player is not None:
                self.players.register(player)
                return player

        return None

    async def diagnostics(self) -> dict[str, Any]:
        return await Pool.diagnostics()

    async def node_health(self) -> list[dict[str, Any]]:
        return await Pool.node_health()

    async def failover_player(
        self,
        player: Player,
        *,
        target: Node | None = None,
        timeout: float = 15.0,
    ) -> tuple[bool, str]:
        """Migrate one player to another node using the existing recovery path."""
        previous = player.node
        if target is None:
            try:
                target = self.select_node(
                    guild_id=player.guild.id if player.guild else None,
                    region=previous.region,
                    exclude={previous.identifier},
                )
            except NodeUnavailableError:
                return False, "no_target_node"

        return await Pool.migrate_player(player, target=target, timeout=timeout)
