def generate_ranking_prompt(
    products_data: list[dict],
    top_n: int,
    listing_type: str,
    focus_features: list[str] | None,
    category_hint: str | None
) -> str:
    """
    Prompt dla artykułu rankingowego:
    - naturalny tytuł H1 (Najlepsze {kategoria} – ranking Top N [2025])
    - wprowadzenie (akapit/akapit+)
    - H2 = nazwy produktów (bez emoji), min. 2 akapity na produkt
    - bez wzmianek o braku ocen
    - zakończenie H2 z naturalną etykietą (nie „Podsumowanie”)
    - reguły SEO/PL wg briefu
    """
    rok = 2025  # świeżość – rok w tytule i narracji
    kategoria = (category_hint or listing_type).strip().lower()
    focus_txt = ", ".join(focus_features) if focus_features else "kluczowe cechy, parametry techniczne, materiały, wymiary i zalety użytkowe"

    # Naturalny H1, np. „Najlepsze poganiacze elektryczne – ranking Top 3 [2025]”
    tytul_h1 = f"Najlepsze {kategoria} – ranking Top {top_n} [{rok}]"

    # Zbierz tylko nazwy produktów (H2 będą dokładnie tymi nazwami)
    nazwy_produktow = [p.get("nazwa", "").strip() for p in products_data if p.get("nazwa")]

    # Sekcja końcowa – przykłady nagłówków H2, z których model ma wybrać
    final_h2_options = [
        f"Który {kategoria} wybrać w {rok}?",
        "Końcowe wnioski",
        f"Ranking {kategoria} – podsumowanie"
    ]

    prompt = f"""
++role++
You are a professional Polish-language content writer specializing in SEO articles and thematic long-form content. You write cohesive, research-based chapters in Polish that are grammatically correct, stylistically fluid, and engaging.

++task++
Write a detailed, cohesive chapter for an article based on provided research and context. Craft a new, descriptive chapter title inspired by the input subtopic title, and write the full content in Polish using fluent, structured prose. Ensure the content fits into the larger article narrative.

++goal++
Produce a coherent, well-structured, and fully developed chapter in Polish, with a strong title and markdown formatting, synthesized from the input research. Ensure consistency in tone, structure, and language, while tying clearly into the overall article.

++rules++
- The entire chapter must be written in Polish with correct grammar, syntax, and punctuation.
- Avoid introductory or concluding meta-paragraphs separate from the required structure; keep integrated flow with surrounding content.
- Chapter title must:
  - be descriptive, engaging, and grammatically correct;
  - clearly relate to the overall article topic;
  - use Polish capitalization rules (only the first word and proper nouns capitalized);
  - use a dash (–) or colon (:) with lowercase after the separator unless a proper noun follows.
- Avoid clichés and vague phrases (“W dzisiejszych czasach”, “W dobie”, “transformacyjny”, “jak pokazują badania”).
- Avoid keyword stuffing. Integrate keywords naturally, in correct grammatical forms; use synonyms to keep a natural rhythm.
- Aim for low perplexity: fluent, varied, human-like prose.
- Humanize your writing: write like an experienced editor, with clear logic and stylistic variation.
- Do not mention product or brand names unless provided in the research.
- Avoid predictive prescriptive phrases (“powinno się”, “należy”, “trzeba”) unless explicitly supported.
- Do not include JSON headers.

++context (research)++
Dane wejściowe (pozycje do rankingu):
{json.dumps(products_data, indent=2, ensure_ascii=False)}

Priorytetowe cechy do opisania:
{focus_txt}

++subtopic_title++
{tytul_h1}

++format (MANDATORY)++
Zwróć kompletny rozdział w Markdown zgodnie z układem:
1) **H1**: dokładnie „{tytul_h1}”.
2) **Wprowadzenie**: 1–2 akapity otwierające artykuł (kontekst zastosowań, na co zwrócić uwagę przy wyborze w {rok}).
3) **Sekcje H2** dla KAŻDEGO z poniższych produktów (użyj dokładnie nazwy jako tytułu H2, bez emoji i numerów):
{chr(10).join(["- " + n for n in nazwy_produktow])}
   W każdej sekcji napisz co najmniej DWA akapity, skupiając się na kluczowych cechach, parametrach, materiałach, wymiarach, ergonomii, realnych zaletach i zastosowaniach. 
   Jeśli jakaś informacja nie występuje w danych, pomiń ją naturalnie — nie pisz o braku ocen ani „braku danych”.
4) **Sekcja końcowa H2**: wybierz JEDEN z poniższych tytułów (dokładnie w tej brzmieniu) i napisz 2–3 akapity z wnioskami i rekomendacjami:
{chr(10).join(["- " + t for t in final_h2_options])}

++notes++
- Nie używaj list tabelarycznych ani rozbudowanych tabel.
- Utrzymuj spójny, nowoczesny ton i naturalny rytm zdań.
"""
    return prompt
