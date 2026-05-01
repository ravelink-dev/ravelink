"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

import aiohttp
from discord.utils import classproperty

from . import __version__
from .enums import NodeStatus
from .exceptions import (
    AuthorizationFailedException,
    InvalidClientException,
    InvalidNodeException,
    LavalinkException,
    LavalinkLoadException,
    NodeException,
)
from .lfu import LFUCache
from .payloads import *
from .sources import source_search_prefixes
from .tracks import Playable, Playlist
from .transport import Method, RequestController, json_dumps
from .websocket import Websocket


if TYPE_CHECKING:
    from collections.abc import Iterable

    import discord

    from .player import Player
    from .types.request import Request, UpdateSessionRequest
    from .types.response import (
        EmptyLoadedResponse,
        ErrorLoadedResponse,
        InfoResponse,
        PlayerResponse,
        PluginPayload,
        PlaylistLoadedResponse,
        RoutePlannerStatusResponse,
        SearchLoadedResponse,
        StatsResponse,
        TrackLoadedResponse,
        UpdateResponse,
    )
    from .types.tracks import TrackPayload

    LoadedResponse: TypeAlias = (
        TrackLoadedResponse | SearchLoadedResponse | PlaylistLoadedResponse | EmptyLoadedResponse | ErrorLoadedResponse
    )


__all__ = ("Node", "Pool")


logger: logging.Logger = logging.getLogger(__name__)


