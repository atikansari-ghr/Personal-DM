"""Run external converters with time/memory limits, no inherited secrets and a private temp dir."""
from __future__ import annotations

import os
import resource
import subprocess
from pathlib import Path

from django.conf import settings


class ToolError(Exception):
    pass


SAFE_ENV_KEYS = {"PATH", "LANG", "LC_ALL", "TESSDATA_PREFIX"}


def run(cmd: list[str], *, timeout: int, cwd: Path | None = None, memory_mb: int | None = None,
        extra_env: dict | None = None) -> subprocess.CompletedProcess:
    memory_mb = memory_mb or settings.PROCESS_MEMORY_LIMIT_MB
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["HOME"] = str(cwd or settings.TMP_DIR)
    env["TMPDIR"] = str(cwd or settings.TMP_DIR)
    # Prevent nested thread pools from saturating both CPUs.
    env["OMP_THREAD_LIMIT"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env.update(extra_env or {})

    def limits():
        os.setsid()
        mem = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            pass
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 10))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.nice(10)

    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True, preexec_fn=limits,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{Path(cmd[0]).name} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} is not installed") from exc
    return proc
