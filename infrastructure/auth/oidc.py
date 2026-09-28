"""Strict cached OIDC JWT verification without implicit retries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx
import jwt

from core.auth import OIDCClaims, OIDCConfiguration, OIDCVerificationError


class JWKSetLoader(Protocol):
    async def load(self) -> tuple[dict[str, object], ...]: ...


class HTTPJWKSetLoader:
    """Load one bounded JWK set through strict OIDC discovery."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        issuer: str,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 65_536,
        max_keys: int = 16,
    ) -> None:
        if (
            not isinstance(client, httpx.AsyncClient)
            or not isinstance(issuer, str)
            or not issuer
            or not 0.0 < timeout_seconds <= 30.0
            or not 1_024 <= max_response_bytes <= 1_048_576
            or not 1 <= max_keys <= 64
        ):
            raise ValueError("OIDC discovery configuration is invalid")
        parsed_issuer = urlsplit(issuer)
        if (
            parsed_issuer.scheme != "https"
            or not parsed_issuer.hostname
            or parsed_issuer.username is not None
            or parsed_issuer.password is not None
            or parsed_issuer.query
            or parsed_issuer.fragment
        ):
            raise ValueError("OIDC issuer must be a safe HTTPS URL")
        self._client = client
        self._issuer = issuer
        self._discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._max_keys = max_keys

    async def load(self) -> tuple[dict[str, object], ...]:
        """Fetch discovery and JWKS exactly once each without retries."""
        try:
            discovery = await self._get_json(self._discovery_url)
            if discovery.get("issuer") != self._issuer:
                raise OIDCVerificationError()
            jwks_uri = discovery.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not self._safe_jwks_uri(jwks_uri):
                raise OIDCVerificationError()
            jwks = await self._get_json(jwks_uri)
            keys = jwks.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= self._max_keys:
                raise OIDCVerificationError()
            if not all(isinstance(key, dict) for key in keys):
                raise OIDCVerificationError()
            return tuple(keys)
        except OIDCVerificationError:
            raise
        except Exception:
            raise OIDCVerificationError() from None

    async def _get_json(self, url: str) -> dict[str, object]:
        body = bytearray()
        async with self._client.stream("GET", url, timeout=self._timeout) as response:
            if response.status_code < 200 or response.status_code >= 300:
                raise OIDCVerificationError()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > self._max_response_bytes:
                        raise OIDCVerificationError()
                except ValueError:
                    raise OIDCVerificationError() from None
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > self._max_response_bytes:
                    raise OIDCVerificationError()
                body.extend(chunk)
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise OIDCVerificationError()
        return parsed

    @staticmethod
    def _safe_jwks_uri(uri: str) -> bool:
        parsed = urlsplit(uri)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )


class OIDCVerifier:
    """Validate one access token against one fixed issuer and audience."""

    def __init__(
        self,
        configuration: OIDCConfiguration,
        loader: JWKSetLoader,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            type(configuration) is not OIDCConfiguration
            or not callable(getattr(loader, "load", None))
            or not callable(clock)
        ):
            raise ValueError("OIDC verifier configuration is invalid")
        self._configuration = configuration
        self._loader = loader
        self._clock = clock
        self._keys: dict[str, object] = {}
        self._expires_at = 0.0
        self._cache_generation = 0
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[dict[str, object]] | None = None
        self._refresh_waiters = 0

    async def verify(self, token: str) -> OIDCClaims:
        """Validate exactly once and return only allowlisted claims."""
        try:
            if (
                type(token) is not str
                or not 1 <= len(token.encode("utf-8")) <= self._configuration.max_token_bytes
            ):
                raise ValueError
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise ValueError
            kid = header.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 255:
                raise ValueError
            keys, generation = await self._cached_keys()
            key = keys.get(kid)
            if key is None:
                keys, _generation = await self._cached_keys(refresh_after_generation=generation)
                key = keys.get(kid)
                if key is None:
                    raise ValueError
            payload = jwt.decode(
                token,
                cast(Any, key),
                algorithms=["RS256"],
                audience=self._configuration.audience,
                issuer=str(self._configuration.issuer),
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = payload.get("sub")
            audience = payload.get("aud")
            valid_audience = isinstance(audience, str) or (
                isinstance(audience, list)
                and 1 <= len(audience) <= 16
                and all(isinstance(item, str) and 1 <= len(item) <= 255 for item in audience)
            )
            if not isinstance(subject, str) or not valid_audience:
                raise ValueError
            email = payload.get("email")
            name = payload.get("name")
            return OIDCClaims(
                issuer=str(payload["iss"]),
                subject=subject,
                audience=self._configuration.audience,
                issued_at=datetime.fromtimestamp(float(payload["iat"]), tz=UTC),
                expires_at=datetime.fromtimestamp(float(payload["exp"]), tz=UTC),
                email=email if isinstance(email, str) else None,
                display_name=name if isinstance(name, str) else None,
            )
        except OIDCVerificationError:
            raise
        except Exception:
            raise OIDCVerificationError() from None

    async def _cached_keys(
        self,
        *,
        refresh_after_generation: int | None = None,
    ) -> tuple[dict[str, object], int]:
        now = self._clock()
        cache_is_usable = self._keys and now < self._expires_at
        refresh_is_complete = (
            refresh_after_generation is None or self._cache_generation > refresh_after_generation
        )
        if cache_is_usable and refresh_is_complete:
            return self._keys, self._cache_generation
        async with self._refresh_lock:
            now = self._clock()
            cache_is_usable = self._keys and now < self._expires_at
            refresh_is_complete = (
                refresh_after_generation is None
                or self._cache_generation > refresh_after_generation
            )
            if cache_is_usable and refresh_is_complete:
                return self._keys, self._cache_generation
            refresh_task = self._refresh_task
            if refresh_task is None:
                refresh_task = asyncio.create_task(self._refresh_keys(now))
                self._refresh_task = refresh_task
            self._refresh_waiters += 1
        try:
            keys = await asyncio.shield(refresh_task)
            return keys, self._cache_generation
        finally:
            async with self._refresh_lock:
                self._refresh_waiters -= 1
                if self._refresh_task is refresh_task and self._refresh_waiters == 0:
                    if not refresh_task.done():
                        refresh_task.cancel()
                    self._refresh_task = None

    async def _refresh_keys(self, now: float) -> dict[str, object]:
        jwks = await self._loader.load()
        if not 1 <= len(jwks) <= self._configuration.max_jwks_keys:
            raise OIDCVerificationError()
        parsed: dict[str, object] = {}
        for item in jwks:
            kid = item.get("kid")
            if (
                not isinstance(kid, str)
                or not kid
                or item.get("alg") not in {None, "RS256"}
                or item.get("use") not in {None, "sig"}
                or kid in parsed
            ):
                raise OIDCVerificationError()
            parsed[kid] = jwt.PyJWK.from_dict(item, algorithm="RS256").key
        self._keys = parsed
        self._expires_at = now + self._configuration.jwks_cache_seconds
        self._cache_generation += 1
        return self._keys
