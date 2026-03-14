"""
End-to-End Admin + Tenant Interface Tests

Tests the full lifecycle:
1.  Admin sets up platform keys
2.  Admin creates tenants
3.  Tenant sees platform keys as available
4.  Tenant overrides with BYOK → uses their own key
5.  Tenant reverts to platform → back to default
6.  Admin rotates platform key → all non-BYOK tenants affected
7.  Admin sees override map in dashboard
8.  Tenant usage tracks correctly per source
9.  Admin suspends tenant → all calls blocked
10. Security: tenant can't see platform key values
11. Security: tenant can't see other tenants
12. Security: admin can't see BYOK key values
"""

import json
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vault.admin import AdminConsole
from vault.tenant_console import TenantConsole
from vault.tenant import TenantVault, VaultError

ADMIN_PASS = "admin-master-pass"
TENANT_ALICE_PASS = "alice-pass"
TENANT_BOB_PASS = "bob-pass"


def setup() -> tuple[AdminConsole, Path]:
    """Set up admin with platform keys."""
    tmp = Path(tempfile.mkdtemp(prefix="admin_test_"))
    admin = AdminConsole(base_path=tmp)
    admin.unlock(ADMIN_PASS)

    # Add platform keys for 3 providers
    admin.add_platform_key("apollo", "platform_apollo_key_FAKE")
    admin.add_platform_key("pdl", "platform_pdl_key_FAKE")
    admin.add_platform_key("hunter", "platform_hunter_key_FAKE")

    return admin, tmp


def cleanup(tmp: Path):
    shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# TEST 1: Admin sets up platform + creates tenants
# ============================================================

def test_admin_setup():
    admin, tmp = setup()

    # Create two tenants
    alice = admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")
    bob = admin.create_tenant("Bob Inc", TENANT_BOB_PASS, plan="both",
                              spend_cap_cents=10000, tenant_id="bob")

    assert alice["success"]
    assert bob["success"]
    assert bob["spend_cap"] == "$100.00/mo"

    # Dashboard shows both
    dash = admin.dashboard()
    assert dash["tenant_count"] == 2
    assert len(dash["platform_keys"]) == 3

    print("✅ TEST 1 PASSED: Admin setup + tenant creation works")
    cleanup(tmp)


# ============================================================
# TEST 2: Tenant sees platform keys as available
# ============================================================

def test_tenant_sees_platform():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    # Alice unlocks her console
    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    providers = alice.my_providers()
    assert providers["success"]

    # Alice should see apollo, pdl, hunter as "platform"
    apollo = next(p for p in providers["providers"] if p["provider"] == "apollo")
    assert apollo["using"] == "platform", f"Expected 'platform', got '{apollo['using']}'"
    assert apollo["can_override"] is True

    print("✅ TEST 2 PASSED: Tenant sees platform keys as available")
    cleanup(tmp)


# ============================================================
# TEST 3: Tenant overrides with BYOK → uses their own key
# ============================================================

def test_tenant_byok_override():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Before override: using platform
    check_before = alice.check_provider("apollo")
    assert check_before["key_source"] == "platform"

    # Override with BYOK
    result = alice.use_my_key("apollo", "alice_own_apollo_key_FAKE")
    assert result["success"]
    assert result["source"] == "byok"
    assert "alice_own_apollo_key_FAKE" not in json.dumps(result)  # Key not exposed

    # After override: using BYOK
    check_after = alice.check_provider("apollo")
    assert check_after["key_source"] == "byok"

    # Verify actual key resolution
    key, source = admin.tv.resolve_key("alice", "apollo")
    assert key == "alice_own_apollo_key_FAKE"
    assert source == "byok"

    print("✅ TEST 3 PASSED: Tenant BYOK override works")
    cleanup(tmp)


# ============================================================
# TEST 4: Tenant reverts to platform default
# ============================================================

def test_tenant_revert_to_platform():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Override then revert
    alice.use_my_key("apollo", "alice_temp_key")
    assert alice.check_provider("apollo")["key_source"] == "byok"

    result = alice.use_platform_key("apollo")
    assert result["success"]
    assert result["source"] == "platform"

    # Should be back on platform key
    key, source = admin.tv.resolve_key("alice", "apollo")
    assert key == "platform_apollo_key_FAKE"
    assert source == "platform"

    print("✅ TEST 4 PASSED: Tenant revert to platform works")
    cleanup(tmp)


