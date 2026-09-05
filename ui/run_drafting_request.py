# ============================================================
# VERGİ AI - ROW 18C, MANUEL CLI KÖPRÜSÜ
#
# python -m ui.run_drafting_request --case <case_id>
#     [--generate-pending [--with-agent [--allow-network]]]
#
# VARSAYILAN ÇALIŞTIRMA (bayrak yok) TAMAMEN SALT-OKUNURDUR:
#   - `data/cases/<case_id>/drafting/inputs/lawyer_input.json` (varsa)
#     yüklenir ve `ui.services.drafting_request`'in PAYLAŞILAN TAM
#     wrapper doğrulayıcısıyla (main.py'nin HTTP servisiyle BİREBİR
#     AYNI fonksiyon) doğrulanır;
#   - pending/canonical'ın KENDİ `lawyer_input_hash`'i ile
#     karşılaştırılıp salt-okunur bir durum raporu YAZDIRILIR;
#   - `build_drafting_engine_output`/`write_pending` HİÇ ÇAĞRILMAZ,
#     HİÇBİR dosya YAZILMAZ.
#
# `--generate-pending` VERİLMEDEN gerçek üretim (Drafting Engine/agent/
# network) tetiklenmesi MÜMKÜN DEĞİLDİR - bu, main.py'nin/
# ui.services.drafting_request'in kendisinin ASLA
# Drafting Engine/agent/network çağırmadığı Option A-prime sınırının
# (kullanıcı kararı) BİR PARÇASI olarak, bu köprünün KENDİ bayrak
# kapısıdır. `--with-agent`/`--allow-network`'ün `--generate-pending`
# OLMADAN veya birbirleriyle geçersiz kombinasyonlarda kullanılması
# HİÇBİR MUTASYON OLMADAN reddedilir.
#
# Bu dosya HİÇBİR HTTP route'u SUNMAZ ve `ui/main.py` bu modülü ASLA
# import ETMEZ (mimari sınır, kontrat madde 3 - "Actual generation is
# available only through the separately invoked manual CLI bridge").
#
# Bu turda (Row 18C uygulama turu) hiçbir gerçek --generate-pending
# veya network-etkin çalıştırma YAPILMAMIŞTIR - yalnız izole testler
# (`ui/tests/test_run_drafting_request_isolated.py`) sentetik/tempdir
# ortamlarda bayrak REDDİ/salt-okunur davranışı sınar.
# ============================================================

import argparse
import sys

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:

    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as svc_paths                       # noqa: E402
from ui.services.common import UnknownCaseError                  # noqa: E402
from ui.services import drafting_request as draftreq              # noqa: E402


def _print_wrapper_status(case_id):
    """Salt-okunur: mevcut wrapper'ı yükler, TAM paylaşılan
    doğrulayıcıyı çağırır, pending/canonical eşleşme durumunu
    yazdırır. HİÇBİR DOSYA YAZMAZ. Döner: (wrapper_or_None,
    is_valid_bool)."""

    current_path = draftreq.get_current_input_path(case_id)

    print(f"Kayıtlı avukat girdisi dosyası: {current_path}")

    if not current_path.exists():

        print("Durum: KAYITLI GİRDİ YOK (henüz hiç kaydedilmemiş).")

        return (None, False)

    try:

        wrapper = draftreq.load_current_wrapper(case_id)

        draftreq.validate_wrapper_schema_and_consistency(wrapper, case_id)

    except draftreq.DraftingRequestValidationError as error:

        print("Wrapper doğrulaması: FAIL")

        for message in error.errors:

            print(" -", message)

        return (None, False)

    except Exception as error:

        print(f"Wrapper okunamadı/geçersiz: {type(error).__name__}")

        return (None, False)

    print("Wrapper doğrulaması: PASS")
    print("saved_at:", wrapper.get("saved_at"))
    print("lawyer_input_hash:", wrapper.get("lawyer_input_hash"))

    li = wrapper["lawyer_input"]

    print("draft_intent_type:", li.get("draft_intent_type"))
    print("appeal_level:", li.get("appeal_level"))

    selected = li.get("selected_issue_ids")

    if selected is None:

        print("selected_issue_ids: (sağlanmadı)")

    else:

        print(f"selected_issue_ids: {len(selected)} adet")

    status = draftreq.get_pending_and_canonical_status(case_id, wrapper.get("lawyer_input_hash"))

    for label, key in (("pending", "pending"), ("canonical", "canonical")):

        entry = status[key]

        if not entry["exists"]:

            print(f"{label}: yok")

        elif entry["unreadable"]:

            print(f"{label}: mevcut ama okunamadı/geçersiz")

        else:

            print(f"{label}: mevcut, lawyer_input_hash eşleşiyor mu = {entry['matches_saved']}")

    return (wrapper, True)


