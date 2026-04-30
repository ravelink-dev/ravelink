"""Credits: Ravelink is crafted with a vision to push Discord music frameworks beyond conventional limits. Proudly dedicated to Unknown xD and CodeWithRavager, this project carries forward their influence, ideas, and passion for building powerful systems. Their inspiration shapes Ravelink's foundation and its commitment to performance, stability, thoughtful developer experience, and long-term innovation for music bots worldwide."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

import aiohttp

from .backoff import Backoff
from .exceptions import LavalinkException, NodeException


if TYPE_CHECKING:
    from .types.response import ErrorResponse


__all__ = ("Method", "RequestController", "json_dumps")


logger = logging.getLogger(__name__)

Method = Literal["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"]
QueryParamValue = str | int | float


try:
    import orjson
except ModuleNotFoundError:  # pragma: no cover - optional speed extra
    orjson = None


def json_dumps(data: Any) -> str:
    if orjson is not None:
        return orjson.dumps(data).decode("utf-8")

    import json

    return json.dumps(data, separators=(",", ":"))


def _coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_query_params(params: dict[str, Any] | None) -> dict[str, QueryParamValue]:
    if not params:
        return {}

    normalized: dict[str, QueryParamValue] = {}
    for key, value in params.items():
        if value is None:
            continue

        normalized_key = str(key)
        if isinstance(value, bool):
            normalized[normalized_key] = str(value).lower()
        elif isinstance(value, (str, int, float)):
            normalized[normalized_key] = value
        else:
            normalized[normalized_key] = str(value)

    return normalized


class RequestController:
    """Small REST flow controller used by nodes.

    The controller centralizes timeout handling, retry/backoff behaviour,
    response parsing, and lightweight concurrency control so every node
    request behaves predictably under load.
    """

    RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, *, timeout: float = 15.0, retries: int = 2, concurrency: int = 12) -> None:
        self.timeout = max(1.0, float(timeout))
        self.retries = max(0, int(retries))
        self._limiter = asyncio.Semaphore(max(1, int(concurrency)))

    async def request(
        self,
        session: aiohttp.ClientSession,
        method: Method,
        *,
        url: str,
        headers: dict[str, str],
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        backoff = Backoff(base=1, maximum_time=8.0, maximum_tries=None)
        attempt = 0
        query_params = _normalize_query_params(params)

        while True:
            try:
                async with self._limiter:
                    async with session.request(
                        method=method,
                        url=url,
                        params=query_params,
                        json=json,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as resp:
                        if resp.status == 204:
                            return None

                        if resp.status >= 300:
                            if resp.status in self.RETRYABLE_STATUSES and attempt < self.retries:
                                await self._sleep_for_retry(resp, backoff)
                                attempt += 1
                                continue

                            raise await self._exception_from_response(resp)

                        return await self._read_response(resp)

            except LavalinkException:
                raise
            except (TypeError, ValueError) as exc:
                raise NodeException(f"Invalid Lavalink request {method} {url}: {exc}") from exc
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt >= self.retries:
                    raise NodeException(f"Request to Lavalink failed: {exc}") from exc

                delay = backoff.calculate()
                logger.debug("Retrying Lavalink request %s %s in %.2fs after %r", method, url, delay, exc)
                attempt += 1
                await asyncio.sleep(delay)

    async def _sleep_for_retry(self, resp: aiohttp.ClientResponse, backoff: Backoff) -> None:
        retry_after = resp.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else backoff.calculate()
        except ValueError:
            delay = backoff.calculate()

        await asyncio.sleep(max(0.1, min(delay, 15.0)))

    async def _exception_from_response(self, resp: aiohttp.ClientResponse) -> Exception:
        try:
            exc_data = await resp.json()
        except Exception:
            try:
                body = (await resp.text()).strip()
            except aiohttp.ClientError:
                body = ""

            detail = f": {body[:300]}" if body else ""
            logger.warning("Lavalink returned HTTP %s without a JSON error payload%s", resp.status, detail)
            return NodeException(f"Lavalink returned HTTP {resp.status}{detail}", status=resp.status)

        if not isinstance(exc_data, dict):
            return NodeException(
                f"Lavalink returned HTTP {resp.status} with an invalid error payload.",
                status=resp.status,
            )

        error_data = {
            "timestamp": _coerce_int(exc_data.get("timestamp")),
            "status": _coerce_int(exc_data.get("status"), resp.status),
            "error": str(exc_data.get("error") or exc_data.get("message") or resp.reason or "Unknown error"),
            "path": str(exc_data.get("path") or resp.url),
        }

        trace = exc_data.get("trace")
        if trace:
            error_data["trace"] = str(trace)

        return LavalinkException(data=cast("ErrorResponse", error_data))

    async def _read_response(self, resp: aiohttp.ClientResponse) -> Any:
        try:
            return await resp.json()
        except (aiohttp.ContentTypeError, ValueError):
            pass

        try:
            text = await resp.text()
        except aiohttp.ClientError:
            return None

        return text or None
