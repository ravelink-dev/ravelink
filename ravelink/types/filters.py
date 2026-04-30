"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from typing import Any, TypedDict


class Equalizer(TypedDict):
    band: int
    gain: float


class Karaoke(TypedDict, total=False):
    level: float | None
    monoLevel: float | None
    filterBand: float | None
    filterWidth: float | None


class Timescale(TypedDict, total=False):
    speed: float | None
    pitch: float | None
    rate: float | None


class Tremolo(TypedDict, total=False):
    frequency: float | None
    depth: float | None


class Vibrato(TypedDict, total=False):
    frequency: float | None
    depth: float | None


class Rotation(TypedDict, total=False):
    rotationHz: float | None


class Distortion(TypedDict, total=False):
    sinOffset: float | None
    sinScale: float | None
    cosOffset: float | None
    cosScale: float | None
    tanOffset: float | None
    tanScale: float | None
    offset: float | None
    scale: float | None


class ChannelMix(TypedDict, total=False):
    leftToLeft: float | None
    leftToRight: float | None
    rightToLeft: float | None
    rightToRight: float | None


class LowPass(TypedDict, total=False):
    smoothing: float | None


class FilterPayload(TypedDict, total=False):
    volume: float | None
    equalizer: list[Equalizer] | None
    karaoke: Karaoke
    timescale: Timescale
    tremolo: Tremolo
    vibrato: Vibrato
    rotation: Rotation
    distortion: Distortion
    channelMix: ChannelMix
    lowPass: LowPass
    pluginFilters: dict[str, Any]




