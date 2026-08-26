# LLM Providers

Phase 4 defines a provider-neutral asynchronous boundary. Application code imports request,
response, and error contracts from `core.llm`; only composition code imports infrastructure
adapters.

## Core contract

```python
from core.llm import LLMMessage, LLMProvider, LLMRequest, LLMRole


async def generate_summary(provider: LLMProvider, text: str) -> str:
    response = await provider.generate(
        LLMRequest(
            system_prompt="Summarize accurately and surface uncertainty.",
            messages=(LLMMessage(role=LLMRole.USER, content=text),),
            max_tokens=512,
        )
    )
    return response.content
```

Consumers do not know whether the implementation uses Ollama, a future API gateway, or a cloud
provider. Provider URLs and credentials never belong in `LLMRequest`. Every request has a default
generation ceiling of 2,048 tokens and accepts an explicit maximum no greater than 131,072.

## Ollama

Configure the local adapter through the environment:

```text
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
OLLAMA_TIMEOUT_SECONDS=60
OLLAMA_MAX_RESPONSE_BYTES=10485760
```

Create and close a provider-owned HTTP pool explicitly:

```python
from core.config import get_settings
from infrastructure.llm import OllamaLLMProvider

settings = get_settings()
async with OllamaLLMProvider(
    base_url=settings.ollama_base_url,
    model=settings.ollama_model,
    timeout_seconds=settings.ollama_timeout_seconds,
    max_response_bytes=settings.ollama_max_response_bytes,
) as provider:
    response = await provider.generate(request)
```

An injected `httpx.AsyncClient` remains owned by its caller and is never closed by the adapter.
The adapter makes one request without hidden retries, propagates cancellation, streams into a
bounded buffer, skips unsuccessful response bodies, filters model metadata by both key and bounded
value shape, and normalizes failures without exposing prompts, response bodies, headers, or
credentials. Response cleanup is best-effort and cannot extend the configured wall-clock deadline.
Cleanup operations are tracked by the provider until completion and are cancelled and joined when
the provider closes; compliant HTTP transports must cooperate with asynchronous cancellation.

## Deterministic fake

`FakeLLMProvider` returns queued responses without network I/O. Its recorded request history has a
finite capacity and fails explicitly when exhausted. It is intended for application tests and
controlled development, not automatic production selection.

## Deferred work

Provider routing, retries, fallbacks, budgets, tool calling, cloud gateways, and MLX adapters are
not part of Phase 4. Future adapters can carry their own base URL and secret configuration while
preserving the core contract.
