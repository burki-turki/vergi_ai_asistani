"""Read-only Azure Key Vault Secrets custody for Row 19D Slice 2."""
from __future__ import annotations

import asyncio
import base64
import binascii
import concurrent.futures
import contextvars
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .key_custody import (
    KeyCustodyConfigurationError,
    KeyCustodyProviderUnavailableError,
    KeyCustodyTransientError,
)
from .transient_secrets import UnknownKeyError

_DOCUMENT_FIELDS = frozenset({"version", "current_key_id", "keys", "server_pepper"})
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_DOCUMENT_BYTES = 16_384
_MAX_KEYS = 64
_MAX_PEPPER_BYTES = 1_024
_CACHE_TTL_SECONDS = 60.0
_OUTER_BUDGET_SECONDS = 5.0
_CONNECT_TIMEOUT_SECONDS = 1.0
_READ_TIMEOUT_SECONDS = 1.0
_ATTEMPT_UPPER_BOUND_SECONDS = 2.0
_MAX_RETRY_DELAY_SECONDS = 0.25
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class AzureCustodyConfigurationError(KeyCustodyConfigurationError):
    """Azure custody configuration is invalid."""


class AzureCustodyDocumentError(AzureCustodyConfigurationError):
    """The fetched Azure secret is not a trusted custody document."""


class AzureCustodyProviderError(KeyCustodyProviderUnavailableError):
    """A non-retryable Azure provider failure."""


class AzureCustodyTransientError(KeyCustodyTransientError):
    """A retryable Azure provider failure or outer deadline expiry."""


@dataclass(frozen=True, repr=False)
class AzureCustodyConfig:
    vault_url: str
    secret_name: str
    credential_kind: str
    managed_identity_client_id: str | None = None
    workload_tenant_id: str | None = None
    workload_client_id: str | None = None
    workload_token_file: str | None = None

    def fingerprint(self) -> tuple[str, ...]:
        return (
            self.vault_url,
            self.secret_name,
            self.credential_kind,
            self.managed_identity_client_id or "",
            self.workload_tenant_id or "",
            self.workload_client_id or "",
            self.workload_token_file or "",
        )


@dataclass(frozen=True, repr=False)
class AzureCustodySnapshot:
    document_version: int
    current_key_id: str
    keys: Mapping[str, bytes]
    server_pepper: bytes
    secret_version_id: str
    generation: int
    loaded_at_monotonic: float
    expires_at_monotonic: float


class AzureSnapshotKeyProvider:
    """KeyProvider view over one immutable, coherent Azure snapshot."""

    __slots__ = ("_snapshot",)

    def __init__(self, snapshot: AzureCustodySnapshot) -> None:
        self._snapshot = snapshot

    def get_key(self, key_id: str) -> bytes:
        try:
            return self._snapshot.keys[key_id]
        except KeyError:
            raise UnknownKeyError(key_id) from None

    def current_key_id(self) -> str:
        return self._snapshot.current_key_id


