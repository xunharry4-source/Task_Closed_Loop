from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import re
from typing import Any
import yaml
from dotenv import load_dotenv

_ENV_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)(?::(?P<default>.*))?\}$")

def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result=deepcopy(base)
    for key,value in overlay.items():
        if key in result and isinstance(result[key],dict) and isinstance(value,dict):
            result[key]=deep_merge(result[key],value)
        else:
            result[key]=deepcopy(value)
    return result

def _coerce(value: str) -> Any:
    low=value.strip().lower()
    if low in {'true','false'}: return low=='true'
    if low in {'none','null'}: return None
    try:
        if '.' in value: return float(value)
        return int(value)
    except ValueError:
        return value

def resolve_environment_values(value: Any) -> Any:
    if isinstance(value,dict):
        return {k:resolve_environment_values(v) for k,v in value.items()}
    if isinstance(value,list):
        return [resolve_environment_values(v) for v in value]
    if not isinstance(value,str): return value
    m=_ENV_PATTERN.match(value)
    if not m: return value
    raw=os.getenv(m.group('name'))
    if raw is None: raw=m.group('default')
    return None if raw is None else _coerce(raw)

def _set_dotted(config: dict[str,Any], dotted: str, value: Any) -> None:
    parts=dotted.split('.')
    node=config
    for part in parts[:-1]:
        child=node.get(part)
        if not isinstance(child,dict):
            child={}; node[part]=child
        node=child
    node[parts[-1]]=value

def apply_environment_overrides(config: dict[str,Any]) -> dict[str,Any]:
    mapping=config.get('environment',{}).get('variables',{})
    for dotted, env_name in mapping.items():
        raw=os.getenv(str(env_name))
        if raw is not None:
            _set_dotted(config,str(dotted),_coerce(raw))
    return config

class ConfigLoader:
    def __init__(self,project_root: str|Path): self.project_root=Path(project_root)
    def read_yaml(self,path: str|Path) -> dict[str,Any]:
        p=Path(path)
        if not p.is_absolute(): p=self.project_root/p
        data=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        if not isinstance(data,dict): raise ValueError(f'YAML root must be a mapping: {p}')
        return data
    def _load_dotenv(self) -> None:
        if str(
            os.getenv(
                "TASK_CLOSED_LOOP_DISABLE_DOTENV",
                "",
            )
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return

        p=self.project_root/'config/environment.yml'
        if not p.exists(): return
        cfg=self.read_yaml(p).get('environment',{}).get('dotenv',{})
        if not cfg.get('enabled',True): return
        dotenv_path=self.project_root/cfg.get('file','.env')
        if dotenv_path.exists():
            load_dotenv(dotenv_path=dotenv_path,override=cfg.get('override_existing_environment',False))
    def load(
        self,
        default_path: str | Path = 'config/default.yml',
        *,
        load_dotenv_file: bool = True,
    ) -> dict[str, Any]:
        if load_dotenv_file:
            self._load_dotenv()

        config = self.read_yaml(default_path)
        for extra in config.get('runtime',{}).get('config_files',[]):
            config=deep_merge(config,self.read_yaml(extra))
        config=resolve_environment_values(config)
        return apply_environment_overrides(config)

def load_project_config(
    project_root: str | Path,
    default_path: str | Path = 'config/default.yml',
    *,
    load_dotenv_file: bool = True,
) -> dict[str, Any]:
    return ConfigLoader(project_root).load(
        default_path,
        load_dotenv_file=load_dotenv_file,
    )
