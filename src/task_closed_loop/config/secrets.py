from __future__ import annotations
import os

class SecretNotConfiguredError(RuntimeError):
    pass

def get_secret(env_name: str, *, required: bool=False) -> str | None:
    value=os.getenv(env_name)
    if value:
        return value
    if required:
        raise SecretNotConfiguredError(f'Required secret is not configured: {env_name}')
    return None
