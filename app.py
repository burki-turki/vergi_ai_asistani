from src.rag import answer_question


# ==========================================
# BAŞLIK
# ==========================================

def print_header():

    print()
    print("=" * 60)
    print("           VERGİ MEVZUATI AI ASİSTANI")
    print("=" * 60)

    print(
        "\nMevzuat kaynaklarına dayalı sorularınızı yazabilirsiniz."
    )

    print(
        "Konuşma geçmişi bu oturum boyunca hatırlanır."
    )

    print(
        "Çıkmak için: çık / exit / quit"
    )


# ==========================================
# KAYNAKLAR
# ==========================================

def print_sources(sources):

    if not sources:
        return


    print(
        "\n--- KAYNAKLAR ---"
    )


    for i, source in enumerate(
        sources,
        start=1
    ):

        print(
            f"{i}. "
            f"{source['source']} "
            f"| Sayfa {source['page']} "
            f"| Chunk {source['chunk']} "
            f"| Skor {source['score']:.4f}"
        )


# ==========================================
# CHAT
# ==========================================

def run_chat():

    print_header()


    history = []


    while True:

        question = input(
            "\nSen: "
        ).strip()


        if not question:
            continue


        if question.lower() in [
            "çık",
            "exit",
            "quit"
        ]:

            print(
                "\nVergi AI: Görüşürüz."
            )

            break


        try:

            result = answer_question(
                question,
                history
            )


            print(
                "\nVergi AI:\n"
            )

            print(
                result["answer"]
            )


            print_sources(
                result["sources"]
            )


            # ==================================
            # HISTORY'YE EKLE
            # ==================================

            history.append(
                {
                    "role": "user",
                    "content": question
                }
            )


            history.append(
                {
                    "role": "assistant",
                    "content": result["answer"]
                }
            )


            print(
                f"\n[Konuşma hafızası: "
                f"{len(history)} mesaj]"
            )


        except Exception as error:

            print(
                "\nBir hata oluştu:"
            )

            print(
                error
            )


# ==========================================
# PROGRAM
# ==========================================

if __name__ == "__main__":

    run_chat()