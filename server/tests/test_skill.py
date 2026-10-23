"""The Agent Skill (skill/kilta) follows the agentskills.io format and names only real tools."""

import re
from pathlib import Path

import pytest

from kilta.server import create_server

SKILL_DIR = Path(__file__).resolve().parents[2] / "skill" / "kilta"


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, match.group(2)


def test_frontmatter_follows_the_spec():
    fields, body = frontmatter((SKILL_DIR / "SKILL.md").read_text())
    assert fields["name"] == SKILL_DIR.name == "kilta"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"]) and len(fields["name"]) <= 64
    assert 1 <= len(fields["description"]) <= 1024
    assert "Use when" in fields["description"]  # says when to use it, not only what it does
    assert len(fields.get("compatibility", "x")) <= 500
    assert body.strip().startswith("# Kilta")


def test_the_skill_covers_tool_order_safety_and_voice():
    body = (SKILL_DIR / "SKILL.md").read_text()
    for heading in (
        "## When to use it",
        "## The order of a repair",
        "## Safety rules",
        "## Voice rules",
    ):
        assert heading in body
    for rule in (
        "Never answer for the user",
        "`danger_reported=true`",
        "technician-only",
        "English",
    ):
        assert rule in body


@pytest.mark.parametrize("name", ["SKILL.md", "references/tool-reference.md"])
def test_every_tool_the_skill_names_exists(name):
    import asyncio

    real = {tool.name for tool in asyncio.run(create_server().list_tools())}
    text = (SKILL_DIR / name).read_text()
    not_tools = {"danger_reported", "setting_fixed", "member_id", "manual_id", "not_fixed"}
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text)) - not_tools
    unknown = {n for n in named if n not in real}
    assert not unknown, f"{name} mentions tools that do not exist: {sorted(unknown)}"
    assert {
        "safety_check",
        "next_step",
        "confirm_gate",
    } <= named | real  # sanity: the server has them
