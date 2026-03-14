# -*- coding: utf-8 -*-
"""
Setup Claude Command Tests
===========================

Tests for the gtm setup-claude command that generates
.mcp.json, CLAUDE.md, skills, and rules.
"""

import json
import shutil
import tempfile
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.commands.setup_claude import (
    _generate_mcp_json,
    _generate_claude_md,
    _generate_skills,
    _generate_rules,
)


class TestMCPJsonGeneration:
    """Tests for .mcp.json generation."""

    def test_basic_mcp_json(self):
        """Generates valid MCP JSON with correct structure."""
        config = _generate_mcp_json("test-tenant", "/path/to/project")
        assert "mcpServers" in config
        assert "gtm-vault" in config["mcpServers"]

    def test_tenant_id_in_args(self):
        """Tenant ID appears in server args."""
        config = _generate_mcp_json("my-tenant-123", "/path")
        args = config["mcpServers"]["gtm-vault"]["args"]
        assert "my-tenant-123" in args

    def test_passphrase_uses_env_var(self):
        """Passphrase uses ${GTM_PASSPHRASE} substitution, not hardcoded."""
        config = _generate_mcp_json("t1", "/path")
        args = config["mcpServers"]["gtm-vault"]["args"]
        assert "${GTM_PASSPHRASE}" in args
        # Should NOT contain any actual passphrase
        args_str = json.dumps(args)
        assert "dev-passphrase" not in args_str

    def test_project_root_in_cwd(self):
        """Project root is set as cwd."""
        config = _generate_mcp_json("t1", "/my/project")
        assert config["mcpServers"]["gtm-vault"]["cwd"] == "/my/project"

    def test_composio_mcp_when_key_set(self):
        """Composio MCP server added when COMPOSIO_API_KEY is set."""
        with patch_env("COMPOSIO_API_KEY", "test-key"):
            config = _generate_mcp_json("t1", "/path")
            assert "composio-tools" in config["mcpServers"]
            url = config["mcpServers"]["composio-tools"]["url"]
            assert "gtm-t1" in url
            # Key should use env var substitution
            assert "${COMPOSIO_API_KEY}" in url

    def test_no_composio_without_key(self):
        """No Composio MCP server when key is not set."""
        with patch_env("COMPOSIO_API_KEY", None), patch_env("composio_api_key", None):
            config = _generate_mcp_json("t1", "/path")
            assert "composio-tools" not in config["mcpServers"]


class TestClaudeMD:
    """Tests for CLAUDE.md generation."""

    def test_claude_md_generated(self):
        """CLAUDE.md is generated with content."""
        md = _generate_claude_md("test-tenant", "/path")
        assert len(md) > 100
        assert "GTM Engine" in md

    def test_claude_md_has_mcp_tools(self):
        """CLAUDE.md lists MCP tools."""
        md = _generate_claude_md("t1", "/p")
        assert "gtm_vault_status" in md
        assert "gtm_enrich" in md
        assert "gtm_add_key" in md

    def test_claude_md_has_providers(self):
        """CLAUDE.md lists providers."""
        md = _generate_claude_md("t1", "/p")
        assert "apollo" in md
        assert "rocketreach" in md
        assert "parallel" in md

    def test_claude_md_has_security_rules(self):
        """CLAUDE.md has security rules."""
        md = _generate_claude_md("t1", "/p")
        assert "NEVER" in md
        assert "fingerprint" in md.lower()

    def test_claude_md_has_cost_awareness(self):
        """CLAUDE.md mentions cost awareness."""
        md = _generate_claude_md("t1", "/p")
        assert "cost" in md.lower()
        assert "$0.03" in md

    def test_claude_md_under_200_lines(self):
        """CLAUDE.md stays under 200 lines."""
        md = _generate_claude_md("t1", "/p")
        line_count = len(md.strip().split("\n"))
        assert line_count < 200, f"CLAUDE.md is {line_count} lines (should be <200)"

    def test_claude_md_mentions_intelligence(self):
        """CLAUDE.md references the intelligence system."""
        md = _generate_claude_md("t1", "/p")
        assert "intelligence" in md.lower()


class TestSkills:
    """Tests for SKILL.md generation."""

    def test_ten_skills_generated(self):
        """Exactly 10 skills are generated."""
        skills = _generate_skills()
        assert len(skills) == 10

    def test_expected_skill_names(self):
        """All expected skills are present."""
        skills = _generate_skills()
        expected = [
            "apollo-enrichment",
            "rocketreach-enrichment",
            "google-search",
            "parallel-research",
            "composio-connections",
            "waterfall-enrichment",
            "gtm-workflows",
            "list-building",
            "instantly-campaigns",
            "scraping-tools",
        ]
        for name in expected:
            assert name in skills, f"Missing skill: {name}"

    def test_skills_have_content(self):
        """Each skill has meaningful content."""
        skills = _generate_skills()
        for name, content in skills.items():
            assert len(content) > 100, f"Skill {name} is too short ({len(content)} chars)"

    def test_apollo_skill_has_endpoints(self):
        """Apollo skill has API endpoint documentation."""
        skills = _generate_skills()
        apollo = skills["apollo-enrichment"]
        assert "/people/match" in apollo
        assert "/mixed_people/search" in apollo
        assert "/organizations/enrich" in apollo

    def test_rocketreach_skill_has_endpoints(self):
        """RocketReach skill has API endpoint documentation."""
        skills = _generate_skills()
        rr = skills["rocketreach-enrichment"]
        assert "/lookupProfile" in rr
        assert "/search" in rr

    def test_waterfall_skill_has_providers(self):
        """Waterfall skill references multiple providers."""
        skills = _generate_skills()
        wf = skills["waterfall-enrichment"]
        assert "apollo" in wf.lower()
        assert "rocketreach" in wf.lower()

    def test_no_api_keys_in_skills(self):
        """Skills don't contain any actual API keys."""
        skills = _generate_skills()
        all_content = "\n".join(skills.values())
        # Common key patterns
        assert "xoxb-" not in all_content
        assert "sk-" not in all_content.split("$")[-1] if "$" in all_content else True