class Node:
    """The Node represents a connection to Lavalink.

    The Node is responsible for keeping the websocket alive, resuming session, sending API requests and keeping track
    of connected all :class:`~ravelink.Player`.

    .. container:: operations

        .. describe:: node == other

            Equality check to determine whether this Node is equal to another reference of a Node.

        .. describe:: repr(node)

            The official string representation of this Node.

    Parameters
    ----------
    identifier: str | None
        A unique identifier for this Node. Could be ``None`` to generate a random one on creation.
    uri: str
        The URL/URI that Ravelink will use to connect to Lavalink. Usually this is in the form of something like:
        ``http://localhost:2333`` which includes the port. But you could also provide a domain which won't require a
        port like ``https://lavalink.example.com`` or a public IP address and port like ``http://111.33v1.0.0:2333``.
    password: str
        The password used to connect and authorize this Node.
    session: aiohttp.ClientSession | None
        An optional :class:`aiohttp.ClientSession` used to connect this Node over websocket and REST.
        If ``None``, one will be generated for you. Defaults to ``None``.
    heartbeat: Optional[float]
        A ``float`` in seconds to ping your websocket keep alive. Usually you would not change this.
    retries: int | None
        A ``int`` of retries to attempt when connecting or reconnecting this Node. When the retries are exhausted
        the Node will be closed and cleaned-up. ``None`` will retry forever. Defaults to ``None``.
    client: :class:`discord.Client` | None
        The :class:`discord.Client` or subclasses, E.g. ``commands.Bot`` used to connect this Node. If this is *not*
        passed you must pass this to :meth:`ravelink.Pool.connect`.
    resume_timeout: Optional[int]
        The seconds this Node should configure Lavalink for resuming its current session in case of network issues.
        If this is ``0`` or below, resuming will be disabled. Defaults to ``60``.
    inactive_player_timeout: int | None
        Set the default for :attr:`ravelink.Player.inactive_timeout` on every player that connects to this node.
        Defaults to ``300``.
    inactive_channel_tokens: int | None
        Sets the default for :attr:`ravelink.Player.inactive_channel_tokens` on every player that connects to this node.
        Defaults to ``3``.

        See also: :func:`on_ravelink_inactive_player`.
    """

    def __init__(
        self,
        *,
        identifier: str | None = None,
        uri: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        heartbeat: float = 15.0,
        retries: int | None = None,
        client: discord.Client | None = None,
        region: str | None = None,
        resume_timeout: int = 60,
        inactive_player_timeout: int | None = 300,
        inactive_channel_tokens: int | None = 3,
        request_timeout: float = 15.0,
        request_retries: int = 2,
        request_concurrency: int = 12,
    ) -> None:
        self._identifier = identifier or secrets.token_urlsafe(12)
        self._uri = uri.removesuffix("/")
        self._password = password
        self._session: aiohttp.ClientSession | None = session
        self._session_owner: bool = session is None
        self._heartbeat = heartbeat
        self._retries = retries
        self._client = client
        self._region = region
        self._resume_timeout = resume_timeout
        self._request_controller = RequestController(
            timeout=request_timeout,
            retries=request_retries,
            concurrency=request_concurrency,
        )
        self._close_lock: asyncio.Lock = asyncio.Lock()

        self._status: NodeStatus = NodeStatus.DISCONNECTED
        self._has_closed: bool = False
        self._session_id: str | None = None

        self._players: dict[int, Player] = {}
        self._total_player_count: int | None = None
        self._stats_cache: tuple[float, StatsResponsePayload] | None = None
        self._info_cache: tuple[float, InfoResponsePayload] | None = None
        self._rest_latency_ms: float | None = None

        self._spotify_enabled: bool = False
        self._source_managers: set[str] = set()
        self._supports_dave: bool | None = None
        self._lavalink_semver: str | None = None

        self._websocket: Websocket | None = None

        if inactive_player_timeout and inactive_player_timeout < 10:
            logger.warning('Setting "inactive_player_timeout" below 10 seconds may result in unwanted side effects.')

        self._inactive_player_timeout = (
            inactive_player_timeout if inactive_player_timeout and inactive_player_timeout > 0 else None
        )

        self._inactive_channel_tokens = inactive_channel_tokens

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(json_serialize=json_dumps)
            self._session_owner = True

        return self._session

    def __repr__(self) -> str:
        return f"Node(identifier={self.identifier}, uri={self.uri}, status={self.status}, players={len(self.players)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented

        return other.identifier == self.identifier

    @property
    def headers(self) -> dict[str, str]:
        """A property that returns the headers configured for sending API and websocket requests.

        .. warning::

            This includes your Node password. Please be vigilant when using this property.
        """
        if self.client is None or self.client.user is None:
            msg = f"Unable to build request headers for {self!r} without a ready client user."
            raise InvalidClientException(msg)

        data = {
            "Authorization": self.password,
            "User-Id": str(self.client.user.id),
            "Client-Name": f"Ravelink/{__version__}",
        }

        return data

    @property
    def identifier(self) -> str:
        """The unique identifier for this :class:`Node`.


        .. versionchanged:: v1.0.0

            This property was previously known as ``id``.
        """
        return self._identifier

    @property
    def uri(self) -> str:
        """The URI used to connect this :class:`Node` to Lavalink."""
        return self._uri

    @property
    def status(self) -> NodeStatus:
        """The current :class:`Node` status.

        Refer to: :class:`~ravelink.NodeStatus`
        """
        return self._status

    @property
    def available(self) -> bool:
        """Whether this node is connected and eligible for new work."""
        return self.status is NodeStatus.CONNECTED

    @property
    def region(self) -> str | None:
        """Optional deployment region label used by balancers."""
        return self._region

    @property
    def latency(self) -> float | None:
        """Last observed REST latency in milliseconds, if a request has completed."""
        return self._rest_latency_ms

    @property
    def penalty(self) -> float:
        """Synchronous cached node penalty used for policy-based balancing.

        For precise health checks use :meth:`health_score`, which can fetch fresh
        Lavalink stats. This property only uses local player counts and cached
        stats so custom balancers can make fast decisions without network I/O.
        """
        if not self.available:
            return 1_000_000.0

        base_players = float(self._total_player_count or len(self._players))
        score = base_players * 4.0

        if self._stats_cache is None:
            return score

        stats = self._stats_cache[1]
        cpu = getattr(stats, "cpu", None)
        frame = getattr(stats, "frame_stats", None)

        system_load = float(getattr(cpu, "system_load", getattr(cpu, "systemLoad", 0.0)) or 0.0)
        lavalink_load = float(getattr(cpu, "lavalink_load", getattr(cpu, "lavalinkLoad", 0.0)) or 0.0)
        deficit = float(getattr(frame, "deficit", 0.0) or 0.0)
        nulled = float(getattr(frame, "nulled", 0.0) or 0.0)

        return score + (system_load * 110.0) + (lavalink_load * 140.0) + (deficit * 0.0025) + (nulled * 0.0025)

    @property
    def players(self) -> dict[int, Player]:
        """A mapping of :attr:`discord.Guild.id` to :class:`~ravelink.Player`.


        .. versionchanged:: v1.0.0

            This property now returns a shallow copy of the internal mapping.
        """
        return self._players.copy()

    @property
    def source_managers(self) -> set[str]:
        """The currently enabled source managers reported by Lavalink."""
        return self._source_managers.copy()

    @property
    def client(self) -> discord.Client | None:
        """Returns the :class:`discord.Client` associated with this :class:`Node`.

        Could be ``None`` if it has not been set yet.


        .. versionadded:: v1.0.0
        """
        return self._client

    @property
    def password(self) -> str:
        """Returns the password used to connect this :class:`Node` to Lavalink.

        .. versionadded:: v1.0.0
        """
        return self._password

    @property
    def heartbeat(self) -> float:
        """Returns the duration in seconds that the :class:`Node` websocket should send a heartbeat.

        .. versionadded:: v1.0.0
        """
        return self._heartbeat

    @property
    def session_id(self) -> str | None:
        """Returns the Lavalink session ID. Could be None if this :class:`Node` has not connected yet.

        .. versionadded:: v1.0.0
        """
        return self._session_id

    async def _pool_closer(self) -> None:
        if not self._has_closed:
            await self.close()

    async def close(self, eject: bool = False) -> None:
        """Method to close this Node and cleanup.

        After this method has finished, the event ``on_ravelink_node_closed`` will be fired.

        This method renders the Node websocket disconnected and disconnects all players.

        Parameters
        ----------
        eject: bool
            If ``True``, this will remove the Node from the Pool. Defaults to ``False``.


        .. versionchanged:: v1.0.0

            Added the ``eject`` parameter. Fixed a bug where the connected Players were not being disconnected.
        """
        async with self._close_lock:
            disconnected: list[Player] = []

            for player in self._players.copy().values():
                try:
                    await player.disconnect()
                except Exception as e:
                    logger.debug("An error occurred while disconnecting a player in the close method of %r: %s", self, e)

                disconnected.append(player)

            if self._websocket is not None:
                await self._websocket.cleanup(clear_players=True, final=True)

            self._status = NodeStatus.DISCONNECTED
            self._session_id = None
            self._players = {}

            if self._session_owner and self._session is not None and not self._session.closed:
                await self._session.close()

            self._has_closed = True

            if eject:
                getattr(Pool, "_Pool__nodes").pop(self.identifier, None)

            if self.client is not None:
                self.client.dispatch("ravelink_node_closed", self, disconnected)

    async def _connect(self, *, client: discord.Client | None) -> None:
        client_ = self._client or client

        if not client_:
            raise InvalidClientException(f"Unable to connect {self!r} as you have not provided a valid discord.Client.")

        self._client = client_

        self._has_closed = False
        self._ensure_session()

        websocket: Websocket = Websocket(node=self)
        self._websocket = websocket
        await websocket.connect()
        try:
            info = await self.fetch_info()
        except Exception:
            logger.debug("Unable to fetch Lavalink info for %r during connect.", self, exc_info=True)
        else:
            self._update_capabilities_from_info(info)

    async def send(
        self, method: Method = "GET", *, path: str, data: Any | None = None, params: dict[str, Any] | None = None
    ) -> Any:
        """Method for making requests to the Lavalink node.

        .. warning::

            Usually you wouldn't use this method. Please use the built in methods of :class:`~Node`, :class:`~Pool`
            and :class:`~ravelink.Player`, unless you need to send specific plugin data to Lavalink.

            Using this method may have unwanted side effects on your players and/or nodes.

        Parameters
        ----------
        method: Optional[str]
            The method to use when making this request. Available methods are
            "GET", "POST", "PATCH", "PUT", "DELETE" and "OPTIONS". Defaults to "GET".
        path: str
            The path to make this request to. E.g. "/v4/stats".
        data: Any | None
            The optional JSON data to send along with your request to Lavalink. This should be a dict[str, Any]
            and able to be converted to JSON.
        params: Optional[dict[str, Any]]
            An optional dict of query parameters to send with your request to Lavalink. If you include your query
            parameters in the ``path`` parameter, do not pass them here as well. E.g. {"thing": 1, "other": 2}
            would equate to "?thing=1&other=2".

        Returns
        -------
        Any
            The response from Lavalink which will either be None, a str or JSON.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        session = self._ensure_session()
        clean_path: str = path.strip("/")
        uri: str = f"{self.uri}/{clean_path}"

        started = time.perf_counter()
        try:
            return await self._request_controller.request(
                session,
                method,
                url=uri,
                params=params,
                json=data,
                headers=self.headers,
            )
        finally:
            self._rest_latency_ms = (time.perf_counter() - started) * 1000.0

    def _require_session_id(self) -> str:
        if self.session_id is None:
            raise NodeException(f"{self!r} does not have an active Lavalink session yet.")

        return self.session_id

    async def _fetch_players(self) -> list[PlayerResponse]:
        session_id = self._require_session_id()
        return await self.send("GET", path=f"/v4/sessions/{session_id}/players")

    async def fetch_players(self) -> list[PlayerResponsePayload]:
        """Method to fetch the player information Lavalink holds for every connected player on this node.

        .. warning::

            This payload is not the same as the :class:`ravelink.Player` class. This is the data received from
            Lavalink about the players.


        Returns
        -------
        list[:class:`PlayerResponsePayload`]
            A list of :class:`PlayerResponsePayload` representing each player connected to this node.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        data: list[PlayerResponse] = await self._fetch_players()

        payload: list[PlayerResponsePayload] = [PlayerResponsePayload(p) for p in data]
        return payload

    async def _fetch_player(self, guild_id: int, /) -> PlayerResponse:
        session_id = self._require_session_id()
        return await self.send("GET", path=f"/v4/sessions/{session_id}/players/{guild_id}")

    async def fetch_player_info(self, guild_id: int, /) -> PlayerResponsePayload | None:
        """Method to fetch the player information Lavalink holds for the specific guild.

        .. warning::

            This payload is not the same as the :class:`ravelink.Player` class. This is the data received from
            Lavalink about the player. See: :meth:`~ravelink.Node.get_player`


        Parameters
        ----------
        guild_id: int
            The ID of the guild you want to fetch info for.

        Returns
        -------
        :class:`PlayerResponsePayload` | None
            The :class:`PlayerResponsePayload` representing the player info for the guild ID connected to this node.
            Could be ``None`` if no player is found with the given guild ID.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        try:
            data: PlayerResponse = await self._fetch_player(guild_id)
        except LavalinkException as e:
            if e.status == 404:
                return None

            raise e

        payload: PlayerResponsePayload = PlayerResponsePayload(data)
        return payload

    async def _update_player(self, guild_id: int, /, *, data: Request, replace: bool = False) -> PlayerResponse:
        session_id = self._require_session_id()
        no_replace: bool = not replace
        return await self.send(
            "PATCH",
            path=f"/v4/sessions/{session_id}/players/{guild_id}",
            params={"noReplace": no_replace},
            data=data,
        )

    async def _destroy_player(self, guild_id: int, /) -> None:
        session_id = self._require_session_id()
        await self.send("DELETE", path=f"/v4/sessions/{session_id}/players/{guild_id}")

    async def _update_session(self, *, data: UpdateSessionRequest) -> UpdateResponse:
        session_id = self._require_session_id()
        return await self.send("PATCH", path=f"/v4/sessions/{session_id}", data=data)

    async def _fetch_tracks(self, query: str) -> LoadedResponse:
        return await self.send("GET", path="/v4/loadtracks", params={"identifier": query})

    async def _decode_track(self, track: str, /) -> TrackPayload:
        return await self.send("GET", path="/v4/decodetrack", params={"encodedTrack": track})

    async def decode_track(self, track: str, /) -> Playable:
        """Decode one encoded Lavalink track into a :class:`Playable`."""
        data: TrackPayload = await self._decode_track(track)
        return Playable(data)

    async def _decode_tracks(self, tracks: list[str], /) -> list[TrackPayload]:
        return await self.send("POST", path="/v4/decodetracks", data=tracks)

    async def decode_tracks(self, tracks: list[str], /) -> list[Playable]:
        """Decode encoded Lavalink tracks into :class:`Playable` objects."""
        data: list[TrackPayload] = await self._decode_tracks(tracks)
        return [Playable(track) for track in data]

    async def fetch_plugins(self) -> list[PluginPayload]:
        """Fetch plugin metadata reported by Lavalink."""
        return await self.send("GET", path="/v4/plugins")

    async def fetch_route_planner_status(self) -> RoutePlannerStatusResponse | None:
        """Fetch Lavalink route planner status, if route planning is configured."""
        data: RoutePlannerStatusResponse = await self.send("GET", path="/v4/routeplanner/status")
        if data.get("class") is None:
            return None

        return data

    async def unmark_failed_address(self, address: str, /) -> None:
        """Release one failed route planner address."""
        await self.send("POST", path="/v4/routeplanner/free/address", data={"address": address})

    async def unmark_all_addresses(self) -> None:
        """Release every failed route planner address."""
        await self.send("POST", path="/v4/routeplanner/free/all")

    async def _fetch_info(self) -> InfoResponse:
        return await self.send("GET", path="/v4/info")

    async def fetch_info(self) -> InfoResponsePayload:
        """Method to fetch this Lavalink Nodes info response data.

        Returns
        -------
        :class:`InfoResponsePayload`
            The :class:`InfoResponsePayload` associated with this Node.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        if self._info_cache and self._info_cache[0] > time.monotonic():
            return self._info_cache[1]

        data: InfoResponse = await self._fetch_info()
        payload: InfoResponsePayload = InfoResponsePayload(data)
        self._info_cache = (time.monotonic() + 300.0, payload)
        self._update_capabilities_from_info(payload)
        return payload

    def _update_capabilities_from_info(self, payload: InfoResponsePayload) -> None:
        version = payload.version
        previous_support = self._supports_dave
        previous_version = self._lavalink_semver
        self._lavalink_semver = version.semver
        self._supports_dave = (
            version.major > 4
            or (version.major == 4 and version.minor > 2)
            or (version.major == 4 and version.minor == 2 and version.patch >= 0)
        )
        if previous_support == self._supports_dave and previous_version == version.semver:
            return
        if self._supports_dave:
            logger.info("%r reports Lavalink %s with DAVE-capable voice support.", self, version.semver)
        else:
            logger.warning(
                "%r reports Lavalink %s. Lavalink 4.2.0 or newer is required for DAVE-compatible voice handling.",
                self,
                version.semver,
            )

    async def _fetch_stats(self) -> StatsResponse:
        return await self.send("GET", path="/v4/stats")

    async def fetch_stats(self) -> StatsResponsePayload:
        """Method to fetch this Lavalink Nodes stats response data.

        Returns
        -------
        :class:`StatsResponsePayload`
            The :class:`StatsResponsePayload` associated with this Node.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        data: StatsResponse = await self._fetch_stats()

        payload: StatsResponsePayload = StatsResponsePayload(data)
        self._stats_cache = (time.monotonic(), payload)
        return payload

    async def fetch_stats_cached(self, *, ttl: float = 10.0, force: bool = False) -> StatsResponsePayload:
        """Fetch node stats with a short-lived cache to reduce REST load.

        Parameters
        ----------
        ttl: float
            Cache time-to-live in seconds. Defaults to 10.0.
        force: bool
            If True, bypass cache and force a REST fetch.
        """
        if not force and self._stats_cache is not None:
            cached_at, payload = self._stats_cache
            if (time.monotonic() - cached_at) <= max(0.5, ttl):
                return payload

        return await self.fetch_stats()

    async def health_score(self, *, ttl: float = 10.0) -> float:
        """Return a lower-is-better health score for this node."""
        if self.status is not NodeStatus.CONNECTED:
            return 1_000_000.0

        base_players = float(self._total_player_count or len(self._players))
        try:
            stats = await self.fetch_stats_cached(ttl=ttl)
        except Exception:
            # If stats fail, still allow selection with a heavy penalty.
            return 50_000.0 + (base_players * 4.0)

        cpu = getattr(stats, "cpu", None)
        frame = getattr(stats, "frame_stats", None)

        system_load = float(getattr(cpu, "system_load", getattr(cpu, "systemLoad", 0.0)) or 0.0)
        lavalink_load = float(getattr(cpu, "lavalink_load", getattr(cpu, "lavalinkLoad", 0.0)) or 0.0)
        deficit = float(getattr(frame, "deficit", 0.0) or 0.0)
        nulled = float(getattr(frame, "nulled", 0.0) or 0.0)

        # Weighted hybrid score for both quality and throughput.
        return (
            (system_load * 110.0)
            + (lavalink_load * 140.0)
            + (base_players * 4.0)
            + (deficit * 0.0025)
            + (nulled * 0.0025)
        )

    async def health_snapshot(self, *, ttl: float = 10.0) -> dict[str, Any]:
        """Return a health snapshot suitable for diagnostics dashboards."""
        snapshot: dict[str, Any] = {
            "identifier": self.identifier,
            "uri": self.uri,
            "status": str(self.status),
            "players": int(self._total_player_count or len(self._players)),
            "source_managers": sorted(self._source_managers),
        }
        try:
            stats = await self.fetch_stats_cached(ttl=ttl)
            cpu = getattr(stats, "cpu", None)
            frame = getattr(stats, "frame_stats", None)
            snapshot.update(
                {
                    "system_load": float(getattr(cpu, "system_load", getattr(cpu, "systemLoad", 0.0)) or 0.0),
                    "lavalink_load": float(getattr(cpu, "lavalink_load", getattr(cpu, "lavalinkLoad", 0.0)) or 0.0),
                    "frame_deficit": int(getattr(frame, "deficit", 0) or 0),
                    "frame_nulled": int(getattr(frame, "nulled", 0) or 0),
                    "health_score": await self.health_score(ttl=ttl),
                }
            )
        except Exception:
            snapshot["health_score"] = 1_000_000.0
        return snapshot

    async def _fetch_version(self) -> str:
        return await self.send("GET", path="/version")

    async def fetch_version(self) -> str:
        """Method to fetch this Lavalink version string.

        Returns
        -------
        str
            The version string associated with this Lavalink node.

        Raises
        ------
        LavalinkException
            An error occurred while making this request to Lavalink.
        NodeException
            An error occured while making this request to Lavalink,
            and Lavalink was unable to send any error information.


        .. versionadded:: v1.0.0
        """
        data: str = await self._fetch_version()
        return data

    def get_player(self, guild_id: int, /) -> Player | None:
        """Return a :class:`~ravelink.Player` associated with the provided :attr:`discord.Guild.id`.

        Parameters
        ----------
        guild_id: int
            The :attr:`discord.Guild.id` to retrieve a :class:`~ravelink.Player` for.

        Returns
        -------
        Optional[:class:`~ravelink.Player`]
            The Player associated with this guild ID. Could be None if no :class:`~ravelink.Player` exists
            for this guild.
        """
        return self._players.get(guild_id, None)

    def add_player(self, guild_id: int, player: Player, /) -> None:
        """Add a player to this node's local player cache."""
        self._players[guild_id] = player

    def remove_player(self, guild_id: int, /) -> Player | None:
        """Remove and return a player from this node's local player cache."""
        return self._players.pop(guild_id, None)

    async def voice_update(
        self,
        guild_id: int,
        /,
        *,
        session_id: str,
        token: str,
        endpoint: str,
        channel_id: int | str,
    ) -> PlayerResponse:
        """Send a Discord voice state update to Lavalink."""
        request: dict[str, Any] = {
            "voice": {
                "sessionId": session_id,
                "token": token,
                "endpoint": endpoint,
                "channelId": str(channel_id),
            }
        }
        return await self._update_player(guild_id, data=request)

    @property
    def lavalink_version(self) -> str | None:
        return self._lavalink_semver

    @property
    def supports_dave(self) -> bool | None:
        return self._supports_dave


