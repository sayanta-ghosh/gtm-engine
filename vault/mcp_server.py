"""
MCP Server for GTM Engine Vault

Exposes the vault, proxy, and key manager as MCP tools
that Claude Code can call directly.

Claude sees these tools:
- gtm_vault_status      → Check vault status and available providers
- gtm_add_key           → Store a BYOK key (value encrypted, never returned)
- gtm_remove_key        → Remove a BYOK key (falls back to platform)
- gtm_show_keys         → List all key configs (fingerprints only)
- gtm_enrich            → Make an authenticated enrichment call via proxy
- gtm_check_spend       → Check monthly spend vs cap
- gtm_show_usage        → Show API usage stats

Claude CANNOT:
- Read any actual key values
- Access other tenants' keys
- Bypass encryption

Usage:
    python3 -m vault.mcp_server --tenant-id <id> --passphrase <pass>

    Or via claude mcp add:
    claude mcp add gtm-vault -- python3 -m vault.mcp_server --tenant-id <id>
"""

import json
import sys
import argparse
import logging
from typing import Any
from pathlib import Path

# MCP protocol over stdio (simplified implementation)
# For production, use the official MCP Python SDK


class MCPTool:
    """Definition of a single MCP tool."""
    def __init__(self, name: str, description: str, parameters: dict, handler):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler


