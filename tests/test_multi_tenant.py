"""
Multi-Tenant Vault Security Test Suite

Tests:
1.  Tenant isolation — tenant A cannot access tenant B's keys
2.  BYOK priority — tenant's own key used before platform key
3.  Platform fallback — platform key used when no BYOK exists
4.  Key resolution order is correct
5.  Usage tracking is per-tenant
6.  Key management never exposes values
7.  Tenant deletion doesn't affect other tenants
8.  Bulk key operations work correctly
9.  Rotate key produces new fingerprint
10. Cross-tenant proxy calls are isolated
11. Export config contains no secrets
"""

import json
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vault.tenant import TenantVault, VaultError
from vault.tenant_proxy import TenantProxy
from vault.key_manager import KeyManager

# Test constants
PLATFORM_PASS = "platform-test-pass"
TENANT_A_PASS = "tenant-a-pass"
TENANT_B_PASS = "tenant-b-pass"

FAKE_KEYS = {
    "platform_apollo": "plat_apollo_key_FAKE_123",
    "platform_pdl": "plat_pdl_key_FAKE_456",
    "platform_hunter": "plat_hunter_key_FAKE_789",
    "tenant_a_apollo": "byok_a_apollo_FAKE_aaa",
    "tenant_a_hunter": "byok_a_hunter_FAKE_bbb",
    "tenant_b_pdl": "byok_b_pdl_FAKE_ccc",
}


def setup() -> tuple[TenantVault, str, str, Path]:
    """Create test environment with platform + 2 tenants."""
    tmp = Path(tempfile.mkdtemp(prefix="mt_vault_test_"))

    tv = TenantVault(base_path=tmp)

    # Init platform with shared keys
    tv.initialize_platform(PLATFORM_PASS)
    tv.store_platform_key("apollo", FAKE_KEYS["platform_apollo"])
    tv.store_platform_key("pdl", FAKE_KEYS["platform_pdl"])
    tv.store_platform_key("hunter", FAKE_KEYS["platform_hunter"])

    # Create tenant A with BYOK for apollo + hunter
    result_a = tv.create_tenant("Tenant A", TENANT_A_PASS, tenant_id="tenant-a")
    tid_a = result_a["tenant_id"]
    tv.store_tenant_key(tid_a, "apollo", FAKE_KEYS["tenant_a_apollo"])
    tv.store_tenant_key(tid_a, "hunter", FAKE_KEYS["tenant_a_hunter"])

    # Create tenant B with BYOK for pdl only
    result_b = tv.create_tenant("Tenant B", TENANT_B_PASS, tenant_id="tenant-b")
    tid_b = result_b["tenant_id"]
    tv.store_tenant_key(tid_b, "pdl", FAKE_KEYS["tenant_b_pdl"])

    return tv, tid_a, tid_b, tmp


def cleanup(tmp: Path):
    shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# TEST 1: BYOK takes priority over platform
# ============================================================

def test_byok_priority():
    """Tenant A has BYOK for apollo — should use BYOK, not platform."""
    tv, tid_a, tid_b, tmp = setup()

    key, source = tv.resolve_key(tid_a, "apollo")
    assert source == "byok", f"Expected 'byok', got '{source}'"
    assert key == FAKE_KEYS["tenant_a_apollo"], "Wrong key returned"

    print("✅ TEST 1 PASSED: BYOK key takes priority over platform")
    cleanup(tmp)


# ============================================================
# TEST 2: Platform fallback when no BYOK
# ============================================================

def test_platform_fallback():
    """Tenant A has no BYOK for pdl — should fall back to platform."""
    tv, tid_a, tid_b, tmp = setup()

    key, source = tv.resolve_key(tid_a, "pdl")
    assert source == "platform", f"Expected 'platform', got '{source}'"
    assert key == FAKE_KEYS["platform_pdl"], "Wrong platform key"

    print("✅ TEST 2 PASSED: Falls back to platform key when no BYOK")
    cleanup(tmp)


# ============================================================
# TEST 3: Tenant isolation — A can't access B's BYOK
# ============================================================

def test_tenant_isolation():
    """Tenant A cannot get tenant B's BYOK keys."""
    tv, tid_a, tid_b, tmp = setup()

    # Tenant B has BYOK for pdl
    key_b, source_b = tv.resolve_key(tid_b, "pdl")
    assert key_b == FAKE_KEYS["tenant_b_pdl"], "B should get their own key"

    # Tenant A should get PLATFORM pdl, not B's BYOK
    key_a, source_a = tv.resolve_key(tid_a, "pdl")
    assert key_a == FAKE_KEYS["platform_pdl"], "A should get platform key"
    assert key_a != key_b, "CRITICAL: A got B's key!"

    print("✅ TEST 3 PASSED: Tenant isolation enforced — A cannot access B's keys")
    cleanup(tmp)


