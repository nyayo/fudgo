"""Response envelope helpers.

The v1 Django/DRF frontend depends on this exact JSON contract, so every HTTP
response in v2 — success or error — must go through these helpers.

Success: ``{"success": true, "data": ...}``
Error:   ``{"success": false, "error": {"code": int, "message": str, "details": {}}}``
"""

from typing import Any


def success_envelope(data: Any) -> dict[str, Any]:
    """Wrap a successful payload in the v1 success envelope."""
    return {"success": True, "data": data}


def error_envelope(
    code: int, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the v1 error envelope. ``details`` defaults to an empty object."""
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }
