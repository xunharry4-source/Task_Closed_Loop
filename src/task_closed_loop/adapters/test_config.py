from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ProviderManifest,
    ResourceDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.integration.capability_semantics import (
    infer_can_observe_state,
)


class TestConfigurationError(ValueError):
    pass


class TestConfigProvider:
    """
    Developer test provider.

    Fixed files:

        config/test_resources.yml
        config/test_capabilities.yml
    """

    provider_id = "test_config"

    def __init__(
        self,
        resources_path: str | Path | None = None,
        capabilities_path: str | Path | None = None,
    ):
        self.project_root = (
            Path(__file__).resolve().parents[3]
        )

        self.resources_path = self._resolve_path(
            resources_path,
            "config/test_resources.yml",
        )
        self.capabilities_path = self._resolve_path(
            capabilities_path,
            "config/test_capabilities.yml",
        )

        resources = self._load_resources()
        capabilities = self._load_capabilities()

        self._resources = [
            self._normalize_resource(item)
            for item in resources
        ]
        self._capabilities = [
            self._normalize_capability(item)
            for item in capabilities
        ]

        self._manifest = ProviderManifest(
            provider_id=self.provider_id,
            provider_type="test_config",
            resource_support=tuple(
                sorted(
                    {
                        item["type"]
                        for item in self._resources
                    }
                )
            ),
            capability_support=tuple(
                item["id"]
                for item in self._capabilities
            ),
            principal_refs=tuple(
                sorted(
                    {
                        item["principal"]
                        for item in self._capabilities
                        if item["principal"]
                    }
                )
            ),
            security_domains=tuple(
                sorted(
                    {
                        item["security_domain"]
                        for item in self._capabilities
                        if item["security_domain"]
                    }
                )
            ),
        )

    @property
    def manifest(self):
        return self._manifest

    def _resolve_path(
        self,
        supplied: str | Path | None,
        default_relative: str,
    ) -> Path:
        if supplied is None:
            return self.project_root / default_relative

        path = Path(supplied)
        return (
            path
            if path.is_absolute()
            else self.project_root / path
        )

    def _read_yaml(
        self,
        path: Path,
    ) -> dict[str, Any]:
        if not path.exists():
            raise TestConfigurationError(
                f"缺少测试配置文件：{path}"
            )

        raw = yaml.safe_load(
            path.read_text(encoding="utf-8")
        ) or {}

        if not isinstance(raw, dict):
            raise TestConfigurationError(
                f"测试 YAML 根节点必须是 mapping：{path}"
            )

        return raw

    def _load_resources(self) -> list[Any]:
        raw = self._read_yaml(
            self.resources_path
        )

        resources = raw.get("resources")

        if not isinstance(resources, list):
            raise TestConfigurationError(
                "config/test_resources.yml 中 "
                "resources 必须是 list。"
            )

        if not resources:
            raise TestConfigurationError(
                "Resource 为空。请在 "
                "config/test_resources.yml "
                "中添加至少一条 Resource。"
            )

        return resources

    def _load_capabilities(self) -> list[Any]:
        raw = self._read_yaml(
            self.capabilities_path
        )

        capabilities = raw.get(
            "capabilities"
        )

        if capabilities is None:
            capabilities = []

        if not isinstance(
            capabilities,
            list,
        ):
            raise TestConfigurationError(
                "config/test_capabilities.yml 中 "
                "capabilities 必须是 list。"
            )

        return capabilities

    def _normalize_resource(
        self,
        item: Any,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise TestConfigurationError(
                "每条 Resource 必须是 mapping。"
            )

        resource_id = str(
            item.get("id") or ""
        ).strip()
        resource_type = str(
            item.get("type") or ""
        ).strip()

        if not resource_id:
            raise TestConfigurationError(
                "Resource 缺少 id。"
            )

        if not resource_type:
            raise TestConfigurationError(
                f"Resource '{resource_id}' 缺少 type。"
            )

        if (
            "fact" not in item
            and "payload" not in item
        ):
            raise TestConfigurationError(
                f"Resource '{resource_id}' "
                "需要 fact 或 payload。"
            )

        payload = item.get("payload")
        if payload is None:
            payload = {
                "fact": item.get("fact")
            }

        return {
            "id": resource_id,
            "type": resource_type,
            "source_identity": str(
                item.get("source_identity")
                or resource_id
            ),
            "payload": payload,
            "revision": (
                str(item["revision"])
                if item.get("revision") is not None
                else None
            ),
            "availability": str(
                item.get(
                    "availability",
                    "available",
                )
            ),
        }

    def _normalize_capability(
        self,
        item: Any,
    ) -> dict[str, Any]:
        if isinstance(item, str):
            capability_id = item.strip()

            if not capability_id:
                raise TestConfigurationError(
                    "Capability 字符串为空。"
                )

            return {
                "id": capability_id,
                "description": capability_id,
                "action_type": (
                    capability_id.split(".")[-1]
                ),
                "principal": "local-test",
                "security_domain": "local-test",
                "availability": "available",
                "permissions": ("execute",),
                "target_scope": {},
                "can_observe_state": False,
                "observable_state": None,
                "observation_operations": (),
            }

        if not isinstance(item, dict):
            raise TestConfigurationError(
                "Capability 必须是字符串或 mapping。"
            )

        capability_id = str(
            item.get("id") or ""
        ).strip()

        if not capability_id:
            raise TestConfigurationError(
                "Capability 缺少 id。"
            )

        action_type = str(
            item.get("action_type")
            or capability_id.split(".")[-1]
        ).strip()

        description = str(
            item.get("description")
            or action_type
        ).strip()

        permissions = item.get(
            "permissions",
            ["execute"],
        )
        if not isinstance(
            permissions,
            (list, tuple),
        ):
            raise TestConfigurationError(
                f"Capability '{capability_id}' "
                "permissions 必须是 list。"
            )

        target_scope = (
            item.get("target_scope") or {}
        )
        if not isinstance(target_scope, dict):
            raise TestConfigurationError(
                f"Capability '{capability_id}' "
                "target_scope 必须是 mapping。"
            )

        observation = item.get("observation")
        if observation is None:
            observation = {}
        if not isinstance(observation, dict):
            raise TestConfigurationError(
                f"Capability '{capability_id}' "
                "observation 必须是 mapping。"
            )

        explicit_observe = observation.get("enabled")
        if explicit_observe is None and "can_observe_state" in item:
            explicit_observe = item.get("can_observe_state")

        observation_operations = (
            observation.get("operations")
            or item.get("observation_operations")
            or []
        )
        if not isinstance(observation_operations, (list, tuple)):
            raise TestConfigurationError(
                f"Capability '{capability_id}' "
                "observation.operations 必须是 list。"
            )

        can_observe_state = infer_can_observe_state(
            action_type=action_type,
            description=description,
            permissions=permissions,
            target_scope=target_scope,
            explicit=(
                bool(explicit_observe)
                if explicit_observe is not None
                else None
            ),
        )
        observable_state = (
            observation.get("state_domain")
            or observation.get("description")
            or item.get("observable_state")
        )
        if observable_state is not None:
            observable_state = str(observable_state).strip() or None

        return {
            "id": capability_id,
            "description": description,
            "action_type": action_type,
            "principal": (
                str(item["principal"])
                if item.get("principal") is not None
                else "local-test"
            ),
            "security_domain": (
                str(item["security_domain"])
                if item.get("security_domain") is not None
                else "local-test"
            ),
            "availability": str(
                item.get(
                    "availability",
                    "available",
                )
            ),
            "permissions": tuple(
                str(value)
                for value in permissions
            ),
            "target_scope": target_scope,
            "can_observe_state": can_observe_state,
            "observable_state": observable_state,
            "observation_operations": tuple(
                str(value)
                for value in observation_operations
            ),
        }

    async def discover_resources(self):
        return [
            ResourceDescriptor(
                resource_id=item["id"],
                provider_id=self.provider_id,
                resource_type=item["type"],
                source_identity=item["source_identity"],
            )
            for item in self._resources
        ]

    async def read_resource(self, ref):
        item = next(
            item
            for item in self._resources
            if item["id"] == ref.resource_id
        )

        return ResourceSnapshot(
            resource_id=item["id"],
            provider_id=self.provider_id,
            source_identity=item["source_identity"],
            resource_type=item["type"],
            payload=item["payload"],
            revision=item["revision"],
            availability=item["availability"],
        )

    async def discover_capabilities(self):
        return [
            CapabilityDescriptor(
                capability_id=item["id"],
                provider_id=self.provider_id,
                action_type=item["action_type"],
                principal=item["principal"],
                security_domain=item["security_domain"],
                target_scope=dict(item["target_scope"]),
                permissions=tuple(item["permissions"]),
                availability=item["availability"],
                description=item["description"],
                can_observe_state=item["can_observe_state"],
                observable_state=item["observable_state"],
                observation_operations=tuple(
                    item["observation_operations"]
                ),
            )
            for item in self._capabilities
        ]
