"""Authentication suppliers for GitHub remote operations."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Self

import httpx
import jwt

from core.git_providers import RemoteGitError, RemoteGitErrorCode, RemoteOperationOptions
from infrastructure.git.github.http import GitHubJsonClient

_MAX_TOKEN_LENGTH = 4_096
_MAX_PRIVATE_KEY_LENGTH = 65_536


class ServiceTokenProvider:
    """Supply one configured backend service token without exposing it."""

    def __init__(self, *, token: str) -> None:
        if (
            not token
            or token != token.strip()
            or len(token) > _MAX_TOKEN_LENGTH
            or any(ord(character) < 33 or ord(character) == 127 for character in token)
        ):
            raise ValueError("GitHub service token is invalid")
        self._token = token

    async def get_token(self, *, options: RemoteOperationOptions) -> str:
        return self._token

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class _GitHubAppJwtProvider:
    def __init__(self, *, app_id: int, private_key: str) -> None:
        self._app_id = app_id
        self._private_key = private_key

    async def get_token(self, *, options: RemoteOperationOptions) -> str:
        del options
        now = int(time.time())
        try:
            encoded = jwt.encode(
                {
                    "iat": now - 60,
                    "exp": now + 540,
                    "iss": str(self._app_id),
                },
                self._private_key,
                algorithm="RS256",
            )
        except (jwt.PyJWTError, TypeError, ValueError):
            raise RemoteGitError(RemoteGitErrorCode.AUTHENTICATION_FAILED) from None
        if not _is_safe_token(encoded):
            raise RemoteGitError(RemoteGitErrorCode.AUTHENTICATION_FAILED)
        return encoded

    def __repr__(self) -> str:
        return f"{type(self).__name__}(app_id={self._app_id})"


class GitHubAppInstallationTokenProvider:
    """Exchange a freshly signed app JWT for one short-lived installation token."""

    propagates_cancellation = True

    def __init__(
        self,
        *,
        app_id: int,
        installation_id: int,
        private_key: str,
        max_response_bytes: int,
        base_url: str = "https://api.github.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if type(app_id) is not int or not 1 <= app_id <= 9_223_372_036_854_775_807:
            raise ValueError("GitHub App id is invalid")
        if (
            type(installation_id) is not int
            or not 1 <= installation_id <= 9_223_372_036_854_775_807
        ):
            raise ValueError("GitHub App installation id is invalid")
        if (
            not isinstance(private_key, str)
            or not private_key.strip()
            or len(private_key) > _MAX_PRIVATE_KEY_LENGTH
        ):
            raise ValueError("GitHub App private key is invalid")

        self._installation_id = installation_id
        self._http = GitHubJsonClient(
            token_provider=_GitHubAppJwtProvider(app_id=app_id, private_key=private_key),
            max_response_bytes=max_response_bytes,
            base_url=base_url,
            client=client,
        )

    async def get_token(self, *, options: RemoteOperationOptions) -> str:
        value = await self._http.request_json(
            "POST",
            f"/app/installations/{self._installation_id}/access_tokens",
            options=options,
        )
        if not isinstance(value, dict) or not _is_safe_token(value.get("token")):
            raise RemoteGitError(RemoteGitErrorCode.RESPONSE_INVALID)
        token = value["token"]
        assert isinstance(token, str)
        return token

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        await self._http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(installation_id={self._installation_id})"


def _is_safe_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= _MAX_TOKEN_LENGTH
        and all(33 <= ord(character) < 127 for character in value)
    )
