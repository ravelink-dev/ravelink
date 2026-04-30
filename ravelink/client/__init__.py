"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from .client import Client as Client
from .config import NodeConfig as NodeConfig
from .lifecycle import LifecycleState as LifecycleState
from .registry import PlayerRegistry as PlayerRegistry


__all__ = ("Client", "NodeConfig", "LifecycleState", "PlayerRegistry")
