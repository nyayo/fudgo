"""Password hashing via bcrypt directly.

``passlib`` 1.7.4 is incompatible with ``bcrypt`` 5.x (removed ``bcrypt.__about__``),
so we call :func:`bcrypt.hashpw` / :func:`bcrypt.checkpw` directly. Phase 0
already declared ``passlib[bcrypt]`` as a dependency for v1 parity; we still
import passlib to detect the runtime fallback (none in our path).
"""

import bcrypt


def _to_bytes(value: str) -> bytes:
    # bcrypt has a 72-byte input limit; truncate so we never raise.
    return value.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
