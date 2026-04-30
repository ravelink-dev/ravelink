"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, TypeAlias

import discord
from discord.abc import Connectable
from discord.utils import MISSING

import ravelink

from .enums import AutoPlayMode, NodeStatus, QueueMode
from .exceptions import (
    ChannelTimeoutException,
    InvalidChannelStateException,
    LavalinkException,
    LavalinkLoadException,
    NodeException,
    QueueEmpty,
    RavelinkException,
)
from .filters import Filters
from .node import Pool
from .payloads import (
    PlayerUpdateEventPayload,
    TrackEndEventPayload,
    TrackStartEventPayload,
)
from .queue import Queue
from .sources import source_search_prefixes
from .tracks import Playable, Playlist


if TYPE_CHECKING:
    from collections import deque

    from discord.abc import Connectable
    from discord.types.voice import (
        GuildVoiceState as GuildVoiceStatePayload,
        VoiceServerUpdate as VoiceServerUpdatePayload,
    )
    from typing_extensions import Self

    from .node import Node
    from .payloads import (
        PlayerUpdateEventPayload,
        TrackEndEventPayload,
        TrackStartEventPayload,
    )
    from .types.request import Request as RequestPayload
    from .types.state import PlayerVoiceState, VoiceState

    VocalGuildChannel = discord.VoiceChannel | discord.StageChannel

logger: logging.Logger = logging.getLogger(__name__)


try:
    import async_timeout
except ModuleNotFoundError:  # pragma: no cover - compatibility shim for Python 3.11+ installs
    class _AsyncTimeoutShim:
        @staticmethod
        def timeout(value: float):
            return asyncio.timeout(value)

    async_timeout = _AsyncTimeoutShim()  # type: ignore[assignment]


T_a: TypeAlias = list[Playable] | Playlist


