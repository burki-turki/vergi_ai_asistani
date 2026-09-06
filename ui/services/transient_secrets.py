# ============================================================
# Row 19B - Transient secret encryption (PKCE verifier storage).
#
# AEAD (AES-256-GCM) encryption for short-lived secrets that must be
# recoverable within a bounded window (the OIDC PKCE code_verifier,
# stored server-side between the authorization redirect and the
# callback). This module owns ONLY the crypto envelope: key lookup is
# delegated to an injected key provider so production (Row 19D real
# KMS custody/rotation) and tests (a fake in-memory provider) share
# the exact same code path here.
#
# Fails closed on: unknown key_id, AEAD tag verification failure
# (tampered ciphertext, wrong key, wrong AAD), or an expired
# transaction (checked by the caller via `expires_at`, not this
# module - this module has no notion of transaction lifetime).
#
# Dependency note: uses `cryptography` (PyCA) only - already present
# in every environment this project targets (it is joserfc's own
# declared dependency for signature verification, so it is never an
# "extra" package). No hand-written crypto primitives.
#
# Runs standalone, no network/DB required - see
# ui/tests/test_oidc_client_isolated.py for executed coverage.
# ============================================================

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class UnknownKeyError(Exception):
    """Raised when a ciphertext names a key_id the provider does not have."""


class DecryptionFailedError(Exception):
    """Raised on AEAD tag verification failure (tampered/wrong key/wrong AAD)."""


class KeyProvider(Protocol):
    """Row 19D owns the real implementation (KMS-backed). Row 19B tests
    against a fake in-memory provider satisfying this same interface."""

    def get_key(self, key_id: str) -> bytes:
        """Return the raw 32-byte AES-256 key for key_id, or raise UnknownKeyError."""
        ...

    def current_key_id(self) -> str:
        """Return the key_id that should be used for NEW encryptions."""
        ...


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_id: str
    alg: str  # always "AES-256-GCM" in this version


_ALG = "AES-256-GCM"
_NONCE_LEN = 12  # 96-bit nonce, standard for AES-GCM


def encrypt_transient_secret(
    plaintext: bytes,
    *,
    key_provider: KeyProvider,
    associated_data: bytes = b"",
) -> EncryptedSecret:
    """Encrypt `plaintext` under the provider's current key. `associated_data`
    should bind context that must not be swappable (e.g. the state_hash of
    the OIDC transaction this verifier belongs to) - AEAD authenticates it
    without encrypting it."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # lazy import

    key_id = key_provider.current_key_id()
    key = key_provider.get_key(key_id)
    if len(key) != 32:
        raise ValueError("AES-256-GCM requires a 32-byte key")

    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
    return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, key_id=key_id, alg=_ALG)


def decrypt_transient_secret(
    secret: EncryptedSecret,
    *,
    key_provider: KeyProvider,
    associated_data: bytes = b"",
) -> bytes:
    """Decrypt `secret`. Fails closed (raises) on:
    - unknown key_id (UnknownKeyError)
    - unsupported alg (ValueError)
    - AEAD tag verification failure - tampered ciphertext, wrong key, or a
      mismatched associated_data (DecryptionFailedError)
    Never returns a partial/best-effort plaintext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    if secret.alg != _ALG:
        raise ValueError(f"unsupported alg: {secret.alg!r}")

    try:
        key = key_provider.get_key(secret.key_id)
    except UnknownKeyError:
        raise
    except KeyError as exc:
        raise UnknownKeyError(secret.key_id) from exc

    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(secret.nonce, secret.ciphertext, associated_data)
    except InvalidTag as exc:
        raise DecryptionFailedError("AEAD tag verification failed") from exc


class InMemoryKeyProvider:
    """Fake key provider for tests only. Row 19D's real provider is backed
    by a KMS and is out of scope for Row 19B."""

    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}
        self._current: str | None = None

    def add_key(self, key_id: str, key: bytes, *, make_current: bool = True) -> None:
        self._keys[key_id] = key
        if make_current or self._current is None:
            self._current = key_id

    def get_key(self, key_id: str) -> bytes:
        try:
            return self._keys[key_id]
        except KeyError:
            raise UnknownKeyError(key_id) from None

    def current_key_id(self) -> str:
        if self._current is None:
            raise UnknownKeyError("<no current key configured>")
        return self._current
