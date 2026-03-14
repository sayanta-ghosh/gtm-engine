"""
Composio MCP Setup for GTM Engine

This script generates MCP URLs for your Composio-connected tools
and provides the exact `claude mcp add` commands to run.

Prerequisites:
- Composio account with API key
- Slack and Google Sheets already connected in Composio dashboard

Usage:
  python3 setup_composio.py

It will:
1. Connect to Composio with your API key
2. Generate MCP session URLs for Slack + Google Sheets
3. Print the exact `claude mcp add` commands to run
"""

import os
import sys
from dotenv import load_dotenv

# Load env vars
load_dotenv()

def setup_composio():
    """Generate Composio MCP URLs and Claude Code setup commands."""

    # Check for API key
    api_key = os.getenv("COMPOSIO_API_KEY")

    if not api_key:
        print("\n⚠️  COMPOSIO_API_KEY not found in environment.")
        print("\nTo set it up:")
        print("  1. Go to https://app.composio.dev/settings → API Keys")
        print("  2. Copy your API key")
        print("  3. Add to your .env file:")
        print('     COMPOSIO_API_KEY="your_key_here"')
        print("  4. Run this script again\n")
        return False

    print("\n🔧 Composio MCP Setup for Claude Code")
    print("=" * 50)

    try:
        from composio import Composio

        client = Composio(api_key=api_key)

        # Generate MCP sessions for each toolkit
        toolkits = {
            "slack": "Slack messaging, channels, approvals",
            "googlesheets": "Google Sheets read/write for dashboards",
        }

        mcp_commands = []

        for toolkit_name, description in toolkits.items():
            print(f"\n📡 Setting up {toolkit_name}...")
            try:
                session = client.create(
                    user_id="gtm-engine-user",
                    toolkits=[toolkit_name],
                )
                mcp_url = session.mcp.url

                cmd = (
                    f'claude mcp add --transport sse '
                    f'{toolkit_name}-composio "{mcp_url}"'
                )
                mcp_commands.append((toolkit_name, cmd, description))
                print(f"   ✅ {toolkit_name} session created")

            except Exception as e:
                print(f"   ❌ {toolkit_name} failed: {e}")
                print(f"   → Make sure {toolkit_name} is connected at https://app.composio.dev/connections")

        if mcp_commands:
            print("\n" + "=" * 50)
            print("📋 Run these commands in your terminal:\n")

            for toolkit_name, cmd, description in mcp_commands:
                print(f"# {description}")
                print(f"{cmd}\n")

            print("=" * 50)
            print("\n✅ After running the commands above:")
            print("   1. Restart Claude Code")
            print("   2. Run /mcp to verify connections")
            print("   3. Try: 'Send a test message to #general on Slack'")
            print("   4. Try: 'Create a new Google Sheet called GTM Dashboard'\n")

            return True

    except ImportError:
        print("\n❌ composio-core not installed. Run:")
        print("   pip3 install composio-core\n")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")

        # Provide manual fallback
        print("\n📋 Manual Setup (if API connection fails):")
        print("=" * 50)
        print()
        print("Option A: Use Composio CLI directly\n")
        print("  # Install Composio CLI")
        print("  pip3 install composio-core")
        print()
        print("  # Login")
        print("  composio login")
        print()
        print("  # Add Slack to Claude Code via Composio's Rube MCP")
        print("  # Go to https://mcp.composio.dev and generate your URL")
        print("  # Then run:")
        print('  claude mcp add --transport sse slack-composio "YOUR_COMPOSIO_MCP_URL"')
        print()
        print("Option B: Use Composio's web MCP generator\n")
        print("  1. Go to https://mcp.composio.dev")
        print("  2. Select Slack + Google Sheets toolkits")
        print("  3. Click 'Generate MCP URL'")
        print("  4. Copy the `claude mcp add` command")
        print("  5. Paste in terminal\n")

        return False


def verify_existing_mcps():
    """Check what MCP servers are already configured."""
    print("\n🔍 Checking existing MCP servers...")

    import subprocess
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout:
            print(result.stdout)
        else:
            print("   No MCP servers configured yet, or Claude CLI not in PATH")
    except FileNotFoundError:
        print("   Claude CLI not found in PATH")
    except Exception as e:
        print(f"   Could not check: {e}")


if __name__ == "__main__":
    setup_composio()
