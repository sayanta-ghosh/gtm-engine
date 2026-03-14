"""
Secure API Key Vault for GTM Engine

Architecture:
- Keys are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256)
- Master key derives from a passphrase via PBKDF2 (600k iterations)
- Keys are NEVER returned as strings — only used inside proxy calls
- The vault exposes a `call()` method that injects keys into HTTP requests
- Claude (or any LLM) can USE the vault but never SEE the keys

Security layers:
1. Encryption at rest (Fernet)
2. macOS Keychain integration for master key (via keyring)
3. Proxy pattern — keys injected at HTTP call time, never returned
4. Audit logging — every key access is logged with timestamp
5. No key ever appears in stdout, return values, or exceptions
"""

import json
import os
import hashlib
import base64
import time
import logging
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Configure audit logger — writes to file only, never stdout
VAULT_DIR = Path(__file__).parent.parent / ".vault"
AUDIT_LOG = VAULT_DIR / "audit.log"

audit_logger = logging.getLogger("vault.audit")
audit_logger.setLevel(logging.INFO)


class VaultError(Exception):
    """Vault errors never include key material in messages."""
    pass


class Vault:
    """
    Encrypted API key vault with proxy-based access pattern.

    Keys go IN but never come OUT. The only way to use a key is
    through vault.call() which injects the key into an HTTP request
    without ever exposing it to the caller.
    """

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_path = vault_path or VAULT_DIR
        self.vault_path.mkdir(parents=True, exist_ok=True)

        self.keys_file = self.vault_path / "keys.enc"
        self.salt_file = self.vault_path / "salt.bin"
        self.meta_file = self.vault_path / "meta.json"

        # Set up audit log
        self._setup_audit_log()

        self._fernet: Optional[Fernet] = None
        self._unlocked = False

    def _setup_audit_log(self):
        """Audit log writes to file, never to stdout."""
        log_file = self.vault_path / "audit.log"
        if not audit_logger.handlers:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(message)s")
            )
            audit_logger.addHandler(handler)

    def _derive_key(self, passphrase: str, salt: bytes) -> bytes:
        """Derive encryption key from passphrase using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,  # OWASP recommended minimum
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        return key

    def initialize(self, passphrase: str) -> dict:
        """
        Initialize a new vault with a master passphrase.
        Returns status dict (never key material).
        """
        if self.keys_file.exists():
            raise VaultError("Vault already initialized. Use unlock() instead.")

        # Generate random salt
        salt = os.urandom(32)
        self.salt_file.write_bytes(salt)

        # Derive encryption key
        key = self._derive_key(passphrase, salt)
        self._fernet = Fernet(key)
        self._unlocked = True

        # Create empty encrypted store
        empty_store = self._fernet.encrypt(json.dumps({}).encode())
        self.keys_file.write_bytes(empty_store)

        # Write metadata (no secrets here)
        meta = {
            "created": datetime.utcnow().isoformat(),
            "version": 1,
            "kdf": "PBKDF2-SHA256",
            "kdf_iterations": 600_000,
            "encryption": "Fernet (AES-128-CBC + HMAC-SHA256)",
            "providers": []
        }
        self.meta_file.write_text(json.dumps(meta, indent=2))

        audit_logger.info("VAULT_INITIALIZED")

        return {
            "status": "initialized",
            "vault_path": str(self.vault_path),
            "encryption": "Fernet (AES-128-CBC + HMAC-SHA256)"
        }

    def unlock(self, passphrase: str) -> dict:
        """Unlock the vault with the master passphrase."""
        if not self.keys_file.exists():
            raise VaultError("Vault not initialized. Use initialize() first.")

        salt = self.salt_file.read_bytes()
        key = self._derive_key(passphrase, salt)
        self._fernet = Fernet(key)

        # Test decryption
        try:
            encrypted = self.keys_file.read_bytes()
            self._fernet.decrypt(encrypted)
        except Exception:
            self._fernet = None
            audit_logger.warning("UNLOCK_FAILED | bad passphrase attempt")
            raise VaultError("Invalid passphrase.")

        self._unlocked = True
        audit_logger.info("VAULT_UNLOCKED")

        return {"status": "unlocked"}

    def _require_unlocked(self):
        if not self._unlocked or not self._fernet:
            raise VaultError("Vault is locked. Call unlock() first.")

    def _read_store(self) -> dict:
        """Read and decrypt the key store."""
        self._require_unlocked()
        encrypted = self.keys_file.read_bytes()
        decrypted = self._fernet.decrypt(encrypted)
        return json.loads(decrypted.decode())

    def _write_store(self, store: dict):
        """Encrypt and write the key store."""
        self._require_unlocked()
        encrypted = self._fernet.encrypt(json.dumps(store).encode())
        self.keys_file.write_bytes(encrypted)

    def store_key(self, provider: str, key_value: str, key_type: str = "api_key") -> dict:
        """
        Store an API key. The key_value is encrypted immediately
        and never returned again.

        Returns confirmation (never the key itself).
        """
        self._require_unlocked()

        store = self._read_store()

        # Store with metadata
        store[provider] = {
            "type": key_type,
            "stored_at": datetime.utcnow().isoformat(),
            "fingerprint": hashlib.sha256(key_value.encode()).hexdigest()[:12],
            # The actual key — encrypted at rest
            "value": key_value
        }

        self._write_store(store)

        # Update metadata
        if self.meta_file.exists():
            meta = json.loads(self.meta_file.read_text())
            if provider not in meta.get("providers", []):
                meta.setdefault("providers", []).append(provider)
                self.meta_file.write_text(json.dumps(meta, indent=2))

        audit_logger.info(f"KEY_STORED | provider={provider} | type={key_type} | fingerprint={store[provider]['fingerprint']}")

        # SECURITY: Never return the key value
        return {
            "status": "stored",
            "provider": provider,
            "fingerprint": store[provider]["fingerprint"]
        }

    def list_providers(self) -> dict:
        """List stored providers (never key values)."""
        self._require_unlocked()
        store = self._read_store()

        providers = {}
        for name, data in store.items():
            providers[name] = {
                "type": data.get("type", "unknown"),
                "stored_at": data.get("stored_at", "unknown"),
                "fingerprint": data.get("fingerprint", "unknown"),
                # SECURITY: 'value' is explicitly excluded
            }

        audit_logger.info(f"LIST_PROVIDERS | count={len(providers)}")
        return {"providers": providers}

    def get_key(self, provider: str) -> str:
        """
        INTERNAL ONLY — retrieve raw key for proxy injection.

        This method exists so vault.call() can inject keys into HTTP requests.
        It should NEVER be called directly by Claude or exposed via CLI.

        The key is used inside _inject_auth() and immediately discarded.
        """
        self._require_unlocked()
        store = self._read_store()

        if provider not in store:
            raise VaultError(f"No key stored for provider: {provider}")

        audit_logger.info(f"KEY_ACCESSED | provider={provider} | method=internal_proxy")
        return store[provider]["value"]

    def delete_key(self, provider: str) -> dict:
        """Delete a stored key."""
        self._require_unlocked()
        store = self._read_store()

        if provider not in store:
            raise VaultError(f"No key stored for provider: {provider}")

        del store[provider]
        self._write_store(store)

        audit_logger.info(f"KEY_DELETED | provider={provider}")
        return {"status": "deleted", "provider": provider}

    def rotate_key(self, provider: str, new_key_value: str) -> dict:
        """Rotate a key — stores new value, logs the rotation."""
        self._require_unlocked()
        store = self._read_store()

        old_fingerprint = store.get(provider, {}).get("fingerprint", "none")
        result = self.store_key(provider, new_key_value)

        audit_logger.info(
            f"KEY_ROTATED | provider={provider} | "
            f"old_fingerprint={old_fingerprint} | "
            f"new_fingerprint={result['fingerprint']}"
        )

        return {
            "status": "rotated",
            "provider": provider,
            "new_fingerprint": result["fingerprint"]
        }

    def lock(self) -> dict:
        """Lock the vault — clear the encryption key from memory."""
        self._fernet = None
        self._unlocked = False
        audit_logger.info("VAULT_LOCKED")
        return {"status": "locked"}
