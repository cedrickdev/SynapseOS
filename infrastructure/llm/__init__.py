"""Language model provider adapters."""

from infrastructure.llm.fake import FakeLLMProvider
from infrastructure.llm.ollama import OllamaLLMProvider

__all__ = ["FakeLLMProvider", "OllamaLLMProvider"]
