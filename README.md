# Ravelink

[![CI](https://github.com/ravelink-dev/ravelink/actions/workflows/ci.yml/badge.svg)](https://github.com/ravelink-dev/ravelink/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide.

Ravelink v1.0.0 is a production-focused Discord.py music framework for Lavalink. It provides node pooling, resilient player lifecycle management, typed track and playlist models, advanced queues, autoplay, filters, diagnostics, and reconnect-aware event handling for large Discord music bots.

This release is dedicated with respect and appreciation to **Unknown xD**.

## Highlights

- Discord.py-native `Player` implementation for `VoiceChannel.connect(cls=ravelink.Player)`.
- Lavalink v4 REST and websocket support with session resume, reconnect backoff, and safer cleanup.
- Node pool with health scoring, automatic best-node selection, diagnostics, migration, and failover helpers.
- Queue and autoplay systems with history, loop modes, related-track discovery, dedupe, and async waiters.
- Search abstraction through `Playable.search()` and `Pool.fetch_tracks()` with URL and source-prefix support.
- Track, playlist, payload, filter, stats, and info models with type hints and `py.typed` packaging.
- Centralized request controller with concurrency control, retryable status handling, timeouts, and rate-limit awareness.
- Event surface for player, node, stats, websocket, inactive-player, and plugin/extra Lavalink events.

## Install

```bash
pip install ".[voice]"
```

The `voice` extra installs Discord voice dependencies, including PyNaCl and davey for DAVE-capable voice support.

For a bot project, install Discord.py dependencies and run a Lavalink v4 node:

```bash
pip install "Ravelink[voice]"
```

## Minimal Usage

```python
import discord
from discord.ext import commands

import ravelink

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


@bot.event
async def on_ready() -> None:
    node = ravelink.Node(uri="http://localhost:2333", password="youshallnotpass")
    await ravelink.Pool.connect(nodes=[node], client=bot, cache_capacity=256)


@bot.command()
async def play(ctx: commands.Context, *, query: str) -> None:
    if not ctx.author.voice:
        return

    player: ravelink.Player = ctx.voice_client or await ctx.author.voice.channel.connect(cls=ravelink.Player)
    results = await ravelink.Playable.search(query)

    if not results:
        await ctx.send("No tracks found.")
        return

    track = results.tracks[0] if isinstance(results, ravelink.Playlist) else results[0]
    await player.play(track)
    await ctx.send(f"Playing: **{track.title}**")
```

See [example.py](example.py) for a complete discord.py reference bot with commands and event listeners.

## Client Runtime API

For new bots, Ravelink also exposes a small runtime facade over the lower-level
`Pool` and Discord.py voice protocol integration:

```python
rv = ravelink.Client(
    bot=bot,
    nodes=[
        ravelink.NodeConfig(
            identifier="main",
            uri="http://127.0.0.1:2333",
            password="youshallnotpass",
            region="asia",
        )
    ],
    strategy="latency_weighted",
    cache_capacity=512,
)

await rv.start()

player = await rv.connect(ctx.guild, channel=ctx.author.voice.channel)
result = await rv.search("shubh - cheques", source="ytsearch")

if result.first:
    await player.play(result.first)
```

Built-in node balancing strategies include `round_robin`, `least_players`,
`least_penalty`, `region_affinity`, and `latency_weighted`. Custom balancers can
implement `select_node(...)` and be passed to `Client(..., balancer=...)`.

## Events

Ravelink dispatches Discord.py events with the `ravelink_` prefix:

- `on_ravelink_node_ready(payload)`
- `on_ravelink_node_disconnected(node)`
- `on_ravelink_node_closed(node, disconnected_players)`
- `on_ravelink_track_start(payload)`
- `on_ravelink_track_end(payload)`
- `on_ravelink_track_exception(payload)`
- `on_ravelink_track_stuck(payload)`
- `on_ravelink_websocket_closed(payload)`
- `on_ravelink_player_update(payload)`
- `on_ravelink_player_failover(payload)`
- `on_ravelink_stats_update(payload)`
- `on_ravelink_extra_event(payload)`
- `on_ravelink_inactive_player(player)`

## Diagnostics

```python
snapshot = await ravelink.Pool.diagnostics()
health = await ravelink.Pool.node_health()
```

Diagnostics are intentionally lightweight so they can be called from owner commands, health endpoints, or debug logs.

## About

Ravelink is designed as an independent, open-source music framework for serious Discord bot developers. The project focuses on predictable async behavior, stable node and player lifecycle handling, extensible public APIs, and a clean foundation for future transports, plugins, and audio features.

Dedicated to **Unknown xD**.
