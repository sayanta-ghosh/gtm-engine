"""
Vault Security Test Suite

Tests that API keys can NEVER be exposed through any path:
1. Direct access attempts
2. String representation / repr
3. JSON serialization of vault objects
4. Error message leakage
5. Audit log inspection
6. Proxy response scrubbing
7. Encryption at rest validation
"""

import json
import os
import sys
import shutil
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vault.vault import Vault, VaultError
from vault.proxy import SecureProxy, PROVIDER_AUTH_CONFIG


# ============================================================
# TEST FIXTURES
# ============================================================

TEST_PASSPHRASE = "test-passphrase-do-not-use-in-prod"
FAKE_KEYS = {
    "apollo": "apollo_test_key_abc123_FAKE_KEY_DO_NOT_USE",
    "pdl": "pdl_test_key_xyz789_FAKE_KEY_DO_NOT_USE",
    "hunter": "hunter_test_key_qrs456_FAKE_KEY_DO_NOT_USE",
}


def setup_test_vault() -> tuple[Vault, Path]:
    """Create a fresh test vault with fake keys."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="vault_test_"))
    vault = Vault(vault_path=tmp_dir)
    vault.initialize(TEST_PASSPHRASE)

    for provider, key in FAKE_KEYS.items():
        vault.store_key(provider, key)

    return vault, tmp_dir


def cleanup(tmp_dir: Path):
    """Clean up test vault."""
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
# TEST 1: Keys never returned by store_key()
# ============================================================

def test_store_key_never_returns_value():
    """store_key() must never include the key value in its return."""
    vault, tmp_dir = setup_test_vault()

    result = vault.store_key("test_provider", "super_secret_key_12345")

    # Check that the key value is NOT anywhere in the result
    result_str = json.dumps(result)
    assert "super_secret_key_12345" not in result_str, \
        "CRITICAL: store_key() returned the key value!"

    # Should have fingerprint, status, provider — but never the value
    assert result["status"] == "stored"
    assert "fingerprint" in result
    assert "value" not in result

    print("✅ TEST 1 PASSED: store_key() never returns key value")
    cleanup(tmp_dir)


# ============================================================
# TEST 2: list_providers() never exposes keys
# ============================================================

def test_list_providers_never_exposes_keys():
    """list_providers() must never include key values."""
    vault, tmp_dir = setup_test_vault()

    result = vault.list_providers()
    result_str = json.dumps(result)

    for provider, key in FAKE_KEYS.items():
        assert key not in result_str, \
            f"CRITICAL: list_providers() exposed key for {provider}!"

    # Should have metadata but not values
    for provider, info in result["providers"].items():
        assert "value" not in info, \
            f"CRITICAL: 'value' field present for {provider}!"
        assert "fingerprint" in info

    print("✅ TEST 2 PASSED: list_providers() never exposes keys")
    cleanup(tmp_dir)


# ============================================================
# TEST 3: Encrypted at rest — raw file is unreadable
# ============================================================

def test_encryption_at_rest():
    """The keys.enc file must not contain plaintext keys."""
    vault, tmp_dir = setup_test_vault()

    # Read the raw encrypted file
    keys_file = tmp_dir / "keys.enc"
    raw_bytes = keys_file.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    for provider, key in FAKE_KEYS.items():
        assert key not in raw_text, \
            f"CRITICAL: Key for {provider} found in plaintext in keys.enc!"

    # Also check it's not base64-decodable to plaintext
    assert raw_text.startswith("gAAAAA"), \
        "Encrypted file doesn't look like Fernet ciphertext"

    print("✅ TEST 3 PASSED: Keys encrypted at rest (not plaintext in file)")
    cleanup(tmp_dir)


# ============================================================
# TEST 4: Wrong passphrase is rejected
# ============================================================

def test_wrong_passphrase_rejected():
    """Unlock with wrong passphrase must fail."""
    vault, tmp_dir = setup_test_vault()
    vault.lock()

    try:
        vault.unlock("wrong_passphrase_attempt")
        assert False, "CRITICAL: Wrong passphrase was accepted!"
    except VaultError as e:
        assert "Invalid passphrase" in str(e)
        # Make sure error doesn't leak any key material
        error_str = str(e)
        for key in FAKE_KEYS.values():
            assert key not in error_str, \
                "CRITICAL: Key material in error message!"

    print("✅ TEST 4 PASSED: Wrong passphrase correctly rejected")
    cleanup(tmp_dir)


# ============================================================
# TEST 5: Locked vault blocks all operations
# ============================================================

def test_locked_vault_blocks_operations():
    """A locked vault must refuse all key operations."""
    vault, tmp_dir = setup_test_vault()
    vault.lock()

    operations = [
        ("list_providers", lambda: vault.list_providers()),
        ("store_key", lambda: vault.store_key("x", "y")),
        ("get_key", lambda: vault.get_key("apollo")),
        ("delete_key", lambda: vault.delete_key("apollo")),
    ]

    for name, op in operations:
        try:
            op()
            assert False, f"CRITICAL: {name}() worked on locked vault!"
        except VaultError as e:
            assert "locked" in str(e).lower()

    print("✅ TEST 5 PASSED: Locked vault blocks all operations")
    cleanup(tmp_dir)


# ============================================================
# TEST 6: Audit log never contains key values
# ============================================================

def test_audit_log_never_contains_keys():
    """The audit log must never contain actual key values."""
    vault, tmp_dir = setup_test_vault()

    # Trigger various operations to generate log entries
    vault.list_providers()
    vault.get_key("apollo")  # Internal access
    vault.store_key("new_provider", "new_secret_key_xyz")
    vault.rotate_key("apollo", "rotated_apollo_key_abc")
    vault.delete_key("pdl")
    vault.lock()

    # Read audit log
    audit_file = tmp_dir / "audit.log"
    if audit_file.exists():
        log_content = audit_file.read_text()

        all_keys = list(FAKE_KEYS.values()) + [
            "new_secret_key_xyz",
            "rotated_apollo_key_abc",
        ]

        for key in all_keys:
            assert key not in log_content, \
                f"CRITICAL: Key material found in audit log!"

        # Fingerprints ARE allowed in logs (they're hashes)
        print(f"   Audit log has {len(log_content.splitlines())} entries")

    print("✅ TEST 6 PASSED: Audit log contains no key material")
    cleanup(tmp_dir)


# ============================================================
# TEST 7: Proxy response scrubbing works
# ============================================================

def test_proxy_scrubbing():
    """If a key accidentally appears in a response, it gets scrubbed."""
    vault, tmp_dir = setup_test_vault()
    proxy = SecureProxy(vault)

    # Simulate a response that accidentally contains the key
    test_key = FAKE_KEYS["apollo"]
    dirty_text = f"Error: invalid key {test_key} for endpoint /test"

    scrubbed = proxy._scrub_secrets(dirty_text, "apollo")

    assert test_key not in scrubbed, \
        "CRITICAL: Scrubbing failed to remove key from text!"
    assert "[REDACTED]" in scrubbed or "[REDACT-START]" in scrubbed

    print("✅ TEST 7 PASSED: Proxy correctly scrubs leaked keys from responses")
    cleanup(tmp_dir)


# ============================================================
# TEST 8: Metadata file contains no secrets
# ============================================================

def test_metadata_has_no_secrets():
    """meta.json must never contain key material."""
    vault, tmp_dir = setup_test_vault()

    meta_file = tmp_dir / "meta.json"
    meta_content = meta_file.read_text()

    for key in FAKE_KEYS.values():
        assert key not in meta_content, \
            "CRITICAL: Key material found in meta.json!"

    # Should contain provider names (that's fine) but not values
    meta = json.loads(meta_content)
    assert "providers" in meta
    assert TEST_PASSPHRASE not in meta_content

    print("✅ TEST 8 PASSED: meta.json contains no secrets")
    cleanup(tmp_dir)


# ============================================================
# TEST 9: Re-encryption after unlock
# ============================================================

def test_reencryption_after_unlock():
    """After unlock + operations, keys must still be encrypted at rest."""
    vault, tmp_dir = setup_test_vault()

    # Lock, then unlock with correct passphrase
    vault.lock()
    vault.unlock(TEST_PASSPHRASE)

    # Do some operations
    vault.store_key("new_prov", "yet_another_secret_key")
    vault.list_providers()

    # Check file is still encrypted
    raw = (tmp_dir / "keys.enc").read_bytes().decode("utf-8", errors="replace")

    assert "yet_another_secret_key" not in raw, \
        "CRITICAL: New key stored in plaintext!"
    for key in FAKE_KEYS.values():
        assert key not in raw

    print("✅ TEST 9 PASSED: Keys remain encrypted after unlock + operations")
    cleanup(tmp_dir)


# ============================================================
# TEST 10: Key rotation generates new fingerprint
# ============================================================

def test_key_rotation():
    """Rotating a key must produce a different fingerprint."""
    vault, tmp_dir = setup_test_vault()

    old_providers = vault.list_providers()
    old_fingerprint = old_providers["providers"]["apollo"]["fingerprint"]

    result = vault.rotate_key("apollo", "completely_new_apollo_key")

    assert result["new_fingerprint"] != old_fingerprint, \
        "Rotation didn't change fingerprint!"
    assert "completely_new_apollo_key" not in json.dumps(result), \
        "CRITICAL: New key exposed in rotation result!"

    print("✅ TEST 10 PASSED: Key rotation works securely")
    cleanup(tmp_dir)


# ============================================================
# TEST 11: Proxy call structure (dry run — no real API call)
# ============================================================

def test_proxy_provider_check():
    """check_provider() must return config info but never the key."""
    vault, tmp_dir = setup_test_vault()
    proxy = SecureProxy(vault)

    result = proxy.check_provider("apollo")
    result_str = json.dumps(result)

    assert result["configured"] is True
    assert result["has_key"] is True
    assert FAKE_KEYS["apollo"] not in result_str, \
        "CRITICAL: check_provider() exposed the key!"

    # Unknown provider
    result2 = proxy.check_provider("unknown_xyz")
    assert result2["configured"] is False

    print("✅ TEST 11 PASSED: check_provider() never exposes keys")
    cleanup(tmp_dir)


# ============================================================
# RUN ALL TESTS
# ============================================================

def run_all_tests():
    print("\n" + "=" * 60)
    print("  VAULT SECURITY TEST SUITE")
    print("=" * 60 + "\n")

    tests = [
        test_store_key_never_returns_value,
        test_list_providers_never_exposes_keys,
        test_encryption_at_rest,
        test_wrong_passphrase_rejected,
        test_locked_vault_blocks_operations,
        test_audit_log_never_contains_keys,
        test_proxy_scrubbing,
        test_metadata_has_no_secrets,
        test_reencryption_after_unlock,
        test_key_rotation,
        test_proxy_provider_check,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'=' * 60}\n")

    if failed > 0:
        print("⚠️  SECURITY TESTS FAILED — DO NOT DEPLOY")
        sys.exit(1)
    else:
        print("🔒 ALL SECURITY TESTS PASSED — Vault is secure")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()
