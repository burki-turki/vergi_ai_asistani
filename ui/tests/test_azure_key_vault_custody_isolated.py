"""Networkless isolated tests for Row 19D Slice 2 Azure custody."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

opened_env_files: list[str] = []


def _audit(event, args):
    if event == "open" and args:
        try:
            path = os.fspath(args[0])
        except TypeError:
            return
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if Path(path).name == ".env":
            opened_env_files.append(path)


sys.addaudithook(_audit)

from ui.services import azure_key_vault_custody as az
from ui.services import key_custody as kc

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect(exc_type, function, label):
    try:
        function()
    except exc_type:
        check(label, True)
    except BaseException as error:
        check(label, False, f"{type(error).__name__}: {error}")
    else:
        check(label, False, "no exception")


def encoded(byte: bytes, length: int) -> str:
    return base64.b64encode(byte * length).decode("ascii")


def document(key_id="azure-a", key_byte=b"K", pepper_byte=b"P"):
    return {
        "version": 1,
        "current_key_id": key_id,
        "keys": {key_id: encoded(key_byte, 32)},
        "server_pepper": encoded(pepper_byte, 32),
    }


def document_text(**kwargs) -> str:
    return json.dumps(document(**kwargs), separators=(",", ":"))


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Secret:
    def __init__(self, value, version="vault-version-1"):
        self.value = value
        self.properties = types.SimpleNamespace(version=version)


class ScriptedClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get_secret(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ManualExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, function, *args):
        future = concurrent.futures.Future()
        self.submissions.append((future, function, args))
        return future

    def run(self, index=0):
        future, function, args = self.submissions[index]
        try:
            future.set_result(function(*args))
        except BaseException as error:
            future.set_exception(error)

    def shutdown(self, **_kwargs):
        return None


config = az.AzureCustodyConfig(
    vault_url="https://unit.vault.azure.net",
    secret_name="custody",
    credential_kind="system_assigned_managed_identity",
)

# Strict parser, immutable mapping, and non-secret metadata separation.
snapshot = az._parse_snapshot(
    document_text(), secret_version_id="vault-version-1", generation=7, loaded_at=10.0,
)
check("valid parser produces frozen snapshot", snapshot.current_key_id == "azure-a")
check("secret version is separate from application key id", snapshot.secret_version_id == "vault-version-1" and snapshot.current_key_id != snapshot.secret_version_id)
check("snapshot TTL is exactly 60 monotonic seconds", snapshot.expires_at_monotonic == 70.0)
def mutate_snapshot_mapping():
    snapshot.keys["x"] = b"x"


expect(TypeError, mutate_snapshot_mapping, "snapshot mapping is immutable")
check("snapshot repr redacts secret bytes", "server_pepper" not in repr(snapshot) and encoded(b"P", 32) not in repr(snapshot))

bad_documents = [
    ("duplicate root", '{"version":1,"version":1,"current_key_id":"a","keys":{"a":"' + encoded(b"K", 32) + '"},"server_pepper":"' + encoded(b"P", 32) + '"}'),
    ("duplicate key", '{"version":1,"current_key_id":"a","keys":{"a":"' + encoded(b"K", 32) + '","a":"' + encoded(b"K", 32) + '"},"server_pepper":"' + encoded(b"P", 32) + '"}'),
    ("non-finite", '{"version":NaN,"current_key_id":"a","keys":{},"server_pepper":"AA=="}'),
]
for label, raw in bad_documents:
    expect(
        az.AzureCustodyDocumentError,
        lambda value=raw: az._parse_snapshot(value, secret_version_id="v", generation=1, loaded_at=0.0),
        label + " rejected",
    )

for label, mutate in [
    ("missing field", lambda d: d.pop("version")),
    ("unknown field", lambda d: d.update(extra=True)),
    ("bool version", lambda d: d.update(version=True)),
    ("empty keys", lambda d: d.update(keys={})),
    ("current key absent", lambda d: d.update(current_key_id="other")),
    ("short AES key", lambda d: d["keys"].update({"azure-a": encoded(b"K", 31)})),
    ("short pepper", lambda d: d.update(server_pepper=encoded(b"P", 31))),
    ("long pepper", lambda d: d.update(server_pepper=encoded(b"P", 1025))),
]:
    item = document()
    mutate(item)
    expect(
        az.AzureCustodyDocumentError,
        lambda value=json.dumps(item): az._parse_snapshot(value, secret_version_id="v", generation=1, loaded_at=0.0),
        label + " rejected",
    )

many = document()
many["keys"] = {f"k-{index}": encoded(b"K", 32) for index in range(65)}
many["current_key_id"] = "k-0"
expect(
    az.AzureCustodyDocumentError,
    lambda: az._parse_snapshot(json.dumps(many), secret_version_id="v", generation=1, loaded_at=0.0),
    "more than 64 keys rejected",
)
expect(
    az.AzureCustodyDocumentError,
    lambda: az._parse_snapshot("x" * 16_385, secret_version_id="v", generation=1, loaded_at=0.0),
    "document over 16384 UTF-8 bytes rejected",
)
expect(
    az.AzureCustodyDocumentError,
    lambda: az._parse_snapshot(document_text(), secret_version_id="", generation=1, loaded_at=0.0),
    "empty Azure version rejected",
)

# One process-local manager, one fetch, one immutable snapshot for both accessors.
clock = FakeClock()
client = ScriptedClient([
    Secret(document_text(), "vault-v1"),
    Secret(document_text(key_id="azure-b", key_byte=b"B", pepper_byte=b"Q"), "vault-v2"),
])
manager = az.AzureCustodyManager(config, client_factory=lambda _config: client, clock=clock)
provider = manager.get_key_provider()
pepper = manager.get_server_pepper()
check("key and pepper share exact snapshot identity", provider._snapshot is manager.get_snapshot())
check("provider and pepper come from one coherent generation", provider.current_key_id() == "azure-a" and pepper == b"P" * 32)
check("second accessor performs no second fetch", len(client.calls) == 1)
args, kwargs = client.calls[0]
check("get_secret uses exact name with no version argument", args == ("custody",))
check(
    "transport timeouts and outer remainder are explicit",
    kwargs["connection_timeout"] == 1.0 and kwargs["read_timeout"] == 1.0 and kwargs["timeout"] == 5.0,
)
clock.advance(59.999)
check("valid TTL reuses same object", manager.get_snapshot() is provider._snapshot and len(client.calls) == 1)
clock.advance(0.001)
rotated = manager.get_snapshot()
check("expiry refresh publishes one whole new generation", rotated.current_key_id == "azure-b" and rotated.server_pepper == b"Q" * 32 and rotated.secret_version_id == "vault-v2")
check("rotation cannot create torn key and pepper", rotated.keys["azure-b"] == b"B" * 32 and len(client.calls) == 2)

# Validation-before-publish and no stale extension.
bad_client = ScriptedClient([Secret("{", "bad"), Secret(document_text(), "good")])
bad_manager = az.AzureCustodyManager(config, client_factory=lambda _config: bad_client, clock=FakeClock())
expect(az.AzureCustodyDocumentError, bad_manager.get_snapshot, "malformed candidate fails closed")
check("malformed candidate is never published", bad_manager._snapshot is None)
check("next generation can publish only a fully valid candidate", bad_manager.get_snapshot().secret_version_id == "good")

# Deterministic single-flight and cancellation with a manual executor.
async def async_manager_checks():
    single_clock = FakeClock()
    single_client = ScriptedClient([Secret(document_text(), "single")])
    executor = ManualExecutor()
    single_manager = az.AzureCustodyManager(
        config, client_factory=lambda _config: single_client, clock=single_clock, executor=executor,
    )
    first = asyncio.create_task(single_manager.get_snapshot_async())
    second = asyncio.create_task(single_manager.get_snapshot_async())
    await asyncio.sleep(0)
    check("concurrent misses submit exactly one fetch", len(executor.submissions) == 1)
    executor.run()
    one, two = await asyncio.gather(first, second)
    check("single-flight waiters receive the same snapshot identity", one is two and len(single_client.calls) == 1)

    cancel_client = ScriptedClient([Secret(document_text(), "late")])
    cancel_executor = ManualExecutor()
    cancel_manager = az.AzureCustodyManager(
        config, client_factory=lambda _config: cancel_client, clock=FakeClock(), executor=cancel_executor,
    )
    task = asyncio.create_task(cancel_manager.get_snapshot_async())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        check("async cancellation propagates", True)
    else:
        check("async cancellation propagates", False)
    cancel_executor.run()
    await asyncio.sleep(0)
    check("revoked generation cannot publish a late validated result", cancel_manager._snapshot is None)

asyncio.run(async_manager_checks())

# Expired lease cannot publish even when a fully validated worker result arrives.
expiry_clock = FakeClock()
expiry_executor = ManualExecutor()
expiry_client = ScriptedClient([Secret(document_text(), "late-expiry")])
expiry_manager = az.AzureCustodyManager(
    config, client_factory=lambda _config: expiry_client, clock=expiry_clock, executor=expiry_executor,
)
_cached, lease = expiry_manager._begin()
expiry_executor.run()
candidate = lease.future.result()
expiry_clock.advance(5.001)
expect(az.AzureCustodyTransientError, lambda: expiry_manager._publish(lease, candidate), "expired generation publish is rejected")
check("expired generation leaves cache empty", expiry_manager._snapshot is None)

# Retry arithmetic, exact status matrix, Retry-After cap, and one SDK layer.
check(
    "retry arithmetic is exact",
    2 * (az._CONNECT_TIMEOUT_SECONDS + az._READ_TIMEOUT_SECONDS) + az._MAX_RETRY_DELAY_SECONDS
    == 4.25 <= az._OUTER_BUDGET_SECONDS,
)


class FakeRetryPolicy:
    def __init__(self, **kwargs):
        self.options = kwargs

    def get_retry_after(self, response):
        return response.retry_after

    def get_backoff_time(self, settings):
        return settings.get("backoff", 0.0)

    def send(self, request):
        return request


policy = az._make_retry_policy(FakeRetryPolicy)
check(
    "SDK retry layer has exact counts and backoff",
    policy.options == {
        "retry_total": 1,
        "retry_connect": 1,
        "retry_read": 1,
        "retry_status": 1,
        "retry_backoff_factor": 0.25,
        "retry_backoff_max": 0.25,
    },
)
for status in [408, 429, 500, 502, 503, 504]:
    response = types.SimpleNamespace(http_response=types.SimpleNamespace(status_code=status))
    check(f"status {status} is retryable", policy.is_retry({"total": 1}, response))
for status in [400, 401, 403, 404, 409, 501, 505, 599]:
    response = types.SimpleNamespace(http_response=types.SimpleNamespace(status_code=status))
    check(f"status {status} is not retryable", not policy.is_retry({"total": 1}, response))

retry_clock = FakeClock()
budget = az._RetryBudget(retry_clock() + 5.0, retry_clock)
token = az._ACTIVE_RETRY_BUDGET.set(budget)
try:
    slept = []
    transport = types.SimpleNamespace(sleep=lambda delay: slept.append(delay))
    response = types.SimpleNamespace(retry_after=0.25)
    policy.sleep({}, transport, response)
    check("Retry-After at cap is honored once", slept == [0.25])
    response.retry_after = 0.251
    expect(az.AzureCustodyTransientError, lambda: policy.sleep({}, transport, response), "Retry-After above cap fails closed")
    retry_clock.advance(3.0)
    response.retry_after = 0.1
    expect(az.AzureCustodyTransientError, lambda: policy.sleep({}, transport, response), "retry cannot consume reserved next-attempt budget")
finally:
    az._ACTIVE_RETRY_BUDGET.reset(token)

class StatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


for status in [408, 429, 500, 502, 503, 504]:
    check(f"exhausted status {status} classifies 503", isinstance(az._classify_provider_exception(StatusError(status)), az.AzureCustodyTransientError))
for status in [400, 401, 403, 404, 409, 501, 505]:
    check(f"status {status} classifies permanent 500", isinstance(az._classify_provider_exception(StatusError(status)), az.AzureCustodyProviderError))

# Exact env config and process-local singleton identity.
azure_names = [
    "VERGI_AZURE_KEY_VAULT_URL",
    "VERGI_AZURE_KEY_VAULT_SECRET_NAME",
    "VERGI_AZURE_CREDENTIAL_KIND",
    "VERGI_AZURE_MANAGED_IDENTITY_CLIENT_ID",
    "VERGI_AZURE_WORKLOAD_TENANT_ID",
    "VERGI_AZURE_WORKLOAD_CLIENT_ID",
    "VERGI_AZURE_WORKLOAD_TOKEN_FILE",
    "VERGI_KEY_PROVIDER_KIND",
]
saved_env = {name: os.environ.get(name) for name in azure_names}
try:
    for name in azure_names:
        os.environ.pop(name, None)
    os.environ["VERGI_AZURE_KEY_VAULT_URL"] = "https://unit.vault.azure.net"
    os.environ["VERGI_AZURE_KEY_VAULT_SECRET_NAME"] = "custody"
    os.environ["VERGI_KEY_PROVIDER_KIND"] = "azure_key_vault_secret"
    global_client = ScriptedClient([Secret(document_text(), "global-v1")])
    az._reset_azure_custody_manager_for_tests(client_factory=lambda _config: global_client, clock=FakeClock())
    first_manager = az.get_azure_custody_manager()
    configured_provider = kc.get_configured_key_provider()
    configured_pepper = kc.get_configured_server_pepper()
    check("configured accessors use one process-local manager", az.get_azure_custody_manager() is first_manager)
    check("configured accessors share snapshot and version identity", configured_provider._snapshot is first_manager._snapshot and configured_provider._snapshot.secret_version_id == "global-v1")
    check("configured pepper uses the same fetched generation", configured_pepper == first_manager._snapshot.server_pepper and len(global_client.calls) == 1)
    os.environ["VERGI_AZURE_KEY_VAULT_SECRET_NAME"] = "changed"
    expect(az.AzureCustodyConfigurationError, az.get_azure_custody_manager, "config fingerprint change fails closed")
finally:
    az._reset_azure_custody_manager_for_tests()
    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

# Credential construction is explicit and lazy. Fake modules prove class choice without installing SDK.
records = []
class FakeManagedIdentityCredential:
    def __init__(self, **kwargs):
        records.append(("managed", kwargs))

class FakeWorkloadIdentityCredential:
    def __init__(self, **kwargs):
        records.append(("workload", kwargs))

class FakeSdkRetryPolicy(FakeRetryPolicy):
    pass

class FakeSecretClient:
    def __init__(self, **kwargs):
        records.append(("client", kwargs))

module_names = [
    "azure", "azure.core", "azure.core.pipeline", "azure.core.pipeline.policies",
    "azure.identity", "azure.keyvault", "azure.keyvault.secrets",
]
saved_modules = {name: sys.modules.get(name) for name in module_names}
try:
    for name in module_names:
        sys.modules[name] = types.ModuleType(name)
    sys.modules["azure.core.pipeline.policies"].RetryPolicy = FakeSdkRetryPolicy
    sys.modules["azure.identity"].ManagedIdentityCredential = FakeManagedIdentityCredential
    sys.modules["azure.identity"].WorkloadIdentityCredential = FakeWorkloadIdentityCredential
    sys.modules["azure.keyvault.secrets"].SecretClient = FakeSecretClient

    records.clear()
    az._create_secret_client(config)
    check("unset/default kind constructs system-assigned ManagedIdentityCredential", records[0] == ("managed", {"retry_total": 0}))

    records.clear()
    az._create_secret_client(az.AzureCustodyConfig(
        "https://unit.vault.azure.net", "custody", "user_assigned_managed_identity",
        managed_identity_client_id="client-id",
    ))
    check("user-assigned MI requires and passes explicit client id", records[0] == ("managed", {"client_id": "client-id", "retry_total": 0}))

    records.clear()
    az._create_secret_client(az.AzureCustodyConfig(
        "https://unit.vault.azure.net", "custody", "workload_identity",
        workload_tenant_id="tenant", workload_client_id="client", workload_token_file="token-file",
    ))
    check(
        "workload identity passes exact tenant/client/token-file",
        records[0] == ("workload", {
            "tenant_id": "tenant", "client_id": "client", "token_file_path": "token-file", "retry_total": 0,
        }),
    )
    check("SecretClient receives one custom SDK retry policy", records[1][0] == "client" and isinstance(records[1][1]["retry_policy"], FakeSdkRetryPolicy))
finally:
    for name, value in saved_modules.items():
        if value is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = value

check("test reset seam returns no custody material", az._reset_azure_custody_manager_for_tests() is None)
check("no .env file is opened", opened_env_files == [], repr(opened_env_files))

print(f"--- test_azure_key_vault_custody_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
