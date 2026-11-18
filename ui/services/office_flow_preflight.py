# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - F0 HAZIRLIK DENETİMİ
#
# Salt-okunur denetimler + TEMP/TMP yönlendirmesi. Her denetim KAPALI bir
# kod üretir; başarısızlık = DUR (akış F1'e geçmez).
#
#   - dış YZ paketi/anahtarı yok (anthropic/openai import edilemez;
#     ANTHROPIC_*/OPENAI_* ortam değişkeni yok)
#   - office-root: mutlak, var, dizin, repo DIŞI
#   - office-root ile vaka kökü AYNI birimde (st_dev); sistem sürücüsü değil
#     (geliştirme/test için açık `allow_system_drive` ile gevşetilir ve bu
#     ekranda UYARI olarak görünür)
#   - DSN loopback
#   - TEMP/TMP koşu dizinine yönlendirilir
#
# NOT: Şifrelemenin GERÇEKTEN var olduğunu bu modül KANITLAMAZ (kodda
# şifreleme probu yoktur); yalnız tutarlılığı ölçer. Cihaz ölçümleri T3'tür.
# ============================================================

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ui.services.office_flow_records import OfficeFlowError

FORBIDDEN_PACKAGES = ("anthropic", "openai")
FORBIDDEN_ENV_PREFIXES = ("ANTHROPIC_", "OPENAI_")
LOOPBACK_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})


@dataclass
class PreflightResult:
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def first_failure(self):
        return self.failed[0] if self.failed else None


def default_import_probe(name: str) -> bool:
    """True = paket import EDİLEBİLİR (yani YASAK paket mevcut)."""
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def check_external_ai_absent(*, import_probe=None, env=None) -> list:
    probe = import_probe or default_import_probe
    environment = os.environ if env is None else env
    failures = []
    for package in FORBIDDEN_PACKAGES:
        if probe(package):
            failures.append("DIS_YZ_PAKETI_VAR")
            break
    for key in environment:
        if any(str(key).upper().startswith(prefix) for prefix in FORBIDDEN_ENV_PREFIXES):
            failures.append("DIS_YZ_ORTAM_ANAHTARI_VAR")
            break
    return failures


_URI_HOST_RE = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?(\[[^\]]+\]|[^:/?#]*)")
_KV_HOST_RE = re.compile(r"(?:^|\s)host\s*=\s*('(?:[^'\\]|\\.)*'|[^\s]+)")


def dsn_host(dsn: str, env=None) -> str:
    """DSN'deki açık host; yoksa PGHOST; yoksa '' (yerel soket)."""
    environment = os.environ if env is None else env
    text = (dsn or "").strip()
    host = None
    match = _URI_HOST_RE.match(text)
    if match:
        host = match.group(1).strip("[]")
    else:
        kv = _KV_HOST_RE.search(text)
        if kv:
            host = kv.group(1).strip("'")
    if not host:
        host = environment.get("PGHOST", "")
    return host.strip().lower()


def check_dsn_loopback(dsn, env=None):
    host = dsn_host(dsn, env)
    if host in LOOPBACK_HOSTS or host.startswith("/"):
        return []
    return ["DSN_LOOPBACK_DEGIL"]


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child_real = Path(os.path.realpath(str(child)))
        parent_real = Path(os.path.realpath(str(parent)))
    except OSError:
        return True
    return child_real == parent_real or parent_real in child_real.parents


def check_office_root(office_root, *, repo_root) -> list:
    root = Path(office_root)
    if not root.is_absolute() or not root.is_dir():
        return ["OFFICE_ROOT_GECERSIZ"]
    if _is_inside(root, Path(repo_root)):
        return ["OFFICE_ROOT_GECERSIZ"]
    return []


def default_volume_probe(path) -> int:
    return os.stat(str(path)).st_dev


def default_drive_of(path) -> str:
    return os.path.splitdrive(os.path.realpath(str(path)))[0].upper()


def check_same_volume(office_root, case_root, *, volume_probe=None) -> list:
    probe = volume_probe or default_volume_probe
    try:
        if probe(office_root) != probe(case_root):
            return ["BIRIM_FARKLI"]
    except OSError:
        return ["BIRIM_FARKLI"]
    return []


def check_not_system_drive(office_root, *, system_drive=None, drive_of=None) -> list:
    system = (system_drive if system_drive is not None else os.environ.get("SystemDrive", "C:")).upper()
    drive = (drive_of or default_drive_of)(office_root)
    if drive and drive == system:
        return ["SISTEM_SURUCUSU"]
    return []


def run_preflight(
    *, office_root, case_root, repo_root, dsn=None, env=None, import_probe=None,
    volume_probe=None, allow_system_drive=False, system_drive=None, drive_of=None,
) -> PreflightResult:
    """Tüm denetimleri koşturur (ilk hatada durmaz; tüm kodlar toplanır)."""
    result = PreflightResult()
    checks = [
        ("dis_yz_yok", check_external_ai_absent(import_probe=import_probe, env=env)),
        ("office_root", check_office_root(office_root, repo_root=repo_root)),
        ("ayni_birim", check_same_volume(office_root, case_root, volume_probe=volume_probe)),
        ("dsn_loopback", check_dsn_loopback(
            dsn if dsn is not None else os.environ.get("VERGI_IAM_DATABASE_URL", ""), env,
        )),
    ]
    system_failures = check_not_system_drive(office_root, system_drive=system_drive, drive_of=drive_of)
    if system_failures and allow_system_drive:
        result.warnings.append("SISTEM_SURUCUSU_IZIN_VERILDI_GELISTIRME")
    else:
        checks.append(("sistem_surucusu_degil", system_failures))
    for name, failures in checks:
        if failures:
            result.failed.extend(failures)
        else:
            result.passed.append(name)
    return result


# ----------------------------------------------------------------
# TEMP/TMP yönlendirmesi
# ----------------------------------------------------------------

_TEMP_ENV_KEYS = ("TMP", "TEMP", "TMPDIR")


@dataclass
class TempRedirection:
    previous_tempdir: object
    previous_env: dict


def redirect_temp(tmp_dir) -> TempRedirection:
    """`tempfile` ve TMP/TEMP/TMPDIR'i koşu dizinine yönlendirir. Mevcut
    değerleri döndürür (geri almak için)."""
    target = str(tmp_dir)
    previous = TempRedirection(
        previous_tempdir=tempfile.tempdir,
        previous_env={key: os.environ.get(key) for key in _TEMP_ENV_KEYS},
    )
    for key in _TEMP_ENV_KEYS:
        os.environ[key] = target
    tempfile.tempdir = target
    return previous


def restore_temp(previous: TempRedirection) -> None:
    tempfile.tempdir = previous.previous_tempdir
    for key, value in previous.previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def verify_temp_redirected(tmp_dir) -> bool:
    return (
        os.path.realpath(tempfile.gettempdir()) == os.path.realpath(str(tmp_dir))
        and all(os.path.realpath(os.environ.get(key, "")) == os.path.realpath(str(tmp_dir))
                for key in _TEMP_ENV_KEYS)
    )


def raise_if_failed(result: PreflightResult) -> None:
    code = result.first_failure()
    if code is not None:
        raise OfficeFlowError(code)
