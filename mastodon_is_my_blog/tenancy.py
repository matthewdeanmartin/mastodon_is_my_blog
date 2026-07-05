"""Deployment modes and tenant session resolution.

The app runs in one of two modes, selected by the ``MIMB_MODE`` env var:

- ``local`` (default) — **single-user mode**: the self-hosted install from
  PyPI. No sign-in; all data belongs to the ``default`` MetaAccount, and
  credentials may come from the OS keyring / ``accounts.json`` as before.
- ``server`` — **hosted multi-tenant mode**: requests must carry a
  ``mimb_session`` cookie issued by the ``mimb_co`` control plane. The
  cookie is an HS256 JWT signed with the shared ``SESSION_SIGNING_KEY``;
  its ``tenant_id`` claim maps to a MetaAccount here. Keyring and
  ``accounts.json`` are never consulted in server mode — they are
  single-machine constructs.

Session contract (must match mimb_co's ``auth/sessions.py``):
    cookie name  mimb_session
    algorithm    HS256, secret from SESSION_SIGNING_KEY
    claims       sub (user id, str), tenant_id (int), email, iss="mimb_co", exp
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MODE_LOCAL = "local"
MODE_SERVER = "server"

SESSION_COOKIE_NAME = "mimb_session"
SESSION_ISSUER = "mimb_co"

# Env vars that must be set for server mode to start at all.
SERVER_MODE_REQUIRED_ENV = (
    "SESSION_SIGNING_KEY",
    "TOKEN_ENCRYPTION_KEY",
    "APP_BASE_URL",
    # Bearer secret for the /internal control-plane hand-off API — server
    # mode is useless without a control plane that can reach it.
    "HANDOFF_SHARED_SECRET",
)


class SessionValidationError(Exception):
    """The mimb_session cookie is missing required claims or fails to verify."""


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    tenant_id: int
    email: str | None


def get_mode() -> str:
    mode = os.environ.get("MIMB_MODE", MODE_LOCAL).strip().lower()
    if mode not in (MODE_LOCAL, MODE_SERVER):
        raise ValueError(
            f"MIMB_MODE must be {MODE_LOCAL!r} or {MODE_SERVER!r}, got {mode!r}"
        )
    return mode


def is_server_mode() -> bool:
    return get_mode() == MODE_SERVER


def check_server_mode_env() -> None:
    """Fail fast at startup if server mode is missing required configuration."""
    missing = [name for name in SERVER_MODE_REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "MIMB_MODE=server requires these environment variables: "
            + ", ".join(missing)
        )


def verify_session_token(token: str) -> SessionClaims:
    """Validate a mimb_session JWT and return its claims.

    Raises SessionValidationError on any failure (bad signature, expired,
    wrong issuer, missing claims). Never trusts unverified content.
    """
    import jwt  # deferred: only server mode pays the import

    signing_key = os.environ.get("SESSION_SIGNING_KEY")
    if not signing_key:
        raise SessionValidationError("SESSION_SIGNING_KEY is not configured")

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["HS256"],
            issuer=SESSION_ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise SessionValidationError(str(exc)) from exc

    tenant_id = payload.get("tenant_id")
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool):
        raise SessionValidationError("session token missing integer tenant_id claim")

    return SessionClaims(
        user_id=str(payload["sub"]),
        tenant_id=tenant_id,
        email=payload.get("email"),
    )


def tenant_username(tenant_id: int) -> str:
    """The MetaAccount.username under which a control-plane tenant's data lives."""
    return f"tenant_{tenant_id}"
