"""Generate packages/api-contracts/openapi.json from the Fudgo FastAPI app."""

import json
import os
import sys
from pathlib import Path

# Make apps.api importable
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

# Avoid touching the real DB while introspecting FastAPI's dependency graph.
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("JWT_SECRET", "openapi-generator-only")

from app.main import create_app  # noqa: E402

app = create_app()
schema = app.openapi()
out = ROOT / "packages" / "api-contracts" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(schema, indent=2, sort_keys=True))
print(f"Wrote {out} ({len(schema.get('paths', {}))} paths)")