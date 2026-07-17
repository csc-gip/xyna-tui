from __future__ import annotations

import re
from pathlib import Path


PROMPT_PATTERN = re.compile(r"^.*\$ x ", re.MULTILINE)


class FixtureNotFoundError(KeyError):
    """Raised when a command fixture cannot be extracted."""


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_command_output(raw_text: str, command: str) -> str:
    """Extract output section for a command from shell transcript fixtures."""
    lines = raw_text.splitlines()
    start_idx = None

    for i, line in enumerate(lines):
        marker = "$ x "
        pos = line.find(marker)
        if pos == -1:
            continue
        issued = line[pos + len(marker) :].strip()
        if issued == command:
            start_idx = i + 1
            break

    if start_idx is None:
        raise FixtureNotFoundError(command)

    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "$ x " in lines[i]:
            end_idx = i
            break

    return "\n".join(lines[start_idx:end_idx]).strip()


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def fixtures_root(repo_root: Path) -> Path:
    return repo_root / "fixtures" / "xyna-cli"


def fixture_path(repo_root: Path, name: str) -> Path:
    return fixtures_root(repo_root) / name
