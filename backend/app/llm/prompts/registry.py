"""Versioned prompts: `prompts/{name}/v{N}.md` with YAML front matter and `# System` / `# User` sections."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SECTION = re.compile(r"^# (System|User)\s*$", re.M)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str
    meta: dict[str, Any]

    def render_user(self, **values: str) -> str:
        text = self.user
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text


def _parse(name: str, path: Path) -> Prompt:
    m = _FRONT.match(path.read_text())
    if not m:
        raise ValueError(f"{path} is missing YAML front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    chunks = _SECTION.split(m.group(2))
    sections = {chunks[i]: chunks[i + 1].strip() for i in range(1, len(chunks) - 1, 2)}
    return Prompt(
        name, str(meta.get("version", path.stem)), sections["System"], sections.get("User", ""), meta
    )


class PromptRegistry:
    def __init__(self, root: Path = PROMPTS_DIR, pins: dict[str, str | None] | None = None) -> None:
        self.root = root
        self.pins = pins or {}

    def versions(self, name: str) -> list[str]:
        files = sorted((self.root / name).glob("v*.md"), key=lambda p: int(p.stem[1:]))
        return [p.stem for p in files]

    def get(self, name: str, version: str | None = None) -> Prompt:
        version = version or self.pins.get(name)
        if version is None:
            available = self.versions(name)
            if not available:
                raise KeyError(f"no prompt named {name}")
            version = available[-1]
        return _load(self.root, name, version)


@cache
def _load(root: Path, name: str, version: str) -> Prompt:
    path = root / name / f"{version}.md"
    if not path.exists():
        raise KeyError(f"prompt {name}/{version} not found")
    return _parse(name, path)