# ============================================================
# TEST 5: Admin rotates platform key → affects non-BYOK tenants
# ============================================================

def test_admin_rotates_platform_key():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")
    admin.create_tenant("Bob Inc", TENANT_BOB_PASS, plan="both", tenant_id="bob")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    bob = TenantConsole(admin.tv, tenant_id="bob")
    bob.unlock(TENANT_BOB_PASS)

    # Alice overrides apollo with BYOK
    alice.use_my_key("apollo", "alice_own_key")

    # Admin rotates platform apollo key
    result = admin.rotate_platform_key("apollo", "new_platform_apollo_key")
    assert result["success"]

    # Alice should still use HER key (BYOK takes priority)
    key_a, source_a = admin.tv.resolve_key("alice", "apollo")
    assert key_a == "alice_own_key"
    assert source_a == "byok"

    # Bob should get the NEW platform key
    key_b, source_b = admin.tv.resolve_key("bob", "apollo")
    assert key_b == "new_platform_apollo_key"
    assert source_b == "platform"

    print("✅ TEST 5 PASSED: Platform key rotation only affects non-BYOK tenants")
    cleanup(tmp)


# ============================================================
# TEST 6: Admin dashboard shows BYOK override map
# ============================================================

def test_admin_dashboard_overrides():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")
    admin.create_tenant("Bob Inc", TENANT_BOB_PASS, plan="both", tenant_id="bob")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Alice overrides apollo
    alice.use_my_key("apollo", "alice_key")

    dash = admin.dashboard()
    assert "apollo" in dash["byok_overrides"]
    assert "Alice Corp" in dash["byok_overrides"]["apollo"]
    assert "Bob Inc" not in dash.get("byok_overrides", {}).get("apollo", [])

    print("✅ TEST 6 PASSED: Admin dashboard shows correct override map")
    cleanup(tmp)


# ============================================================
# TEST 7: Usage tracks separately per key source
# ============================================================

def test_usage_tracking():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Use platform key for pdl
    admin.tv.resolve_key("alice", "pdl")  # platform
    admin.tv.resolve_key("alice", "pdl")  # platform

    # Override apollo and use it
    alice.use_my_key("apollo", "alice_apollo")
    admin.tv.resolve_key("alice", "apollo")  # byok

    usage = alice.my_usage()
    assert usage["success"]
    assert usage["usage"]["pdl"]["platform_calls"] == 2
    assert usage["usage"]["apollo"]["byok_calls"] == 1

    print("✅ TEST 7 PASSED: Usage tracked per key source")
    cleanup(tmp)


# ============================================================
# TEST 8: Admin suspend → all tenant calls blocked
# ============================================================

def test_admin_suspend():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Suspend
    result = admin.suspend_tenant("alice")
    assert result["success"]

    # All calls should fail
    try:
        admin.tv.resolve_key("alice", "apollo")
        assert False, "Should be blocked"
    except VaultError as e:
        assert "locked" in str(e).lower()

    # Reactivate
    result2 = admin.reactivate_tenant("alice", TENANT_ALICE_PASS)
    assert result2["success"]

    # Should work again
    key, source = admin.tv.resolve_key("alice", "apollo")
    assert source == "platform"

    print("✅ TEST 8 PASSED: Suspend blocks all calls, reactivate restores")
    cleanup(tmp)


# ============================================================
# TEST 9: Tenant CANNOT see platform key values
# ============================================================

def test_tenant_cant_see_platform_values():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # All tenant-facing methods
    outputs = [
        json.dumps(alice.my_providers()),
        json.dumps(alice.my_usage()),
        json.dumps(alice.check_all()),
        json.dumps(alice.byok_vs_platform()),
    ]

    all_output = " ".join(outputs)
    assert "platform_apollo_key_FAKE" not in all_output
    assert "platform_pdl_key_FAKE" not in all_output
    assert "platform_hunter_key_FAKE" not in all_output

    print("✅ TEST 9 PASSED: Tenant cannot see platform key values")
    cleanup(tmp)