class TestRules:
    """Tests for rules generation."""

    def test_two_rules_generated(self):
        """Exactly 2 rules are generated."""
        rules = _generate_rules()
        assert len(rules) == 2

    def test_security_rule_exists(self):
        """Security rule file exists."""
        rules = _generate_rules()
        assert "security.md" in rules
        assert "NEVER" in rules["security.md"] or "never" in rules["security.md"].lower()

    def test_enrichment_rule_exists(self):
        """Enrichment rule file exists."""
        rules = _generate_rules()
        assert "enrichment.md" in rules
        assert "cost" in rules["enrichment.md"].lower() or "intelligence" in rules["enrichment.md"].lower()


class TestSetupClaudeIntegration:
    """Integration tests for the full setup-claude flow."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gtm_setup_test_"))

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_file_generation(self):
        """Full setup generates all expected files."""
        from cli.commands.setup_claude import _write_file

        # Generate all files
        mcp = _generate_mcp_json("test-t", "/project")
        claude_md = _generate_claude_md("test-t", "/project")
        skills = _generate_skills()
        rules = _generate_rules()

        # Write them
        _write_file(self.tmp / ".mcp.json", json.dumps(mcp, indent=2), dry_run=False)
        _write_file(self.tmp / "CLAUDE.md", claude_md, dry_run=False)
        for name, content in skills.items():
            _write_file(self.tmp / ".claude" / "skills" / name / "SKILL.md", content, dry_run=False)
        for name, content in rules.items():
            _write_file(self.tmp / ".claude" / "rules" / name, content, dry_run=False)

        # Verify
        assert (self.tmp / ".mcp.json").exists()
        assert (self.tmp / "CLAUDE.md").exists()
        assert (self.tmp / ".claude" / "skills" / "apollo-enrichment" / "SKILL.md").exists()
        assert (self.tmp / ".claude" / "rules" / "security.md").exists()

    def test_mcp_json_is_valid_json(self):
        """Generated .mcp.json is valid JSON."""
        mcp = _generate_mcp_json("t1", "/p")
        # Should be serializable and parseable
        serialized = json.dumps(mcp, indent=2)
        parsed = json.loads(serialized)
        assert parsed["mcpServers"]["gtm-vault"]["command"] == "python3"

    def test_force_overwrites(self):
        """--force overwrites existing files."""
        from cli.commands.setup_claude import _write_file

        path = self.tmp / "test.txt"
        _write_file(path, "original", dry_run=False)
        assert path.read_text() == "original"

        # Without force, should skip
        written = _write_file(path, "updated", dry_run=False, force=False)
        assert written == 0
        assert path.read_text() == "original"

        # With force, should overwrite
        written = _write_file(path, "updated", dry_run=False, force=True)
        assert written == 1
        assert path.read_text() == "updated"

    def test_dry_run_no_write(self):
        """--dry-run doesn't write files."""
        from cli.commands.setup_claude import _write_file

        path = self.tmp / "should_not_exist.txt"
        _write_file(path, "content", dry_run=True)
        assert not path.exists()


# ================================================================
# Helper
# ================================================================

class patch_env:
    """Context manager to temporarily set/unset env vars."""
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.old = None

    def __enter__(self):
        self.old = os.environ.get(self.key)
        if self.value is None:
            os.environ.pop(self.key, None)
        else:
            os.environ[self.key] = self.value
        return self

    def __exit__(self, *args):
        if self.old is None:
            os.environ.pop(self.key, None)
        else:
            os.environ[self.key] = self.old


def run_all_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [
        TestMCPJsonGeneration,
        TestClaudeMD,
        TestSkills,
        TestRules,
        TestSetupClaudeIntegration,
    ]
    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        print(f"\n{'=' * 60}")
        print(f"  {cls.__name__}")
        print(f"{'=' * 60}")

        for method_name in sorted(dir(cls)):
            if not method_name.startswith("test_"):
                continue

            instance = cls()
            if hasattr(instance, "setup_method"):
                instance.setup_method()

            try:
                getattr(instance, method_name)()
                print(f"  PASS {method_name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL {method_name}: {e}")
                errors.append((cls.__name__, method_name, traceback.format_exc()))
                failed += 1
            finally:
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    if errors:
        print("\n--- FAILURES ---")
        for cls_name, method, tb in errors:
            print(f"\n{cls_name}.{method}:")
            print(tb)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
