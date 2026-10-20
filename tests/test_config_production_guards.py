import os
import subprocess
import sys


VALID_PRODUCTION = {
    "JARVIS_ENV": "production",
    "JWT_SECRET_KEY": "x" * 32,
    "DEVELOPER_PASSWORD": "production-password",
    "AUTH_COOKIE_SECURE": "true",
    "DEVELOPER_MFA_REQUIRED": "true",
}


def import_config(extra_environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(VALID_PRODUCTION)
    environment.update(extra_environment)
    return subprocess.run(
        [sys.executable, "-c", "import jarvis.config"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_production_configuration_imports():
    result = import_config({})
    assert result.returncode == 0, result.stderr


def test_production_rejects_default_jwt_secret():
    result = import_config({"JWT_SECRET_KEY": "dev-secret-change-in-production"})
    assert result.returncode != 0
    assert "JWT_SECRET_KEY" in result.stderr


def test_production_rejects_short_jwt_secret():
    result = import_config({"JWT_SECRET_KEY": "too-short"})
    assert result.returncode != 0
    assert "JWT_SECRET_KEY" in result.stderr


def test_production_rejects_default_developer_password():
    result = import_config({"DEVELOPER_PASSWORD": "changeme123"})
    assert result.returncode != 0
    assert "DEVELOPER_PASSWORD" in result.stderr


def test_production_rejects_short_developer_password():
    result = import_config({"DEVELOPER_PASSWORD": "short"})
    assert result.returncode != 0
    assert "DEVELOPER_PASSWORD" in result.stderr


def test_production_rejects_insecure_auth_cookie():
    result = import_config({"AUTH_COOKIE_SECURE": "false"})
    assert result.returncode != 0
    assert "AUTH_COOKIE_SECURE" in result.stderr


def test_production_requires_developer_mfa():
    result = import_config({"DEVELOPER_MFA_REQUIRED": "false"})
    assert result.returncode != 0
    assert "DEVELOPER_MFA_REQUIRED" in result.stderr
