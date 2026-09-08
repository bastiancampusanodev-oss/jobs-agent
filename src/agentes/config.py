from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")

@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("AGENT_MODEL", "llama3.2:3b")
    brave_cdp_url: str = os.getenv("BRAVE_CDP_URL", "http://127.0.0.1:9222")
    db_path: Path = Path(os.getenv("AGENTES_DB", str(ROOT / "state" / "agents.db")))


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {p}")
    return data
