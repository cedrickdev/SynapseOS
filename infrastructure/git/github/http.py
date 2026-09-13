"""Bounded JSON HTTP boundary for GitHub's REST API."""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import suppress
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from core.git_providers import (
    GitHubTokenProvider,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteOperationOptions,
)

_DEFAULT_BASE_URL = "https://api.github.com"
MAX_GITHUB_RESPONSE_BYTES = 16 * 1024 * 1024
_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_STATUS_ERRORS = {
    401: RemoteGitErrorCode.AUTHENTICATION_FAILED,
    403: RemoteGitErrorCode.FORBIDDEN,
    404: RemoteGitErrorCode.NOT_FOUND,
    409: RemoteGitErrorCode.CONFLICT,
    422: RemoteGitErrorCode.INVALID_REQUEST,
}


def _discard_task_result(task: asyncio.Task[None]) -> None:
    with suppress(BaseException):
        task.result()


class GitHubJsonClient:
    """Perform one authenticated, bounded GitHub JSON request per call."""

    propagates_cancellation = True

    def __init__(
        self,
        *,
        token_provider: GitHubTokenProvider,
        max_response_bytes: int,
        base_url: str = _DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("GitHub base URL is invalid")
        if (
            type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= MAX_GITHUB_RESPONSE_BYTES
        ):
            raise ValueError("GitHub response size limit is invalid")

        self._token_provider = token_provider
        self._max_response_bytes = max_response_bytes
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None
        self._closed = False
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        options: RemoteOperationOptions,
        json_body: object | None = None,
    ) -> object:
        """Send one request under the caller's single wall-clock deadline."""
        normalized_method = method.upper()
        if self._closed:
            raise RemoteGitError(RemoteGitErrorCode.PROVIDER_FAILED)
        if normalized_method not in _ALLOWED_METHODS:
            raise ValueError("GitHub HTTP method is invalid")
        if not self._is_safe_path(path):
            raise ValueError("GitHub request path is invalid")

        deadline = asyncio.get_running_loop().time() + options.timeout_seconds
        try:
            async with asyncio.timeout_at(deadline):
                return await self._request_json(
                    normalized_method,
                    path,
                    options=options,
                    json_body=json_body,
                    deadline=deadline,
                )
        except TimeoutError:
            raise RemoteGitError(RemoteGitErrorCode.TIMED_OUT) from None
        except httpx.TimeoutException:
            raise RemoteGitError(RemoteGitErrorCode.TIMED_OUT) from None
        except httpx.TransportError:
            raise RemoteGitError(RemoteGitErrorCode.CONNECTION_FAILED) from None

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        options: RemoteOperationOptions,
        json_body: object | None,
        deadline: float,
    ) -> object:
        try:
            token = await self._token_provider.get_token(options=options)
        except RemoteGitError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RemoteGitError(RemoteGitErrorCode.AUTHENTICATION_FAILED) from None
        if not self._is_safe_token(token):
            raise RemoteGitError(RemoteGitErrorCode.AUTHENTICATION_FAILED)

        remaining = deadline - asyncio.get_running_loop().time()
        if not math.isfinite(remaining) or remaining <= 0:
            raise TimeoutError
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        url = f"{self._base_url}{path}"
        if json_body is None:
            request = self._client.build_request(
                method,
                url,
                headers=headers,
                timeout=remaining,
            )
        else:
            request = self._client.build_request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=remaining,
            )
        response = await self._client.send(request, stream=True, follow_redirects=False)
        try:
            if not response.is_success:
                raise RemoteGitError(
                    _STATUS_ERRORS.get(response.status_code, RemoteGitErrorCode.PROVIDER_FAILED),
                    status_code=response.status_code,
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._max_response_bytes:
                    raise RemoteGitError(RemoteGitErrorCode.RESOURCE_LIMIT)
        finally:
            await self._close_response(response, deadline=deadline)

        try:
            value: Any = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID) from None
        if not isinstance(value, (dict, list)):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID)
        return value

    async def _close_response(self, response: httpx.Response, *, deadline: float) -> None:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            self._schedule_response_close(response)
            return
        try:
            async with asyncio.timeout(remaining):
                await response.aclose()
        except TimeoutError:
            self._schedule_response_close(response)
        except asyncio.CancelledError:
            self._schedule_response_close(response)
            raise

    def _schedule_response_close(self, response: httpx.Response) -> None:
        close_task = asyncio.create_task(response.aclose())
        self._cleanup_tasks.add(close_task)
        close_task.add_done_callback(_discard_task_result)
        close_task.add_done_callback(self._cleanup_tasks.discard)

    @staticmethod
    def _is_safe_path(path: str) -> bool:
        parsed = urlsplit(path)
        return (
            path.startswith("/")
            and not path.startswith("//")
            and parsed.scheme == ""
            and parsed.netloc == ""
            and parsed.query == ""
            and parsed.fragment == ""
            and all(part not in {"", ".", ".."} for part in path.split("/")[1:])
        )

    @staticmethod
    def _is_safe_token(token: object) -> bool:
        return (
            isinstance(token, str)
            and bool(token)
            and token == token.strip()
            and len(token) <= 4_096
            and all(33 <= ord(character) < 127 for character in token)
        )

    async def aclose(self) -> None:
        """Close pending responses and only a client owned by this boundary."""
        self._closed = True
        if self._cleanup_tasks:
            cleanup_tasks = tuple(self._cleanup_tasks)
            for task in cleanup_tasks:
                task.cancel()
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        if self._closed:
            raise RemoteGitError(RemoteGitErrorCode.PROVIDER_FAILED)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self._base_url!r})"
