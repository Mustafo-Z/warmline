"""Reading secrets from an untracked .env file.

The ElevenLabs key and the voice passcode live in `.env` at the repository root
on the machine that serves the API, with permissions that keep them to one
user. They are not in the launchd plist, because files in /Library/LaunchDaemons
are readable by every account on the machine.
"""

from __future__ import annotations

import os
from pathlib import Path


def default_env_path() -> Path:
    override = os.environ.get("WARMLINE_ENV_FILE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".env"


def load_env_file(path: Path | None = None) -> list[str]:
    """Load KEY=value lines into the environment, never overriding what is set.

    Returns the names it loaded, so a caller can log which settings came from
    the file without logging their values.
    """
    target = path or default_env_path()
    if not target.is_file():
        return []

    loaded: list[str] = []
    for raw in target.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
