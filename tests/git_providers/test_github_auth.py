"""Tests for bounded GitHub authentication suppliers."""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import Iterator

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.git_providers import (
    GitHubTokenProvider,
    RemoteGitError,
    RemoteGitErrorCode,
    RemoteOperationOptions,
)


@pytest.fixture(scope="module")
def rsa_key_pair() -> Iterator[tuple[str, bytes]]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    yield private_pem, public_pem


def test_github_authentication_module_exists() -> None:
    module = importlib.import_module("infrastructure.git.github.auth")

    assert module.__name__ == "infrastructure.git.github.auth"


def test_service_token_supplier_returns_only_in_memory_and_redacts_repr() -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    token = "github_pat_secret-service-token"
    provider = module.ServiceTokenProvider(token=token)

    supplied = asyncio.run(provider.get_token(options=RemoteOperationOptions(timeout_seconds=1.0)))

    assert supplied == token
    assert isinstance(provider, GitHubTokenProvider)
    assert token not in repr(provider)


@pytest.mark.parametrize("token", ["", "   ", "x" * 4_097, "token\nvalue"])
def test_service_token_supplier_rejects_invalid_secrets_without_echoing_them(token: str) -> None:
    module = importlib.import_module("infrastructure.git.github.auth")

    with pytest.raises(ValueError) as raised:
        module.ServiceTokenProvider(token=token)

    if token:
        assert token not in str(raised.value)


def test_app_supplier_signs_rs256_jwt_and_exchanges_once_per_call(
    rsa_key_pair: tuple[str, bytes],
) -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    private_key, public_key = rsa_key_pair
    requests: list[httpx.Request] = []
    issued_tokens = iter(("ghs_first-installation-token", "ghs_second-installation-token"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "token": next(issued_tokens),
                "expires_at": "2026-09-13T12:00:00Z",
                "permissions": {"contents": "write"},
            },
        )

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key=private_key,
        max_response_bytes=2_048,
        client=raw_client,
    )
    options = RemoteOperationOptions(timeout_seconds=2)

    first = asyncio.run(provider.get_token(options=options))
    second = asyncio.run(provider.get_token(options=options))

    assert first == "ghs_first-installation-token"
    assert second == "ghs_second-installation-token"
    assert len(requests) == 2
    for request in requests:
        assert request.method == "POST"
        assert str(request.url) == ("https://api.github.com/app/installations/67890/access_tokens")
        assert request.content == b""
        authorization = request.headers["authorization"]
        assert authorization.startswith("Bearer ")
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": False},
        )
        assert claims["iss"] == "12345"
        assert claims["exp"] - claims["iat"] == 600
        assert claims["iat"] <= int(time.time())
        assert private_key not in authorization
    rendered = repr(provider)
    assert private_key not in rendered
    assert first not in rendered
    assert second not in rendered
    asyncio.run(raw_client.aclose())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="private-key-or-token-from-provider"),
        httpx.Response(201, json={"token": ""}),
        httpx.Response(201, json={"token": "x" * 4_097}),
        httpx.Response(201, json={"expires_at": "2026-09-13T12:00:00Z"}),
    ],
)
def test_app_supplier_normalizes_failed_or_invalid_exchange_without_secret_leakage(
    response: httpx.Response,
    rsa_key_pair: tuple[str, bytes],
) -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    private_key, _ = rsa_key_pair
    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key=private_key,
        max_response_bytes=2_048,
        client=raw_client,
    )

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(provider.get_token(options=RemoteOperationOptions(timeout_seconds=1)))

    rendered = repr(raised.value) + str(raised.value)
    assert private_key not in rendered
    assert "private-key-or-token-from-provider" not in rendered
    assert "x" * 64 not in rendered
    assert raised.value.__cause__ is None
    asyncio.run(raw_client.aclose())


def test_app_supplier_normalizes_signing_failure_without_private_key_leakage() -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    private_key = "-----BEGIN PRIVATE KEY-----\nnot-a-key-secret\n-----END PRIVATE KEY-----"
    provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key=private_key,
        max_response_bytes=2_048,
    )

    with pytest.raises(RemoteGitError) as raised:
        asyncio.run(provider.get_token(options=RemoteOperationOptions(timeout_seconds=1)))

    assert raised.value.code is RemoteGitErrorCode.AUTHENTICATION_FAILED
    assert private_key not in repr(raised.value) + str(raised.value)
    assert raised.value.__cause__ is None
    asyncio.run(provider.aclose())


def test_app_supplier_propagates_cancellation_without_second_exchange(
    rsa_key_pair: tuple[str, bytes],
) -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    private_key, _ = rsa_key_pair
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key=private_key,
        max_response_bytes=2_048,
        client=raw_client,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.get_token(options=RemoteOperationOptions(timeout_seconds=1)))

    assert calls == 1
    asyncio.run(raw_client.aclose())


def test_app_supplier_close_does_not_close_injected_client(
    rsa_key_pair: tuple[str, bytes],
) -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    private_key, _ = rsa_key_pair
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json={"token": "x"}))
    )
    provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key=private_key,
        max_response_bytes=2_048,
        client=raw_client,
    )

    asyncio.run(provider.aclose())

    assert not raw_client.is_closed
    asyncio.run(raw_client.aclose())


def test_app_supplier_response_bound_accepts_16_mib_and_rejects_larger_values() -> None:
    module = importlib.import_module("infrastructure.git.github.auth")
    exact_provider = module.GitHubAppInstallationTokenProvider(
        app_id=12_345,
        installation_id=67_890,
        private_key="not-used-until-token-request",
        max_response_bytes=16_777_216,
    )

    asyncio.run(exact_provider.aclose())

    with pytest.raises(ValueError, match="size limit"):
        module.GitHubAppInstallationTokenProvider(
            app_id=12_345,
            installation_id=67_890,
            private_key="not-used-until-token-request",
            max_response_bytes=16_777_217,
        )


def test_public_package_exports_github_authentication_and_http_boundaries() -> None:
    package = importlib.import_module("infrastructure.git.github")

    assert package.ServiceTokenProvider.__name__ == "ServiceTokenProvider"
    assert package.GitHubAppInstallationTokenProvider.__name__ == (
        "GitHubAppInstallationTokenProvider"
    )
    assert package.GitHubJsonClient.__name__ == "GitHubJsonClient"