class Pool:
    """The Ravelink Pool represents a collection of :class:`~ravelink.Node` and helper methods for searching tracks.

    To connect a :class:`~ravelink.Node` please use this Pool.

    .. note::

        All methods and attributes on this class are class level, not instance. Do not create an instance of this class.
    """

    __nodes: ClassVar[dict[str, Node]] = {}
    __cache: LFUCache | None = None

    @classmethod
    def _connected_nodes(cls) -> list[Node]:
        return [n for n in cls.__nodes.values() if n.status is NodeStatus.CONNECTED]

    @classmethod
    async def get_best_node(
        cls,
        *,
        strategy: Literal["hybrid", "players"] = "hybrid",
        exclude: set[str] | None = None,
    ) -> Node:
        """Asynchronously select the healthiest currently connected node."""
        exclude_ids = exclude or set()
        nodes = [n for n in cls._connected_nodes() if n.identifier not in exclude_ids]
        if not nodes:
            raise InvalidNodeException("No nodes are currently assigned to the ravelink.Pool in a CONNECTED state.")

        if strategy == "players":
            return sorted(nodes, key=lambda n: n._total_player_count or len(n.players))[0]

        scored = await asyncio.gather(*(n.health_score(ttl=8.0) for n in nodes), return_exceptions=True)
        ranked: list[tuple[float, Node]] = []
        for node, score in zip(nodes, scored):
            if isinstance(score, Exception):
                ranked.append((1_000_000.0, node))
            else:
                ranked.append((float(score), node))
        ranked.sort(key=lambda pair: pair[0])
        return ranked[0][1]

    @classmethod
    async def node_health(cls) -> list[dict[str, Any]]:
        """Return health snapshots for all connected nodes."""
        nodes = cls._connected_nodes()
        if not nodes:
            return []
        snapshots = await asyncio.gather(*(n.health_snapshot(ttl=8.0) for n in nodes), return_exceptions=True)
        output: list[dict[str, Any]] = []
        for node, item in zip(nodes, snapshots):
            if isinstance(item, Exception):
                output.append(
                    {
                        "identifier": node.identifier,
                        "uri": node.uri,
                        "status": str(node.status),
                        "players": int(node._total_player_count or len(node.players)),
                        "health_score": 1_000_000.0,
                    }
                )
            else:
                output.append(item)
        output.sort(key=lambda x: float(x.get("health_score", 1_000_000.0)))
        return output

    @classmethod
    async def diagnostics(cls) -> dict[str, Any]:
        """Return a lightweight diagnostic snapshot for logging or health endpoints."""
        nodes = cls.nodes
        connected = cls._connected_nodes()
        return {
            "library": "ravelink",
            "version": __version__,
            "nodes": len(nodes),
            "connected_nodes": len(connected),
            "players": sum(len(node._players) for node in nodes.values()),
            "cache_enabled": cls.has_cache(),
            "health": await cls.node_health(),
        }

    @classmethod
    async def migrate_player(
        cls,
        player: Player,
        *,
        target: Node | None = None,
        timeout: float = 15.0,
    ) -> tuple[bool, str]:
        """Migrate one live player to another connected node."""
        guild = player.guild
        channel = getattr(player, "channel", None)
        if guild is None or channel is None:
            return False, "missing_guild_or_channel"

        source_node = player.node
        if target is None:
            try:
                target = await cls.get_best_node(exclude={source_node.identifier})
            except InvalidNodeException:
                return False, "no_target_node"

        if target.identifier == source_node.identifier:
            return False, "same_source_target"

        # Snapshot runtime state.
        current = player.current
        position = player.position if current else 0
        paused = player.paused
        volume = player.volume
        autoplay = player.autoplay
        queue_mode = player.queue.mode
        queued_tracks = list(player.queue)
        auto_tracks = list(player.auto_queue)
        runtime_ctx = getattr(player, "ctx", None)
        filters = player.filters

        # Preserve self mute/deaf flags where possible.
        me_voice = guild.me.voice if guild.me else None
        self_deaf = bool(me_voice.self_deaf) if me_voice else True
        self_mute = bool(me_voice.self_mute) if me_voice else False

        try:
            await player.disconnect()
        except Exception:
            pass

        class TargetedPlayer(type(player)):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["nodes"] = [target]
                super().__init__(*args, **kwargs)

        try:
            await asyncio.sleep(0.35)
            new_player: Player = await channel.connect(
                cls=TargetedPlayer,
                timeout=timeout,
                reconnect=True,
                self_deaf=self_deaf,
                self_mute=self_mute,
            )
        except Exception as exc:
            return False, f"reconnect_failed:{exc}"

        try:
            new_player.ctx = runtime_ctx
            new_player.autoplay = autoplay
            new_player.queue.mode = queue_mode

            if volume != 100:
                await new_player.set_volume(volume)

            # Restore queue first, then current track state.
            if queued_tracks:
                await new_player.queue.put_wait(queued_tracks)
            if auto_tracks:
                await new_player.auto_queue.put_wait(auto_tracks)

            await new_player.set_filters(filters)

            if current:
                await new_player.play(current, start=max(0, position), paused=paused)
            elif paused:
                await new_player.pause(True)
        except Exception as exc:
            return False, f"restore_failed:{exc}"

        if target.client is not None:
            payload = PlayerFailoverEventPayload(
                old_player=player,
                player=new_player,
                source=source_node,
                target=target,
            )
            target.client.dispatch("ravelink_player_failover", payload)

        return True, "ok"

    @classmethod
    async def migrate_from_node(
        cls,
        source_identifier: str,
        *,
        target_identifier: str | None = None,
        max_players: int = 25,
    ) -> dict[str, Any]:
        """Migrate active players from a specific source node."""
        source = cls.__nodes.get(source_identifier)
        if source is None:
            return {"ok": False, "reason": "source_not_found", "migrated": 0, "failed": 0}

        if target_identifier:
            target = cls.__nodes.get(target_identifier)
            if target is None or target.status is not NodeStatus.CONNECTED:
                return {"ok": False, "reason": "target_not_connected", "migrated": 0, "failed": 0}
        else:
            try:
                target = await cls.get_best_node(exclude={source.identifier})
            except InvalidNodeException:
                return {"ok": False, "reason": "no_target_available", "migrated": 0, "failed": 0}

        players = list(source._players.values())[: max(1, max_players)]
        migrated = 0
        failed = 0
        errors: list[str] = []
        for player in players:
            ok, reason = await cls.migrate_player(player, target=target)
            if ok:
                migrated += 1
            else:
                failed += 1
                gid = getattr(getattr(player, "guild", None), "id", "unknown")
                errors.append(f"guild={gid}:{reason}")

        return {
            "ok": True,
            "source": source.identifier,
            "target": target.identifier,
            "migrated": migrated,
            "failed": failed,
            "errors": errors[:10],
        }

    @classmethod
    async def auto_failover(
        cls,
        *,
        unhealthy_score: float = 260.0,
        min_players: int = 1,
        max_players_per_node: int = 20,
    ) -> dict[str, Any]:
        """Automatically migrate players away from unhealthy nodes."""
        snapshots = await cls.node_health()
        if len(snapshots) < 2:
            return {"ok": False, "reason": "not_enough_nodes", "migrations": []}

        best = snapshots[0]
        best_id = str(best.get("identifier"))
        migrations: list[dict[str, Any]] = []

        for snap in snapshots[1:]:
            score = float(snap.get("health_score", 1_000_000.0))
            players = int(snap.get("players", 0))
            source_id = str(snap.get("identifier"))
            status = str(snap.get("status", ""))

            if "CONNECTED" not in status:
                continue
            if players < max(1, min_players):
                continue
            if score < unhealthy_score:
                continue

            result = await cls.migrate_from_node(
                source_id,
                target_identifier=best_id,
                max_players=max_players_per_node,
            )
            migrations.append(result)

        return {
            "ok": True,
            "best_node": best_id,
            "migrations": migrations,
        }

    @classmethod
    async def create_node(
        cls,
        *,
        host: str,
        port: int = 2333,
        password: str,
        identifier: str | None = None,
        secure: bool = False,
        client: discord.Client | None = None,
        session: aiohttp.ClientSession | None = None,
        heartbeat: float = 15.0,
        retries: int | None = None,
        region: str | None = None,
        resume_timeout: int = 60,
        inactive_player_timeout: int | None = 300,
        inactive_channel_tokens: int | None = 3,
        request_timeout: float = 15.0,
        request_retries: int = 2,
        request_concurrency: int = 12,
    ) -> Node:
        """Create, connect, and register one node from host-style arguments."""
        scheme = "https" if secure else "http"
        uri = host if "://" in host else f"{scheme}://{host}:{port}"
        node = Node(
            identifier=identifier,
            uri=uri,
            password=password,
            session=session,
            heartbeat=heartbeat,
            retries=retries,
            client=client,
            region=region,
            resume_timeout=resume_timeout,
            inactive_player_timeout=inactive_player_timeout,
            inactive_channel_tokens=inactive_channel_tokens,
            request_timeout=request_timeout,
            request_retries=request_retries,
            request_concurrency=request_concurrency,
        )
        await cls.connect(nodes=[node], client=client)

        if node.identifier not in cls.__nodes:
            raise NodeException(f"Failed to create and connect {node!r}.")

        return node

    @classmethod
    async def connect(
        cls, *, nodes: Iterable[Node], client: discord.Client | None = None, cache_capacity: int | None = None
    ) -> dict[str, Node]:
        """Connect the provided Iterable[:class:`Node`] to Lavalink.

        Parameters
        ----------
        nodes: Iterable[:class:`Node`]
            The :class:`Node`'s to connect to Lavalink.
        client: :class:`discord.Client` | None
            The :class:`discord.Client` to use to connect the :class:`Node`. If the Node already has a client
            set, this method will **not** override it. Defaults to None.
        cache_capacity: int | None
            An optional integer of the amount of track searches to cache. This is an experimental mode.
            Passing ``None`` will disable this experiment. Defaults to ``None``.

        Returns
        -------
        dict[str, :class:`Node`]
            A mapping of :attr:`Node.identifier` to :class:`Node` associated with the :class:`Pool`.


        Raises
        ------
        AuthorizationFailedException
            The node password was incorrect.
        InvalidClientException
            The :class:`discord.Client` passed was not valid.
        NodeException
            The node failed to connect properly. Please check that your Lavalink version is version 4.


        .. versionchanged:: v1.0.0

            The ``client`` parameter is no longer required.
            Added the ``cache_capacity`` parameter.
        """
        for node in nodes:
            client_ = node.client or client

            if node.identifier in cls.__nodes:
                msg: str = f'Unable to connect {node!r} as you already have a node with identifier "{node.identifier}"'
                logger.error(msg)

                continue

            if node.status in (NodeStatus.CONNECTING, NodeStatus.CONNECTED):
                logger.error("Unable to connect %r as it is already in a connecting or connected state.", node)
                continue

            try:
                await node._connect(client=client_)
            except InvalidClientException as e:
                logger.error(e)
            except AuthorizationFailedException:
                logger.error("Failed to authenticate %r on Lavalink with the provided password.", node)
            except NodeException:
                logger.error(
                    "Failed to connect to %r. Check that your Lavalink major version is '4' and that you are trying to connect to Lavalink on the correct port.",
                    node,
                )
            else:
                cls.__nodes[node.identifier] = node

        if cache_capacity is not None and cls.nodes:
            if cache_capacity <= 0:
                logger.warning("LFU Request cache capacity must be > 0. Not enabling cache.")

            else:
                cls.__cache = LFUCache(capacity=cache_capacity)
                logger.info("Experimental request caching has been toggled ON. To disable run Pool.toggle_cache()")

        return cls.nodes

    @classmethod
    async def reconnect(cls) -> dict[str, Node]:
        for node in cls.__nodes.values():
            if node.status is not NodeStatus.DISCONNECTED:
                continue

            try:
                await node._connect(client=None)
            except InvalidClientException as e:
                logger.error(e)
            except AuthorizationFailedException:
                logger.error("Failed to authenticate %r on Lavalink with the provided password.", node)
            except NodeException:
                logger.error(
                    "Failed to connect to %r. Check that your Lavalink major version is '4' and that you are trying to connect to Lavalink on the correct port.",
                    node,
                )

        return cls.nodes

    @classmethod
    async def close(cls) -> None:
        """Close and clean up all :class:`~ravelink.Node` on this Pool.

        This calls :meth:`ravelink.Node.close` on each node.


        .. versionadded:: v1.0.0
        """
        for node in list(cls.__nodes.values()):
            await node.close()
        cls.__nodes.clear()
        cls.__cache = None

    @classproperty
    def nodes(cls) -> dict[str, Node]:
        """A mapping of :attr:`Node.identifier` to :class:`Node` that have previously been successfully connected.


        .. versionchanged:: v1.0.0

            This property now returns a copy.
        """
        nodes = cls.__nodes.copy()
        return nodes

    @classmethod
    def get_node(cls, identifier: str | None = None, /) -> Node:
        """Retrieve a :class:`Node` from the :class:`Pool` with the given identifier.

        If no identifier is provided, this method returns the ``best`` node.

        Parameters
        ----------
        identifier: str | None
            An optional identifier to retrieve a :class:`Node`.

        Raises
        ------
        InvalidNodeException
            Raised when a Node can not be found, or no :class:`Node` exists on the :class:`Pool`.


        .. versionchanged:: v1.0.0

            The ``id`` parameter was changed to ``identifier`` and is positional only.
        """
        if identifier:
            if identifier not in cls.__nodes:
                raise InvalidNodeException(f'A Node with the identifier "{identifier}" does not exist.')

            return cls.__nodes[identifier]

        nodes: list[Node] = [n for n in cls.__nodes.values() if n.status is NodeStatus.CONNECTED]
        if not nodes:
            raise InvalidNodeException("No nodes are currently assigned to the ravelink.Pool in a CONNECTED state.")

        return sorted(nodes, key=lambda n: n._total_player_count or len(n.players))[0]

    @classmethod
    async def fetch_tracks(cls, query: str, /, *, node: Node | None = None) -> list[Playable] | Playlist:
        """Search for a list of :class:`~ravelink.Playable` or a :class:`~ravelink.Playlist`, with the given query.

        Parameters
        ----------
        query: str
            The query to search tracks for. If this is not a URL based search you should provide the appropriate search
            prefix, e.g. "ytsearch:Rick Roll"
        node: :class:`~ravelink.Node` | None
            An optional :class:`~ravelink.Node` to use when fetching tracks. Defaults to ``None``, which selects the
            most appropriate :class:`~ravelink.Node` automatically.

        Returns
        -------
        list[Playable] | Playlist
            A list of :class:`~ravelink.Playable` or a :class:`~ravelink.Playlist`
            based on your search ``query``. Could be an empty list, if no tracks were found.

        Raises
        ------
        LavalinkLoadException
            Exception raised when Lavalink fails to load results based on your query.


        .. versionchanged:: v1.0.0

            This method was previously known as both ``.get_tracks`` and ``.get_playlist``. This method now searches
            for both :class:`~ravelink.Playable` and :class:`~ravelink.Playlist` and returns the appropriate type,
            or an empty list if no results were found.

            This method no longer accepts the ``cls`` parameter.


        .. versionadded:: v1.0.0

            Added the ``node`` Keyword-Only argument.
        """

        # TODO: Documentation Extension for `.. positional-only::` marker.
        def _result_from_loaded(resp: LoadedResponse, cache_key: str) -> list[Playable] | Playlist:
            if resp["loadType"] == "track":
                track = Playable(data=resp["data"])
                if cls.__cache is not None and not track.is_stream:
                    cls.__cache.put(cache_key, [track])
                return [track]

            if resp["loadType"] == "search":
                tracks = [Playable(data=tdata) for tdata in resp["data"]]
                if cls.__cache is not None:
                    cls.__cache.put(cache_key, tracks)
                return tracks

            if resp["loadType"] == "playlist":
                playlist = Playlist(data=resp["data"])
                if cls.__cache is not None:
                    cls.__cache.put(cache_key, playlist)
                return playlist

            if resp["loadType"] == "empty":
                return []

            if resp["loadType"] == "error":
                raise LavalinkLoadException(data=resp["data"])

            return []

        is_url = "://" in query
        has_prefix = ":" in query and not is_url

        connected = cls._connected_nodes()
        if not connected:
            raise InvalidNodeException("No nodes are currently assigned to the ravelink.Pool in a CONNECTED state.")

        if node and node.status is NodeStatus.CONNECTED:
            candidates = [node] + [n for n in connected if n.identifier != node.identifier]
        else:
            primary = await cls.get_best_node(strategy="hybrid")
            candidates = [primary] + [n for n in connected if n.identifier != primary.identifier]

        # For plain text terms, try every known enabled search manager for best hit rate/quality.
        if is_url or has_prefix:
            candidate_queries = [query]
        else:
            manager_names = {manager for candidate in candidates for manager in candidate.source_managers}
            prefixes = source_search_prefixes(manager_names) or ["ytmsearch", "ytsearch", "scsearch"]
            candidate_queries = [f"{prefix}:{query}" for prefix in prefixes]

        final_load_exc: LavalinkLoadException | None = None
        for raw_query in candidate_queries:
            cache_key = raw_query.strip()

            if cls.__cache is not None:
                potential: list[Playable] | Playlist = cls.__cache.get(cache_key, None)
                if potential:
                    return potential

            for candidate in candidates:
                try:
                    resp: LoadedResponse = await candidate._fetch_tracks(raw_query)
                    result = _result_from_loaded(resp, cache_key)
                    if result:
                        return result
                except LavalinkLoadException as exc:
                    final_load_exc = exc
                    continue
                except (NodeException, LavalinkException):
                    continue
                except Exception:
                    continue

        if final_load_exc:
            raise final_load_exc
        return []

    @classmethod
    def cache(cls, capacity: int | None | bool = None) -> None:
        if capacity in (None, False):
            cls.__cache = None
            return

        if not isinstance(capacity, int):  # type: ignore
            raise ValueError("The LFU cache expects an integer, None or bool.")

        if capacity <= 0:
            cls.__cache = None
            return

        cls.__cache = LFUCache(capacity=capacity)

    @classmethod
    def has_cache(cls) -> bool:
        return cls.__cache is not None





