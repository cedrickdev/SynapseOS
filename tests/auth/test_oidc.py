"""Unit tests for strict provider-neutral OIDC token verification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from core.auth import OIDCClaims, OIDCConfiguration, OIDCVerificationError
from infrastructure.auth import HTTPJWKSetLoader, OIDCVerifier

ISSUER = "https://auth.example/application/o/synapseos/"
AUDIENCE = "synapseos-api"


class _Keys:
    def __init__(self, jwk: dict[str, object]) -> None:
        self.jwk = jwk
        self.calls = 0

    async def load(self) -> tuple[dict[str, object], ...]:
        self.calls += 1
        return (self.jwk,)


class _RotatingKeys:
    def __init__(self, first: dict[str, object], second: dict[str, object]) -> None:
        self._sets = ((first,), (second,))
        self.calls = 0

    async def load(self) -> tuple[dict[str, object], ...]:
        selected = self._sets[min(self.calls, 1)]
        self.calls += 1
        return selected


class _ConcurrentKeys(_Keys):
    async def load(self) -> tuple[dict[str, object], ...]:
        self.calls += 1
        await asyncio.sleep(0)
        return (self.jwk,)


class _CancelledKeys:
    async def load(self) -> tuple[dict[str, object], ...]:
        raise asyncio.CancelledError


class _ConcurrentFailingKeys:
    def __init__(self) -> None:
        self.calls = 0

    async def load(self) -> tuple[dict[str, object], ...]:
        self.calls += 1
        await asyncio.sleep(0)
        raise OIDCVerificationError


class _BlockingKeys(_Keys):
    def __init__(self, jwk: dict[str, object]) -> None:
        super().__init__(jwk)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def load(self) -> tuple[dict[str, object], ...]:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return (self.jwk,)


def _configuration(**overrides: object) -> OIDCConfiguration:
    values: dict[str, object] = {"issuer": ISSUER, "audience": AUDIENCE}
    values.update(overrides)
    return OIDCConfiguration.model_validate(values)


def _material() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk["kid"] = "test-key"
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return private, jwk


def _token(private: rsa.RSAPrivateKey, **overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "authentik-user-001",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "email": "owner@example.com",
        "name": "Project Owner",
    }
    payload.update(overrides)
    return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "test-key"})


def test_oidc_verifier_validates_and_bounds_cached_jwks() -> None:
    private, jwk = _material()
    keys = _Keys(jwk)
    verifier = OIDCVerifier(
        _configuration(jwks_cache_seconds=60.0),
        keys,
    )

    first = asyncio.run(verifier.verify(_token(private)))
    second = asyncio.run(verifier.verify(_token(private)))

    assert first.subject == "authentik-user-001"
    assert first.email == "owner@example.com"
    assert second.issuer == ISSUER
    assert keys.calls == 1


@pytest.mark.parametrize(
    "override",
    (
        {"iss": "https://attacker.example/"},
        {"aud": "other-api"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
    ),
)
def test_oidc_verifier_rejects_invalid_issuer_audience_and_expiry(
    override: dict[str, object],
) -> None:
    private, jwk = _material()
    verifier = OIDCVerifier(_configuration(), _Keys(jwk))

    with pytest.raises(OIDCVerificationError):
        asyncio.run(verifier.verify(_token(private, **override)))


def test_oidc_verifier_rejects_unknown_key_after_one_forced_refresh() -> None:
    private, jwk = _material()
    keys = _Keys(jwk)
    verifier = OIDCVerifier(_configuration(), keys)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "subject",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private,
        algorithm="RS256",
        headers={"kid": "unknown"},
    )

    with pytest.raises(OIDCVerificationError):
        asyncio.run(verifier.verify(token))
    assert keys.calls == 2


def test_oidc_verifier_rejects_invalid_signature() -> None:
    trusted_private, jwk = _material()
    attacker_private, _attacker_jwk = _material()
    verifier = OIDCVerifier(_configuration(), _Keys(jwk))

    with pytest.raises(OIDCVerificationError):
        asyncio.run(verifier.verify(_token(attacker_private)))

    assert trusted_private is not attacker_private


def test_oidc_verifier_accepts_standard_multi_valued_audience() -> None:
    private, jwk = _material()
    verifier = OIDCVerifier(_configuration(), _Keys(jwk))

    claims = asyncio.run(verifier.verify(_token(private, aud=[AUDIENCE, "synapseos-web"])))

    assert claims.audience == AUDIENCE


def test_oidc_verifier_loads_rotated_keys_before_cache_expiry() -> None:
    first_private, first_jwk = _material()
    second_private, second_jwk = _material()
    second_jwk["kid"] = "rotated-key"
    clock = [100.0]
    keys = _RotatingKeys(first_jwk, second_jwk)
    verifier = OIDCVerifier(
        _configuration(jwks_cache_seconds=10.0),
        keys,
        clock=lambda: clock[0],
    )

    asyncio.run(verifier.verify(_token(first_private)))
    rotated = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "rotated-subject",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        second_private,
        algorithm="RS256",
        headers={"kid": "rotated-key"},
    )

    assert asyncio.run(verifier.verify(rotated)).subject == "rotated-subject"
    assert keys.calls == 2


def test_oidc_verifier_coalesces_concurrent_cache_misses() -> None:
    private, jwk = _material()
    keys = _ConcurrentKeys(jwk)
    verifier = OIDCVerifier(_configuration(), keys)

    async def scenario() -> None:
        await asyncio.gather(
            verifier.verify(_token(private)),
            verifier.verify(_token(private)),
        )

    asyncio.run(scenario())

    assert keys.calls == 1


def test_oidc_verifier_coalesces_concurrent_failed_cache_misses() -> None:
    private, _jwk = _material()
    keys = _ConcurrentFailingKeys()
    verifier = OIDCVerifier(_configuration(), keys)

    async def scenario() -> None:
        results = await asyncio.gather(
            verifier.verify(_token(private)),
            verifier.verify(_token(private)),
            return_exceptions=True,
        )
        assert all(isinstance(result, OIDCVerificationError) for result in results)

    asyncio.run(scenario())

    assert keys.calls == 1


def test_oidc_verifier_cancels_one_waiter_without_cancelling_shared_refresh() -> None:
    private, jwk = _material()

    async def scenario() -> tuple[OIDCClaims, int]:
        keys = _BlockingKeys(jwk)
        verifier = OIDCVerifier(_configuration(), keys)
        first = asyncio.create_task(verifier.verify(_token(private)))
        second = asyncio.create_task(verifier.verify(_token(private)))
        await keys.started.wait()
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        keys.release.set()
        return await second, keys.calls

    result, calls = asyncio.run(scenario())

    assert result.subject == "authentik-user-001"
    assert calls == 1


def test_oidc_verifier_propagates_cancellation() -> None:
    private, _jwk = _material()
    verifier = OIDCVerifier(_configuration(), _CancelledKeys())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(verifier.verify(_token(private)))


def test_oidc_discovery_loader_fetches_exact_endpoints_once_with_bounds() -> None:
    _private, jwk = _material()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": "https://auth.example/application/o/synapseos/jwks/",
                },
            )
        return httpx.Response(200, json={"keys": [jwk]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    loader = HTTPJWKSetLoader(
        client,
        issuer=ISSUER,
        timeout_seconds=2.0,
        max_response_bytes=16_384,
        max_keys=4,
    )

    keys = asyncio.run(loader.load())
    asyncio.run(client.aclose())

    assert keys == (jwk,)
    assert calls == [
        "https://auth.example/application/o/synapseos/.well-known/openid-configuration",
        "https://auth.example/application/o/synapseos/jwks/",
    ]


def test_oidc_discovery_loader_rejects_mismatched_issuer_without_jwks_call() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "issuer": "https://attacker.example/",
                "jwks_uri": "https://attacker.example/jwks",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    loader = HTTPJWKSetLoader(client, issuer=ISSUER)

    with pytest.raises(OIDCVerificationError):
        asyncio.run(loader.load())
    asyncio.run(client.aclose())
    assert calls == 1


def test_oidc_discovery_loader_propagates_cancellation() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    loader = HTTPJWKSetLoader(client, issuer=ISSUER)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loader.load())
    asyncio.run(client.aclose())
