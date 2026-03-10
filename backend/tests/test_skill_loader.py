"""Tests for skill_loader.py — parsing, loading, migration."""
from __future__ import annotations
import os
import tempfile
import pytest
from agents.skill_loader import (
    _parse_skill_md,
    build_available_skills_xml,
    _resolve_skill_id,
    SkillDefinition,
)


class TestParseSkillMd:
    def _write_skill(self, tmpdir: str, content: str) -> str:
        path = os.path.join(tmpdir, "SKILL.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_skill(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_skill(d, (
                "---\n"
                "name: test-skill\n"
                "description: A test skill\n"
                "---\n"
                "# Usage\nDo the thing."
            ))
            skill = _parse_skill_md("test-skill", path)
            assert skill is not None
            assert skill.id == "test-skill"
            assert skill.name == "test-skill"
            assert skill.description == "A test skill"
            assert "Usage" in skill.content

    def test_missing_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_skill(d, "Just some text without frontmatter")
            skill = _parse_skill_md("bad", path)
            assert skill is None

    def test_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_skill(d, "---\n[invalid yaml: {\n---\nbody")
            skill = _parse_skill_md("bad", path)
            assert skill is None

    def test_missing_file(self):
        skill = _parse_skill_md("missing", "/nonexistent/path/SKILL.md")
        assert skill is None

    def test_name_mismatch_still_loads(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_skill(d, (
                "---\n"
                "name: different-name\n"
                "description: desc\n"
                "---\n"
                "body"
            ))
            skill = _parse_skill_md("my-skill", path)
            # Should still parse, just with a warning
            assert skill is not None
            assert skill.id == "my-skill"
            assert skill.name == "different-name"


class TestBuildAvailableSkillsXml:
    def test_returns_xml_structure(self):
        xml = build_available_skills_xml()
        assert xml.startswith("<available_skills>")
        assert xml.endswith("</available_skills>")

    def test_filtered_by_ids(self):
        xml = build_available_skills_xml(["web-search"])
        assert "web-search" in xml

    def test_nonexistent_skill_filtered_out(self):
        xml = build_available_skills_xml(["nonexistent-skill-xyz"])
        lines = xml.strip().split("\n")
        # Should only have opening and closing tags
        assert len(lines) == 2


class TestResolveSkillId:
    def test_unknown_id_returns_self(self):
        assert _resolve_skill_id("brand-new-skill") == "brand-new-skill"

    def test_kebab_case_unchanged(self):
        assert _resolve_skill_id("web-search") == "web-search"
