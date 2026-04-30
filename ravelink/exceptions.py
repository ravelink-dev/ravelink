"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .types.response import ErrorResponse, LoadedErrorPayload


__all__ = (
    "RavelinkException",
    "NodeException",
    "NodeConnectionError",
    "NodeAuthenticationError",
    "NodeUnavailableError",
    "InvalidClientException",
    "AuthorizationFailedException",
    "InvalidNodeException",
    "LavalinkException",
    "LavalinkLoadException",
    "SearchError",
    "NoTracksFound",
    "InvalidChannelStateException",
    "ChannelTimeoutException",
    "PlayerNotConnected",
    "QueueEmpty",
    "VoiceStateError",
    "FailoverError",
    "FilterValidationError",
)


class RavelinkException(Exception):
    """Base Ravelink Exception class.

    All Ravelink exceptions derive from this exception.
    """


class NodeException(RavelinkException):
    """Error raised when an Unknown or Generic error occurs on a Node.

    This exception may be raised when an error occurs reaching your Node.

    Attributes
    ----------
    status: int | None
        The status code received when making a request. Could be None.
    """

    def __init__(self, msg: str | None = None, status: int | None = None) -> None:
        super().__init__(msg)

        self.status = status


class NodeConnectionError(NodeException):
    """Raised when Ravelink cannot establish or maintain a node connection."""


class NodeAuthenticationError(NodeConnectionError):
    """Raised when Lavalink rejects a node password or authorization header."""


class NodeUnavailableError(NodeException):
    """Raised when no healthy node is available for an operation."""


class InvalidClientException(RavelinkException):
    """Exception raised when an invalid :class:`discord.Client`
    is provided while connecting a :class:`ravelink.Node`.
    """


class AuthorizationFailedException(RavelinkException):
    """Exception raised when Lavalink fails to authenticate a :class:`~ravelink.Node`, with the provided password."""


class InvalidNodeException(RavelinkException):
    """Exception raised when a :class:`Node` is tried to be retrieved from the
    :class:`Pool` without existing, or the ``Pool`` is empty.
    """


class LavalinkException(RavelinkException):
    """Exception raised when Lavalink returns an invalid response.

    Attributes
    ----------
    status: int
        The response status code.
    reason: str | None
        The response reason. Could be ``None`` if no reason was provided.
    """

    def __init__(self, msg: str | None = None, /, *, data: ErrorResponse) -> None:
        self.timestamp: int = data["timestamp"]
        self.status: int = data["status"]
        self.error: str = data["error"]
        self.trace: str | None = data.get("trace")
        self.path: str = data["path"]

        if not msg:
            msg = f"Failed to fulfill request to Lavalink: status={self.status}, reason={self.error}, path={self.path}"

        super().__init__(msg)


class LavalinkLoadException(RavelinkException):
    """Exception raised when an error occurred loading tracks via Lavalink.

    Attributes
    ----------
    error: str
        The error message from Lavalink.
    severity: str
        The severity of this error sent via Lavalink.
    cause: str
        The cause of this error sent via Lavalink.
    """

    def __init__(self, msg: str | None = None, /, *, data: LoadedErrorPayload) -> None:
        self.error: str = data["message"]
        self.severity: str = data["severity"]
        self.cause: str = data["cause"]

        if not msg:
            msg = f"Failed to Load Tracks: error={self.error}, severity={self.severity}, cause={self.cause}"

        super().__init__(msg)


class SearchError(RavelinkException):
    """Raised when a search resolver cannot load or normalize tracks."""


class NoTracksFound(SearchError):
    """Raised by strict search helpers when Lavalink returns no playable tracks."""


class InvalidChannelStateException(RavelinkException):
    """Exception raised when a :class:`~ravelink.Player` tries to connect to an invalid channel or
    has invalid permissions to use this channel.
    """


class ChannelTimeoutException(RavelinkException):
    """Exception raised when connecting to a voice channel times out."""


class PlayerNotConnected(RavelinkException):
    """Raised when an operation requires an active player voice connection."""


class QueueEmpty(RavelinkException):
    """Exception raised when you try to retrieve from an empty queue."""


class VoiceStateError(RavelinkException):
    """Raised when Discord voice state cannot be synchronized with Lavalink."""


class FailoverError(RavelinkException):
    """Raised when Ravelink cannot migrate or restore a player after node failure."""


class FilterValidationError(RavelinkException):
    """Raised when a filter payload cannot be validated before being sent."""





