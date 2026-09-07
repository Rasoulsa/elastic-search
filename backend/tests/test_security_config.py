import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings


def test_jwt_signing_uses_djangos_configured_secret():
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.SECRET_KEY


@pytest.mark.parametrize("configured_value", [None, "", "   "])
def test_django_settings_fail_fast_without_a_non_empty_secret(configured_value):
    environment = os.environ.copy()
    environment.pop("DJANGO_SECRET_KEY", None)
    if configured_value is not None:
        environment["DJANGO_SECRET_KEY"] = configured_value

    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY must be set to a non-empty value." in result.stderr
