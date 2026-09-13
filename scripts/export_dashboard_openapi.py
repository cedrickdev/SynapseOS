"""Export the deterministic FastAPI contract consumed by the Nuxt client generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from apps.api.main import create_app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_dashboard_openapi.py OUTPUT_PATH")

    output_path = Path(sys.argv[1]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app(dashboard_service_token="openapi-export-only").openapi()
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
