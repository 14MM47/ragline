"""Entra SSO auth — backend-for-frontend OIDC, opaque session cookie.

Sign-in happens on login.microsoftonline.com; ragline never sees a password.
The browser holds only a signed random session id; identity, groups, and
expiry live server-side (storage/auth_models.py).
"""
