"""Shared helpers for CLI-backed LLM adapters.

A CLI adapter spawns a local coding-agent binary to satisfy the same domain contract
as the API adapters. Two rules apply to every such adapter:

- the child process gets a whitelisted environment, never the parent's, because
  `config/loader.py` loads the project `.env` into `os.environ` and those values
  (database DSNs, tokens, API keys) must not reach a subprocess;
- the child runs in an empty temporary directory, so the repository and any `.env`
  are outside its working root and its ancestor chain.
"""

from __future__ import annotations

import os

# Variables a local CLI legitimately needs: its own credential store under HOME,
# the executable search path, locale and a temp location.
ENV_PASSTHROUGH = (
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "USER",
    "SHELL",
    "NODE_OPTIONS",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
)


def whitelist_environment(
    *,
    extra_allow: tuple[str, ...] = (),
) -> dict[str, str]:
    """Build a minimal child environment from the current process.

    Only `ENV_PASSTHROUGH` plus `extra_allow` are copied; everything else — including
    anything python-dotenv loaded from the project `.env` — is dropped.
    """

    names = tuple(ENV_PASSTHROUGH) + tuple(extra_allow)
    env = {
        name: os.environ[name]
        for name in names
        if os.environ.get(name)
    }
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def as_bool(value, default: bool = False) -> bool:
    """Parse a config value that may arrive as a real bool or an env-substituted string."""

    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
