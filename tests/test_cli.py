# -*- coding: utf-8 -*-
"""
CLI Unit Tests
==============

Tests for the Click-based CLI commands, config persistence,
and intelligence tracking.
"""

import json
import shutil
import tempfile
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.config import (
    load_config, save_config, load_intelligence, save_intelligence,
    track_enrichment, get_provider_stats, get_intelligence_summary,
)


class TestConfig:
    """Tests for CLI config persistence."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gtm_cli_test_"))
        self._original_dir = os.environ.get("HOME")
        # Patch the GTM_DIR to use temp
        import cli.config as cfg
        self._orig_gtm_dir = cfg.GTM_DIR
        self._orig_config = cfg.CONFIG_FILE
        self._orig_intel = cfg.INTELLIGENCE_FILE
        cfg.GTM_DIR = self.tmp
        cfg.CONFIG_FILE = self.tmp / "config.json"
        cfg.INTELLIGENCE_FILE = self.tmp / "intelligence.json"

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        import cli.config as cfg
        cfg.GTM_DIR = self._orig_gtm_dir
        cfg.CONFIG_FILE = self._orig_config
        cfg.INTELLIGENCE_FILE = self._orig_intel

    def test_save_and_load_config(self):
        """Config round-trips through JSON."""
        config = {
            "tenant_id": "test-tenant",
            "vault_base": "/tmp/vault",
            "project_root": "/tmp/project",
        }
        save_config(config)
        loaded = load_config()
        assert loaded["tenant_id"] == "test-tenant"
        assert loaded["vault_base"] == "/tmp/vault"

    def test_load_missing_config(self):
        """Missing config returns empty dict."""
        loaded = load_config()
        assert loaded == {}

    def test_save_creates_directory(self):
        """save_config creates ~/.gtm/ if needed."""
        import cli.config as cfg
        subdir = self.tmp / "nested" / "dir"
        cfg.GTM_DIR = subdir
        cfg.CONFIG_FILE = subdir / "config.json"
        save_config({"test": True})
        assert (subdir / "config.json").exists()


class TestIntelligence:
    """Tests for intelligence tracking."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gtm_intel_test_"))
        import cli.config as cfg
        self._orig_gtm_dir = cfg.GTM_DIR
        self._orig_config = cfg.CONFIG_FILE
        self._orig_intel = cfg.INTELLIGENCE_FILE
        cfg.GTM_DIR = self.tmp
        cfg.CONFIG_FILE = self.tmp / "config.json"
        cfg.INTELLIGENCE_FILE = self.tmp / "intelligence.json"

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        import cli.config as cfg
        cfg.GTM_DIR = self._orig_gtm_dir
        cfg.CONFIG_FILE = self._orig_config
        cfg.INTELLIGENCE_FILE = self._orig_intel

    def test_initial_intelligence(self):
        """Fresh intelligence has zero totals."""
        intel = load_intelligence()
        assert intel["total_enriched"] == 0
        assert intel["total_cost_cents"] == 0
        assert intel["providers"] == {}

    def test_track_enrichment(self):
        """Tracking increments counters."""
        track_enrichment("apollo", success=True, records=1, hits=1, cost_cents=3.0)
        track_enrichment("apollo", success=True, records=1, hits=1, cost_cents=3.0)
        track_enrichment("apollo", success=True, records=1, hits=0, cost_cents=3.0)

        intel = load_intelligence()
        assert intel["providers"]["apollo"]["total_calls"] == 3
        assert intel["providers"]["apollo"]["total_records"] == 3
        assert intel["providers"]["apollo"]["total_hits"] == 2
        assert intel["providers"]["apollo"]["total_cost_cents"] == 9.0
        assert intel["total_enriched"] == 3

    def test_track_enrichment_error(self):
        """Failed enrichment tracks errors."""
        track_enrichment("pdl", success=False, records=1, hits=0, cost_cents=0)
        intel = load_intelligence()
        assert intel["providers"]["pdl"]["total_errors"] == 1

    def test_get_provider_stats(self):
        """Provider stats calculate hit rate and avg cost."""
        track_enrichment("apollo", success=True, records=10, hits=9, cost_cents=30.0)
        stats = get_provider_stats("apollo")
        assert stats["total_records"] == 10
        assert stats["total_hits"] == 9
        assert stats["hit_rate"] == 90.0
        assert stats["avg_cost_per_record"] == 0.03  # $0.03

    def test_get_provider_stats_empty(self):
        """Empty provider returns zero stats."""
        stats = get_provider_stats("nonexistent")
        assert stats["total_calls"] == 0
        assert stats["hit_rate"] == 0

    def test_intelligence_summary(self):
        """Summary aggregates across providers."""
        track_enrichment("apollo", success=True, records=50, hits=45, cost_cents=150)
        track_enrichment("rocketreach", success=True, records=30, hits=25, cost_cents=120)

        summary = get_intelligence_summary()
        assert summary["total_enriched"] == 80
        assert summary["total_cost"] == 2.70  # $2.70
        assert "apollo" in summary["providers"]
        assert "rocketreach" in summary["providers"]
        assert summary["providers"]["apollo"]["hit_rate"] == 90.0

    def test_segment_tracking(self):
        """Enrichments can be tracked per segment."""
        track_enrichment("apollo", success=True, records=10, hits=9,
                        cost_cents=30, segment="saas-50-200")
        track_enrichment("apollo", success=True, records=10, hits=5,
                        cost_cents=30, segment="enterprise")

        intel = load_intelligence()
        segments = intel["providers"]["apollo"]["segments"]
        assert "saas-50-200" in segments
        assert segments["saas-50-200"]["hits"] == 9
        assert segments["enterprise"]["hits"] == 5

    def test_persistence(self):
        """Intelligence persists across loads."""
        track_enrichment("apollo", success=True, records=1, hits=1, cost_cents=3)
        # Load fresh
        intel = load_intelligence()
        assert intel["providers"]["apollo"]["total_calls"] == 1


