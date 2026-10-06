"""Session cookie — an itsdangerous-signed wrapper around the DB session id.

The id alone is already an unguessable 256-bit random value validated against
the auth_session table; the signature is defense-in-depth (a tampered or
foreign cookie is rejected without a DB round-trip) and ties cookies to this
deployment's SESSION_SECRET, so rotating the secret invalidates every cookie
at once.
"""

import base64
import hashlib

from itsdangerous import BadSignature, Signer

from ragline.config import settings

COOKIE_NAME = "ragline_session"


# --- Refresh-token encryption at rest ---------------------------------------
# The Entra refresh token stored on AppSession is a real off-box credential
# (usable against the token endpoint together with the client secret), so it
# is Fernet-encrypted with a key derived from SESSION_SECRET rather than
# stored plaintext — a DB copy alone doesn't yield usable tokens.


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(
        hashlib.sha256(f"ragline-refresh-token:{settings.session_secret}".encode()).digest()
    )
    return Fernet(key)


def encrypt_refresh_token(token: str) -> str:
    if not token:
        return ""
    return _fernet().encrypt(token.encode()).decode()


def decrypt_refresh_token(value: str) -> str | None:
    """Stored value -> refresh token; None when empty, tampered, or encrypted
    under a rotated SESSION_SECRET (the session then fails re-validation and
    the user just signs in again — fail closed, never crash)."""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return None


def _signer() -> Signer:
    return Signer(settings.session_secret, salt="ragline-session-cookie")


def sign_session_id(session_id: str) -> str:
    return _signer().sign(session_id).decode()


def unsign_session_id(cookie_value: str) -> str | None:
    """Signed cookie value -> session id, or None for tampered/foreign input."""
    try:
        return _signer().unsign(cookie_value).decode()
    except (BadSignature, UnicodeDecodeError):
        return None


def set_session_cookie(response, session_id: str) -> None:
    """Attach the session cookie with the full hardening set.

    Secure: never sent over plain HTTP (the intranet deployment is HTTPS-only).
    HttpOnly: invisible to JavaScript — an XSS can act as the user while the
    tab is open but cannot exfiltrate a durable credential.
    SameSite=Lax: sent on top-level navigations (so the Entra redirect back to
    us works) but not on cross-site subresource requests.
    """
    response.set_cookie(
        COOKIE_NAME,
        sign_session_id(session_id),
        max_age=settings.session_absolute_days * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
