Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide.

# Ravelink Events

All events are dispatched through Discord.py with the `ravelink_` prefix.

```python
@bot.event
async def on_ravelink_track_start(payload: ravelink.TrackStartEventPayload) -> None:
    ...
```

## Node

- `on_ravelink_node_ready(payload)` fires when a Lavalink websocket is ready.
- `on_ravelink_node_disconnected(node)` fires before reconnect scheduling after a websocket disconnect.
- `on_ravelink_node_closed(node, disconnected_players)` fires after a node is intentionally closed.

## Player And Tracks

- `on_ravelink_track_start(payload)`
- `on_ravelink_track_end(payload)`
- `on_ravelink_track_exception(payload)`
- `on_ravelink_track_stuck(payload)`
- `on_ravelink_player_update(payload)`
- `on_ravelink_player_failover(payload)`
- `on_ravelink_websocket_closed(payload)`
- `on_ravelink_inactive_player(player)`

## Stats And Plugins

- `on_ravelink_stats_update(payload)` exposes Lavalink node stats.
- `on_ravelink_extra_event(payload)` forwards unknown or plugin-specific Lavalink events.

See `example.py` for practical handlers for every major event.
