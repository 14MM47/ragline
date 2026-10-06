"""Unit-test defaults.

Auth is forced OFF for the legacy suite: these tests predate the auth layer
and exercise routes/pipelines, not sign-in. Tests that target auth behaviour
flip settings.auth_enabled back on themselves (see test_auth_*.py), and this
fixture restores the field afterwards either way.
"""

import os

import pytest

# The suite runs auth-off; mark the environment as an explicit dev box so the
# main.py startup guard (which refuses AUTH_ENABLED=off without this) doesn't
# abort at import. Set at module load, before any test imports ragline.main.
os.environ.setdefault("RAGLINE_ALLOW_INSECURE_DEV", "1")

from ragline.config import settings


@pytest.fixture(autouse=True)
def _auth_defaults():
    original_enabled = settings.auth_enabled
    original_secret = settings.session_secret
    settings.auth_enabled = False
    # A deterministic secret so cookie signing works wherever a test enables auth.
    settings.session_secret = "unit-test-secret"
    yield
    settings.auth_enabled = original_enabled
    settings.session_secret = original_secret
