from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List

from .errors import CapabilityExecutionError

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class DotEnvSecretStore:
    """File-backed secret storage for the Execution Project.

    Real secret values live only in the configured .env file. This class does
    not read from, write to, or export values through os.environ.
    """

    def __init__(self, env_path: Path):
        self.env_path = Path(env_path).resolve()

    @staticmethod
    def _decode_value(raw: str) -> str:
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
                value = value.replace(r'\"', '"').replace(r"\\", "\\")
        return value

    @staticmethod
    def _encode_value(value: str) -> str:
        # Always double-quote so spaces, #, = and empty strings are preserved.
        escaped = (
            str(value)
            .replace("\\", "\\\\")
            .replace('"', r'\"')
            .replace("\n", r"\n")
            .replace("\r", r"\r")
            .replace("\t", r"\t")
        )
        return f'"{escaped}"'

    @staticmethod
    def _validate_key(key: str) -> str:
        key = str(key or "").strip()
        if not key or not _KEY_RE.fullmatch(key):
            raise CapabilityExecutionError(f"invalid .env secret key: {key!r}")
        return key

    def _load(self, *, allow_missing: bool = False) -> Dict[str, str]:
        if not self.env_path.exists():
            if allow_missing:
                return {}
            raise CapabilityExecutionError(f"secret .env file does not exist: {self.env_path}")
        if not self.env_path.is_file():
            raise CapabilityExecutionError(f"secret .env path is not a file: {self.env_path}")

        values: Dict[str, str] = {}
        for line_no, line in enumerate(self.env_path.read_text(encoding="utf-8").splitlines(), start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("export "):
                raise CapabilityExecutionError(
                    f".env line {line_no} uses 'export'; secrets must remain file-backed and must not be exported"
                )
            if "=" not in text:
                raise CapabilityExecutionError(f"invalid .env line {line_no}: expected KEY=VALUE")
            key, raw_value = text.split("=", 1)
            key = self._validate_key(key.strip())
            if key in values:
                raise CapabilityExecutionError(f"duplicate secret key in .env: {key}")
            values[key] = self._decode_value(raw_value)
        return values

    def resolve(self, refs: Iterable[str]) -> Dict[str, str]:
        requested = [self._validate_key(ref) for ref in refs]
        if not requested:
            return {}
        available = self._load()
        result: Dict[str, str] = {}
        for key in requested:
            if key not in available:
                raise CapabilityExecutionError(f"required secret is not available in .env: {key}")
            result[key] = available[key]
        return result

    def list_refs(self) -> List[str]:
        return sorted(self._load(allow_missing=True))

    def set(self, key: str, value: str) -> None:
        key = self._validate_key(key)
        values = self._load(allow_missing=True)
        values[key] = str(value)
        self._write(values)

    def remove(self, key: str) -> bool:
        key = self._validate_key(key)
        values = self._load(allow_missing=True)
        if key not in values:
            return False
        del values[key]
        self._write(values)
        return True

    def _write(self, values: Dict[str, str]) -> None:
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        body = "# Execution Project private credentials. Do not export these values.\n"
        body += "\n".join(f"{key}={self._encode_value(values[key])}" for key in sorted(values))
        if values:
            body += "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=self.env_path.name + ".", dir=str(self.env_path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.env_path)
            try:
                os.chmod(self.env_path, 0o600)
            except OSError:
                pass
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


# The resolver and the writable store are intentionally the same file-backed
# implementation. Alias retained only as a semantic name for execution code.
DotEnvSecretResolver = DotEnvSecretStore
