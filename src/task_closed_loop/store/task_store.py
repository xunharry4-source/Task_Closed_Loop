"""The durable task store: projects, the three middle layers, themes and tasks.

Until now nothing survived a run — `existing_tasks` was always empty, so the dedupe
rules that were written for it had never once executed. This store is that missing
boundary, and it is also what makes the chain's hard rule checkable: a task may only
be written when a problem / value / demand of the *same* project exists.

The default store is the user's own 参谋.db, which already enforces that rule with
triggers. Therefore: never create or alter tables in a database that already exists —
if a table is missing, say which one and stop. A brand-new path gets the bundled
schema, including the same triggers.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence

STORE_TABLES = (
    "entities",
    "problems",
    "value_opportunities",
    "capability_voids",
    "task_questions",
    "tasks",
    "exclusions",
)

OPEN_TASK_STATES = ("待办", "进行中")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  entity_id TEXT PRIMARY KEY, name TEXT, domain TEXT, description TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS problems(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, source TEXT, dimension TEXT, evidence TEXT,
  severity INTEGER CHECK(severity BETWEEN 1 AND 5), economic_impact TEXT, solutions TEXT,
  status TEXT DEFAULT '存在', task_id INTEGER, first_seen TEXT DEFAULT (date('now','localtime')),
  last_seen TEXT DEFAULT (date('now','localtime')), note TEXT, root_cause TEXT,
  problem_level TEXT, entity_id TEXT);
CREATE TABLE IF NOT EXISTS value_opportunities(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, resources_used TEXT, capabilities_used TEXT,
  evidence TEXT, value_type TEXT, value_score INTEGER CHECK(value_score BETWEEN 1 AND 5),
  economic_value TEXT, how_created TEXT, status TEXT DEFAULT '可创造', task_id INTEGER,
  created_at TEXT DEFAULT (date('now','localtime')), note TEXT, value_level TEXT, entity_id TEXT);
CREATE TABLE IF NOT EXISTS capability_voids(
  id INTEGER PRIMARY KEY, entity_id TEXT, required_capability TEXT, pain_point_evidence TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')), title TEXT, demand_level TEXT,
  status TEXT DEFAULT '待转任务', task_id INTEGER, last_seen TEXT);
CREATE TABLE IF NOT EXISTS task_questions(
  id INTEGER PRIMARY KEY, entity_id TEXT NOT NULL, week TEXT NOT NULL, question TEXT NOT NULL,
  direction TEXT, resource_info TEXT, status TEXT DEFAULT '待问', yield_count INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')), capability_info TEXT,
  theme_kind TEXT DEFAULT '固定', UNIQUE(entity_id,week,question));
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, priority INTEGER DEFAULT 3,
  status TEXT DEFAULT '待办', source TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')), note TEXT, value_type TEXT,
  value_score INTEGER, economic_note TEXT, task_key TEXT, evidence TEXT, expected_result TEXT,
  decision TEXT DEFAULT '未决', expires_at TEXT, times_proposed INTEGER DEFAULT 1,
  task_type TEXT, deliverable TEXT, task_origin TEXT, task_tier TEXT, entity_id TEXT,
  theme TEXT, theme_kind TEXT, source_table TEXT, source_id INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_key ON tasks(task_key) WHERE task_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS exclusions(
  id INTEGER PRIMARY KEY, pattern TEXT NOT NULL, scope TEXT, reason TEXT, source_task_id INTEGER,
  created_at TEXT DEFAULT (datetime('now','localtime')), target_key TEXT, expires_at TEXT);
CREATE TRIGGER IF NOT EXISTS trg_tasks_source BEFORE INSERT ON tasks WHEN NOT (
 (NEW.source_table='problems' AND EXISTS(SELECT 1 FROM problems p WHERE p.id=NEW.source_id AND p.entity_id=NEW.entity_id)) OR
 (NEW.source_table='value_opportunities' AND EXISTS(SELECT 1 FROM value_opportunities v WHERE v.id=NEW.source_id AND v.entity_id=NEW.entity_id)) OR
 (NEW.source_table='capability_voids' AND EXISTS(SELECT 1 FROM capability_voids c WHERE c.id=NEW.source_id AND c.entity_id=NEW.entity_id)))
BEGIN SELECT RAISE(ABORT,'任务必须有同项目的来源 问题/价值/需求'); END;
"""


class TaskStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredTask:
    task_id: int
    title: str
    task_key: str
    entity_id: str
    task_type: str
    task_tier: str
    theme: str
    status: str
    decision: str
    expires_at: str | None
    times_proposed: int
    evidence: str
    expected_result: str


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def iso_week(moment: date | None = None) -> str:
    moment = moment or date.today()
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def compute_task_key(*, entity_id: str, task_type: str, core_target: Iterable[str]) -> str:
    """hash(project, task type, core target).

    `core_target` is the normalized work relation plus the sorted stable object anchors,
    i.e. exactly what the existing audits already treat as a task's real identity
    (`generation_audit.candidate_identity_anchors`). The LLM-authored `task_identity`
    is deliberately not part of the key: it is free text and two runs word it
    differently for the same work.
    """

    payload = json.dumps(
        {
            "entity_id": str(entity_id),
            "task_type": str(task_type),
            "core_target": sorted(str(value) for value in core_target if str(value).strip()),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class TaskStore:
    def __init__(self, path: str | Path, *, create_if_missing: bool = True):
        self.path = Path(path).expanduser()
        existed = self.path.exists()
        if not existed:
            if not create_if_missing:
                raise TaskStoreError(f"任务库不存在：{self.path}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        if not existed:
            # Only a brand-new store gets its schema from here. An existing database —
            # the user's own 参谋.db — is never created or altered by this code.
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        self._require_tables()

    # -- lifecycle ----------------------------------------------------------

    def _require_tables(self) -> None:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
        present = {str(row["name"]) for row in rows}
        missing = [name for name in STORE_TABLES if name not in present]
        if missing:
            raise TaskStoreError(
                f"任务库 {self.path} 缺少表：{', '.join(missing)}。"
                "本程序不会修改既有数据库的结构，请先确认这是正确的任务库。"
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "TaskStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @contextmanager
    def _write(self):
        """Commit on success, roll back on any database error, then re-raise."""

        try:
            yield
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _columns(self, table: str) -> set[str]:
        rows = self._connection.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}

    def _insert(self, table: str, values: dict[str, Any]) -> int:
        usable = {
            key: value for key, value in values.items() if key in self._columns(table)
        }
        columns = ", ".join(usable)
        placeholders = ", ".join("?" for _ in usable)
        # A write the database refuses (e.g. the lineage trigger) must not leave an open
        # transaction behind: that would lock out every later write in the same run.
        with self._write():
            cursor = self._connection.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                tuple(usable.values()),
            )
        return int(cursor.lastrowid)

    def _update(self, table: str, row_id: int, values: dict[str, Any]) -> None:
        usable = {
            key: value for key, value in values.items() if key in self._columns(table)
        }
        if not usable:
            return
        assignments = ", ".join(f"{key} = ?" for key in usable)
        with self._write():
            self._connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*usable.values(), row_id),
            )

    # -- projects -----------------------------------------------------------

    def ensure_project(self, *, project_id: str, name: str = "", domain: str = "", description: str = "") -> None:
        row = self._connection.execute(
            "SELECT entity_id FROM entities WHERE entity_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            self._insert(
                "entities",
                {
                    "entity_id": project_id,
                    "name": name or project_id,
                    "domain": domain,
                    "description": description,
                },
            )
            return
        with self._write():
            self._connection.execute(
                "UPDATE entities SET name = COALESCE(NULLIF(?, ''), name),"
                " domain = COALESCE(NULLIF(?, ''), domain),"
                " description = COALESCE(NULLIF(?, ''), description)"
                " WHERE entity_id = ?",
                (name, domain, description, project_id),
            )

    def known_project_ids(self) -> set[str]:
        rows = self._connection.execute("SELECT entity_id FROM entities").fetchall()
        return {str(row["entity_id"]) for row in rows}

    # -- middle layers ------------------------------------------------------

    def _upsert_by_title(
        self,
        table: str,
        *,
        entity_id: str,
        title: str,
        insert_values: dict[str, Any],
        refresh_values: dict[str, Any],
    ) -> tuple[int, bool]:
        row = self._connection.execute(
            f"SELECT id FROM {table} WHERE entity_id = ? AND title = ?",
            (entity_id, title),
        ).fetchone()
        if row is not None:
            row_id = int(row["id"])
            self._update(table, row_id, refresh_values)
            return row_id, False
        return self._insert(table, insert_values), True

    def save_problem(self, *, entity_id: str, record) -> tuple[int, bool]:
        evidence = _json_text(list(record.reality_basis_refs))
        return self._upsert_by_title(
            "problems",
            entity_id=entity_id,
            title=record.title,
            insert_values={
                "title": record.title,
                "entity_id": entity_id,
                "problem_level": record.problem_level,
                "root_cause": record.root_cause,
                "dimension": record.dimension,
                "evidence": evidence,
                "severity": max(1, min(5, int(record.severity or 3))),
                "economic_impact": record.economic_impact,
                "solutions": record.solutions,
                "note": record.note,
                "source": "task_closed_loop",
                "status": "存在",
                "first_seen": _today(),
                "last_seen": _today(),
            },
            refresh_values={
                "last_seen": _today(),
                "evidence": evidence,
                "severity": max(1, min(5, int(record.severity or 3))),
                "root_cause": record.root_cause,
                "problem_level": record.problem_level,
            },
        )

    def save_value(self, *, entity_id: str, record) -> tuple[int, bool]:
        evidence = _json_text(list(record.reality_basis_refs))
        return self._upsert_by_title(
            "value_opportunities",
            entity_id=entity_id,
            title=record.title,
            insert_values={
                "title": record.title,
                "entity_id": entity_id,
                "value_level": record.value_level,
                "value_type": self._known_value_type(record.value_type),
                "value_score": max(1, min(5, int(record.value_score or 3))),
                "economic_value": record.economic_value,
                "how_created": record.how_created,
                "resources_used": _json_text(list(record.resources_used)),
                "capabilities_used": _json_text(list(record.capabilities_used)),
                "evidence": evidence,
                "note": record.note,
                "status": "可创造",
                "created_at": _today(),
            },
            refresh_values={
                "evidence": evidence,
                "value_level": record.value_level,
                "how_created": record.how_created,
                "value_score": max(1, min(5, int(record.value_score or 3))),
            },
        )

    def save_demand(self, *, entity_id: str, record) -> tuple[int, bool]:
        evidence = record.pain_point_evidence or _json_text(list(record.reality_basis_refs))
        return self._upsert_by_title(
            "capability_voids",
            entity_id=entity_id,
            title=record.title,
            insert_values={
                "title": record.title,
                "entity_id": entity_id,
                "demand_level": record.demand_level,
                "required_capability": record.required_capability,
                "pain_point_evidence": evidence,
                "status": "待转任务",
                "last_seen": _today(),
            },
            refresh_values={
                "last_seen": _today(),
                "pain_point_evidence": evidence,
                "demand_level": record.demand_level,
            },
        )

    def _known_value_type(self, value_type: str) -> str | None:
        """`tasks.value_type` / `value_opportunities.value_type` reference value_types(name).

        Foreign keys are off by default in SQLite, but writing a name that is not in the
        user's own taxonomy would still be junk data. Keep it only when it matches.
        """

        name = str(value_type or "").strip()
        if not name:
            return None
        try:
            row = self._connection.execute(
                "SELECT name FROM value_types WHERE name = ?", (name,)
            ).fetchone()
        except sqlite3.Error:
            return None
        return name if row is not None else None

    # -- themes -------------------------------------------------------------

    def save_theme(
        self,
        *,
        entity_id: str,
        week: str,
        theme: str,
        theme_kind: str,
        resource_info: str,
        capability_info: str,
    ) -> int:
        row = self._connection.execute(
            "SELECT id FROM task_questions WHERE entity_id = ? AND week = ? AND question = ?",
            (entity_id, week, theme),
        ).fetchone()
        if row is not None:
            row_id = int(row["id"])
            self._update(
                "task_questions",
                row_id,
                {
                    "resource_info": resource_info,
                    "capability_info": capability_info,
                    "theme_kind": theme_kind,
                },
            )
            return row_id
        return self._insert(
            "task_questions",
            {
                "entity_id": entity_id,
                "week": week,
                "question": theme,
                "theme_kind": theme_kind,
                "resource_info": resource_info,
                "capability_info": capability_info,
                "status": "待问",
            },
        )

    def mark_theme_asked(self, theme_row_id: int, *, yield_count: int) -> None:
        self._update(
            "task_questions",
            theme_row_id,
            {"status": "已问", "yield_count": int(yield_count)},
        )

    def previous_theme_yield(self, *, entity_id: str, week: str) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT question, yield_count FROM task_questions"
            " WHERE entity_id = ? AND week <> ? ORDER BY week DESC LIMIT 50",
            (entity_id, week),
        ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            question = str(row["question"])
            if question not in out:
                out[question] = int(row["yield_count"] or 0)
        return out

    # -- exclusions and open tasks -----------------------------------------

    def exclusions(self, *, entity_id: str | None = None) -> list[dict[str, str]]:
        rows = self._connection.execute(
            "SELECT pattern, scope, reason, target_key, expires_at FROM exclusions"
        ).fetchall()
        out: list[dict[str, str]] = []
        today = _today()
        for row in rows:
            expires = str(row["expires_at"] or "").strip()
            if expires and expires < today:
                continue
            scope = str(row["scope"] or "").strip()
            # A scope naming another project does not apply here. Scopes that are not a
            # project id (e.g. 关键词) are global.
            if entity_id and scope and scope != entity_id and scope in self.known_project_ids():
                continue
            out.append(
                {
                    "pattern": str(row["pattern"] or "").strip(),
                    "scope": scope,
                    "reason": str(row["reason"] or "").strip(),
                    "target_key": str(row["target_key"] or "").strip(),
                }
            )
        return [item for item in out if item["pattern"] or item["target_key"]]

    def open_tasks(self, *, entity_id: str) -> list[StoredTask]:
        placeholders = ", ".join("?" for _ in OPEN_TASK_STATES)
        rows = self._connection.execute(
            f"SELECT * FROM tasks WHERE entity_id = ? AND status IN ({placeholders})",
            (entity_id, *OPEN_TASK_STATES),
        ).fetchall()
        return [self._stored_task(row) for row in rows]

    def task_by_key(self, task_key: str) -> StoredTask | None:
        row = self._connection.execute(
            "SELECT * FROM tasks WHERE task_key = ?", (task_key,)
        ).fetchone()
        return self._stored_task(row) if row is not None else None

    @staticmethod
    def _stored_task(row: sqlite3.Row) -> StoredTask:
        keys = row.keys()

        def value(name: str, default: Any = "") -> Any:
            return row[name] if name in keys and row[name] is not None else default

        return StoredTask(
            task_id=int(value("id", 0)),
            title=str(value("title")),
            task_key=str(value("task_key")),
            entity_id=str(value("entity_id")),
            task_type=str(value("task_type")),
            task_tier=str(value("task_tier")),
            theme=str(value("theme")),
            status=str(value("status")),
            decision=str(value("decision")),
            expires_at=str(value("expires_at")) or None,
            times_proposed=int(value("times_proposed", 1) or 1),
            evidence=str(value("evidence")),
            expected_result=str(value("expected_result")),
        )

    # -- tasks --------------------------------------------------------------

    def save_task(
        self,
        *,
        entity_id: str,
        title: str,
        task_key: str,
        task_tier: str,
        task_type: str,
        theme: str,
        theme_kind: str,
        source_table: str,
        source_id: int,
        evidence: Sequence[str] | str,
        expected_result: str,
        deliverable: str = "",
        note: str = "",
        priority: int = 3,
        value_type: str = "",
        value_score: int | None = None,
        economic_note: str = "",
        task_origin: str = "",
    ) -> tuple[int, str]:
        """Write one task, or fold it into the one that is already there.

        Returns (task_id, outcome) where outcome is 'inserted' | 'repeated' | 'shelved'.
        """

        existing = self.task_by_key(task_key)
        if existing is not None:
            if (
                existing.decision == "搁置"
                and existing.expires_at
                and str(existing.expires_at) > _today()
            ):
                return existing.task_id, "shelved"
            self._update(
                "tasks",
                existing.task_id,
                {
                    "times_proposed": existing.times_proposed + 1,
                    "evidence": _json_text(evidence),
                    "expected_result": expected_result or existing.expected_result,
                    "updated_at": _now(),
                },
            )
            return existing.task_id, "repeated"

        task_id = self._insert(
            "tasks",
            {
                "title": title,
                "entity_id": entity_id,
                "task_key": task_key,
                "task_tier": task_tier,
                "task_type": task_type,
                "theme": theme,
                "theme_kind": theme_kind,
                "source_table": source_table,
                "source_id": int(source_id),
                "evidence": _json_text(evidence),
                "expected_result": expected_result,
                "deliverable": deliverable,
                "note": note,
                "priority": int(priority),
                "value_type": self._known_value_type(value_type),
                "value_score": value_score,
                "economic_note": economic_note,
                "task_origin": task_origin,
                "source": "task_closed_loop",
                "status": "待办",
                "decision": "未决",
                "times_proposed": 1,
            },
        )
        self._mark_source_converted(
            source_table=source_table, source_id=int(source_id), task_id=task_id
        )
        return task_id, "inserted"

    def _mark_source_converted(self, *, source_table: str, source_id: int, task_id: int) -> None:
        if source_table not in {"problems", "value_opportunities", "capability_voids"}:
            raise TaskStoreError(f"未知来源表：{source_table}")
        with self._write():
            self._connection.execute(
                f"UPDATE {source_table} SET status = '已转任务', task_id = ? WHERE id = ?",
                (task_id, source_id),
            )


def open_task_store(config: dict) -> TaskStore | None:
    """Build the store from config, or None when it is switched off."""

    section = (config or {}).get("task_store") or {}
    if not bool(section.get("enabled", True)):
        return None
    path = str(section.get("path") or "").strip()
    if not path:
        raise TaskStoreError("task_store.enabled=true 但没有配置 task_store.path。")
    return TaskStore(path, create_if_missing=bool(section.get("create_if_missing", True)))