class GTMVaultMCPServer:
    """
    MCP server that exposes vault operations as tools.

    Security model:
    - Runs as a separate process (Claude can't inspect memory)
    - Keys never appear in tool responses
    - All operations are tenant-scoped
    - Audit log captures every access
    """

    def __init__(self, tenant_id: str, passphrase: str, platform_passphrase: str = None):
        from .tenant import TenantVault
        from .key_manager import KeyManager
        from .tenant_proxy import TenantProxy

        self.tenant_id = tenant_id

        # Initialize vaults
        self.tv = TenantVault()

        # Unlock platform vault if passphrase provided
        if platform_passphrase:
            self.tv.initialize_platform(platform_passphrase)

        # Unlock tenant vault
        self.tv.unlock_tenant(tenant_id, passphrase)

        # Initialize managers
        self.km = KeyManager(self.tv)
        self.proxy = TenantProxy(self.tv)

        # Register tools
        self.tools = self._register_tools()

    def _register_tools(self) -> list[MCPTool]:
        """Register all MCP tools."""
        return [
            MCPTool(
                name="gtm_vault_status",
                description=(
                    "Check the vault status and list available providers for this tenant. "
                    "Shows which providers have keys (BYOK or platform) and their status. "
                    "Never shows actual key values."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=self._handle_vault_status,
            ),
            MCPTool(
                name="gtm_add_key",
                description=(
                    "Store a BYOK (bring-your-own-key) API key for an enrichment provider. "
                    "The key is encrypted immediately and can never be retrieved. "
                    "This key takes priority over any platform key for this provider. "
                    "Supported providers: apollo, pdl, hunter, leadmagic, zerobounce, "
                    "apify, firecrawl, composio, instantly, crustdata."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Provider name (e.g., 'apollo', 'pdl', 'hunter')",
                        },
                        "key_value": {
                            "type": "string",
                            "description": "The API key to store. Will be encrypted immediately.",
                        },
                    },
                    "required": ["provider", "key_value"],
                },
                handler=self._handle_add_key,
            ),
            MCPTool(
                name="gtm_remove_key",
                description=(
                    "Remove a BYOK key for a provider. The tenant will fall back "
                    "to the platform key if available. Permanent action."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Provider name to remove key for",
                        },
                    },
                    "required": ["provider"],
                },
                handler=self._handle_remove_key,
            ),
            MCPTool(
                name="gtm_show_keys",
                description=(
                    "List all API key configurations for this tenant. "
                    "Shows provider name, source (byok/platform), status, "
                    "and fingerprint — NEVER the actual key values."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=self._handle_show_keys,
            ),
            MCPTool(
                name="gtm_enrich",
                description=(
                    "Make an authenticated enrichment API call via the secure proxy. "
                    "The API key is injected automatically (BYOK first, platform fallback). "
                    "The key is never visible in the request or response."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Provider to call (e.g., 'apollo', 'pdl')",
                        },
                        "method": {
                            "type": "string",
                            "description": "HTTP method (GET, POST, etc.)",
                            "default": "POST",
                        },
                        "endpoint": {
                            "type": "string",
                            "description": "API endpoint path (e.g., '/people/match')",
                        },
                        "data": {
                            "type": "object",
                            "description": "Request body (JSON)",
                        },
                        "params": {
                            "type": "object",
                            "description": "Query parameters",
                        },
                    },
                    "required": ["provider", "endpoint"],
                },
                handler=self._handle_enrich,
            ),
            MCPTool(
                name="gtm_show_usage",
                description=(
                    "Show API usage statistics for this tenant. "
                    "Breaks down calls by provider and key source (byok/platform)."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=self._handle_show_usage,
            ),
            MCPTool(
                name="gtm_supported_providers",
                description=(
                    "List all supported enrichment and sequencing providers "
                    "with their base URLs and auth methods."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=self._handle_supported_providers,
            ),
        ]

    # ================================================================
    # TOOL HANDLERS
    # ================================================================

    def _handle_vault_status(self, params: dict) -> dict:
        return self.proxy.check_all_providers(self.tenant_id)

    def _handle_add_key(self, params: dict) -> dict:
        return self.km.add_key(
            self.tenant_id,
            params["provider"],
            params["key_value"],
        )

    def _handle_remove_key(self, params: dict) -> dict:
        return self.km.remove_key(self.tenant_id, params["provider"])

    def _handle_show_keys(self, params: dict) -> dict:
        return self.km.show_keys(self.tenant_id)

    def _handle_enrich(self, params: dict) -> dict:
        return self.proxy.call(
            tenant_id=self.tenant_id,
            provider=params["provider"],
            method=params.get("method", "POST"),
            endpoint=params["endpoint"],
            data=params.get("data"),
            params=params.get("params"),
        )

    def _handle_show_usage(self, params: dict) -> dict:
        return self.km.show_usage(self.tenant_id)

    def _handle_supported_providers(self, params: dict) -> dict:
        return self.km.list_supported_providers()

    # ================================================================
    # MCP PROTOCOL (JSON-RPC over stdio)
    # ================================================================

    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions in MCP format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.parameters,
            }
            for tool in self.tools
        ]

    def handle_request(self, request: dict) -> dict:
        """Handle a single JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "gtm-vault",
                        "version": "1.0.0",
                    },
                },
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tool_definitions()},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})

            for tool in self.tools:
                if tool.name == tool_name:
                    try:
                        result = tool.handler(tool_args)
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps(result, indent=2),
                                    }
                                ]
                            },
                        }
                    except Exception as e:
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32000,
                                "message": str(e),
                            },
                        }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
            }

        elif method == "notifications/initialized":
            return None  # Notification, no response needed

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}",
                },
            }

    def run_stdio(self):
        """Run the MCP server on stdio (JSON-RPC over stdin/stdout)."""
        logging.basicConfig(
            filename=str(Path(__file__).parent.parent / ".vault" / "mcp_server.log"),
            level=logging.INFO,
        )

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="GTM Vault MCP Server")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID")
    parser.add_argument("--passphrase", required=True, help="Tenant vault passphrase")
    parser.add_argument("--platform-passphrase", help="Platform vault passphrase")
    args = parser.parse_args()

    server = GTMVaultMCPServer(
        tenant_id=args.tenant_id,
        passphrase=args.passphrase,
        platform_passphrase=args.platform_passphrase,
    )
    server.run_stdio()


if __name__ == "__main__":
    main()
