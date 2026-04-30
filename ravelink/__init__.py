"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

"""Ravelink, a production-focused Discord.py music framework.

Ravelink v1.0.0 is dedicated to Unknown xD and maintained as an
open-source foundation for resilient Lavalink-powered Discord music bots.
"""

from .version import (
    __author__ as __author__,
    __copyright__ as __copyright__,
    __display_version__ as __display_version__,
    __license__ as __license__,
    __title__ as __title__,
    __version__ as __version__,
)


from .balancers import *
from .client import *
from .enums import *
from .exceptions import *
from .filters import *
from .lfu import CapacityZero as CapacityZero, LFUCache as LFUCache
from .node import *
from .payloads import *
from .player import Player as Player
from .queue import *
from .search import *
from .tracks import *
from .transport import RequestController as RequestController
from .utils import ExtrasNamespace as ExtrasNamespace