class Player(discord.VoiceProtocol):
    """The Player is a :class:`discord.VoiceProtocol` used to connect your :class:`discord.Client` to a
    :class:`discord.VoiceChannel`.

    The player controls the music elements of the bot including playing tracks, the queue, connecting etc.
    See Also: The various methods available.

    .. note::

        Since the Player is a :class:`discord.VoiceProtocol`, it is attached to the various ``voice_client`` attributes
        in discord.py, including ``guild.voice_client``, ``ctx.voice_client`` and ``interaction.voice_client``.

    Attributes
    ----------
    queue: :class:`~ravelink.Queue`
        The queue associated with this player.
    auto_queue: :class:`~ravelink.Queue`
        The auto_queue associated with this player. This queue holds tracks that are recommended by the AutoPlay feature.
    """

    channel: VocalGuildChannel

    def __call__(self, client: discord.Client, channel: VocalGuildChannel) -> Self:
        super().__init__(client, channel)

        self._guild = channel.guild

        return self

    def __init__(
        self, client: discord.Client = MISSING, channel: Connectable = MISSING, *, nodes: list[Node] | None = None
    ) -> None:
        super().__init__(client, channel)

        self.client: discord.Client = client
        self._guild: discord.Guild | None = None

        self._voice_state: PlayerVoiceState = {"voice": {}}

        self._node: Node
        if not nodes:
            self._node = Pool.get_node()
        else:
            self._node = sorted(nodes, key=lambda n: len(n.players))[0]

        if self.client is MISSING and self.node.client:
            self.client = self.node.client

        self._last_update: int | None = None
        self._last_position: int = 0
        self._ping: int = -1

        self._connected: bool = False
        self._connection_event: asyncio.Event = asyncio.Event()
        self._operation_lock: asyncio.Lock = asyncio.Lock()
        self._destroyed: bool = False

        self._current: Playable | None = None
        self._original: Playable | None = None
        self._previous: Playable | None = None

        self.queue: Queue = Queue()
        self.auto_queue: Queue = Queue()

        self._volume: int = 100
        self._paused: bool = False

        self._auto_cutoff: int = 20
        self._auto_weight: int = 3
        self._previous_seeds_cutoff: int = self._auto_cutoff * self._auto_weight
        self._history_count: int | None = None

        self._autoplay: AutoPlayMode = AutoPlayMode.disabled
        self.__previous_seeds: asyncio.Queue[str] = asyncio.Queue(maxsize=self._previous_seeds_cutoff)

        self._auto_lock: asyncio.Lock = asyncio.Lock()
        self._error_count: int = 0

        self._inactive_channel_limit: int | None = self._node._inactive_channel_tokens
        self._inactive_channel_count: int = self._inactive_channel_limit if self._inactive_channel_limit else 0

        self._filters: Filters = Filters()

        # Needed for the inactivity checks...
        self._inactivity_task: asyncio.Task[bool] | None = None
        self._inactivity_wait: int | None = self._node._inactive_player_timeout

    def _inactivity_task_callback(self, task: asyncio.Task[bool]) -> None:
        cancelled: bool = False

        try:
            result: bool = task.result()
        except asyncio.CancelledError:
            cancelled = True
            result = False

        if cancelled or result is False:
            logger.debug("Disregarding Inactivity Check Task <%s> as it was previously cancelled.", task.get_name())
            return

        if result is not True:
            logger.debug("Disregarding Inactivity Check Task <%s> as it received an unknown result.", task.get_name())
            return

        if not self._guild:
            logger.debug("Disregarding Inactivity Check Task <%s> as it has no guild.", task.get_name())
            return

        if self.playing:
            logger.debug(
                "Disregarding Inactivity Check Task <%s> as Player <%s> is playing.", task.get_name(), self._guild.id
            )
            return

        self.client.dispatch("ravelink_inactive_player", self)
        logger.debug('Dispatched "on_ravelink_inactive_player" for Player <%s>.', self._guild.id)

    async def _inactivity_runner(self, wait: int) -> bool:
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return False

        return True

    def _inactivity_cancel(self) -> None:
        if self._inactivity_task:
            try:
                self._inactivity_task.cancel()
            except Exception:
                pass

        self._inactivity_task = None

    def _inactivity_start(self) -> None:
        if self._inactivity_wait is not None and self._inactivity_wait > 0:
            self._inactivity_task = asyncio.create_task(self._inactivity_runner(self._inactivity_wait))
            self._inactivity_task.add_done_callback(self._inactivity_task_callback)

    async def _track_start(self, payload: TrackStartEventPayload) -> None:
        self._inactivity_cancel()

    async def _auto_play_event(self, payload: TrackEndEventPayload) -> None:
        if not self.channel:
            return

        members: int = len([m for m in self.channel.members if not m.bot])
        self._inactive_channel_count = (
            self._inactive_channel_count - 1 if not members else self._inactive_channel_limit or 0
        )

        if self._inactive_channel_limit and self._inactive_channel_count <= 0:
            self._inactive_channel_count = self._inactive_channel_limit  # Reset...

            self._inactivity_cancel()
            self.client.dispatch("ravelink_inactive_player", self)

        elif self._autoplay is AutoPlayMode.disabled:
            self._inactivity_start()
            return

        if self._error_count >= 3:
            logger.warning(
                "AutoPlay was unable to continue as you have received too many consecutive errors."
                "Please check the error log on Lavalink."
            )
            self._inactivity_start()
            return

        if payload.reason == "replaced":
            self._error_count = 0
            return

        elif payload.reason == "loadFailed":
            self._error_count += 1

        else:
            self._error_count = 0

        if self.node.status is not NodeStatus.CONNECTED:
            logger.warning(
                '"Unable to use AutoPlay on Player for Guild "%s" due to disconnected Node.', str(self.guild)
            )
            return

        if not isinstance(self.queue, Queue) or not isinstance(self.auto_queue, Queue):  # type: ignore
            logger.warning(
                '"Unable to use AutoPlay on Player for Guild "%s" due to unsupported Queue.', str(self.guild)
            )
            self._inactivity_start()
            return

        if self.queue.mode is QueueMode.loop:
            await self._do_partial(history=False)

        elif self.queue.mode is QueueMode.loop_all or (self._autoplay is AutoPlayMode.partial or self.queue):
            await self._do_partial()

        elif self._autoplay is AutoPlayMode.enabled:
            async with self._auto_lock:
                await self._do_recommendation()

    async def _do_partial(self, *, history: bool = True) -> None:
        # We still do the inactivity start here since if play fails and we have no more tracks...
        # we should eventually fire the inactivity event...
        self._inactivity_start()

        if self._current is None:
            try:
                track: Playable = self.queue.get()
            except QueueEmpty:
                return

            await self.play(track, add_history=history)

    @staticmethod
    def _autoplay_query_title(track: Playable) -> str:
        author: str = (track.author or "").strip()
        title: str = (track.title or "").strip()
        return f"{author} - {title}" if author else title

    @staticmethod
    def _autoplay_identity(track: Playable) -> str:
        author = (track.author or "").strip().lower()
        title = (track.title or "").strip().lower()
        if author or title:
            return f"{author}|{title}"
        return (getattr(track, "identifier", None) or getattr(track, "encoded", None) or "").lower()

    @staticmethod
    def _source_aliases(source: str) -> set[str]:
        normalized = (source or "").strip().lower()
        aliases = {normalized}
        if normalized in {"youtube", "yt", "ytmusic", "youtube music"}:
            aliases.update({"youtube", "ytmusic"})
        elif normalized in {"applemusic", "apple music", "apple"}:
            aliases.update({"applemusic", "apple music"})
        elif normalized in {"yandexmusic", "yandex music", "yandex"}:
            aliases.update({"yandexmusic", "yandex music"})
        return aliases

    @staticmethod
    def _has_source_manager(source_managers: set[str], key: str) -> bool:
        key_ = key.strip().lower()
        return any(key_ in manager for manager in source_managers)

    def _autoplay_queries_from_track(self, track: Playable, source_managers: set[str]) -> list[str]:
        queries: list[str] = []
        source_aliases = self._source_aliases(track.source)
        manager_aliases = {manager.strip().lower() for manager in source_managers}
        has_spotify = self._has_source_manager(manager_aliases, "spotify")
        author_query = (track.author or "").strip()
        title_query = self._autoplay_query_title(track)
        if not title_query:
            return queries

        # Strong source-specific strategies.
        if "spotify" in source_aliases and track.identifier and has_spotify:
            queries.append(f"sprec:seed_tracks={track.identifier}&limit=12")
            self._add_to_previous_seeds(track.identifier)
        elif ("youtube" in source_aliases or "ytmusic" in source_aliases) and track.identifier:
            ytm_seed = track.identifier
            queries.append(f"https://music.youtube.com/watch?v={ytm_seed}&list=RD{ytm_seed}")
            self._add_to_previous_seeds(ytm_seed)

        # Artist-first fallback tends to produce related tracks instead of replaying the exact same song.
        enabled_prefixes = source_search_prefixes(manager_aliases)
        if not enabled_prefixes:
            enabled_prefixes = ["ytmsearch", "ytsearch", "scsearch"]

        if author_query:
            queries.extend(f"{prefix}:{author_query}" for prefix in enabled_prefixes)
            if "ytmsearch" in enabled_prefixes:
                queries.append(f"ytmsearch:{author_query} radio")
            if "ytsearch" in enabled_prefixes:
                queries.append(f"ytsearch:{author_query} mix")

        # Source-matched fallback if manager is enabled.
        if "soundcloud" in source_aliases:
            queries.append(f"scsearch:{author_query or title_query}")
        if "youtube" in source_aliases:
            queries.append(f"ytmsearch:{author_query or title_query}")
            queries.append(f"ytsearch:{author_query or title_query}")
        if "ytmusic" in source_aliases:
            queries.append(f"ytmsearch:{author_query or title_query}")
            queries.append(f"ytsearch:{author_query or title_query}")
        if "spotify" in source_aliases:
            queries.append(f"spsearch:{author_query or title_query}")
        if "applemusic" in source_aliases or "apple music" in source_aliases:
            queries.append(f"amsearch:{author_query or title_query}")
        if "deezer" in source_aliases:
            queries.append(f"dzsearch:{author_query or title_query}")
        if "yandexmusic" in source_aliases or "yandex music" in source_aliases:
            queries.append(f"ymsearch:{author_query or title_query}")

        # Exact title fallback goes last so we only try it after artist/radio-style discovery.
        queries.extend(f"{prefix}:{title_query}" for prefix in enabled_prefixes)

        deduped_queries: list[str] = []
        seen_queries: set[str] = set()
        for query in queries:
            normalized_query = query.strip().lower()
            if not normalized_query or normalized_query in seen_queries:
                continue
            seen_queries.add(normalized_query)
            deduped_queries.append(query)

        return deduped_queries

    async def _search_autoplay_query(self, query: str) -> list[Playable]:
        try:
            search: ravelink.Search = await Pool.fetch_tracks(query, node=self._node)
        except (LavalinkLoadException, LavalinkException):
            return []
        except Exception as exc:
            logger.debug('AutoPlay query failed for guild "%s" query "%s": %s', self.guild.id if self.guild else "?", query, exc)
            return []

        if not search:
            return []

        return search.tracks.copy() if isinstance(search, Playlist) else search

    async def _search_autoplay_queries_batched(
        self, queries: list[str], *, batch_size: int = 4
    ) -> list[list[Playable] | Exception]:
        results: list[list[Playable] | Exception] = []
        step = max(1, min(batch_size, 8))
        for idx in range(0, len(queries), step):
            chunk = queries[idx : idx + step]
            chunk_results = await asyncio.gather(
                *(self._search_autoplay_query(query) for query in chunk),
                return_exceptions=True,
            )
            results.extend(chunk_results)
        return results

    async def _do_recommendation(
        self,
        *,
        populate_track: ravelink.Playable | None = None,
        max_population: int | None = None,
    ) -> None:
        assert self.guild is not None
        assert self.queue.history is not None and self.auto_queue.history is not None

        max_population_: int = max_population if max_population else self._auto_cutoff
        source_managers = self._node.source_managers

        if len(self.auto_queue) > self._auto_cutoff + 1 and not populate_track:
            # We still do the inactivity start here since if play fails and we have no more tracks...
            # we should eventually fire the inactivity event...
            self._inactivity_start()

            track: Playable = self.auto_queue.get()
            self.auto_queue.history.put(track)

            await self.play(track, add_history=False)
            return

        weighted_history: list[Playable] = self.queue.history[::-1][: max(5, 5 * self._auto_weight)]
        weighted_upcoming: list[Playable] = self.auto_queue[: max(3, int((5 * self._auto_weight) / 3))]
        changed_history: list[Playable] = self.queue.history[::-1]
        choices: list[Playable | None] = [
            *changed_history[:3],
            *weighted_history,
            *weighted_upcoming,
            self._current,
            self._previous,
        ]

        # Filter out tracks which are None...
        _previous = {str(seed).strip().lower() for seed in self.__previous_seeds._queue if str(seed).strip()}  # type: ignore[attr-defined]
        seeds: list[Playable] = [
            t
            for t in choices
            if t is not None and (token := self._autoplay_dedupe_token(t)) is not None and token not in _previous
        ]
        random.shuffle(seeds)

        if populate_track:
            seeds.insert(0, populate_track)

        count: int = len(self.queue.history)
        changed_by: int = min(3, count) if self._history_count is None else count - self._history_count
        if changed_by > 0:
            self._history_count = count

        changed_priority = [t for t in changed_history[: max(1, min(changed_by, 3))] if t is not None]
        ordered_seeds: list[Playable] = [*changed_priority, *seeds]

        queries: list[str] = []
        seen_queries: set[str] = set()
        for seed in ordered_seeds[:12]:
            for query in self._autoplay_queries_from_track(seed, source_managers):
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                queries.append(query)
            if len(queries) >= 14:
                break

        if not queries:
            if not self.auto_queue:
                logger.info('Player "%s" could not build autoplay queries.', self.guild.id)
                self._inactivity_start()
            return

        raw_results = await self._search_autoplay_queries_batched(queries, batch_size=4)

        filtered_r: list[Playable] = []
        for result in raw_results:
            if isinstance(result, Exception):
                continue
            filtered_r.extend(result)

        if not filtered_r and not self.auto_queue:
            logger.info('Player "%s" could not load any songs via AutoPlay.', self.guild.id)
            self._inactivity_start()
            return

        history: list[Playable] = (
            self.auto_queue[:40] + self.queue[:40] + self.queue.history[:-41:-1] + self.auto_queue.history[:-61:-1]
        )
        history_encoded: set[str] = {h.encoded for h in history if getattr(h, "encoded", None)}
        history_identifiers: set[str] = {h.identifier for h in history if getattr(h, "identifier", None)}
        history_identities: set[str] = {identity for h in history if (identity := self._autoplay_identity(h))}
        current_encoded = self._current.encoded if self._current and getattr(self._current, "encoded", None) else None
        current_identity = self._autoplay_identity(self._current) if self._current else None

        added: int = 0

        random.shuffle(filtered_r)
        for track in filtered_r:
            identity = self._autoplay_identity(track)
            if current_encoded and track.encoded == current_encoded:
                continue
            if current_identity and identity == current_identity:
                continue
            if track.encoded in history_encoded or track.identifier in history_identifiers or identity in history_identities:
                continue

            track._recommended = True
            added += await self.auto_queue.put_wait(track)
            history_encoded.add(track.encoded)
            history_identifiers.add(track.identifier)
            history_identities.add(identity)

            if added >= max_population_:
                break

        logger.debug('Player "%s" added "%s" tracks to the auto_queue via AutoPlay.', self.guild.id, added)

        if not self._current and not populate_track:
            try:
                now: Playable = self.auto_queue.get()
                self.auto_queue.history.put(now)

                await self.play(now, add_history=False)
            except ravelink.QueueEmpty:
                logger.info('Player "%s" could not load any songs via AutoPlay.', self.guild.id)
                self._inactivity_start()

    @property
    def inactive_channel_tokens(self) -> int | None:
        """A settable property which returns the token limit as an ``int`` of the amount of tracks to play before firing
        the :func:`on_ravelink_inactive_player` event when a channel is inactive.

        This property could return ``None`` if the check has been disabled.

        A channel is considered inactive when no real members (Members other than bots) are in the connected voice
        channel. On each consecutive track played without a real member in the channel, this token bucket will reduce
        by ``1``. After hitting ``0``, the :func:`on_ravelink_inactive_player` event will be fired and the token bucket
        will reset to the set value. The default value for this property is ``3``.

        This property can be set with any valid ``int`` or ``None``. If this property is set to ``<= 0`` or ``None``,
        the check will be disabled.

        Setting this property to ``1`` will fire the :func:`on_ravelink_inactive_player` event at the end of every track
        if no real members are in the channel and you have not disconnected the player.

        If this check successfully fires the :func:`on_ravelink_inactive_player` event, it will cancel any waiting
        :attr:`inactive_timeout` checks until a new track is played.

        The default for every player can be set on :class:`~ravelink.Node`.

        - See: :class:`~ravelink.Node`
        - See: :func:`on_ravelink_inactive_player`

        .. warning::

            Setting this property will reset the bucket.

        .. versionadded:: v1.0.0
        """
        return self._inactive_channel_limit

    @inactive_channel_tokens.setter
    def inactive_channel_tokens(self, value: int | None) -> None:
        if not value or value <= 0:
            self._inactive_channel_limit = None
            return

        self._inactive_channel_limit = value
        self._inactive_channel_count = value

    @property
    def inactive_timeout(self) -> int | None:
        """A property which returns the time as an ``int`` of seconds to wait before this player dispatches the
        :func:`on_ravelink_inactive_player` event.

        This property could return ``None`` if no time has been set.

        An inactive player is a player that has not been playing anything for the specified amount of seconds.

        - Pausing the player while a song is playing will not activate this countdown.
        - The countdown starts when a track ends and cancels when a track starts.
        - The countdown will not trigger until a song is played for the first time or this property is reset.
        - The default countdown for all players is set on :class:`~ravelink.Node`.

        This property can be set with a valid ``int`` of seconds to wait before dispatching the
        :func:`on_ravelink_inactive_player` event or ``None`` to remove the timeout.


        .. warning::

            Setting this to a value of ``0`` or below is the equivalent of setting this property to ``None``.


        When this property is set, the timeout will reset, and all previously waiting countdowns are cancelled.

        - See: :class:`~ravelink.Node`
        - See: :func:`on_ravelink_inactive_player`


        .. versionadded:: v1.0.0
        """
        return self._inactivity_wait

    @inactive_timeout.setter
    def inactive_timeout(self, value: int | None) -> None:
        if not value or value <= 0:
            self._inactivity_wait = None
            self._inactivity_cancel()
            return

        if value < 10:
            logger.warning('Setting "inactive_timeout" below 10 seconds may result in unwanted side effects.')

        self._inactivity_wait = value
        self._inactivity_cancel()

        if self.connected and not self.playing:
            self._inactivity_start()

    @property
    def autoplay(self) -> AutoPlayMode:
        """A property which returns the :class:`ravelink.AutoPlayMode` the player is currently in.

        This property can be set with any :class:`ravelink.AutoPlayMode` enum value.


        .. versionchanged:: v1.0.0

            This property now accepts and returns a :class:`ravelink.AutoPlayMode` enum value.
        """
        return self._autoplay

    @autoplay.setter
    def autoplay(self, value: Any) -> None:
        if not isinstance(value, AutoPlayMode):
            raise ValueError("Please provide a valid 'ravelink.AutoPlayMode' to set.")

        self._autoplay = value

    @property
    def node(self) -> Node:
        """The :class:`Player`'s currently selected :class:`Node`.


        .. versionchanged:: v1.0.0

            This property was previously known as ``current_node``.
        """
        return self._node

    @property
    def guild(self) -> discord.Guild | None:
        """Returns the :class:`Player`'s associated :class:`discord.Guild`.

        Could be None if this :class:`Player` has not been connected.
        """
        return self._guild

    @property
    def connected(self) -> bool:
        """Returns a bool indicating if the player is currently connected to a voice channel.

        .. versionchanged:: v1.0.0

            This property was previously known as ``is_connected``.
        """
        channel_id = self._voice_state.get("channel_id") or self._voice_state["voice"].get("channel_id")
        return self._connected and (bool(channel_id) or bool(self.channel))

    @property
    def current(self) -> Playable | None:
        """Returns the currently playing :class:`~ravelink.Playable` or None if no track is playing."""
        return self._current

    @property
    def volume(self) -> int:
        """Returns an int representing the currently set volume, as a percentage.

        See: :meth:`set_volume` for setting the volume.
        """
        return self._volume

    @property
    def filters(self) -> Filters:
        """Property which returns the :class:`~ravelink.Filters` currently assigned to the Player.

        See: :meth:`~ravelink.Player.set_filters` for setting the players filters.

        .. versionchanged:: v1.0.0

            This property was previously known as ``filter``.
        """
        return self._filters

    @property
    def paused(self) -> bool:
        """Returns the paused status of the player. A currently paused player will return ``True``.

        See: :meth:`pause` and :meth:`play` for setting the paused status.
        """
        return self._paused

    @property
    def ping(self) -> int:
        """Returns the ping in milliseconds as int between your connected Lavalink Node and Discord (Players Channel).

        Returns ``-1`` if no player update event has been received or the player is not connected.
        """
        return self._ping

    @property
    def playing(self) -> bool:
        """Returns whether the :class:`~Player` is currently playing a track and is connected.

        Due to relying on validation from Lavalink, this property may in some cases return ``True`` directly after
        skipping/stopping a track, although this is not the case when disconnecting the player.

        This property will return ``True`` in cases where the player is paused *and* has a track loaded.

        .. versionchanged:: v1.0.0

            This property used to be known as the `is_playing()` method.
        """
        return self._connected and self._current is not None

    @property
    def position(self) -> int:
        """Returns the position of the currently playing :class:`~ravelink.Playable` in milliseconds.

        This property relies on information updates from Lavalink.

        In cases there is no :class:`~ravelink.Playable` loaded or the player is not connected,
        this property will return ``0``.

        This property will return ``0`` if no update has been received from Lavalink.

        .. versionchanged:: v1.0.0

            This property now uses a monotonic clock.
        """
        if self.current is None or not self.playing:
            return 0

        if not self.connected:
            return 0

        if self._last_update is None:
            return 0

        if self.paused:
            return self._last_position

        position: int = int((time.monotonic_ns() - self._last_update) / 1000000) + self._last_position
        return min(position, self.current.length)

    def snapshot(self) -> dict[str, Any]:
        """Return a lightweight, JSON-shaped snapshot of this player's runtime state."""
        history = list(self.queue.history) if self.queue.history is not None else []
        auto_history = list(self.auto_queue.history) if self.auto_queue.history is not None else []
        channel = self.channel if getattr(self, "channel", MISSING) is not MISSING else None
        voice_channel_id = (
            channel.id
            if channel
            else self._voice_state.get("channel_id") or self._voice_state["voice"].get("channel_id")
        )

        def track_payload(track: Playable | None) -> dict[str, Any] | None:
            if track is None:
                return None
            return {
                "encoded": track.encoded,
                "identifier": track.identifier,
                "title": track.title,
                "author": track.author,
                "uri": track.uri,
                "source_name": track.source,
                "length": track.length,
                "is_stream": track.is_stream,
                "is_seekable": track.is_seekable,
                "artwork_url": track.artwork,
                "isrc": track.isrc,
                "position": track.position,
                "extras": dict(track.extras),
            }

        return {
            "guild_id": self.guild.id if self.guild else None,
            "voice_channel_id": voice_channel_id,
            "node_id": self.node.identifier,
            "current_track": track_payload(self.current),
            "previous_track": track_payload(self._previous),
            "position": self.position,
            "volume": self.volume,
            "paused": self.paused,
            "connected": self.connected,
            "filters": self.filters(),
            "queue": [track_payload(track) for track in self.queue],
            "history": [track_payload(track) for track in history],
            "auto_queue": [track_payload(track) for track in self.auto_queue],
            "auto_history": [track_payload(track) for track in auto_history],
            "autoplay": self.autoplay.name,
            "loop_mode": self.queue.mode.name,
            "queue_policy": self.queue.policy.value,
            "last_update": time.time(),
        }

    async def _update_event(self, payload: PlayerUpdateEventPayload) -> None:
        # Convert nanoseconds into milliseconds...
        self._last_update = time.monotonic_ns()
        self._last_position = payload.position

        self._ping = payload.ping

    async def on_voice_state_update(self, data: GuildVoiceStatePayload, /) -> None:
        channel_id = data["channel_id"]

        if not channel_id:
            await self._destroy()
            return

        self._connected = True

        self._voice_state["voice"]["session_id"] = data["session_id"]
        self._voice_state["voice"]["channel_id"] = str(channel_id)
        self._voice_state["channel_id"] = str(channel_id)
        self.channel = self.client.get_channel(int(channel_id))  # type: ignore

    async def on_voice_server_update(self, data: VoiceServerUpdatePayload, /) -> None:
        self._voice_state["voice"]["token"] = data["token"]
        self._voice_state["voice"]["endpoint"] = data["endpoint"]

        await self._dispatch_voice_update()

    async def _dispatch_voice_update(self) -> None:
        assert self.guild is not None
        data: VoiceState = self._voice_state["voice"]

        session_id: str | None = data.get("session_id", None)
        token: str | None = data.get("token", None)
        endpoint: str | None = data.get("endpoint", None)

        channel_id = data.get("channel_id") or self._voice_state.get("channel_id")
        if channel_id is None and self.channel:
            channel_id = str(self.channel.id)

        if not session_id or not token or not endpoint or not channel_id:
            return

        try:
            await self.node.voice_update(
                self.guild.id,
                session_id=session_id,
                token=token,
                endpoint=endpoint,
                channel_id=channel_id,
            )
        except LavalinkException:
            try:
                await self.disconnect()
            except RavelinkException:
                logger.debug("Failed to disconnect player after Lavalink rejected the voice update.", exc_info=True)
        except NodeException:
            logger.warning("Unable to dispatch VOICE_UPDATE for guild %s to Lavalink.", self.guild.id, exc_info=True)
        else:
            self._connection_event.set()

        logger.debug("Player %s is dispatching VOICE_UPDATE.", self.guild.id)

    async def _dave_transition(self) -> None:
        """Refresh Lavalink voice state after Discord signals a DAVE transition."""
        if not self.connected or self.guild is None:
            return

        await asyncio.sleep(0.25)
        await self._dispatch_voice_update()

    async def connect(
        self, *, timeout: float = 10.0, reconnect: bool, self_deaf: bool = False, self_mute: bool = False
    ) -> None:
        """

        .. warning::

            Do not use this method directly on the player. See: :meth:`discord.VoiceChannel.connect` for more details.


        Pass the :class:`ravelink.Player` to ``cls=`` in :meth:`discord.VoiceChannel.connect`.


        Raises
        ------
        ChannelTimeoutException
            Connecting to the voice channel timed out.
        InvalidChannelStateException
            You tried to connect this player without an appropriate voice channel.
        """
        if self.channel is MISSING:
            msg: str = 'Please use "discord.VoiceChannel.connect(cls=...)" and pass this Player to cls.'
            raise InvalidChannelStateException(f"Player tried to connect without a valid channel: {msg}")

        if not self._guild:
            self._guild = self.channel.guild

        self._destroyed = False
        self._connection_event.clear()
        self.node.add_player(self._guild.id, self)

        assert self.guild is not None
        await self.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)

        try:
            async with async_timeout.timeout(timeout):
                await self._connection_event.wait()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.node.remove_player(self._guild.id)
            try:
                await self.guild.change_voice_state(channel=None)
            except Exception:
                logger.debug("Failed to leave voice after player connection timeout.", exc_info=True)

            msg = f"Unable to connect to {self.channel} as it exceeded the timeout of {timeout} seconds."
            raise ChannelTimeoutException(msg)

    async def move_to(
        self,
        channel: VocalGuildChannel | None,
        *,
        timeout: float = 10.0,
        self_deaf: bool | None = None,
        self_mute: bool | None = None,
    ) -> None:
        """Method to move the player to another channel.

        Parameters
        ----------
        channel: :class:`discord.VoiceChannel` | :class:`discord.StageChannel`
            The new channel to move to.
        timeout: float
            The timeout in ``seconds`` before raising. Defaults to 10.0.
        self_deaf: bool | None
            Whether to deafen when moving. Defaults to ``None`` which keeps the current setting or ``False``
            if they can not be determined.
        self_mute: bool | None
            Whether to self mute when moving. Defaults to ``None`` which keeps the current setting or ``False``
            if they can not be determined.

        Raises
        ------
        ChannelTimeoutException
            Connecting to the voice channel timed out.
        InvalidChannelStateException
            You tried to connect this player without an appropriate guild.
        """
        if not self.guild:
            raise InvalidChannelStateException("Player tried to move without a valid guild.")

        self._connection_event.clear()
        voice: discord.VoiceState | None = self.guild.me.voice

        if self_deaf is None and voice:
            self_deaf = voice.self_deaf

        if self_mute is None and voice:
            self_mute = voice.self_mute

        self_deaf = bool(self_deaf)
        self_mute = bool(self_mute)

        await self.guild.change_voice_state(channel=channel, self_mute=self_mute, self_deaf=self_deaf)

        if channel is None:
            return

        try:
            async with async_timeout.timeout(timeout):
                await self._connection_event.wait()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            msg = f"Unable to connect to {channel} as it exceeded the timeout of {timeout} seconds."
            raise ChannelTimeoutException(msg)

    async def play(
        self,
        track: Playable,
        *,
        replace: bool = True,
        start: int = 0,
        end: int | None = None,
        volume: int | None = None,
        paused: bool | None = None,
        add_history: bool = True,
        filters: Filters | None = None,
        populate: bool = False,
        max_populate: int = 5,
    ) -> Playable:
        """Play the provided :class:`~ravelink.Playable`.

        Parameters
        ----------
        track: :class:`~ravelink.Playable`
            The track to being playing.
        replace: bool
            Whether this track should replace the currently playing track, if there is one. Defaults to ``True``.
        start: int
            The position to start playing the track at in milliseconds.
            Defaults to ``0`` which will start the track from the beginning.
        end: Optional[int]
            The position to end the track at in milliseconds.
            Defaults to ``None`` which means this track will play until the very end.
        volume: Optional[int]
            Sets the volume of the player. Must be between ``0`` and ``1000``.
            Defaults to ``None`` which will not change the current volume.
            See Also: :meth:`set_volume`
        paused: bool | None
            Whether the player should be paused, resumed or retain current status when playing this track.
            Setting this parameter to ``True`` will pause the player. Setting this parameter to ``False`` will
            resume the player if it is currently paused. Setting this parameter to ``None`` will not change the status
            of the player. Defaults to ``None``.
        add_history: Optional[bool]
            If this argument is set to ``True``, the :class:`~Player` will add this track into the
            :class:`ravelink.Queue` history, if loading the track was successful. If ``False`` this track will not be
            added to your history. This does not directly affect the ``AutoPlay Queue`` but will alter how ``AutoPlay``
            recommends songs in the future. Defaults to ``True``.
        filters: Optional[:class:`~ravelink.Filters`]
            An Optional[:class:`~ravelink.Filters`] to apply when playing this track. Defaults to ``None``.
            If this is ``None`` the currently set filters on the player will be applied.
        populate: bool
            Whether the player should find and fill AutoQueue with recommended tracks based on the track provided.
            Defaults to ``False``.

            Populate will only search for recommended tracks when the current tracks has been accepted by Lavalink.
            E.g. if this method does not raise an error.

            You should consider when you use the ``populate`` keyword argument as populating the AutoQueue on every
            request could potentially lead to a large amount of tracks being populated.
        max_populate: int
            The maximum amount of tracks that should be added to the AutoQueue when the ``populate`` keyword argument is
            set to ``True``. This is NOT the exact amount of tracks that will be added. You should set this to a lower
            amount to avoid the AutoQueue from being overfilled.

            This argument has no effect when ``populate`` is set to ``False``.

            Defaults to ``5``.


        Returns
        -------
        :class:`~ravelink.Playable`
            The track that began playing.


        .. versionchanged:: v1.0.0

            Added the ``paused`` parameter. Parameters ``replace``, ``start``, ``end``, ``volume`` and ``paused``
            are now all keyword-only arguments.

            Added the ``add_history`` keyword-only argument.

            Added the ``filters`` keyword-only argument.


        .. versionchanged:: v1.0.0

            Added the ``populate`` keyword-only argument.
        """
        assert self.guild is not None

        original_vol: int = self._volume
        vol: int = volume or self._volume

        if vol != self._volume:
            self._volume = vol

        if replace or not self._current:
            self._current = track
            self._original = track

        old_previous = self._previous
        self._previous = self._current
        self.queue._loaded = track

        pause: bool = paused if paused is not None else self._paused

        if filters:
            self._filters = filters

        request: RequestPayload = {
            "track": {"encoded": track.encoded, "userData": dict(track.extras)},
            "volume": vol,
            "position": start,
            "endTime": end,
            "paused": pause,
            "filters": self._filters(),
        }

        try:
            async with self._operation_lock:
                await self.node._update_player(self.guild.id, data=request, replace=replace)
                self._paused = pause
        except LavalinkException as e:
            self.queue._loaded = old_previous
            self._current = None
            self._original = None
            self._previous = old_previous
            self._volume = original_vol
            raise e

        if add_history:
            assert self.queue.history is not None
            self.queue.history.put(track)

        if populate:
            await self._do_recommendation(populate_track=track, max_population=max_populate)

        return track

    async def pause(self, value: bool = True, /) -> None:
        """Set the paused or resume state of the player.

        Parameters
        ----------
        value: bool
            A bool indicating whether the player should be paused or resumed. True indicates that the player should be
            ``paused``. False will resume the player if it is currently paused.


        .. versionchanged:: v1.0.0

            This method now expects a positional-only bool value. The ``resume`` method has been removed.
        """
        assert self.guild is not None

        request: RequestPayload = {"paused": value}
        async with self._operation_lock:
            await self.node._update_player(self.guild.id, data=request)
            self._paused = value

    async def resume(self) -> None:
        """Resume playback.

        This is a convenience alias for ``await player.pause(False)``.
        """
        await self.pause(False)

    async def seek(self, position: int = 0, /) -> None:
        """Seek to the provided position in the currently playing track, in milliseconds.

        Parameters
        ----------
        position: int
            The position to seek to in milliseconds. To restart the song from the beginning,
            you can disregard this parameter or set position to 0.


        .. versionchanged:: v1.0.0

            The ``position`` parameter is now positional-only, and has a default of 0.
        """
        assert self.guild is not None

        if not self._current:
            return

        request: RequestPayload = {"position": position}
        async with self._operation_lock:
            await self.node._update_player(self.guild.id, data=request)

    async def set_filters(self, filters: Filters | None = None, /, *, seek: bool = False) -> None:
        """Set the :class:`ravelink.Filters` on the player.

        Parameters
        ----------
        filters: Optional[:class:`~ravelink.Filters`]
            The filters to set on the player. Could be ``None`` to reset the currently applied filters.
            Defaults to ``None``.
        seek: bool
            Whether to seek immediately when applying these filters. Seeking uses more resources, but applies the
            filters immediately. Defaults to ``False``.


        .. versionchanged:: v1.0.0

            This method now accepts a positional-only argument of filters, which now defaults to None. Filters
            were redesigned in this version, see: :class:`ravelink.Filters`.


        .. versionchanged:: v1.0.0

            This method was previously known as ``set_filter``.
        """
        assert self.guild is not None

        if filters is None:
            filters = Filters()

        request: RequestPayload = {"filters": filters()}
        async with self._operation_lock:
            await self.node._update_player(self.guild.id, data=request)
            self._filters = filters

        if self.playing and seek:
            await self.seek(self.position)

    async def set_volume(self, value: int = 100, /) -> None:
        """Set the :class:`Player` volume, as a percentage, between 0 and 1000.

        By default, every player is set to 100 on creation. If a value outside 0 to 1000 is provided it will be
        clamped.

        Parameters
        ----------
        value: int
            A volume value between 0 and 1000. To reset the player to 100, you can disregard this parameter.


        .. versionchanged:: v1.0.0

            The ``value`` parameter is now positional-only, and has a default of 100.
        """
        assert self.guild is not None
        vol: int = max(min(value, 1000), 0)

        request: RequestPayload = {"volume": vol}
        async with self._operation_lock:
            await self.node._update_player(self.guild.id, data=request)
            self._volume = vol

    async def disconnect(self, **kwargs: Any) -> None:
        """Disconnect the player from the current voice channel and remove it from the :class:`~ravelink.Node`.

        This method will cause any playing track to stop and potentially trigger the following events:

            - ``on_ravelink_track_end``
            - ``on_ravelink_websocket_closed``


        .. warning::

            Please do not re-use a :class:`Player` instance that has been disconnected, unwanted side effects are
            possible.
        """
        assert self.guild

        async with self._operation_lock:
            await self._destroy()
            await self.guild.change_voice_state(channel=None)

    async def stop(self, *, force: bool = True) -> Playable | None:
        """An alias to :meth:`skip`.

        See Also: :meth:`skip` for more information.

        .. versionchanged:: v1.0.0

            This method is now known as ``skip``, but the alias ``stop`` has been kept for backwards compatibility.
        """
        return await self.skip(force=force)

    async def skip(self, *, force: bool = True) -> Playable | None:
        """Stop playing the currently playing track.

        Parameters
        ----------
        force: bool
            Whether the track should skip looping, if :class:`ravelink.Queue` has been set to loop.
            Defaults to ``True``.

        Returns
        -------
        :class:`~ravelink.Playable` | None
            The currently playing track that was skipped, or ``None`` if no track was playing.


        .. versionchanged:: v1.0.0

            This method was previously known as ``stop``. To avoid confusion this method is now known as ``skip``.
            This method now returns the :class:`~ravelink.Playable` that was skipped.
        """
        assert self.guild is not None
        old: Playable | None = self._current

        if force:
            self.queue._loaded = None

        request: RequestPayload = {"track": {"encoded": None}}
        async with self._operation_lock:
            await self.node._update_player(self.guild.id, data=request, replace=True)

        return old

    def _invalidate(self) -> None:
        self._connected = False
        self._connection_event.clear()
        self._inactivity_cancel()

        try:
            self.cleanup()
        except (AttributeError, KeyError):
            pass

    async def _destroy(self) -> None:
        assert self.guild
        if self._destroyed:
            return
        self._destroyed = True

        self._invalidate()
        player: Player | None = self.node.remove_player(self.guild.id)

        if player:
            try:
                await self.node._destroy_player(self.guild.id)
            except RavelinkException:
                pass

    def _add_to_previous_seeds(self, seed: str) -> None:
        # Helper method to manage previous seeds.
        if not seed:
            return
        if self.__previous_seeds.full():
            self.__previous_seeds.get_nowait()
        self.__previous_seeds.put_nowait(seed)

    @staticmethod
    def _autoplay_dedupe_token(track: Playable) -> str | None:
        for value in (
            getattr(track, "encoded", None),
            getattr(track, "identifier", None),
            Player._autoplay_identity(track),
        ):
            normalized = (value or "").strip().lower()
            if normalized:
                return normalized
        return None
