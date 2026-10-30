"""Settings loader: config/settings.yaml with ${VAR:default} expansion and .env support."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]          # PS5-Agentic-Testing/
REPO_ROOT = PKG_ROOT.parent
CONFIG_DIR = PKG_ROOT / "config"
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader. Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        out = _VAR.sub(sub, value)
        low = out.lower()
        if low in ("true", "false"):
            return low == "true"
        try:
            return int(out) if out.lstrip("-").isdigit() else (
                float(out) if re.fullmatch(r"-?\d+\.\d+", out) else out)
        except ValueError:
            return out
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_yaml(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class Settings:
    """Typed-ish accessor over settings.yaml. Paths are resolved to absolute."""

    def __init__(self, path: Path | str = CONFIG_DIR / "settings.yaml"):
        load_dotenv()
        self.path = Path(path)
        self.data: dict[str, Any] = _expand(load_yaml(self.path))
        p = self.data.get("paths", {})
        self.automation_root = self._abs(p.get("automation_root", "../PS5-Automation-Python"))
        self.controls_config = self._abs(p.get("controls_config",
                                               "../PS5-Automation-Python/config/controls.yaml"))
        self.scenarios_dir = self._abs(p.get("scenarios_dir", "./scenarios"))
        self.prompts_dir = self._abs(p.get("prompts_dir", "./config/prompts"))
        self.artifacts_dir = self._abs(p.get("artifacts_dir", "./artifacts"))
        self.reports_dir = self._abs(p.get("reports_dir", "./artifacts/reports"))
        self.config_dir = CONFIG_DIR

    @staticmethod
    def _abs(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (PKG_ROOT / path).resolve()

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def console_profile(self) -> str:
        return str(self.get("console.profile", "ps5"))

    @property
    def dry_run(self) -> bool:
        return bool(self.get("runtime.dry_run", False))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