class TestCLIImport:
    """Tests that CLI modules import correctly."""

    def test_main_imports(self):
        """cli.main imports without error."""
        from cli.main import cli
        assert cli is not None

    def test_config_imports(self):
        """cli.config imports without error."""
        from cli.config import load_config, save_config
        assert load_config is not None

    def test_output_imports(self):
        """cli.output imports without error."""
        from cli.output import console, provider_table, intelligence_panel
        assert console is not None

    def test_all_commands_registered(self):
        """All 7 commands are registered."""
        from cli.main import cli
        command_names = list(cli.commands.keys())
        expected = ["init", "add-key", "status", "enrich",
                    "dashboard", "connect", "setup-claude"]
        for cmd in expected:
            assert cmd in command_names, f"Missing command: {cmd}"


class TestProviderConfig:
    """Tests for the new providers in PROVIDER_AUTH_CONFIG."""

    def test_new_providers_exist(self):
        """New providers are in PROVIDER_AUTH_CONFIG."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        assert "rocketreach" in PROVIDER_AUTH_CONFIG
        assert "rapidapi_google" in PROVIDER_AUTH_CONFIG
        assert "parallel" in PROVIDER_AUTH_CONFIG
        assert "google_search" not in PROVIDER_AUTH_CONFIG  # removed: use rapidapi_google only

    def test_rocketreach_config(self):
        """RocketReach has correct auth config."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        rr = PROVIDER_AUTH_CONFIG["rocketreach"]
        assert rr["base_url"] == "https://api.rocketreach.co/v2/api"
        assert rr["auth_method"] == "header"
        assert rr["header_name"] == "Api-Key"

    def test_rapidapi_google_config(self):
        """RapidAPI Google has correct auth config."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        rg = PROVIDER_AUTH_CONFIG["rapidapi_google"]
        assert "rapidapi" in rg["base_url"]
        assert rg["auth_method"] == "header"
        assert rg["header_name"] == "X-RapidAPI-Key"

    def test_parallel_config(self):
        """Parallel AI has correct auth config."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        p = PROVIDER_AUTH_CONFIG["parallel"]
        assert p["base_url"]
        assert p["auth_method"] == "bearer"

    def test_google_search_removed(self):
        """Native Google Search removed — use rapidapi_google instead."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        assert "google_search" not in PROVIDER_AUTH_CONFIG
        assert "rapidapi_google" in PROVIDER_AUTH_CONFIG

    def test_total_provider_count(self):
        """Should have 13 total providers (10 original + 3 new)."""
        from vault.proxy import PROVIDER_AUTH_CONFIG
        assert len(PROVIDER_AUTH_CONFIG) == 13


def run_all_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [TestConfig, TestIntelligence, TestCLIImport, TestProviderConfig]
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