# ============================================================
# TEST 10: Admin CANNOT see BYOK key values
# ============================================================

def test_admin_cant_see_byok_values():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)
    alice.use_my_key("apollo", "super_secret_alice_key")

    # Admin methods
    outputs = [
        json.dumps(admin.dashboard()),
        json.dumps(admin.tenant_detail("alice")),
        json.dumps(admin.list_platform_keys()),
    ]

    all_output = " ".join(outputs)
    assert "super_secret_alice_key" not in all_output, \
        "CRITICAL: Admin can see tenant's BYOK key value!"

    print("✅ TEST 10 PASSED: Admin cannot see tenant BYOK key values")
    cleanup(tmp)


# ============================================================
# TEST 11: Tenant can't see other tenants
# ============================================================

def test_tenant_isolation():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")
    admin.create_tenant("Bob Inc", TENANT_BOB_PASS, plan="both", tenant_id="bob")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    bob = TenantConsole(admin.tv, tenant_id="bob")
    bob.unlock(TENANT_BOB_PASS)

    bob.use_my_key("pdl", "bob_secret_pdl_key")

    # Alice's view should contain nothing about Bob
    alice_output = json.dumps(alice.my_providers()) + json.dumps(alice.my_usage())
    assert "bob" not in alice_output.lower()
    assert "bob_secret_pdl_key" not in alice_output

    print("✅ TEST 11 PASSED: Tenant isolation — can't see other tenants")
    cleanup(tmp)


# ============================================================
# TEST 12: Tenant key rotation
# ============================================================

def test_tenant_key_rotation():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)

    # Add key
    r1 = alice.use_my_key("apollo", "old_key_123")
    old_fp = r1["fingerprint"]

    # Rotate
    r2 = alice.rotate_my_key("apollo", "new_key_456")
    assert r2["success"]
    assert r2["new_fingerprint"] != old_fp
    assert "new_key_456" not in json.dumps(r2)
    assert "old_key_123" not in json.dumps(r2)

    # Verify resolution
    key, source = admin.tv.resolve_key("alice", "apollo")
    assert key == "new_key_456"
    assert source == "byok"

    print("✅ TEST 12 PASSED: Tenant key rotation works securely")
    cleanup(tmp)


# ============================================================
# TEST 13: Admin removes platform key → warns about affected tenants
# ============================================================

def test_admin_remove_platform_key():
    admin, tmp = setup()
    admin.create_tenant("Alice Corp", TENANT_ALICE_PASS, plan="both", tenant_id="alice")
    admin.create_tenant("Bob Inc", TENANT_BOB_PASS, plan="both", tenant_id="bob")

    alice = TenantConsole(admin.tv, tenant_id="alice")
    alice.unlock(TENANT_ALICE_PASS)
    alice.use_my_key("apollo", "alice_apollo")  # Alice has BYOK

    # Remove platform apollo key
    result = admin.remove_platform_key("apollo")
    assert result["success"]
    # Alice has BYOK so should NOT be in affected list
    assert "alice" not in result["affected_tenants"]
    # Bob has no BYOK so SHOULD be affected
    assert "bob" in result["affected_tenants"]

    print("✅ TEST 13 PASSED: Admin remove warns about affected tenants correctly")
    cleanup(tmp)


# ============================================================
# RUN ALL
# ============================================================

def run_all():
    print("\n" + "=" * 60)
    print("  ADMIN + TENANT INTERFACE TESTS")
    print("=" * 60 + "\n")

    tests = [
        test_admin_setup,
        test_tenant_sees_platform,
        test_tenant_byok_override,
        test_tenant_revert_to_platform,
        test_admin_rotates_platform_key,
        test_admin_dashboard_overrides,
        test_usage_tracking,
        test_admin_suspend,
        test_tenant_cant_see_platform_values,
        test_admin_cant_see_byok_values,
        test_tenant_isolation,
        test_tenant_key_rotation,
        test_admin_remove_platform_key,
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
        print("⚠️  ADMIN/TENANT INTERFACE TESTS FAILED")
        sys.exit(1)
    else:
        print("🔒 ALL ADMIN + TENANT TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run_all()
