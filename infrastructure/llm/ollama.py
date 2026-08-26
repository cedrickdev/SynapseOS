"""Bounded HTTP adapter for Ollama's chat API."""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import suppress
from types import TracebackType
from typing import Any, Self, TypeGuard
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from core.llm import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMModelMetadata,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    LLMUsage,
)

_STRING_DETAIL_FIELDS = ("family", "parameter_size", "quantization_level")
_MAX_DETAIL_LENGTH = 256
_MAX_FAMILIES = 16


def _sanitize_details(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, object] = {}
    for field in _STRING_DETAIL_FIELDS:
        item = value.get(field)
        if isinstance(item, str) and len(item) <= _MAX_DETAIL_LENGTH:
            sanitized[field] = item
    families = value.get("families")
    if (
        isinstance(families, list)
        and len(families) <= _MAX_FAMILIES
        and all(isinstance(item, str) and len(item) <= _MAX_DETAIL_LENGTH for item in families)
    ):
        sanitized["families"] = families
    return sanitized


def _is_valid_counter(value: object) -> TypeGuard[int | None]:
    return value is None or (type(value) is int and value >= 0)


def _discard_task_result(task: asyncio.Task[None]) -> None:
    with suppress(BaseException):
        task.result()


class OllamaLLMProvider:
    """Translate provider-neutral requests to Ollama without hidden retries."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_response_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise LLMConfigurationError("Invalid Ollama base URL", provider="ollama")
        if not model.strip():
            raise LLMConfigurationError("Ollama model must not be blank", provider="ollama")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise LLMConfigurationError("Ollama timeout must be positive", provider="ollama")
        if max_response_bytes <= 0:
            raise LLMConfigurationError(
                "Ollama response size limit must be positive", provider="ollama"
            )

        self._base_url = base_url.rstrip("/")
        self._model = model.strip()
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._closed = False
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one bounded, non-streaming Ollama response."""
        if self._closed:
            raise LLMConfigurationError("Ollama provider is closed", provider="ollama")
        deadline = asyncio.get_running_loop().time() + self._timeout
        try:
            async with asyncio.timeout_at(deadline):
                return await self._generate(request, deadline)
        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("Ollama request timed out", provider="ollama") from error
        except httpx.ConnectError as error:
            raise LLMConnectionError("Ollama is unavailable", provider="ollama") from error
        except httpx.TransportError as error:
            raise LLMConnectionError(
                "Ollama response stream was interrupted", provider="ollama"
            ) from error

    async def _generate(self, request: LLMRequest, deadline: float) -> LLMResponse:
        """Perform one request inside the caller's wall-clock deadline."""
        messages: list[dict[str, str]] = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(
            {"role": message.role.value, "content": message.content} for message in request.messages
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        options: dict[str, int | float] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        options["num_predict"] = request.max_tokens
        if options:
            payload["options"] = options

        http_request = self._client.build_request(
            "POST",
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=self._timeout,
        )
        response = await self._client.send(http_request, stream=True)
        try:
            if not response.is_success:
                raise LLMResponseError(
                    "Ollama returned an unsuccessful response",
                    provider="ollama",
                    status_code=response.status_code,
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._max_response_bytes:
                    raise LLMResponseError(
                        "Ollama response exceeded the configured size limit",
                        provider="ollama",
                    )
        finally:
            self._schedule_response_close(response)

        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise TypeError
            message = data["message"]
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise TypeError
            model = data.get("model", self._model)
            if not isinstance(model, str):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise LLMResponseError(
                "Ollama returned an invalid response", provider="ollama"
            ) from error
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        usage = None
        if prompt_tokens is not None or completion_tokens is not None:
            if not _is_valid_counter(prompt_tokens) or not _is_valid_counter(completion_tokens):
                raise LLMResponseError("Ollama returned an invalid response", provider="ollama")
            total_tokens = (
                prompt_tokens + completion_tokens
                if prompt_tokens is not None and completion_tokens is not None
                else None
            )
            usage = LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        details = _sanitize_details(data.get("details"))
        try:
            return LLMResponse(
                content=message["content"],
                finish_reason=data.get("done_reason"),
                usage=usage,
                model=LLMModelMetadata(provider="ollama", model=model, details=details),
            )
        except ValidationError as error:
            raise LLMResponseError(
                "Ollama returned an invalid response", provider="ollama"
            ) from error

    def _schedule_response_close(self, response: httpx.Response) -> None:
        close_task = asyncio.create_task(response.aclose())
        self._cleanup_tasks.add(close_task)
        close_task.add_done_callback(_discard_task_result)
        close_task.add_done_callback(self._cleanup_tasks.discard)

    async def aclose(self) -> None:
        """Close only a client owned by this provider."""
        self._closed = True
        if self._cleanup_tasks:
            for task in self._cleanup_tasks:
                task.cancel()
            await asyncio.gather(*tuple(self._cleanup_tasks), return_exceptions=True)
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter the provider-owned network resource scope."""
        if self._closed:
            raise LLMConfigurationError("Ollama provider is closed", provider="ollama")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release provider-owned network resources."""
        await self.aclose()
