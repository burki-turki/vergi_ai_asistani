# ============================================================
# VERGİ AI - LAWYER UI, GÜVENLİK YARDIMCILARI (targeted remediation)
#
# Bu modüldeki HER fonksiyon KASITLI olarak framework-bağımsızdır -
# hiçbiri `Request`/`Response` nesnesi almaz, yalnız ilkel değerler
# (str/None) alır ve ilkel değer döner. Bu, main.py'nin FastAPI'ye
# ihtiyaç duymadan, bu turda GERÇEKTEN ÇALIŞTIRILABİLEN saf-Python
# testlerle doğrulanabilmesini sağlar (bkz. inceleme talimatı §11).
# main.py yalnız `request.client.host`/`request.headers.get(...)`
# gibi ham değerleri buradaki fonksiyonlara AKTARIR.
# ============================================================

import hashlib
import hmac
import secrets


# ============================================================
# CSRF TOKEN
#
# Bu uygulamada oturum/cookie YOKTUR (tek kullanıcılı, yerel araç) -
# bu yüzden klasik session-bağlı CSRF token yerine, HER review
# ekranına özgü bir HMAC token üretilir: token, o ekranın tam olarak
# HANGİ kaydı (case_id + row/aile anahtarı + expected_hash) onaylamak
# üzere gösterildiğine BAĞLIDIR. Sunucu-taraflı gizli anahtar yalnız
# process ömrü boyunca bellekte tutulur (diske/repoya YAZILMAZ,
# yeniden başlatmada yeniden üretilir) - bu, "expected_hash tek
# başına CSRF token yerine geçmez" ilkesini karşılar: token, hash'i
# BİLMEYEN bir üçüncü tarafın asla üretemeyeceği ayrı bir HMAC'tir.
# ============================================================

def new_csrf_secret():
    """Process ömrü boyunca sabit, öngörülemez bir gizli anahtar
    üretir. main.py bunu import anında BİR KEZ çağırıp modül
    değişkeninde tutar - her istek için yeniden üretilmez."""

    return secrets.token_bytes(32)


def make_csrf_token(secret, *parts):
    """`parts` - o mutasyonu benzersiz şekilde tanımlayan string'ler
    (case_id, aile/row anahtarı, expected_hash gibi). Aynı `parts` +
    aynı `secret` HER ZAMAN aynı token'ı üretir (bu yüzden review
    sayfası render edilirken VE confirm POST'unda doğrulanırken
    ayrıca saklanması gerekmez - deterministik olarak yeniden
    hesaplanır)."""

    message = "\x1f".join(str(part) for part in parts).encode("utf-8")

    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_csrf_token(secret, token, *parts):
    """Sabit-zamanlı (`hmac.compare_digest`) karşılaştırma - zamanlama
    yan-kanalıyla token tahmini riskini ortadan kaldırır."""

    if not token or not isinstance(token, str):

        return False

    expected = make_csrf_token(secret, *parts)

    return hmac.compare_digest(token, expected)


# ============================================================
# AYNI-ORİJİN (Origin/Referer) KONTROLÜ
#
# Talimat: "Same-origin Origin/Referer validation where present."
# Header YOKSA (bazı eski istemciler POST'ta Origin göndermez)
# reddetmiyoruz - CSRF token zaten zorunlu birincil savunma; bu
# yalnız EK bir katmandır. Header VARSA ve host uyuşmuyorsa REDDEDER.
# ============================================================

def _extract_host(header_value):

    if not header_value:

        return None

    # "https://127.0.0.1:8000" -> "127.0.0.1:8000" ; "http://x/path" -> "x"
    without_scheme = header_value.split("://", 1)[-1]

    return without_scheme.split("/", 1)[0]


def is_same_origin(origin_header, referer_header, host_header):

    if origin_header:

        return _extract_host(origin_header) == host_header

    if referer_header:

        return _extract_host(referer_header) == host_header

    return True


# ============================================================
# LOOPBACK-ONLY ZORUNLULUĞU
#
# Talimat: "Add request-level protection that rejects non-loopback
# clients/hosts even if a user manually starts uvicorn on 0.0.0.0."
# Bu kontrol `host="127.0.0.1"` varsayılanına DEĞİL, GERÇEK bağlanan
# istemcinin IP'sine bakar - dolayısıyla sunucu yanlışlıkla
# `--host 0.0.0.0` ile başlatılsa bile LAN'dan gelen istekler
# reddedilir.
# ============================================================

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_loopback_host(client_host):

    return client_host in LOOPBACK_HOSTS
