"""Local-only resource-bounded MarkItDown worker process."""

from __future__ import annotations

import resource
import sys
from contextlib import suppress
from pathlib import Path


def _install_runtime_denials() -> None:
    """Deny Python socket and child-process capabilities inside the converter worker."""

    def deny_capabilities(event: str, arguments: tuple[object, ...]) -> None:
        del arguments
        if event.startswith("socket."):
            raise PermissionError("network access is disabled")
        if event == "subprocess.Popen" or event == "os.system" or event.startswith("os.spawn"):
            raise PermissionError("child processes are disabled")

    sys.addaudithook(deny_capabilities)


def _apply_limits(max_output_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_AS"):
        memory_limit = 1024 * 1024 * 1024
        _, hard_limit = resource.getrlimit(resource.RLIMIT_AS)
        soft_limit = (
            memory_limit if hard_limit == resource.RLIM_INFINITY else min(memory_limit, hard_limit)
        )
        with suppress(OSError, ValueError):
            resource.setrlimit(resource.RLIMIT_AS, (soft_limit, hard_limit))


def main() -> int:
    """Convert exactly one validated local file and emit bounded UTF-8 Markdown."""
    if len(sys.argv) != 3:
        return 2
    path = Path(sys.argv[1])
    try:
        max_output_bytes = int(sys.argv[2])
    except ValueError:
        return 2
    if max_output_bytes < 1 or path.suffix.lower() not in {".pdf", ".docx", ".pptx", ".xlsx"}:
        return 2
    _apply_limits(max_output_bytes)
    _install_runtime_denials()
    try:
        from markitdown import MarkItDown

        result = MarkItDown().convert_local(path)
        content = result.text_content.encode("utf-8")
    except Exception:
        return 1
    if not content or len(content) > max_output_bytes:
        return 1
    sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
