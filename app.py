# ============================================================
# PILOT READINESS ADIM 4b - KAPATILMIŞ EGRESS GİRİŞ NOKTASI.
#
# Bu dosya eskiden `input()` ile avukatın SERBEST METNİNİ alan ve onu
# `src.rag.answer_question(question, history)`'a geçiren etkileşimli bir
# sohbet döngüsüydü (`run_chat`/`print_header`/`print_sources`). O gövde
# bu turda BİLİNÇLİ olarak SİLİNDİ (kullanıcı kararı K3); dosya yalnız
# reddetmek için duruyor.
#
# Neden kapatıldı (ölçülü, abartısız):
#   * Repo'daki TEK, hiçbir kapısı olmayan serbest-metin girişiydi -
#     ne kimlik doğrulama, ne yetkilendirme, ne maskeleme, ne audit,
#     ne de bir `--allow-network` rızası taşıyordu.
#   * Eski `from src.rag import answer_question` MODÜL BAŞI importu,
#     `src/rag.py`'nin kendi modül-seviyesi `client = Anthropic()`
#     satırını daha `app.py` hiçbir şey yapmadan ÖNCE çalıştırıyordu.
#   * Bugün bu yol LATENT'tir, canlı bir egress DEĞİLDİR: `rewrite_query`
#     ilk turda boş `history` ile modeli çağırmadan döner ve retrieval
#     `RagBundleNotPinnedError` ile fail-closed olur, bu yüzden `history`
#     hiç dolmaz. `rag.py`'ye pinlenmiş bir bundle bağlandığı an (RAG
#     Slice 2) sessizce canlıya dönerdi - kapatma bu yüzden derinlemesine
#     savunmadır, geçmişe dönük bir egress iddiası DEĞİLDİR.
#
# Sözleşme (repo emsali: `src/ingest.py`, `src/issue_spotting_engine.py`):
# MODÜL SEVİYESİNDE HİÇBİR IMPORT YOKTUR - `sys` bile `main()` içinde
# lazy import edilir - bu yüzden `src.rag` (ve dolayısıyla `anthropic`)
# bu dosya çalıştırıldığında ASLA import edilmez. Ret, sabit bir mesajı
# stderr'e basar ve sarmalanmamış bir `SystemExit(2)` ile gerçek OS çıkış
# kodu 2 üretir; stdout'a hiçbir şey yazılmaz ve hiçbir zaman `input()`
# okunmaz.
#
# DÜRÜST SINIR: bu bir erişim kapatmasıdır, bir egress KANITI değildir.
# `src/rag.py` bu turda DEĞİŞTİRİLMEDİ (kullanıcı kararı K5) ve hâlâ
# modül seviyesinde bir istemci kurar; onu import eden GELECEKTEKİ
# herhangi bir kod yine dış modele ulaşabilir.
# ============================================================

REFUSAL_MESSAGE = (
    "HATA: Bu etkileşimli sohbet giriş noktası artık DEVRE DIŞIDIR "
    "(Pilot Readiness Adım 4b).\n"
    "Avukatın serbest metnini hiçbir maskeleme/yetkilendirme/audit katmanı olmadan "
    "dış bir LLM'e gönderebilen tek kapısız yol buydu.\n"
    "Denetlenen üretim yolları için: python -m ui.cli_mutate --help"
)


def main():
    import sys

    print(REFUSAL_MESSAGE, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
