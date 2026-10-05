"""Configuration: defaults, overset.toml / pyproject [tool.overset], and flags.

Precedence, low to high: built-in defaults, the config file, command-line
flags. `select` / `ignore` / `extend-select` / `extend-ignore` take full codes
(OVS001) or prefixes (OVS, OVS1), with ruff's semantics.

The brand lives here, not in the code: `palette`, `fonts`, and `font-dirs`
(folders of font files to render with) make overset check one house style
without knowing any.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from overset.deck import EMU_PER_PT
from overset.rules import load_rules
from overset.rules.base import REGISTRY

CONFIG_NAMES = ("overset.toml", ".overset.toml")


@dataclass
class Settings:
    select: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    extend_select: tuple[str, ...] = ()
    extend_ignore: tuple[str, ...] = ()
    render: bool = True
    render_as: str = "powerpoint"  # "powerpoint": shrink-to-fit frozen at its stored scale; "libreoffice": as-is
    vision: bool = False
    min_font_pt: float = 10.0
    max_words: int = 90
    tolerance_pt: float = 2.0
    min_contrast: float = 3.0
    max_aspect_distortion: float = 0.02
    palette: list[str] = field(default_factory=list)
    palette_tolerance: float = 12.0
    fonts: list[str] = field(default_factory=list)
    font_dirs: list[Path] = field(default_factory=list)
    vision_model: str = "anthropic:claude-sonnet-5-5"
    vision_threshold: float = 0.7
    vision_input: str = "both"  # "slides" | "sheet" | "both"
    vision_brief: str = ""
    source: str = "defaults"

    @property
    def tolerance_emu(self) -> int:
        return round(self.tolerance_pt * EMU_PER_PT)

    @staticmethod
    def _matches(code: str, patterns) -> bool:
        return any(code == p or code.startswith(p) for p in patterns)

    def active_codes(self) -> list[str]:
        load_rules()
        chosen = []
        for code, r in sorted(REGISTRY.items()):
            enabled = self._matches(code, self.select) if self.select else r.default
            if r.kind == "vision" and self.vision and not self.select:
                enabled = True
            if self._matches(code, self.extend_select):
                enabled = True
            if self._matches(code, self.ignore) or self._matches(code, self.extend_ignore):
                enabled = False
            if r.kind in ("render", "vision") and not self.render:  # vision looks at the render
                enabled = False
            if r.kind == "vision" and not self.vision:
                enabled = False
            if enabled:
                chosen.append(code)
        return chosen


def find_config(start: Path) -> Path | None:
    start = start.resolve()
    for directory in (start, *start.parents):
        for name in CONFIG_NAMES:
            if (directory / name).is_file():
                return directory / name
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file() and "overset" in tomllib.loads(pyproject.read_text()).get("tool", {}):
            return pyproject
    return None


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    return (value,) if isinstance(value, str) else tuple(str(v) for v in value)


def from_mapping(data: dict, base: Path | None = None, source: str = "config") -> Settings:
    known = {f.name for f in fields(Settings)}
    s = Settings(source=source)
    for key, value in data.items():
        name = key.replace("-", "_")
        if name not in known or name == "source":
            raise ValueError(f"unknown setting {key!r}")
        if name in ("select", "ignore", "extend_select", "extend_ignore"):
            value = _as_tuple(value)
        elif name == "font_dirs":
            value = [((base or Path.cwd()) / Path(v).expanduser()).resolve() for v in value]
        elif name in ("palette", "fonts"):
            value = [str(v).lstrip("#") if name == "palette" else str(v) for v in value]
        setattr(s, name, value)
    return s


def load(config: Path | None = None, start: Path | None = None) -> Settings:
    path = config or find_config(start or Path.cwd())
    if path is None:
        return Settings()
    data = tomllib.loads(path.read_text())
    if path.name == "pyproject.toml":
        data = data.get("tool", {}).get("overset", {})
    return from_mapping(data, base=path.parent, source=str(path))
