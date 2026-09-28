"""Executable production-like Docker Compose contract tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
AUTHENTIK_BLUEPRINT = ROOT / "deployment" / "authentik" / "synapseos.yaml"
SECRET_ENV = {
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "DASHBOARD_SERVICE_TOKEN",
    "NUXT_BACKEND_SERVICE_TOKEN",
    "NUXT_OIDC_CLIENT_SECRET",
    "GITHUB_SERVICE_TOKEN",
    "AUTHENTIK_POSTGRESQL_PASSWORD",
    "AUTHENTIK_SECRET_KEY",
}


def _deployment_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "POSTGRES_USER": "synapse",
            "POSTGRES_PASSWORD": "test-synapse-password",
            "POSTGRES_DB": "synapseos",
            "DATABASE_URL": (
                "postgresql+psycopg://synapse:test-synapse-password@db:5432/synapseos"
            ),
            "DASHBOARD_SERVICE_TOKEN": "test-dashboard-service-token",
            "NUXT_BACKEND_SERVICE_TOKEN": "test-dashboard-service-token",
            "OIDC_ISSUER": "https://auth.example/application/o/synapseos/",
            "OIDC_AUDIENCE": "synapseos-api",
            "OIDC_DISCOVERY_URL": (
                "http://authentik-server:9000/application/o/synapseos/"
                ".well-known/openid-configuration"
            ),
            "NUXT_OIDC_AUTHORIZATION_ENDPOINT": ("http://localhost:9000/application/o/authorize/"),
            "NUXT_OIDC_TOKEN_ENDPOINT": ("http://authentik-server:9000/application/o/token/"),
            "NUXT_OIDC_CLIENT_ID": "synapseos-web",
            "NUXT_OIDC_CLIENT_SECRET": "test-oidc-client-secret",
            "NUXT_OIDC_REDIRECT_URI": "http://localhost:3000/api/auth/callback",
            "NUXT_OIDC_COMPANY_SLUG": "test-company",
            "GITHUB_SERVICE_TOKEN": "test-github-service-token",
            "AUTHENTIK_POSTGRESQL_PASSWORD": "test-authentik-db-password",
            "AUTHENTIK_SECRET_KEY": "test-authentik-secret-key",
        }
    )
    return environment


def _compose_config(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("docker", "compose", "--profile", "smoke", "config", "--format", "json"),
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _configured_model() -> dict[str, Any]:
    result = _compose_config(_deployment_environment())
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_compose_rejects_missing_secret_configuration() -> None:
    environment = os.environ.copy()
    for name in SECRET_ENV:
        environment.pop(name, None)

    result = _compose_config(environment)

    assert result.returncode != 0


def test_compose_defines_separate_ordered_processes_and_persistent_services() -> None:
    model = _configured_model()
    services = model["services"]

    assert set(services) == {
        "api",
        "authentik-db",
        "authentik-server",
        "authentik-worker",
        "db",
        "migrate",
        "smoke",
        "web",
        "worker",
    }
    assert services["api"]["build"]["target"] == "api"
    assert services["worker"]["build"]["target"] == "worker"
    assert services["migrate"]["build"]["target"] == "migrate"
    assert services["web"]["build"]["dockerfile"] == "apps/web/Dockerfile"
    assert services["smoke"]["build"]["target"] == "smoke"
    assert services["migrate"]["restart"] == "no"
    for service_name in ("api", "worker"):
        dependencies = services[service_name]["depends_on"]
        assert dependencies["db"]["condition"] == "service_healthy"
        assert dependencies["migrate"]["condition"] == "service_completed_successfully"
        assert services[service_name]["stop_grace_period"] == "30s"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    for dependency in ("api", "authentik-server", "db", "web", "worker"):
        assert services["smoke"]["depends_on"][dependency]["condition"] == "service_healthy"
    assert services["authentik-server"]["depends_on"]["authentik-db"]["condition"] == (
        "service_healthy"
    )
    assert services["authentik-worker"]["depends_on"]["authentik-db"]["condition"] == (
        "service_healthy"
    )
    assert set(model["volumes"]) == {
        "authentik_data",
        "authentik_pgdata",
        "synapseos_pgdata",
        "synapseos_workspaces",
    }


def test_compose_enforces_health_checks_and_network_boundaries() -> None:
    model = _configured_model()
    services = model["services"]

    for service_name in ("api", "authentik-db", "authentik-server", "db", "web", "worker"):
        assert services[service_name]["healthcheck"]["test"]
    assert "127.0.0.1" in services["db"]["ports"][0]["host_ip"]
    assert set(services["db"]["networks"]) == {"backend"}
    assert set(services["worker"]["networks"]) == {"backend", "egress"}
    assert set(services["authentik-db"]["networks"]) == {"identity"}
    assert set(services["authentik-worker"]["networks"]) == {"identity"}
    assert set(services["api"]["networks"]) == {"backend", "egress", "frontend"}
    assert set(services["web"]["networks"]) == {"frontend"}
    assert set(services["authentik-server"]["networks"]) == {"frontend", "identity"}
    assert model["networks"]["backend"]["driver_opts"] == {
        "com.docker.network.bridge.enable_ip_masquerade": "false"
    }


def test_compose_uses_production_settings_and_no_implicit_migration_startup() -> None:
    services = _configured_model()["services"]

    assert services["api"]["environment"]["APP_ENV"] == "production"
    assert services["worker"]["environment"]["APP_ENV"] == "production"
    assert services["api"]["environment"]["OIDC_ISSUER"].startswith("https://")
    assert services["web"]["environment"]["NITRO_PRESET"] == "node-server"
    assert services["web"]["environment"]["NUXT_BACKEND_BASE_URL"] == "http://api:8000"
    assert services["api"].get("command") is None
    assert services["worker"].get("command") is None


def test_compose_bootstraps_a_real_oidc_provider_for_local_smoke_checks() -> None:
    services = _configured_model()["services"]

    assert AUTHENTIK_BLUEPRINT.is_file()
    blueprint = AUTHENTIK_BLUEPRINT.read_text(encoding="utf-8")
    assert "authentik_providers_oauth2.oauth2provider" in blueprint
    assert "authentik_core.application" in blueprint
    assert "slug: synapseos" in blueprint
    assert "!Env NUXT_OIDC_CLIENT_SECRET" in blueprint
    assert "test-oidc-client-secret" not in blueprint

    for service_name in ("authentik-server", "authentik-worker"):
        service = services[service_name]
        assert service["environment"]["AUTHENTIK_DISABLE_UPDATE_CHECK"] == "true"
        assert service["environment"]["NUXT_OIDC_CLIENT_ID"] == "synapseos-web"
        assert service["environment"]["NUXT_OIDC_REDIRECT_URI"] == (
            "http://localhost:3000/api/auth/callback"
        )
        assert any(
            volume["target"] == "/blueprints/custom/synapseos.yaml" and volume["read_only"] is True
            for volume in service["volumes"]
        )

    assert services["smoke"]["environment"]["SMOKE_OIDC_DISCOVERY_URL"] == (
        "http://authentik-server:9000/application/o/synapseos/.well-known/openid-configuration"
    )
    assert services["smoke"]["environment"]["SMOKE_FRONTEND_URL"] == ("http://web:3000/login")