def main(argv=None):

    parser = argparse.ArgumentParser(
        description=(
            "Row 18C - Yapılandırılmış avukat girdisi CLI köprüsü. "
            "VARSAYILAN çalıştırma TAMAMEN SALT-OKUNURDUR."
        ),
    )

    parser.add_argument("--case", dest="case_id", required=True, help="case_id (allowlisted).")
    parser.add_argument("--generate-pending", action="store_true", dest="generate_pending")
    parser.add_argument("--with-agent", action="store_true", dest="with_agent")
    parser.add_argument("--allow-network", action="store_true", dest="allow_network")

    args = parser.parse_args(argv)

    # Bayrak kombinasyonu reddi - HİÇBİR ŞEY YAPILMADAN, case_id
    # doğrulamasından/wrapper yüklemesinden BİLE ÖNCE (kontrat madde 9).
    if args.with_agent and not args.generate_pending:

        print("HATA: --with-agent yalnız --generate-pending İLE BİRLİKTE kullanılabilir.")

        return 2

    if args.allow_network and not args.generate_pending:

        print("HATA: --allow-network yalnız --generate-pending İLE BİRLİKTE kullanılabilir.")

        return 2

    if args.allow_network and not args.with_agent:

        print("HATA: --allow-network yalnız --with-agent İLE BİRLİKTE kullanılabilir.")

        return 2

    try:

        case_id = svc_paths.resolve_case_id(args.case_id)

    except UnknownCaseError:

        print(f"HATA: bilinmeyen case_id: {args.case_id!r}")

        return 2

    print("======================================")
    print(" VERGİ AI - ROW 18C CLI KÖPRÜSÜ")
    print("======================================")
    print("case_id:", case_id)
    print()

    wrapper, is_valid = _print_wrapper_status(case_id)

    if not args.generate_pending:

        print()
        print("Bu çalıştırma SALT-OKUNURDUR - build_drafting_engine_output/write_pending")
        print("HİÇ ÇAĞRILMADI, hiçbir dosya YAZILMADI.")
        print("Gerçek üretim için: --generate-pending (+ --with-agent [+ --allow-network]) gereklidir.")

        return 0

    # BURADAN SONRASI YALNIZ --generate-pending VERİLDİĞİNDE çalışır.
    if not is_valid or wrapper is None:

        print()
        print("HATA: --generate-pending için geçerli, kaydedilmiş bir wrapper GEREKLİDİR.")

        return 2

    # Row 15'in GERÇEK, PUBLIC iki fonksiyonu - main()'in kendisinin
    # çağırdığı AYNI sırayla, HİÇBİR DEĞİŞİKLİK OLMADAN (kontrat madde
    # 9 - bu köprü Row 15'in tek bir satırını bile YENİDEN YAZMAZ).
    from drafting_engine import build_drafting_engine_output, write_pending

    print()
    print("--generate-pending: Drafting Engine ÇALIŞTIRILIYOR ...")
    print(f"--with-agent={args.with_agent} --allow-network={args.allow_network}")

    result = build_drafting_engine_output(
        case_id, lawyer_input=wrapper["lawyer_input"],
        use_agent=args.with_agent, network_allowed=args.allow_network,
    )

    pending_path, validation, _history = write_pending(
        case_id, result["analysis"], result["issue_count"],
    )

    print()
    print("Pending:", pending_path)
    print("Draft coverage:", len(result["analysis"]["draft_coverage"]))
    print("Sections:", result["section_count"])
    print("Suggestions:", result["suggestion_count"])
    print("Validator:", "PASS" if validation["valid"] else "FAIL")

    return 0 if validation["valid"] else 1


if __name__ == "__main__":

    sys.exit(main())