# ============================================================
# TEST 4: No key available → error
# ============================================================

def test_no_key_error():
    """If no BYOK and no platform key, should error."""
    tv, tid_a, tid_b, tmp = setup()

    try:
        tv.resolve_key(tid_a, "firecrawl")  # No key anywhere
        assert False, "Should have raised VaultError"
    except VaultError as e:
        assert "firecrawl" in str(e)
        # Make sure error doesn't leak other keys
        for key in FAKE_KEYS.values():
            assert key not in str(e), "Key material in error!"

    print("✅ TEST 4 PASSED: Missing key raises clean error")
    cleanup(tmp)


# ============================================================
# TEST 5: Usage tracking is per-tenant
# ============================================================

def test_usage_tracking():
    """Usage is tracked separately per tenant."""
    tv, tid_a, tid_b, tmp = setup()

    # Make some calls
    tv.resolve_key(tid_a, "apollo")  # BYOK
    tv.resolve_key(tid_a, "apollo")  # BYOK again
    tv.resolve_key(tid_a, "pdl")     # Platform fallback
    tv.resolve_key(tid_b, "pdl")     # B's BYOK

    usage_a = tv.get_usage(tid_a)
    usage_b = tv.get_usage(tid_b)

    assert usage_a["total_calls"] == 3, f"A should have 3 calls, got {usage_a['total_calls']}"
    assert usage_b["total_calls"] == 1, f"B should have 1 call, got {usage_b['total_calls']}"

    # Check A's breakdown
    assert usage_a["usage"]["apollo"]["byok_calls"] == 2
    assert usage_a["usage"]["pdl"]["platform_calls"] == 1

    print("✅ TEST 5 PASSED: Usage tracked per-tenant correctly")
    cleanup(tmp)


# ============================================================
# TEST 6: Key manager never exposes values
# ============================================================

def test_key_manager_no_exposure():
    """KeyManager methods never return actual key values."""
    tv, tid_a, tid_b, tmp = setup()
    km = KeyManager(tv)

    # show_keys
    result = km.show_keys(tid_a)
    result_str = json.dumps(result)
    for key in FAKE_KEYS.values():
        assert key not in result_str, f"CRITICAL: Key exposed in show_keys!"

    # add_key
    result2 = km.add_key(tid_a, "firecrawl", "firecrawl_secret_123")
    result2_str = json.dumps(result2)
    assert "firecrawl_secret_123" not in result2_str, "CRITICAL: Key exposed in add_key!"

    # show_usage
    result3 = km.show_usage(tid_a)
    result3_str = json.dumps(result3)
    for key in FAKE_KEYS.values():
        assert key not in result3_str, "CRITICAL: Key exposed in show_usage!"

    print("✅ TEST 6 PASSED: KeyManager never exposes key values")
    cleanup(tmp)


# ============================================================
# TEST 7: Deleting tenant B's key doesn't affect A
# ============================================================

def test_delete_isolation():
    """Deleting B's BYOK key doesn't affect A's keys."""
    tv, tid_a, tid_b, tmp = setup()

    # Get A's apollo key before
    key_a_before, _ = tv.resolve_key(tid_a, "apollo")

    # Delete B's pdl key
    tv.delete_tenant_key(tid_b, "pdl")

    # A's apollo should be unchanged
    key_a_after, _ = tv.resolve_key(tid_a, "apollo")
    assert key_a_before == key_a_after, "A's key changed after B's deletion!"

    # B should fall back to platform for pdl
    key_b, source_b = tv.resolve_key(tid_b, "pdl")
    assert source_b == "platform", "B should fall back to platform after delete"

    print("✅ TEST 7 PASSED: Deleting one tenant's key doesn't affect others")
    cleanup(tmp)


# ============================================================
# TEST 8: Bulk add keys works correctly
# ============================================================

def test_bulk_add():
    """Bulk key addition stores all keys securely."""
    tv, tid_a, tid_b, tmp = setup()
    km = KeyManager(tv)

    result = km.bulk_add_keys(tid_b, {
        "apollo": "bulk_apollo_key",
        "hunter": "bulk_hunter_key",
    })

    assert result["success"] is True
    result_str = json.dumps(result)
    assert "bulk_apollo_key" not in result_str
    assert "bulk_hunter_key" not in result_str

    # Verify B now uses BYOK for apollo
    key, source = tv.resolve_key(tid_b, "apollo")
    assert source == "byok"
    assert key == "bulk_apollo_key"

    print("✅ TEST 8 PASSED: Bulk add works securely")
    cleanup(tmp)


