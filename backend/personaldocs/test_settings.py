"""Test settings: isolated temp data/config directories, fast password hashing."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="pd-test-")
os.environ.setdefault("PD_TESTING", "1")
os.environ.setdefault("PD_DATA_DIR", os.path.join(_tmp, "data"))
os.environ.setdefault("PD_CONFIG_DIR", os.path.join(_tmp, "config"))

from .settings import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"handlers": [], "level": "CRITICAL"}}
