"""
GTM Engine CLI Configuration

Manages persistent config at ~/.gtm/config.json and intelligence
tracking at ~/.gtm/intelligence.json.

The passphrase is NEVER stored to disk. It's resolved from:
1. GTM_PASSPHRASE environment variable (recommended)
2. Interactive prompt
"""

import json
import os
import time
from pathlib import Path
from typing import Optional


GTM_DIR = Path.home() / ".gtm"
CONFIG_FILE = GTM_DIR / "config.json"
INTELLIGENCE_FILE = GTM_DIR / "intelligence.json"


def ensure_gtm_dir():
    """Create ~/.gtm/ if it doesn't exist."""
    GTM_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config from ~/.gtm/config.json."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict):
    """Save config to ~/.gtm/config.json."""
    ensure_gtm_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_tenant_id() -> Optional[str]:
    """Get tenant_id from config."""
    return load_config().get("tenant_id")


def get_vault_base() -> Optional[str]:
    """Get vault base path from config."""
    return load_config().get("vault_base")


def get_project_root() -> Optional[str]:
    """Get project root from config."""
    return load_config().get("project_root")


def resolve_passphrase(passphrase: Optional[str] = None) -> Optional[str]:
    """
    Resolve passphrase from flag, env var, or prompt.
    Returns None if not available (caller should prompt).
    """
    if passphrase:
        return passphrase
    return os.environ.get("GTM_PASSPHRASE")


# ================================================================
# INTELLIGENCE TRACKING
# ================================================================

def load_intelligence() -> dict:
    """Load intelligence data from ~/.gtm/intelligence.json."""
    if not INTELLIGENCE_FILE.exists():
        return {
            "providers": {},
            "waterfalls": {},
            "total_enriched": 0,
            "total_cost_cents": 0,
            "started_at": time.time(),
        }
    try:
        return json.loads(INTELLIGENCE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {
            "providers": {},
            "waterfalls": {},
            "total_enriched": 0,
            "total_cost_cents": 0,
            "started_at": time.time(),
        }


def save_intelligence(data: dict):
    """Save intelligence data."""
    ensure_gtm_dir()
    INTELLIGENCE_FILE.write_text(json.dumps(data, indent=2) + "\n")


def track_enrichment(
    provider: str,
    success: bool,
    records: int = 1,
    hits: int = 0,
    cost_cents: float = 0,
    segment: str = "default",
):
    """
    Track an enrichment call for intelligence.

    This builds up per-provider and per-segment hit rates
    and cost data over time.
    """
    intel = load_intelligence()

    # Per-provider stats
    if provider not in intel["providers"]:
        intel["providers"][provider] = {
            "total_calls": 0,
            "total_records": 0,
            "total_hits": 0,
            "total_errors": 0,
            "total_cost_cents": 0,
            "segments": {},
        }

    prov = intel["providers"][provider]
    prov["total_calls"] += 1
    prov["total_records"] += records
    prov["total_hits"] += hits
    if not success:
        prov["total_errors"] += 1
    prov["total_cost_cents"] += cost_cents

    # Per-segment stats within provider
    if segment not in prov["segments"]:
        prov["segments"][segment] = {
            "calls": 0,
            "records": 0,
            "hits": 0,
            "cost_cents": 0,
        }
    seg = prov["segments"][segment]
    seg["calls"] += 1
    seg["records"] += records
    seg["hits"] += hits
    seg["cost_cents"] += cost_cents

    # Global totals
    intel["total_enriched"] += records
    intel["total_cost_cents"] += cost_cents

    save_intelligence(intel)


def get_provider_stats(provider: str) -> dict:
    """Get intelligence stats for a provider."""
    intel = load_intelligence()
    prov = intel["providers"].get(provider, {})
    total_records = prov.get("total_records", 0)
    total_hits = prov.get("total_hits", 0)
    total_cost = prov.get("total_cost_cents", 0)

    return {
        "total_calls": prov.get("total_calls", 0),
        "total_records": total_records,
        "total_hits": total_hits,
        "hit_rate": (total_hits / total_records * 100) if total_records > 0 else 0,
        "total_cost": total_cost / 100,  # dollars
        "avg_cost_per_record": (total_cost / total_records / 100) if total_records > 0 else 0,
        "total_errors": prov.get("total_errors", 0),
    }


def get_intelligence_summary() -> dict:
    """Get a summary of all intelligence data."""
    intel = load_intelligence()
    providers = {}
    for name, data in intel.get("providers", {}).items():
        total_records = data.get("total_records", 0)
        total_hits = data.get("total_hits", 0)
        total_cost = data.get("total_cost_cents", 0)
        providers[name] = {
            "calls": data.get("total_calls", 0),
            "records": total_records,
            "hits": total_hits,
            "hit_rate": round(total_hits / total_records * 100, 1) if total_records > 0 else 0,
            "cost": round(total_cost / 100, 2),
            "avg_cost": round(total_cost / total_records / 100, 3) if total_records > 0 else 0,
            "errors": data.get("total_errors", 0),
        }

    return {
        "providers": providers,
        "total_enriched": intel.get("total_enriched", 0),
        "total_cost": round(intel.get("total_cost_cents", 0) / 100, 2),
        "days_active": round((time.time() - intel.get("started_at", time.time())) / 86400, 1),
    }
