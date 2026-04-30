"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .exceptions import NodeUnavailableError

if TYPE_CHECKING:
    from .node import Node


__all__ = (
    "BaseBalancer",
    "RoundRobinBalancer",
    "LeastPlayersBalancer",
    "PenaltyBalancer",
    "RegionAffinityBalancer",
    "LatencyWeightedBalancer",
    "resolve_balancer",
)


@runtime_checkable
class BaseBalancer(Protocol):
    """Protocol for custom node-selection policies."""

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node: ...


def _eligible(nodes: Sequence[Node], exclude: set[str] | None = None) -> list[Node]:
    excluded = exclude or set()
    candidates = [node for node in nodes if node.identifier not in excluded and node.available]
    if not candidates:
        raise NodeUnavailableError("No connected Ravelink nodes are available for selection.")

    return candidates


def _players(node: Node) -> int:
    total = getattr(node, "_total_player_count", None)
    return int(total if total is not None else len(node.players))


class RoundRobinBalancer:
    """Select connected nodes in a stable round-robin cycle."""

    def __init__(self) -> None:
        self._index = 0

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        candidates = _eligible(nodes, exclude)
        selected = candidates[self._index % len(candidates)]
        self._index += 1
        return selected


class LeastPlayersBalancer:
    """Prefer the node with the fewest active Lavalink players."""

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        return min(_eligible(nodes, exclude), key=_players)


class PenaltyBalancer:
    """Prefer the node with the lowest cached health penalty."""

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        return min(_eligible(nodes, exclude), key=lambda node: (node.penalty, _players(node), node.identifier))


class RegionAffinityBalancer:
    """Prefer nodes matching a requested region, then fall back to penalty."""

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        candidates = _eligible(nodes, exclude)
        if region:
            preferred = [node for node in candidates if node.region == region]
            if preferred:
                candidates = preferred

        return min(candidates, key=lambda node: (node.penalty, _players(node), node.identifier))


class LatencyWeightedBalancer:
    """Prefer low-latency nodes while still accounting for player pressure."""

    def select_node(
        self,
        nodes: Sequence[Node],
        *,
        guild_id: int | None = None,
        region: str | None = None,
        exclude: set[str] | None = None,
    ) -> Node:
        candidates = _eligible(nodes, exclude)
        if region:
            preferred = [node for node in candidates if node.region == region]
            if preferred:
                candidates = preferred

        def score(node: Node) -> tuple[float, int, str]:
            latency = node.latency if node.latency is not None else 250.0
            return ((latency * 0.75) + (node.penalty * 0.25), _players(node), node.identifier)

        return min(candidates, key=score)


def resolve_balancer(strategy: str | BaseBalancer | None) -> BaseBalancer:
    """Normalize a strategy name or custom balancer into a balancer object."""
    if strategy is None:
        return LatencyWeightedBalancer()

    if not isinstance(strategy, str):
        return strategy

    normalized = strategy.lower().strip()
    if normalized in {"round_robin", "round-robin", "rr"}:
        return RoundRobinBalancer()
    if normalized in {"least_players", "least-players", "players"}:
        return LeastPlayersBalancer()
    if normalized in {"least_penalty", "penalty", "hybrid"}:
        return PenaltyBalancer()
    if normalized in {"region", "region_affinity", "region-affinity"}:
        return RegionAffinityBalancer()
    if normalized in {"latency", "latency_weighted", "latency-weighted"}:
        return LatencyWeightedBalancer()

    raise ValueError(f"Unknown Ravelink node balancing strategy: {strategy!r}")
