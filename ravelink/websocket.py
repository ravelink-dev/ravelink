"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from . import __version__
from .backoff import Backoff
from .enums import NodeStatus
from .exceptions import AuthorizationFailedException, InvalidClientException, NodeException
from .payloads import *
from .tracks import Playable


if TYPE_CHECKING:
    from .node import Node
    from .player import Player
    from .types.request import UpdateSessionRequest
    from .types.response import InfoResponse
    from .types.state import PlayerState
    from .types.websocket import TrackExceptionPayload, WebsocketOP


logger: logging.Logger = logging.getLogger(__name__)


class Websocket:
    def __init__(self, *, node: Node) -> None:
        self.node = node

        self.backoff: Backoff = Backoff()

        self.socket: aiohttp.ClientWebSocketResponse | None = None
        self.keep_alive_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._closed_finally: bool = False

    @property
    def headers(self) -> dict[str, str]:
        if self.node.client is None or self.node.client.user is None:
            msg = f"Unable to build websocket headers for {self.node!r} without a ready client user."
            raise InvalidClientException(msg)

        data = {
            "Authorization": self.node.password,
            "User-Id": str(self.node.client.user.id),
            "Client-Name": f"Ravelink/{__version__}",
        }

        if self.node.session_id:
            data["Session-Id"] = self.node.session_id

        return data

    def is_connected(self) -> bool:
        return self.socket is not None and not self.socket.closed

    async def _update_node(self) -> None:
        if self.node._resume_timeout > 0:
            udata: UpdateSessionRequest = {"resuming": True, "timeout": self.node._resume_timeout}
            await self.node._update_session(data=udata)

        info: InfoResponse = await self.node._fetch_info()
        self.node._source_managers = {manager.lower() for manager in info.get("sourceManagers", [])}
        self.node._spotify_enabled = "spotify" in self.node._source_managers
        self.node._update_capabilities_from_info(InfoResponsePayload(info))

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._closed_finally:
                return

            self.node._status = NodeStatus.CONNECTING

            if self.keep_alive_task:
                try:
                    self.keep_alive_task.cancel()
                except Exception as e:
                    logger.debug(
                        "Failed to cancel websocket keep alive while connecting. "
                        "This is most likely not a problem and will not affect websocket connection: '%s'",
                        e,
                    )

            retries: int | None = self.node._retries
            session: aiohttp.ClientSession = self.node._ensure_session()
            heartbeat: float = self.node.heartbeat
            uri: str = f"{self.node.uri.removesuffix('/')}/v4/websocket"
            github: str = "https://github.com/ravelink-dev/ravelink/issues"

            while True:
                try:
                    self.socket = await session.ws_connect(  # type: ignore
                        url=uri,
                        heartbeat=heartbeat,
                        headers=self.headers,
                    )
                except Exception as e:
                    if isinstance(e, aiohttp.WSServerHandshakeError) and e.status == 401:
                        await self.cleanup(clear_players=False, final=True)
                        raise AuthorizationFailedException from e
                    elif isinstance(e, aiohttp.WSServerHandshakeError) and e.status == 404:
                        await self.cleanup(clear_players=False, final=True)
                        raise NodeException from e
                    else:
                        logger.warning(
                            'An unexpected error occurred while connecting %r to Lavalink: "%s"\n'
                            "If this error persists or Ravelink is unable to reconnect, please see: %s",
                            self.node,
                            e,
                            github,
                        )

                if self.is_connected():
                    self.keep_alive_task = asyncio.create_task(self.keep_alive())
                    self.backoff = Backoff()
                    break

                if retries == 0:
                    msg = (
                        f"{self.node!r} was unable to connect to Lavalink after exhausting "
                        "the configured retry count."
                    )
                    logger.warning(
                        '%r was unable to successfully connect/reconnect to Lavalink after "%s" connection attempt. '
                        "This Node has exhausted the retry count.",
                        self.node,
                        retries + 1,
                    )

                    await self.cleanup(clear_players=False, final=False)
                    raise NodeException(msg)

                if retries:
                    retries -= 1

                delay: float = self.backoff.calculate()
                logger.info('%r retrying websocket connection in "%s" seconds.', self.node, delay)

                await asyncio.sleep(delay)

    def _schedule_reconnect(self) -> None:
        if self._closed_finally:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self.node._status = NodeStatus.DISCONNECTED
        self.dispatch("node_disconnected", self.node)
        self._reconnect_task = asyncio.create_task(self.connect())
        self._reconnect_task.add_done_callback(self._log_background_exception)

    async def keep_alive(self) -> None:
        assert self.socket is not None

        try:
            while True:
                message: aiohttp.WSMessage = await self.socket.receive()

                if message.type in (  # pyright: ignore[reportUnknownMemberType]
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    self._schedule_reconnect()
                    break

                if message.data is None:  # pyright: ignore[reportUnknownMemberType]
                    logger.debug("Received an empty message from Lavalink websocket. Disregarding.")
                    continue

                try:
                    data: WebsocketOP = message.json()
                except Exception:
                    logger.debug("Received a malformed websocket payload from Lavalink.", exc_info=True)
                    continue

                try:
                    await self._handle_payload(data)
                except Exception:
                    op = data.get("op") if isinstance(data, dict) else None
                    logger.warning("Failed to process Lavalink websocket payload.", exc_info=True)
                    if op == "ready":
                        self._schedule_reconnect()
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Ravelink websocket listener crashed for %r; scheduling reconnect.",
                self.node,
                exc_info=True,
            )
            self._schedule_reconnect()

    async def _handle_payload(self, data: WebsocketOP) -> None:
        if not isinstance(data, dict):
            logger.debug("Received a non-object websocket payload from Lavalink. Disregarding.")
            return

        op = data.get("op")

        if op == "ready":
            resumed: bool = data["resumed"]
            session_id: str = data["sessionId"]

            self.node._status = NodeStatus.CONNECTED
            self.node._session_id = session_id

            await self._update_node()

            ready_payload: NodeReadyEventPayload = NodeReadyEventPayload(
                node=self.node, resumed=resumed, session_id=session_id
            )
            self.dispatch("node_ready", ready_payload)

        elif op == "playerUpdate":
            playerup: Player | None = self.get_player(data["guildId"])
            state: PlayerState = data["state"]

            updatepayload: PlayerUpdateEventPayload = PlayerUpdateEventPayload(player=playerup, state=state)
            self.dispatch("player_update", updatepayload)

            if playerup:
                await playerup._update_event(updatepayload)

        elif op == "stats":
            statspayload: StatsEventPayload = StatsEventPayload(data=data)
            self.node._total_player_count = statspayload.players
            self.dispatch("stats_update", statspayload)

        elif op == "event":
            player: Player | None = self.get_player(data["guildId"])

            if data["type"] == "TrackStartEvent":
                track: Playable = Playable(data["track"])

                startpayload: TrackStartEventPayload = TrackStartEventPayload(player=player, track=track)
                self.dispatch("track_start", startpayload)

                if player:
                    await player._track_start(startpayload)

            elif data["type"] == "TrackEndEvent":
                track: Playable = Playable(data["track"])
                reason: str = data["reason"]

                if player and reason != "replaced":
                    player._current = None

                endpayload: TrackEndEventPayload = TrackEndEventPayload(player=player, track=track, reason=reason)
                self.dispatch("track_end", endpayload)

                if player:
                    task = asyncio.create_task(player._auto_play_event(endpayload))
                    task.add_done_callback(self._log_background_exception)

            elif data["type"] == "TrackExceptionEvent":
                track: Playable = Playable(data["track"])
                exception: TrackExceptionPayload = data["exception"]

                excpayload: TrackExceptionEventPayload = TrackExceptionEventPayload(
                    player=player, track=track, exception=exception
                )
                self.dispatch("track_exception", excpayload)

            elif data["type"] == "TrackStuckEvent":
                track: Playable = Playable(data["track"])
                threshold: int = data["thresholdMs"]

                stuckpayload: TrackStuckEventPayload = TrackStuckEventPayload(
                    player=player, track=track, threshold=threshold
                )
                self.dispatch("track_stuck", stuckpayload)

            elif data["type"] == "WebSocketClosedEvent":
                code: int = data["code"]
                reason: str = data["reason"]
                by_remote: bool = data["byRemote"]

                wcpayload: WebsocketClosedEventPayload = WebsocketClosedEventPayload(
                    player=player, code=code, reason=reason, by_remote=by_remote
                )
                self.dispatch("websocket_closed", wcpayload)
                if player and wcpayload.is_dave_transition:
                    task = asyncio.create_task(player._dave_transition())
                    task.add_done_callback(self._log_background_exception)

            else:
                other_payload: ExtraEventPayload = ExtraEventPayload(node=self.node, player=player, data=data)
                self.dispatch("extra_event", other_payload)
        else:
            logger.debug("Received an unknown OP from Lavalink '%s'. Disregarding.", op)

    @staticmethod
    def _log_background_exception(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.debug("Background player event task failed.", exc_info=True)

    def get_player(self, guild_id: str | int) -> Player | None:
        return self.node.get_player(int(guild_id))

    def dispatch(self, event: str, /, *args: Any, **kwargs: Any) -> None:
        assert self.node.client is not None

        self.node.client.dispatch(f"ravelink_{event}", *args, **kwargs)
        logger.debug("%r dispatched the event 'on_ravelink_%s'", self.node, event)

    async def cleanup(self, *, clear_players: bool = False, final: bool = False) -> None:
        self._closed_finally = final

        current = asyncio.current_task()
        if self.keep_alive_task and self.keep_alive_task is not current:
            try:
                self.keep_alive_task.cancel()
            except Exception:
                pass
        if final and self._reconnect_task and self._reconnect_task is not current:
            try:
                self._reconnect_task.cancel()
            except Exception:
                pass

        if self.socket:
            try:
                await self.socket.close()
            except Exception:
                pass

        self.node._status = NodeStatus.DISCONNECTED
        self.node._session_id = None
        if clear_players:
            self.node._players = {}

        self.node._websocket = None

        logger.debug("Successfully cleaned up the websocket for %r", self.node)





