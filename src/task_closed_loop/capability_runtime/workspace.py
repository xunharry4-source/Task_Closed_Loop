from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import yaml


_DEFAULT_PROJECT = {
    "schema_version": 2,
    "project_id": "task-closed-loop-execution-workspace",
    "project_role": "persistent_capability_workspace",
    "owner_system": "task-closed-loop",
    "cli": {
        "preflight_engine": "auto",
        "task_execution_engine": "inherit_preflight",
        "allowed_engines": ["codex_cli", "gemini_cli", "claude_cli"],
        "capability_build_engine": "inherit_preflight",
    },
    "policies": {
        "architecture_owned_by_host": True,
        "cli_may_modify_architecture": False,
        "cli_may_repair_locked_architecture": True,
        "cli_may_create_capabilities": True,
        "cli_may_modify_verified_capabilities": "task_scoped",
        "secrets_must_not_be_written_to_source": True,
        "secrets_must_not_be_written_to_environment": True,
        "secrets_source": "dotenv_file",
        "new_capability_requires_tests": True,
        "new_capability_requires_registry_entry": True,
        "execution_requires_verified_capability": True,
        "cli_self_report_is_not_verification": True,
        "trusted_outcome_requires_host_verification": True,
        "external_write_requires_readback_verification": True,
        "filesystem_write_requires_artifact_or_readback_verification": True,
    },
    "paths": {
        "capability_registry": "capability_registry.yml",
        "capabilities": "capabilities",
        "connectors": "connectors",
        "builds": "builds",
        "artifacts": "artifacts",
        "state": "state",
        "logs": "logs",
        "temp": "temp",
        # Stage 1-2 assets: CLI-authored resource/capability analysis code and the
        # two standard files that are the only Task-layer input contract.
        "analysis": "analysis",
        "generated": "generated",
        "secrets_file": ".env",
    },
    "execution_project_version": "1.1.0",
}

_REQUIRED_DIRECTORIES = (
    "capabilities",
    "connectors",
    "builds",
    "artifacts",
    "state",
    "logs",
    "temp",
    "analysis",
    "analysis/resources",
    "analysis/functions",
    "analysis/results",
    "generated",
)

_REQUIRED_FILES = (
    "project.yml",
    "capability_registry.yml",
    ".env",
    # Host-owned unified interface: the entry and the two templates. They ship with the
    # template and are filled in deterministically, never written by a CLI.
    "analysis/main.py",
    "analysis/templates.py",
)


class CliProjectStructureError(RuntimeError):
    """Stage 1 gate: the CLI Project directory is not a usable working project."""


class ExecutionWorkspaceManager:
    """Low-level verifier/bootstrap helper for the persistent CLI Project.

    Formal Stage 1 policy is owned by ``app.stages``: a missing project is copied
    from the template; an existing invalid project is repaired by a CLI *in place*.
    ``ensure`` remains a deterministic bootstrap primitive and is not the repair
    policy for an already-existing invalid production project.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def verify(self) -> list[str]:
        """Return structural problems; an empty list means the project is usable."""

        problems: list[str] = []
        if not self.root.exists():
            return [f"CLI Project 目录不存在：{self.root}"]
        if not self.root.is_dir():
            return [f"CLI Project 路径不是目录：{self.root}"]

        for name in _REQUIRED_FILES:
            path = self.root / name
            if not path.is_file():
                problems.append(f"缺少必需文件：{name}")

        for name in _REQUIRED_DIRECTORIES:
            path = self.root / name
            if not path.is_dir():
                problems.append(f"缺少必需目录：{name}/")

        project_path = self.root / "project.yml"
        if project_path.is_file():
            try:
                data = yaml.safe_load(project_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                problems.append(f"project.yml 无法解析：{exc}")
            else:
                if not isinstance(data, dict):
                    problems.append("project.yml 顶层必须是映射。")
                elif data.get("project_role") != _DEFAULT_PROJECT["project_role"]:
                    problems.append(
                        "project.yml 的 project_role 不是 "
                        f"{_DEFAULT_PROJECT['project_role']}；该目录不是 CLI Project。"
                    )

        return problems

    def ensure(
        self,
        *,
        overrides: dict[str, Any] | None = None,
        template_root: Path | None = None,
    ) -> Path:
        """Deterministically bootstrap/fill a workspace, then re-verify it.

        Formal production Stage 1 calls this only for a *newly copied* template (or
        tests/tooling). Existing invalid production projects are repaired by CLI.
        """

        self.root.mkdir(parents=True, exist_ok=True)
        template = Path(template_root).resolve() if template_root else None
        if template is not None and not template.is_dir():
            template = None

        project_path = self.root / "project.yml"
        if not project_path.exists():
            data = dict(_DEFAULT_PROJECT)
            if overrides:
                # Only a shallow top-level override is intentionally supported here;
                # architecture shape remains Host-owned.
                data.update(overrides)
            project_path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        registry = self.root / "capability_registry.yml"
        if not registry.exists():
            registry.write_text(
                yaml.safe_dump({"schema_version": 1, "capabilities": []}, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        env_path = self.root / ".env"
        if not env_path.exists():
            # The secret store is never shipped in the template; only its example is.
            env_path.write_text("# Private capability credentials. Never export these values.\n", encoding="utf-8")
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".env\n__pycache__/\n*.pyc\n", encoding="utf-8")
        for name in _REQUIRED_DIRECTORIES:
            (self.root / name).mkdir(parents=True, exist_ok=True)

        if template is not None:
            self._copy_missing_template_files(template)

        problems = self.verify()
        if problems:
            raise CliProjectStructureError(
                f"CLI Project 结构仍然不合格（{self.root}）：" + "；".join(problems)
            )
        return self.root

    HOST_OWNED_FILES = ("analysis/main.py", "analysis/templates.py", "analysis/README.md")

    def fill_host_owned_files(self, template: Path) -> list[str]:
        """Install the Host-owned interface files: the entry and the two templates.

        They define the interface between the Host and the analysis code, so the Host
        provides them instead of asking a CLI to reinvent the entry every run. A
        differing copy left over from before is superseded, not silently kept — but it
        is moved aside as `<name>.superseded` rather than deleted. Analysis
        implementations under `analysis/resources/` and `analysis/functions/` are never
        touched.
        """

        template = Path(template)
        filled: list[str] = []
        for relative in self.HOST_OWNED_FILES:
            source = template / relative
            target = self.root / relative
            if not source.is_file():
                continue
            wanted = source.read_bytes()
            if target.exists():
                if target.read_bytes() == wanted:
                    continue
                backup = target.with_suffix(target.suffix + ".superseded")
                if not backup.exists():
                    backup.write_bytes(target.read_bytes())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wanted)
            filled.append(relative)
        return filled

    def _copy_missing_template_files(self, template: Path) -> None:
        """Fill in files the template provides and this project is missing.

        Existing files are never overwritten: the CLI Project accumulates long-lived
        code and must survive repeated Stage 1 checks untouched.
        """

        for source in sorted(template.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(template)
            if relative.name == ".gitkeep":
                continue
            if relative.name == ".env":
                continue
            target = self.root / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