def _required_value(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value or value != value.strip():
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    return value


def _optional_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    if not value or value != value.strip():
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    return value


def _load_config() -> AzureCustodyConfig:
    vault_url = _required_value("VERGI_AZURE_KEY_VAULT_URL")
    parsed = urlsplit(vault_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    secret_name = _required_value("VERGI_AZURE_KEY_VAULT_SECRET_NAME")
    raw_kind = os.environ.get("VERGI_AZURE_CREDENTIAL_KIND")
    if raw_kind is None:
        credential_kind = "system_assigned_managed_identity"
    elif not raw_kind or raw_kind != raw_kind.strip():
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    else:
        credential_kind = raw_kind
    if credential_kind not in {
        "system_assigned_managed_identity",
        "user_assigned_managed_identity",
        "workload_identity",
    }:
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")

    managed_client_id = _optional_value("VERGI_AZURE_MANAGED_IDENTITY_CLIENT_ID")
    workload_tenant_id = _optional_value("VERGI_AZURE_WORKLOAD_TENANT_ID")
    workload_client_id = _optional_value("VERGI_AZURE_WORKLOAD_CLIENT_ID")
    workload_token_file = _optional_value("VERGI_AZURE_WORKLOAD_TOKEN_FILE")
    workload_values = (workload_tenant_id, workload_client_id, workload_token_file)
    if credential_kind == "system_assigned_managed_identity":
        if managed_client_id is not None or any(value is not None for value in workload_values):
            raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    elif credential_kind == "user_assigned_managed_identity":
        if managed_client_id is None or any(value is not None for value in workload_values):
            raise AzureCustodyConfigurationError("Azure custody configuration is invalid")
    elif managed_client_id is not None or any(value is None for value in workload_values):
        raise AzureCustodyConfigurationError("Azure custody configuration is invalid")

    return AzureCustodyConfig(
        vault_url=vault_url,
        secret_name=secret_name,
        credential_kind=credential_kind,
        managed_identity_client_id=managed_client_id,
        workload_tenant_id=workload_tenant_id,
        workload_client_id=workload_client_id,
        workload_token_file=workload_token_file,
    )


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise AzureCustodyDocumentError("Azure custody document is invalid")
        result[name] = value
    return result


def _reject_non_json_number(_value: str) -> None:
    raise AzureCustodyDocumentError("Azure custody document is invalid")


def _decode_base64(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise AzureCustodyDocumentError("Azure custody document is invalid") from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    return decoded


def _valid_key_id(value: Any) -> bool:
    return isinstance(value, str) and _KEY_ID_PATTERN.fullmatch(value) is not None


def _parse_snapshot(
    value: Any,
    *,
    secret_version_id: Any,
    generation: int,
    loaded_at: float,
) -> AzureCustodySnapshot:
    if not isinstance(value, str):
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise AzureCustodyDocumentError("Azure custody document is invalid") from None
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    try:
        document = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_fields,
            parse_constant=_reject_non_json_number,
        )
    except AzureCustodyDocumentError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError):
        raise AzureCustodyDocumentError("Azure custody document is invalid") from None
    if not isinstance(document, dict) or frozenset(document) != _DOCUMENT_FIELDS:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    version = document["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    current_key_id = document["current_key_id"]
    if not _valid_key_id(current_key_id):
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    encoded_keys = document["keys"]
    if not isinstance(encoded_keys, dict) or not 1 <= len(encoded_keys) <= _MAX_KEYS:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    keys: dict[str, bytes] = {}
    for key_id, encoded in encoded_keys.items():
        if not _valid_key_id(key_id):
            raise AzureCustodyDocumentError("Azure custody document is invalid")
        key = _decode_base64(encoded)
        if len(key) != 32:
            raise AzureCustodyDocumentError("Azure custody document is invalid")
        keys[key_id] = key
    if current_key_id not in keys:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    pepper = _decode_base64(document["server_pepper"])
    if not 32 <= len(pepper) <= _MAX_PEPPER_BYTES:
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    if not isinstance(secret_version_id, str) or not secret_version_id.strip():
        raise AzureCustodyDocumentError("Azure custody document is invalid")
    private_keys = dict(keys)
    return AzureCustodySnapshot(
        document_version=1,
        current_key_id=current_key_id,
        keys=MappingProxyType(private_keys),
        server_pepper=pepper,
        secret_version_id=secret_version_id,
        generation=generation,
        loaded_at_monotonic=loaded_at,
        expires_at_monotonic=loaded_at + _CACHE_TTL_SECONDS,
    )


@dataclass(frozen=True)
class _RetryBudget:
    deadline: float
    clock: Callable[[], float] = field(compare=False, repr=False)

    def remaining(self) -> float:
        return self.deadline - self.clock()

    def require_attempt(self) -> None:
        if self.remaining() < _ATTEMPT_UPPER_BOUND_SECONDS:
            raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")

    def validate_delay(self, delay: float) -> None:
        if delay < 0 or delay > _MAX_RETRY_DELAY_SECONDS:
            raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
        if delay + _ATTEMPT_UPPER_BOUND_SECONDS > self.remaining():
            raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")


_ACTIVE_RETRY_BUDGET: contextvars.ContextVar[_RetryBudget | None] = contextvars.ContextVar(
    "azure_custody_retry_budget", default=None,
)


def _make_retry_policy(retry_policy_type: type) -> Any:
    class AzureCustodyRetryPolicy(retry_policy_type):
        def is_retry(self, settings, response) -> bool:
            if settings.get("total", 0) <= 0:
                return False
            return response.http_response.status_code in _RETRYABLE_STATUS_CODES

        def send(self, request):
            budget = _ACTIVE_RETRY_BUDGET.get()
            if budget is None:
                raise AzureCustodyConfigurationError("Azure custody retry context is unavailable")
            budget.require_attempt()
            return super().send(request)

        def sleep(self, settings, transport, response=None) -> None:
            retry_after = self.get_retry_after(response) if response is not None else None
            delay = self.get_backoff_time(settings) if retry_after is None else retry_after
            budget = _ACTIVE_RETRY_BUDGET.get()
            if budget is None:
                raise AzureCustodyConfigurationError("Azure custody retry context is unavailable")
            budget.validate_delay(float(delay))
            if delay:
                transport.sleep(delay)

    return AzureCustodyRetryPolicy(
        retry_total=1,
        retry_connect=1,
        retry_read=1,
        retry_status=1,
        retry_backoff_factor=0.25,
        retry_backoff_max=0.25,
    )


def _create_secret_client(config: AzureCustodyConfig) -> Any:
    try:
        from azure.core.pipeline.policies import RetryPolicy
        from azure.identity import ManagedIdentityCredential, WorkloadIdentityCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        raise AzureCustodyConfigurationError("Azure custody SDK is unavailable") from None

    if config.credential_kind == "system_assigned_managed_identity":
        credential = ManagedIdentityCredential(retry_total=0)
    elif config.credential_kind == "user_assigned_managed_identity":
        credential = ManagedIdentityCredential(client_id=config.managed_identity_client_id, retry_total=0)
    else:
        credential = WorkloadIdentityCredential(
            tenant_id=config.workload_tenant_id,
            client_id=config.workload_client_id,
            token_file_path=config.workload_token_file,
            retry_total=0,
        )
    return SecretClient(
        vault_url=config.vault_url,
        credential=credential,
        retry_policy=_make_retry_policy(RetryPolicy),
    )


@dataclass(repr=False)
class _GenerationLease:
    generation: int
    start: float
    deadline: float
    future: concurrent.futures.Future[AzureCustodySnapshot] | None = None
    revoked: bool = False


class AzureCustodyManager:
    """Single-flight process-local manager with one atomic snapshot pointer."""

    def __init__(
        self,
        config: AzureCustodyConfig,
        *,
        client_factory: Callable[[AzureCustodyConfig], Any] = _create_secret_client,
        clock: Callable[[], float] = time.monotonic,
        executor: Any = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._clock = clock
        self._executor = executor or concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="azure-custody",
        )
        self._owns_executor = executor is None
        self._lock = threading.Lock()
        self._client: Any = None
        self._snapshot: AzureCustodySnapshot | None = None
        self._lease: _GenerationLease | None = None
        self._generation = 0

    @property
    def config_fingerprint(self) -> tuple[str, ...]:
        return self._config.fingerprint()

    def _begin(self) -> tuple[AzureCustodySnapshot | None, _GenerationLease | None]:
        with self._lock:
            now = self._clock()
            if self._snapshot is not None and now < self._snapshot.expires_at_monotonic:
                return self._snapshot, None
            if self._lease is not None and not self._lease.revoked:
                return None, self._lease
            self._generation += 1
            lease = _GenerationLease(self._generation, now, now + _OUTER_BUDGET_SECONDS)
            self._lease = lease
            lease.future = self._executor.submit(self._fetch_candidate, lease)
            return None, lease

    def _fetch_candidate(self, lease: _GenerationLease) -> AzureCustodySnapshot:
        budget = _RetryBudget(lease.deadline, self._clock)
        token = _ACTIVE_RETRY_BUDGET.set(budget)
        try:
            budget.require_attempt()
            if self._client is None:
                self._client = self._client_factory(self._config)
            remaining = budget.remaining()
            if remaining <= 0:
                raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
            secret = self._client.get_secret(
                self._config.secret_name,
                connection_timeout=_CONNECT_TIMEOUT_SECONDS,
                read_timeout=_READ_TIMEOUT_SECONDS,
                timeout=remaining,
            )
            loaded_at = self._clock()
            if loaded_at > lease.deadline:
                raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
            properties = getattr(secret, "properties", None)
            return _parse_snapshot(
                getattr(secret, "value", None),
                secret_version_id=getattr(properties, "version", None),
                generation=lease.generation,
                loaded_at=loaded_at,
            )
        except (AzureCustodyConfigurationError, AzureCustodyProviderError, AzureCustodyTransientError):
            raise
        except BaseException as exc:
            raise _classify_provider_exception(exc) from None
        finally:
            _ACTIVE_RETRY_BUDGET.reset(token)

    def _revoke(self, lease: _GenerationLease) -> None:
        with self._lock:
            if self._lease is lease:
                lease.revoked = True
                self._lease = None
                self._generation += 1

    def _finish_failure(self, lease: _GenerationLease) -> None:
        with self._lock:
            if self._lease is lease:
                self._lease = None

    def _publish(self, lease: _GenerationLease, candidate: AzureCustodySnapshot) -> AzureCustodySnapshot:
        with self._lock:
            if self._snapshot is candidate and self._snapshot.generation == lease.generation:
                return self._snapshot
            if (
                self._lease is not lease
                or lease.revoked
                or lease.generation != candidate.generation
                or self._clock() > lease.deadline
            ):
                raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
            self._snapshot = candidate
            self._lease = None
            return candidate

    def get_snapshot(self) -> AzureCustodySnapshot:
        snapshot, lease = self._begin()
        if snapshot is not None:
            return snapshot
        assert lease is not None and lease.future is not None
        try:
            candidate = lease.future.result(timeout=max(0.0, lease.deadline - self._clock()))
        except concurrent.futures.TimeoutError:
            self._revoke(lease)
            raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable") from None
        except BaseException:
            self._finish_failure(lease)
            raise
        return self._publish(lease, candidate)

    async def get_snapshot_async(self) -> AzureCustodySnapshot:
        snapshot, lease = self._begin()
        if snapshot is not None:
            return snapshot
        assert lease is not None and lease.future is not None
        wrapped = asyncio.wrap_future(lease.future)
        try:
            candidate = await asyncio.wait_for(
                asyncio.shield(wrapped), timeout=max(0.0, lease.deadline - self._clock()),
            )
        except asyncio.CancelledError:
            self._revoke(lease)
            raise
        except asyncio.TimeoutError:
            self._revoke(lease)
            raise AzureCustodyTransientError("Azure custody provider is temporarily unavailable") from None
        except BaseException:
            self._finish_failure(lease)
            raise
        return self._publish(lease, candidate)

    def get_key_provider(self) -> AzureSnapshotKeyProvider:
        return AzureSnapshotKeyProvider(self.get_snapshot())

    async def get_key_provider_async(self) -> AzureSnapshotKeyProvider:
        return AzureSnapshotKeyProvider(await self.get_snapshot_async())

    def get_server_pepper(self) -> bytes:
        return self.get_snapshot().server_pepper

    async def get_server_pepper_async(self) -> bytes:
        return (await self.get_snapshot_async()).server_pepper

    def _close_for_tests(self) -> None:
        with self._lock:
            if self._lease is not None:
                self._lease.revoked = True
            self._lease = None
            self._snapshot = None
            self._client = None
            self._generation += 1
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)


def _classify_provider_exception(exc: BaseException) -> Exception:
    status = getattr(exc, "status_code", None)
    if status in _RETRYABLE_STATUS_CODES:
        return AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
    if status is not None:
        return AzureCustodyProviderError("Azure custody provider is unavailable")
    if type(exc).__name__ in {
        "ServiceRequestError",
        "ServiceResponseError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
    }:
        return AzureCustodyTransientError("Azure custody provider is temporarily unavailable")
    return AzureCustodyProviderError("Azure custody provider is unavailable")


_MANAGER_LOCK = threading.Lock()
_MANAGER: AzureCustodyManager | None = None
_TEST_CLIENT_FACTORY: Callable[[AzureCustodyConfig], Any] | None = None
_TEST_CLOCK: Callable[[], float] | None = None
_TEST_EXECUTOR: Any = None


def get_azure_custody_manager() -> AzureCustodyManager:
    global _MANAGER
    config = _load_config()
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = AzureCustodyManager(
                config,
                client_factory=_TEST_CLIENT_FACTORY or _create_secret_client,
                clock=_TEST_CLOCK or time.monotonic,
                executor=_TEST_EXECUTOR,
            )
        elif _MANAGER.config_fingerprint != config.fingerprint():
            raise AzureCustodyConfigurationError("Azure custody configuration changed during process lifetime")
        return _MANAGER


def _reset_azure_custody_manager_for_tests(
    *,
    client_factory: Callable[[AzureCustodyConfig], Any] | None = None,
    clock: Callable[[], float] | None = None,
    executor: Any = None,
) -> None:
    global _MANAGER, _TEST_CLIENT_FACTORY, _TEST_CLOCK, _TEST_EXECUTOR
    with _MANAGER_LOCK:
        old_manager = _MANAGER
        _MANAGER = None
        _TEST_CLIENT_FACTORY = client_factory
        _TEST_CLOCK = clock
        _TEST_EXECUTOR = executor
    if old_manager is not None:
        old_manager._close_for_tests()
