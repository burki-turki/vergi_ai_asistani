# ============================================================
# VERGİ AI - LAWYER UI, ORTAK YARDIMCILAR (Row 18a)
# ============================================================

import hashlib
from pathlib import Path


class ApprovalUiError(Exception):
    """Row 18'e özgü hatalar için taban sınıf (approval modüllerinin
    KENDİ hata sınıflarının yerine GEÇMEZ - onları sarmalar/yeniden
    fırlatır)."""


class StaleViewError(ApprovalUiError):
    """Kullanıcı bir review ekranını gördükten SONRA hedef pending
    dosya değişmişse fırlatılır. Bu durumda ilgili approve
    fonksiyonu HİÇ ÇAĞRILMAZ (Prensip 9: fail-closed)."""


class PendingNotFoundError(ApprovalUiError):
    """Onaylanmak istenen pending dosya artık yok (örn. sayfa açıkken
    başka bir yerden approve edilmiş/silinmiş)."""


class UnknownCaseError(ApprovalUiError):
    """case_id, `paths.list_case_ids()`'in keşfettiği gerçek bir case
    diziniyle TAM eşleşmiyor (boş, traversal/separator biçimi veya
    gerçekten var olmayan bir ID dahil - targeted remediation,
    inceleme bulgusu: case_id daha önce bazı route'larda hiç
    doğrulanmadan Row 6-17 modüllerinin path birleştirmesine
    gidiyordu)."""


class UnsupportedApprovalFamilyError(ApprovalUiError):
    """Bu onay ailesi için (şu an: fact, timeline) case_id başına
    'hangi pending GÜNCEL/aktif olan' sorusunu deterministik olarak
    çözecek yetkili bir resolver Row 1-17'de YOKTUR (kod okunarak
    doğrulandı: fact_approval.py/timeline_approval.py yalnız KENDİSİNE
    doğrudan verilen bir pending_path üzerinde çalışır, case_id'den
    "güncel pending" üreten bir fonksiyon taşımaz). Row 18a bu boşluğu
    dosya adı/mtime/dizin sırasına göre SESSİZCE doldurmaz - bu aile
    UI'da onay düğmesi OLMADAN, yalnız bilgi amaçlı listelenir."""


class CsrfError(ApprovalUiError):
    """CSRF token eksik/geçersiz veya Origin/Referer aynı-origin
    kontrolünden geçemedi - onay fonksiyonu HİÇ ÇAĞRILMADAN
    reddedilir."""


class LiveViewInvalidError(ApprovalUiError):
    """Row 17'nin canlı görünümü (`build_case_view()`) kendi şeması
    veya semantik kontrolleriyle DOĞRULANAMADI - fail-closed: canlı
    görünüm ASLA doğrulanmadan render edilmez."""


def sha256_file(path):

    path = Path(path)

    if not path.exists():

        return None

    digest = hashlib.sha256()

    with open(path, "rb") as file:

        while True:

            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def find_latest_audit(reviews_dir, pattern="*.approval.json"):
    """
    CLAUDE.md §2 konvansiyonu: her artefaktın audit kaydı kendi
    `reviews/` alt dizininde `*.approval.json` olarak durur. Row 18
    bu dizin YAPISINI İCAT ETMEZ - yalnız zaten belgelenmiş
    konvansiyona göre EN SON yazılan dosyayı (mtime) bulur.
    """

    reviews_dir = Path(reviews_dir)

    if not reviews_dir.is_dir():

        return None

    candidates = sorted(
        reviews_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime,
    )

    return candidates[-1] if candidates else None


def summarize_json_value(value, max_items=20):
    """
    Herhangi bir onay modülünün pending/canonical içeriğini, o
    modüle ÖZGÜ bir alan-adı sözlüğü İCAT ETMEDEN genel biçimde
    özetler: skaler alanlar olduğu gibi, liste alanları 'N kayıt'
    olarak gösterilir (ham JSON ayrıca her zaman erişilebilir kalır).
    Bu, 12 farklı şemanın alan adlarını UI'da YANLIŞ yorumlama
    riskini ortadan kaldırır (Prensip 9).
    """

    if isinstance(value, dict):

        summary = {}

        for key, item in value.items():

            if isinstance(item, list):

                summary[key] = f"{len(item)} kayıt"

            elif isinstance(item, dict):

                summary[key] = "{...}"

            else:

                summary[key] = item

        return summary

    return value
