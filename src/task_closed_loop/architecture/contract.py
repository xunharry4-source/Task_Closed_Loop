from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ArchitectureContractError(RuntimeError):
    """The frozen production architecture was modified or is incomplete."""


_LOCKED_STAGE_SEQUENCE = (
    (1, "cli_project_check"),
    (2, "resource_capability_materialization"),
    (3, "initial_task_generation"),
    (4, "task_audit"),
    (5, "qualified_task_count_check"),
    (6, "task_dimension_generation"),
    (7, "task_regeneration"),
)

_LOCKED_STAGE_2_INPUTS = ("local_resources", "remote_resources", "functions")
_LOCKED_INVARIANTS = {
    "stage_1_and_2_must_finish_before_stage_3",
    "stage_3_generation_and_stage_4_audit_are_distinct_calls",
    "stage_5_counts_only_stage_4_accepted_business_tasks",
    "stage_6_runs_only_when_stage_5_is_too_few",
    "stage_7_uses_resources_capabilities_valid_tasks_and_dimensions",
    "stage_7_tasks_must_return_to_stage_4",
    "cli_authored_stage_2_code_lives_and_evolves_inside_cli_project",
    "task_layer_reads_only_standard_resource_and_capability_files",
}


@dataclass(frozen=True)
class ArchitectureContract:
    raw: dict[str, Any]

    @property
    def cli_project_default_directory(self) -> str:
        return str(self.raw["cli_project"]["default_directory"])

    @property
    def cli_project_template_directory(self) -> str:
        return str(self.raw["cli_project"]["template_directory"])

    @property
    def task_files(self) -> dict[str, str]:
        return dict(self.raw["task_files"])

    @property
    def stage_sequence(self) -> tuple[tuple[int, str], ...]:
        return tuple(
            (int(item["number"]), str(item["id"]))
            for item in self.raw["stages"]
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArchitectureContractError(message)


def _read_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ArchitectureContractError(f"缺少架构锁文件：{path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ArchitectureContractError(f"架构锁文件无法解析：{exc}") from exc
    contract = document.get("architecture_contract")
    if not isinstance(contract, dict):
        raise ArchitectureContractError("architecture_contract.yml 缺少 architecture_contract 映射。")
    return contract


def load_locked_architecture_contract(
    project_root: str | Path,
    path: str | Path = "config/architecture_contract.yml",
) -> ArchitectureContract:
    root = Path(project_root).resolve()
    candidate = Path(path)
    contract_path = candidate if candidate.is_absolute() else root / candidate
    data = _read_contract(contract_path)

    _require(data.get("id") == "task_closed_loop_production_pipeline", "架构 id 被修改。")
    _require(str(data.get("version")) == "1.2", "架构版本必须锁定为 1.2。")
    _require(data.get("locked") is True, "架构必须 locked=true。")

    cli = data.get("cli_project") or {}
    stage_1 = cli.get("stage_1") or {}
    _require(cli.get("default_directory") == "cli_project", "默认 CLI 工作目录必须是 cli_project。")
    _require(cli.get("template_directory") == "cli_project_template", "CLI 模板目录必须是 cli_project_template。")
    _require(stage_1.get("when_missing") == "copy_template", "Stage 1 缺失目录必须复制模板。")
    _require(stage_1.get("when_valid") == "reuse", "Stage 1 正确目录必须直接复用。")
    _require(stage_1.get("when_invalid") == "repair_with_cli_in_place", "Stage 1 错误目录必须由 CLI 原位修复。")

    stage_2 = data.get("stage_2") or {}
    _require(
        tuple(stage_2.get("input_sections") or ()) == _LOCKED_STAGE_2_INPUTS,
        "Stage 2 输入必须固定为 local_resources / remote_resources / functions。",
    )
    _require(stage_2.get("cli_working_directory") == "cli_project", "Stage 2 CLI 必须直接在 cli_project 内工作。")
    outputs = stage_2.get("standard_outputs") or {}
    _require(outputs.get("resources") == "generated/resources.generated.yml", "Resource 标准输出路径被修改。")
    _require(outputs.get("capabilities") == "generated/capabilities.generated.yml", "Capability 标准输出路径被修改。")

    stages = tuple((int(x.get("number", 0)), str(x.get("id", ""))) for x in (data.get("stages") or []))
    _require(stages == _LOCKED_STAGE_SEQUENCE, f"Stage 顺序被修改：{stages!r}")
    stage_7 = (data.get("stages") or [])[-1]
    _require(int(stage_7.get("returns_to_stage", 0)) == 4, "Stage 7 生成的新任务必须回到 Stage 4 审查。")

    task_files = data.get("task_files") or {}
    expected_task_files = {
        "initial": "generated/tasks.initial.yml",
        "audited": "generated/tasks.audited.yml",
        "dimensions": "generated/task_dimensions.yml",
        "regenerated_pattern": "generated/tasks.regenerated.round_{round}.yml",
        "final": "generated/tasks.final.yml",
    }
    _require(task_files == expected_task_files, "Task 生产文件路径被修改。")

    boundaries = data.get("code_boundaries") or {}
    _require(boundaries.get("pipeline_module") == "src/task_closed_loop/pipeline/production.py", "正式 Pipeline 模块被修改。")
    _require(boundaries.get("contracts_root") == "src/task_closed_loop/contracts", "Contracts 根目录被修改。")
    _require(boundaries.get("implementations_root") == "src/task_closed_loop/implementations", "Implementations 根目录被修改。")
    boundary_rules = set(boundaries.get("rules") or [])
    required_boundary_rules = {
        "pipeline_imports_contracts_only",
        "contracts_never_import_implementations",
        "runtime_is_composition_root_only",
        "behavior_changes_modify_implementations_not_pipeline",
        "architecture_changes_require_contract_version_bump",
    }
    _require(required_boundary_rules.issubset(boundary_rules), "接口/实现架构锁规则缺失。")

    invariants = set(data.get("invariants") or [])
    required_invariants = set(_LOCKED_INVARIANTS) | {
        "pipeline_depends_on_contracts_not_concrete_implementations",
        "future_behavior_changes_replace_or_modify_implementations",
    }
    _require(required_invariants.issubset(invariants), "架构硬约束缺失。")

    return ArchitectureContract(raw=data)
