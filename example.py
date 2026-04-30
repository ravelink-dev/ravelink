"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

import ravelink


logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("DISCORD_TOKEN", "")
LAVALINK_URI = os.getenv("LAVALINK_URI", "http://localhost:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_player(ctx: commands.Context) -> ravelink.Player | None:
    return ctx.voice_client if isinstance(ctx.voice_client, ravelink.Player) else None


async def ensure_player(ctx: commands.Context) -> ravelink.Player:
    player = get_player(ctx)
    if player:
        return player

    voice = getattr(ctx.author, "voice", None)
    if voice is None or voice.channel is None:
        raise commands.CommandError("Join a voice channel first.")

    return await voice.channel.connect(cls=ravelink.Player, self_deaf=True, reconnect=True)


@bot.event
async def on_ready() -> None:
    if ravelink.Pool.nodes:
        return

    node = ravelink.Node(
        identifier="main",
        uri=LAVALINK_URI,
        password=LAVALINK_PASSWORD,
        retries=None,
        resume_timeout=120,
        inactive_player_timeout=300,
        inactive_channel_tokens=3,
        request_timeout=15.0,
        request_retries=2,
        request_concurrency=16,
    )
    await ravelink.Pool.connect(nodes=[node], client=bot, cache_capacity=512)
    print(f"Logged in as {bot.user} and connected Ravelink.")


@bot.command(name="join")
async def join(ctx: commands.Context) -> None:
    player = await ensure_player(ctx)
    await ctx.send(f"Connected to **{player.channel}**.")


@bot.command(name="play")
async def play(ctx: commands.Context, *, query: str) -> None:
    player = await ensure_player(ctx)
    results = await ravelink.Playable.search(query)

    if not results:
        await ctx.send("No tracks found.")
        return

    if isinstance(results, ravelink.Playlist):
        added = await player.queue.put_wait(results)
        first = player.queue.get() if not player.playing else None
        if first:
            await player.play(first)
        await ctx.send(f"Queued **{added}** tracks from **{results.name}**.")
        return

    track = results[0]
    track.extras = {"requester_id": ctx.author.id, "requester_name": str(ctx.author)}

    if player.playing:
        await player.queue.put_wait(track)
        await ctx.send(f"Queued **{track.title}**.")
    else:
        await player.play(track, populate=True)
        await ctx.send(f"Playing **{track.title}**.")


@bot.command(name="search")
async def search(ctx: commands.Context, *, query: str) -> None:
    results = await ravelink.Playable.search(query, source=ravelink.TrackSource.YouTubeMusic)
    if not results:
        await ctx.send("No results.")
        return

    tracks = results.tracks if isinstance(results, ravelink.Playlist) else results
    lines = [f"`{index}.` {track.title} - {track.author}" for index, track in enumerate(tracks[:5], start=1)]
    await ctx.send("\n".join(lines))


@bot.command(name="pause")
async def pause(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if player:
        await player.pause(True)
        await ctx.send("Paused.")


@bot.command(name="resume")
async def resume(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if player:
        await player.pause(False)
        await ctx.send("Resumed.")


@bot.command(name="skip")
async def skip(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if not player:
        return

    skipped = await player.skip()
    try:
        next_track = player.queue.get()
    except ravelink.QueueEmpty:
        await ctx.send(f"Skipped **{skipped.title}**." if skipped else "Nothing to skip.")
    else:
        await player.play(next_track)
        await ctx.send(f"Skipped to **{next_track.title}**.")


@bot.command(name="stop")
async def stop(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if player:
        player.queue.reset()
        player.auto_queue.reset()
        await player.stop()
        await ctx.send("Stopped and cleared the queue.")


@bot.command(name="queue")
async def queue(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if not player or not player.queue:
        await ctx.send("The queue is empty.")
        return

    lines = [f"`{index}.` {track.title}" for index, track in enumerate(player.queue[:10], start=1)]
    await ctx.send("\n".join(lines))


@bot.command(name="autoplay")
async def autoplay(ctx: commands.Context, mode: str = "enabled") -> None:
    player = await ensure_player(ctx)
    modes = {
        "on": ravelink.AutoPlayMode.enabled,
        "enabled": ravelink.AutoPlayMode.enabled,
        "partial": ravelink.AutoPlayMode.partial,
        "off": ravelink.AutoPlayMode.disabled,
        "disabled": ravelink.AutoPlayMode.disabled,
    }
    player.autoplay = modes.get(mode.lower(), ravelink.AutoPlayMode.enabled)
    await ctx.send(f"Autoplay set to `{player.autoplay.name}`.")


@bot.command(name="nightcore")
async def nightcore(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if not player:
        return

    filters = ravelink.Filters()
    filters.timescale.set(speed=1.18, pitch=1.12, rate=1.0)
    await player.set_filters(filters, seek=True)
    await ctx.send("Applied a light nightcore filter.")


@bot.command(name="clearfilters")
async def clearfilters(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if player:
        await player.set_filters(None, seek=True)
        await ctx.send("Filters cleared.")


@bot.command(name="diagnostics")
@commands.is_owner()
async def diagnostics(ctx: commands.Context) -> None:
    snapshot = await ravelink.Pool.diagnostics()
    await ctx.send(f"```py\n{snapshot}\n```")


@bot.command(name="leave")
async def leave(ctx: commands.Context) -> None:
    player = get_player(ctx)
    if player:
        await player.disconnect()
        await ctx.send("Disconnected.")


@bot.event
async def on_ravelink_node_ready(payload: ravelink.NodeReadyEventPayload) -> None:
    print(f"Node ready: {payload.node.identifier} resumed={payload.resumed} session={payload.session_id}")


@bot.event
async def on_ravelink_node_disconnected(node: ravelink.Node) -> None:
    print(f"Node disconnected, reconnect will be attempted: {node.identifier}")


@bot.event
async def on_ravelink_node_closed(node: ravelink.Node, disconnected: list[ravelink.Player]) -> None:
    print(f"Node closed: {node.identifier}; disconnected players={len(disconnected)}")


@bot.event
async def on_ravelink_track_start(payload: ravelink.TrackStartEventPayload) -> None:
    if payload.player:
        print(f"Track started in {payload.player.guild}: {payload.track.title}")


@bot.event
async def on_ravelink_track_end(payload: ravelink.TrackEndEventPayload) -> None:
    player = payload.player
    if player is None:
        return

    if payload.reason == "replaced":
        return

    try:
        next_track = player.queue.get()
    except ravelink.QueueEmpty:
        return

    await player.play(next_track)


@bot.event
async def on_ravelink_track_exception(payload: ravelink.TrackExceptionEventPayload) -> None:
    print(f"Track exception: {payload.track.title} -> {payload.exception}")


@bot.event
async def on_ravelink_track_stuck(payload: ravelink.TrackStuckEventPayload) -> None:
    print(f"Track stuck: {payload.track.title} threshold={payload.threshold}ms")


@bot.event
async def on_ravelink_websocket_closed(payload: ravelink.WebsocketClosedEventPayload) -> None:
    print(f"Discord voice websocket closed: code={payload.raw_code} reason={payload.reason}")


@bot.event
async def on_ravelink_player_update(payload: ravelink.PlayerUpdateEventPayload) -> None:
    if payload.player and payload.ping >= 0:
        payload.player.last_known_ping = payload.ping


@bot.event
async def on_ravelink_stats_update(payload: ravelink.StatsEventPayload) -> None:
    print(f"Lavalink stats: players={payload.players} playing={payload.playing}")


@bot.event
async def on_ravelink_extra_event(payload: ravelink.ExtraEventPayload) -> None:
    print(f"Plugin event from {payload.node.identifier}: {payload.data}")


@bot.event
async def on_ravelink_inactive_player(player: ravelink.Player) -> None:
    if player.guild:
        print(f"Inactive player in {player.guild}; disconnecting.")
    await player.disconnect()


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    await ctx.send(str(error))


bot.run(TOKEN)
