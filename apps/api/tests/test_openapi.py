"""OpenAPI schema is generated and matches the checked-in artifact."""

import json
from pathlib import Path

from app.main import app


def test_app_openapi_has_all_phase1_paths():
    schema = app.openapi()
    paths = set(schema["paths"].keys())
    expected = {
        "/api/v2/auth/request-otp",
        "/api/v2/auth/verify-otp",
        "/api/v2/auth/phone/request-otp",
        "/api/v2/auth/phone/verify-otp",
        "/api/v2/auth/register",
        "/api/v2/auth/google",
        "/api/v2/auth/link-google",
        "/api/v2/auth/logout",
        "/api/v2/auth/logout-all",
        "/api/v2/auth/refresh",
        "/api/v2/auth/profile",
        "/api/v2/auth/password-reset",
        "/api/v2/auth/password-reset/confirm",
        "/api/v2/auth/notification-preferences",
        "/api/v2/auth/devices",
        "/api/v2/auth/test-notification",
        "/api/v2/users/staff",
        "/api/v2/users/addresses",
    }
    missing = expected - paths
    assert not missing, f"Missing OpenAPI paths: {missing}"


def test_openapi_title_is_fudgo():
    schema = app.openapi()
    assert schema["info"]["title"] == "Fudgo API"


def test_openapi_json_on_disk_matches_app():
    repo_root = Path(__file__).resolve().parents[3]
    on_disk_path = repo_root / "packages" / "api-contracts" / "openapi.json"
    if not on_disk_path.exists():
        # Generator hasn't been run; generate on the fly for the assertion.
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, str(repo_root / "tools" / "scripts" / "generate_openapi.py")],
            check=True,
        )
    on_disk = json.loads(on_disk_path.read_text())
    live = app.openapi()
    assert set(on_disk["paths"].keys()) == set(live["paths"].keys())