# ============================================================
# TEST 9: Key rotation produces new fingerprint
# ============================================================

def test_rotation():
    """Rotating a key changes the fingerprint."""
    tv, tid_a, tid_b, tmp = setup()
    km = KeyManager(tv)

    keys_before = km.show_keys(tid_a)
    apollo_before = next(
        p for p in keys_before["providers"]
        if p["provider"] == "apollo"
    )

    result = km.rotate_key(tid_a, "apollo", "brand_new_apollo_key")
    assert result["success"] is True
    assert "brand_new_apollo_key" not in json.dumps(result)

    keys_after = km.show_keys(tid_a)
    apollo_after = next(
        p for p in keys_after["providers"]
        if p["provider"] == "apollo"
    )

    assert apollo_before["fingerprint"] != apollo_after["fingerprint"], \
        "Fingerprint should change after rotation"

    print("✅ TEST 9 PASSED: Key rotation changes fingerprint securely")
    cleanup(tmp)


# ============================================================
# TEST 10: Proxy is tenant-scoped
# ============================================================

def test_proxy_isolation():
    """TenantProxy routes to correct key per tenant."""
    tv, tid_a, tid_b, tmp = setup()
    proxy = TenantProxy(tv)

    # Check tenant A's apollo → should be BYOK
    check_a = proxy.check_tenant_provider(tid_a, "apollo")
    assert check_a["key_source"] == "byok"

    # Check tenant B's apollo → should be platform (no BYOK)
    check_b = proxy.check_tenant_provider(tid_b, "apollo")
    assert check_b["key_source"] == "platform"

    # Check tenant B's pdl → should be BYOK
    check_b_pdl = proxy.check_tenant_provider(tid_b, "pdl")
    assert check_b_pdl["key_source"] == "byok"

    print("✅ TEST 10 PASSED: Proxy routes correctly per tenant")
    cleanup(tmp)


# ============================================================
# TEST 11: Export config has no secrets
# ============================================================

def test_export_no_secrets():
    """Config export contains metadata only, never keys."""
    tv, tid_a, tid_b, tmp = setup()
    km = KeyManager(tv)

    export = km.export_config(tid_a)
    export_str = json.dumps(export)

    for key in FAKE_KEYS.values():
        assert key not in export_str, "CRITICAL: Key in export!"

    assert export["note"] == "This export contains metadata only. API keys must be re-added after migration."

    print("✅ TEST 11 PASSED: Export contains no secrets")
    cleanup(tmp)


# ============================================================
# TEST 12: Locked tenant blocks all operations
# ============================================================

def test_locked_tenant():
    """A locked tenant vault refuses key operations."""
    tv, tid_a, tid_b, tmp = setup()

    tv.lock_tenant(tid_a)

    try:
        tv.resolve_key(tid_a, "apollo")
        assert False, "Should fail on locked vault"
    except VaultError:
        pass

    # B should still work
    key_b, source_b = tv.resolve_key(tid_b, "pdl")
    assert source_b == "byok", "B should still work after A is locked"

    print("✅ TEST 12 PASSED: Locked tenant blocks operations, others unaffected")
    cleanup(tmp)


# ============================================================
# TEST 13: Tenant listing never exposes keys
# ============================================================

def test_list_tenants_no_keys():
    """list_tenants() contains no key material."""
    tv, tid_a, tid_b, tmp = setup()

    result = tv.list_tenants()
    result_str = json.dumps(result)

    for key in FAKE_KEYS.values():
        assert key not in result_str, "CRITICAL: Key in tenant listing!"

    assert "tenant-a" in result["tenants"]
    assert "tenant-b" in result["tenants"]
    assert result["tenants"]["tenant-a"]["name"] == "Tenant A"

    print("✅ TEST 13 PASSED: Tenant listing contains no keys")
    cleanup(tmp)


# ============================================================
# RUN ALL TESTS
# ============================================================

def run_all():
    print("\n" + "=" * 60)
    print("  MULTI-TENANT VAULT SECURITY TESTS")
    print("=" * 60 + "\n")

    tests = [
        test_byok_priority,
        test_platform_fallback,
        test_tenant_isolation,
        test_no_key_error,
        test_usage_tracking,
        test_key_manager_no_exposure,
        test_delete_isolation,
        test_bulk_add,
        test_rotation,
        test_proxy_isolation,
        test_export_no_secrets,
        test_locked_tenant,
        test_list_tenants_no_keys,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'=' * 60}\n")

    if failed > 0:
        print("⚠️  MULTI-TENANT SECURITY TESTS FAILED — DO NOT DEPLOY")
        sys.exit(1)
    else:
        print("🔒 ALL MULTI-TENANT TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run_all()
