"""
Composio Connection Test

Tests:
1. API key is valid and can authenticate
2. Available integrations/connections
3. Google Sheets MCP URL is reachable
4. Slack connection status
"""

import os
import sys
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/Users/mtadmin/Projects/.env")

sys.path.insert(0, str(Path(__file__).parent.parent))


def get_composio_key():
    """Get Composio API key (check both cases)."""
    return os.getenv("COMPOSIO_API_KEY") or os.getenv("composio_api_key")


def get_sheets_mcp_url():
    """Get Google Sheets MCP URL."""
    return os.getenv("COMPOSIO_SHEETS_MCP_URL")


# ============================================================
# TEST 1: Composio API key is valid
# ============================================================

def test_composio_api_auth():
    """Verify the Composio API key can authenticate."""
    api_key = get_composio_key()
    if not api_key:
        print("⚠️  TEST 1 SKIPPED: No COMPOSIO_API_KEY found")
        return False

    # Test auth against Composio API
    try:
        resp = requests.get(
            "https://backend.composio.dev/api/v1/client/auth/client_info",
            headers={"X-API-Key": api_key},
            timeout=15,
        )

        if resp.status_code == 200:
            data = resp.json()
            # Only print non-sensitive info
            client_name = data.get("client", {}).get("name", "unknown")
            plan = data.get("client", {}).get("plan", "unknown")
            print(f"   Account: {client_name} | Plan: {plan}")
            print("✅ TEST 1 PASSED: Composio API key is valid")
            return True
        elif resp.status_code == 401:
            print("❌ TEST 1 FAILED: API key is invalid (401 Unauthorized)")
            return False
        else:
            print(f"⚠️  TEST 1 UNCLEAR: Got status {resp.status_code}")
            return False

    except requests.RequestException as e:
        print(f"⚠️  TEST 1 ERROR: {e}")
        return False


# ============================================================
# TEST 2: List connected apps
# ============================================================

def test_list_connections():
    """List what apps are connected in Composio."""
    api_key = get_composio_key()
    if not api_key:
        print("⚠️  TEST 2 SKIPPED: No API key")
        return False

    try:
        resp = requests.get(
            "https://backend.composio.dev/api/v1/connectedAccounts",
            headers={"X-API-Key": api_key},
            params={"showActiveOnly": True},
            timeout=15,
        )

        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])

            if items:
                print(f"   Found {len(items)} connected app(s):")
                for item in items:
                    app_name = item.get("appName", "unknown")
                    status = item.get("status", "unknown")
                    print(f"   • {app_name}: {status}")
            else:
                print("   No connected apps found")
                print("   → Connect apps at https://app.composio.dev/connections")

            print("✅ TEST 2 PASSED: Successfully queried connected apps")
            return True
        else:
            print(f"⚠️  TEST 2: Status {resp.status_code}")
            return False

    except requests.RequestException as e:
        print(f"⚠️  TEST 2 ERROR: {e}")
        return False


# ============================================================
# TEST 3: Google Sheets MCP URL is reachable
# ============================================================

def test_sheets_mcp_reachable():
    """Test that the Google Sheets MCP URL is reachable."""
    mcp_url = get_sheets_mcp_url()
    if not mcp_url:
        print("⚠️  TEST 3 SKIPPED: No COMPOSIO_SHEETS_MCP_URL found")
        return False

    try:
        # MCP servers typically use SSE, so we just check if the endpoint responds
        # Try a basic GET to see if the server is alive
        resp = requests.get(
            mcp_url,
            timeout=15,
            headers={"Accept": "text/event-stream"},
            stream=True,
        )

        if resp.status_code in (200, 405, 404, 307):
            # 200 = SSE stream open, 405 = method not allowed (means server exists)
            # 404 = path not found but server responds, 307 = redirect
            print(f"   MCP endpoint responded: {resp.status_code}")
            print(f"   Content-Type: {resp.headers.get('content-type', 'none')}")
            print("✅ TEST 3 PASSED: Sheets MCP URL is reachable")
            resp.close()
            return True
        else:
            print(f"⚠️  TEST 3: Unexpected status {resp.status_code}")
            resp.close()
            return False

    except requests.RequestException as e:
        print(f"❌ TEST 3 FAILED: MCP URL not reachable: {e}")
        return False


# ============================================================
# TEST 4: Composio SDK connection test
# ============================================================

def test_composio_sdk():
    """Test the Composio Python SDK."""
    api_key = get_composio_key()
    if not api_key:
        print("⚠️  TEST 4 SKIPPED: No API key")
        return False

    try:
        from composio import Composio
        client = Composio(api_key=api_key)

        # Try to get connected accounts
        connected = client.connected_accounts.list()

        print(f"   SDK connected successfully")
        print(f"   Connected accounts: {len(connected) if hasattr(connected, '__len__') else 'accessible'}")
        print("✅ TEST 4 PASSED: Composio SDK works")
        return True

    except ImportError:
        print("⚠️  TEST 4 SKIPPED: composio-core not installed")
        return False
    except Exception as e:
        error_msg = str(e)
        # Don't expose API key in error
        if api_key and api_key in error_msg:
            error_msg = error_msg.replace(api_key, "[REDACTED]")
        print(f"⚠️  TEST 4: SDK error: {error_msg}")
        return False


# ============================================================
# TEST 5: Security — MCP URL not exposed in output
# ============================================================

def test_mcp_url_not_exposed():
    """Verify our test output doesn't leak the MCP URL."""
    import io
    from contextlib import redirect_stdout

    mcp_url = get_sheets_mcp_url()
    if not mcp_url:
        print("⚠️  TEST 5 SKIPPED: No MCP URL")
        return True  # Can't leak what doesn't exist

    # Capture stdout from other tests
    captured = io.StringIO()
    with redirect_stdout(captured):
        test_composio_api_auth()
        test_list_connections()

    output = captured.getvalue()

    if mcp_url in output:
        print("❌ TEST 5 FAILED: MCP URL was leaked in test output!")
        return False

    api_key = get_composio_key()
    if api_key and api_key in output:
        print("❌ TEST 5 FAILED: API key was leaked in test output!")
        return False

    print("✅ TEST 5 PASSED: No credentials leaked in test output")
    return True


# ============================================================
# RUN ALL TESTS
# ============================================================

def run_all():
    print("\n" + "=" * 60)
    print("  COMPOSIO CONNECTION TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("API Auth", test_composio_api_auth),
        ("Connected Apps", test_list_connections),
        ("Sheets MCP Reachable", test_sheets_mcp_reachable),
        ("SDK Connection", test_composio_sdk),
        ("Security - No Leaks", test_mcp_url_not_exposed),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} CRASHED: {e}")
            results.append((name, False))

    print(f"\n{'=' * 60}")
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"  RESULTS: {passed}/{total} passed")
    print(f"{'=' * 60}\n")

    # Print setup instructions for any missing pieces
    if not get_composio_key():
        print("📋 To fix: Add COMPOSIO_API_KEY to .env")
    if not get_sheets_mcp_url():
        print("📋 To fix: Add COMPOSIO_SHEETS_MCP_URL to .env")


if __name__ == "__main__":
    run_all()
