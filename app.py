# app.py
import streamlit as st
import json
from copy import deepcopy
from openai import OpenAI
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from typing import List, Dict, Optional

# =========================
#   KONFIGURACJA STRONY
# =========================
st.set_page_config(page_title="Generator Treści AI", layout="wide", page_icon="🤖")
st.title("🤖 Generator Treści AI — Rankingi")
st.markdown("*Automatyczna analiza produktów/usług/marek i generowanie profesjonalnych rankingów (Top 3/5/10) na 2025*")

# =========================
#   STAN SESJI
# =========================
if 'products' not in st.session_state:
    st.session_state.products: List[Dict] = []
if 'manual_ranking_order' not in st.session_state:
    st.session_state.manual_ranking_order: List[str] = []
if 'processing_status' not in st.session_state:
    st.session_state.processing_status: List[str] = []
if 'urls' not in st.session_state:
    st.session_state.urls: List[str] = [""]

# =========================
#   OPENAI API
# =========================
api_key_provided = "OPENAI_API_KEY" in st.secrets
if not api_key_provided:
    st.error("⚠️ Brak klucza OPENAI_API_KEY w Secrets. Dodaj go, aby korzystać z generowania treści.", icon="🔑")
    st.stop()
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# =========================
#   POMOCNICZE
# =========================
def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = 'https://' + url
    return url

def fetch_with_jina(url: str) -> Optional[str]:
    """
    Pobiera uproszczoną treść strony przez Jina Reader (r.jina.ai).
    Zwraca tekst/markdown lub None.
    """
    try:
        u = _normalize_url(url)
        r = requests.get(f"https://r.jina.ai/{u}", timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.text and len(r.text.strip()) > 0:
            text = r.text.strip()
            if len(text) > 8000:
                text = text[:8000] + "..."
            return text
        return None
    except Exception:
        return None

def fetch_webpage_content(url: str) -> Optional[str]:
    """
    Preferuje Jina Reader; jeśli się nie uda, fallback na klasyczny scraping HTML.
    """
    # 1) Jina Reader
    jina = fetch_with_jina(url)
    if jina:
        return jina

    # 2) Fallback HTML
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    try:
        u = _normalize_url(url)
        response = requests.get(u, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        if len(text) > 8000:
            text = text[:8000] + "..."
        return text
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, 'status_code', '???')
        if code == 403:
            st.warning(f"⚠️ Strona {url} blokuje automatyczne pobieranie. Użyj trybu ręcznego lub skopiuj treść.")
            return None
        st.error(f"Błąd HTTP {code} dla {url}")
        return None
    except requests.exceptions.Timeout:
        st.error(f"⏱️ Przekroczono limit czasu dla: {url}")
        return None
    except Exception as e:
        st.error(f"Błąd pobierania strony {url}: {str(e)}")
        return None

def ddg_search(query: str, max_results: int = 6) -> List[Dict]:
    """
    Prosta wyszukiwarka (DuckDuckGo HTML). Zwraca listę {title, url, snippet}.
    """
    try:
        r = requests.get("https://duckduckgo.com/html/", params={"q": query}, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out: List[Dict] = []
        for res in soup.select(".result"):
            a = res.select_one(".result__a")
            if not a:
                continue
            href = a.get("href")
            if not href:
                continue
            title = a.get_text(" ", strip=True)
            snippet_el = res.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            out.append({"title": title, "url": href, "snippet": snippet})
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []

# =========================
#   EKSTRAKCJA / PROMPTY
# =========================
def extract_product_data_with_llm(
    url: str,
    content: str,
    focus_features: Optional[List[str]] = None,
    listing_type: str = "Produkt"
) -> Optional[Dict]:
    """
    Ekstrakcja danych dla typu: Produkt / Usługa / Marka (LLM).
    """
    focus_txt = ", ".join(focus_features) if focus_features else "kluczowe cechy, parametry techniczne, materiały, wymiary"
    extraction_prompt = f"""Przeanalizuj zawartość i wyciągnij dane dla typu: {listing_type}.

URL: {url}

PRIORYTETOWE CECHY/FUNKCJE (jeśli występują w treści): {focus_txt}

ZAWARTOŚĆ STRONY (skrócona):
{content}

Zwróć TYLKO poprawny JSON w formacie:
{{
  "nazwa": "Pełna nazwa (zgodna z typem {listing_type})",
  "cena": "Cena w formacie tekstowym lub 'Brak informacji o cenie'",
  "cechy": ["5-10 kluczowych cech/funkcjonalności, preferuj priorytetowe jeśli istnieją (materiały, wymiary, parametry)"],
  "ocena": 0,
  "opinie_uzytkownikow": [
    "Podsumowanie opinii pozytywnych (jeśli są)",
    "Podsumowanie opinii negatywnych (jeśli są)"
  ],
  "link": "{url}"
}}

Zasady:
- Jeśli nie ma ceny lub oceny: cena = "Brak informacji o cenie", ocena = 0.
- Cechy wybieraj techniczno-użytkowe, unikaj ogólników marketingowych.
- TYLKO JSON, zero komentarza."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś specjalistą od ekstrakcji danych produktowych/usług/marek. Zwracasz TYLKO poprawny JSON."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.2
        )
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        product_data = json.loads(result_text.strip())
        return product_data
    except json.JSONDecodeError as e:
        st.error(f"Błąd parsowania JSON: {str(e)}\nOdpowiedź (fragment): {result_text[:200]}")
        return None
    except Exception as e:
        st.error(f"Błąd podczas ekstrakcji danych: {str(e)}")
        return None

def extract_data_from_urls(urls: List[str], focus_features: Optional[List[str]], listing_type: str) -> List[Dict]:
    products: List[Dict] = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, url in enumerate(urls):
        u = _normalize_url(url)
        status_text.text(f"Przetwarzam {i+1}/{len(urls)}: {u}")
        content = fetch_webpage_content(u)
        if content:
            product_data = extract_product_data_with_llm(u, content, focus_features=focus_features, listing_type=listing_type)
            if product_data:
                products.append(product_data)
                st.success(f"✓ Pomyślnie przeanalizowano: {product_data.get('nazwa', 'Nieznana pozycja')}")
            else:
                st.warning(f"⚠ Nie udało się wyciągnąć danych z: {u}")
        else:
            st.error(f"✗ Nie udało się pobrać strony: {u}")
        progress_bar.progress((i + 1) / len(urls))

    status_text.empty()
    progress_bar.empty()
    return products

def generate_ranking_prompt(
    products_data: List[Dict],
    top_n: int,
    listing_type: str,
    focus_features: Optional[List[str]],
    category_hint: Optional[str]
) -> str:
    """
    Prompt dla artykułu rankingowego (bez infografik), z tabelą podsumowującą.
    - H1: „Najlepsze {kategoria} – ranking Top N [2025]”
    - Wprowadzenie (1–2 akapity)
    - H2 = nazwy produktów, min. 2 akapity na produkt (cechy, materiały, wymiary, zastosowanie)
    - H2 końcowe: naturalny tytuł (nie „Podsumowanie”)
    - W treści wymagana tabela podsumowująca ranking (Markdown) z kolumnami:
      „Miejsce | Nazwa | Najważniejsze cechy (skrót) | Cena (jeśli podana) | Link”
    """
    rok = 2025  # świeżość – rok w tytule i narracji
    kategoria = (category_hint or listing_type).strip().lower()
    focus_txt = ", ".join(focus_features) if focus_features else "kluczowe cechy, parametry techniczne, materiały, wymiary i zalety użytkowe"
    tytul_h1 = f"Najlepsze {kategoria} – ranking Top {top_n} [{rok}]"

    nazwy_produktow = [p.get("nazwa", "").strip() for p in products_data if p.get("nazwa")]
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
- Avoid prescriptive phrases (“powinno się”, “należy”, “trzeba”) unless explicitly supported.
- Do not include JSON headers.

++context (research)++
Pozycje do rankingu (dane wejściowe w formacie JSON):
{json.dumps(products_data, indent=2, ensure_ascii=False)}

Priorytetowe aspekty do opisania:
{focus_txt}

++subtopic_title++
{tytul_h1}

++format (MANDATORY)++
Zwróć kompletny rozdział w Markdown zgodnie z układem:

1) **H1**: dokładnie „{tytul_h1}”.

2) **Wprowadzenie**: 1–2 akapity otwierające artykuł (kontekst zastosowań, na co zwrócić uwagę przy wyborze w {rok}).

3) **Tabela podsumowująca ranking (Markdown)** umieszczona ZARAZ PO wprowadzeniu, z nagłówkiem H2:
   - Tytuł H2: „Tabela podsumowująca ranking”
   - Kolumny: „Miejsce | Nazwa | Najważniejsze cechy (skrót) | Cena (jeśli podana) | Link”
   - Wypełnij wiersze na podstawie danych wejściowych i kolejności logicznej narracji. 
   - Jeśli cena nie występuje w danych dla danego modelu, pozostaw tę komórkę pustą (nie pisz o braku danych).

4) **Sekcje H2** dla KAŻDEGO z poniższych produktów (użyj dokładnie nazwy jako tytułu H2, bez emoji i numerów):
{chr(10).join(["- " + n for n in nazwy_produktow])}
   W każdej sekcji napisz co najmniej DWA akapity, skupiając się na kluczowych cechach, materiałach, wymiarach, parametrach, ergonomii, realnych zaletach i zastosowaniach. 
   Jeśli jakaś informacja nie występuje w danych, pomiń ją naturalnie — nie pisz o braku ocen ani „braku danych”.

5) **Sekcja końcowa H2**: wybierz JEDEN z poniższych tytułów (dokładnie w tej brzmieniu) i napisz 2–3 akapity z wnioskami i rekomendacjami:
{chr(10).join(["- " + t for t in final_h2_options])}

++notes++
- Unikaj rozbudowanych tabel poza wymaganą „Tabelą podsumowującą ranking”.
- Zachowaj świeżość i kontekst 2025 roku.
- Pisz naturalnie, bez sztucznego powtarzania słów kluczowych.
"""
    return prompt

def generate_llm_response(prompt: str, show_prompt: bool = True):
    """
    Wysyła prompt do LLM i renderuje odpowiedź.
    """
    if show_prompt:
        with st.expander("📋 Zobacz wygenerowany prompt", expanded=False):
            st.text_area("Prompt wysłany do LLM", value=prompt, height=300)

    try:
        with st.spinner("🤖 Generuję artykuł rankingowy..."):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Jesteś ekspertem od tworzenia profesjonalnych treści w języku polskim. Pisz naturalnie, precyzyjnie, merytorycznie."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            content = response.choices[0].message.content
            st.markdown("---")
            st.subheader("📝 Wygenerowana treść:")
            st.markdown(content)
            st.download_button(
                label="💾 Pobierz artykuł (TXT)",
                data=content,
                file_name="ranking_artykul_2025.txt",
                mime="text/plain"
            )
    except Exception as e:
        st.error(f"Wystąpił błąd podczas komunikacji z API OpenAI: {e}")

def move_item_in_list(list_to_modify: List[str], item_to_move: str, direction: str):
    """Przesuwa element na liście w górę lub w dół."""
    try:
        current_index = list_to_modify.index(item_to_move)
        if direction == 'up' and current_index > 0:
            list_to_modify.insert(current_index - 1, list_to_modify.pop(current_index))
        elif direction == 'down' and current_index < len(list_to_modify) - 1:
            list_to_modify.insert(current_index + 1, list_to_modify.pop(current_index))
    except (ValueError, IndexError):
        st.error("Wystąpił błąd podczas przesuwania elementu.")

# =========================
#   SIDEBAR: DANE WEJŚCIOWE
# =========================
with st.sidebar:
    st.header("📊 Krok 1: Dane pozycji (URL / wyszukiwarka / ręcznie)")

    # Ikonki dla typów zestawień w UI (wewnętrznie używamy czystych słów)
    type_options_display = ["📦 Produkt", "🛠 Usługa", "🏷 Marka"]
    type_map = {"📦 Produkt": "Produkt", "🛠 Usługa": "Usługa", "🏷 Marka": "Marka"}
    listing_type_display = st.selectbox("Typ zestawienia:", type_options_display, index=0)
    listing_type = type_map[listing_type_display]  # bez emoji w promptach

    focus_text = st.text_area(
        "Cechy/funkcje priorytetowe (jedna na linię)",
        placeholder="np.\nczas pracy na baterii\nmateriał obudowy\nzasięg działania\nwymiary i waga",
        height=110
    )
    focus_features = [x.strip() for x in focus_text.split("\n") if x.strip()]

    data_source = st.radio("Wybierz źródło:", ("🔗 Linki URL", "🔎 Wyszukiwarka", "✍️ Ręczne dodanie"))

    if data_source == "🔗 Linki URL":
        st.markdown("**Adresy URL (każdy w osobnym boksie):**")
        remove_indices: List[int] = []
        for i, val in enumerate(st.session_state.urls):
            cols = st.columns([0.8, 0.2])
            with cols[0]:
                st.session_state.urls[i] = st.text_input(f"URL #{i+1}", value=val, key=f"url_box_{i}")
            with cols[1]:
                if st.button("🗑️", key=f"del_url_{i}"):
                    remove_indices.append(i)
        for idx in reversed(remove_indices):
            st.session_state.urls.pop(idx)
        if st.button("➕ Dodaj kolejny URL", use_container_width=True):
            st.session_state.urls.append("")

        if st.button("🔍 Analizuj podane strony", type="primary", use_container_width=True):
            urls = [u for u in [_normalize_url(x) for x in st.session_state.urls] if u and len(u) > 8]
            if urls:
                st.session_state.products = extract_data_from_urls(urls, focus_features, listing_type)
                if st.session_state.products:
                    st.success(f"✅ Przeanalizowano {len(st.session_state.products)} pozycji!")
                    st.rerun()
            else:
                st.warning("Dodaj co najmniej jeden poprawny URL.")

    elif data_source == "🔎 Wyszukiwarka":
        st.markdown("**Wpisz frazę, wybierz wynik i dodaj do listy URL:**")
        query = st.text_input("Fraza wyszukiwania", placeholder="np. najlepsze poganiacze elektryczne 2025")
        if st.button("Szukaj", use_container_width=True) and query.strip():
            results = ddg_search(query.strip(), max_results=6)
            if not results:
                st.info("Brak wyników lub błąd wyszukiwania.")
            else:
                for r in results:
                    with st.expander(r["title"], expanded=False):
                        st.caption(r["url"])
                        st.write(r["snippet"])
                        if st.button("➕ Dodaj ten URL", key=f"add_{r['url']}"):
                            st.session_state.urls.append(r["url"])
                            st.success("Dodano do listy URL.")

        st.markdown("---")
        if st.session_state.urls:
            st.subheader("Wybrane URL do analizy")
            for i, u in enumerate(st.session_state.urls):
                st.write(f"- {u}")
            if st.button("🔍 Analizuj zaznaczone URL", type="primary", use_container_width=True):
                urls = [u for u in [_normalize_url(x) for x in st.session_state.urls] if u and len(u) > 8]
                st.session_state.products = extract_data_from_urls(urls, focus_features, listing_type)
                if st.session_state.products:
                    st.success(f"✅ Przeanalizowano {len(st.session_state.products)} pozycji!")
                    st.rerun()

    else:  # Ręczne dodanie
        with st.form("manual_form", clear_on_submit=True):
            st.subheader(f"Dodaj {listing_type.lower()} ręcznie")
            name = st.text_input(f"Nazwa {listing_type.lower()}*")
            price = st.text_input("Cena", placeholder="np. 299 PLN")
            features = st.text_area("Cechy (każda w nowej linii)", placeholder="materiał...\nwymiary...\nparametr 1...\nparametr 2...")
            rating = st.slider("Ocena (opcjonalnie)", 0.0, 10.0, 7.0, 0.5)
            opinions = st.text_area("Opinie użytkowników (opcjonalnie)", placeholder="Pozytywy\nNegatywy")
            if st.form_submit_button("➕ Dodaj", use_container_width=True):
                if name:
                    product = {
                        "nazwa": name,
                        "cena": price if price else "Brak informacji o cenie",
                        "cechy": [f.strip() for f in features.split('\n') if f.strip()],
                        "ocena": rating,
                        "opinie_uzytkownikow": [o.strip() for o in opinions.split('\n') if o.strip()] if opinions else [],
                        "link": ""
                    }
                    st.session_state.products.append(product)
                    st.success(f"✅ Dodano: {name}")
                    st.rerun()
                else:
                    st.error("Nazwa jest wymagana!")

    st.markdown("---")
    st.subheader("📦 Wczytane pozycje")
    if st.session_state.products:
        for i, p in enumerate(st.session_state.products):
            with st.expander(f"{i+1}. {p['nazwa']}", expanded=False):
                if p.get('cena'):
                    st.write(f"**Cena:** {p.get('cena')}")
                if p.get('cechy'):
                    st.write(f"**Cechy:** {len(p['cechy'])} pozycji")
        if st.button("🗑️ Wyczyść wszystko", use_container_width=True):
            st.session_state.products = []
            st.session_state.manual_ranking_order = []
            st.session_state.urls = [""]
            st.rerun()
    else:
        st.info("Brak pozycji. Dodaj je powyżej.")

# =========================
#   GŁÓWNA CZĘŚĆ UI — TYLKO RANKING
# =========================
if not st.session_state.products:
    st.info("👈 **Zacznij od dodania pozycji** w panelu bocznym — wklej linki, wyszukaj lub dodaj ręcznie.", icon="ℹ️")
else:
    st.header("⚙️ Krok 2: Ranking (Top 3/5/10)")

    all_names = [p['nazwa'] for p in st.session_state.products]
    selected = st.multiselect(
        "Wybierz pozycje do rankingu:",
        options=all_names,
        default=all_names
    )

    if not selected:
        st.warning("Wybierz przynajmniej jedną pozycję.")
    else:
        selected_data = [p for p in st.session_state.products if p['nazwa'] in selected]

        # Wybór Top 3 / 5 / 10
        top_choice = st.radio(
            "Zakres rankingu:",
            options=["Top 3", "Top 5", "Top 10"],
            horizontal=True
        )
        top_n = int(top_choice.split()[-1])
        if len(selected_data) < top_n:
            st.info(f"Wybrano mniej pozycji niż {top_n}. Artykuł powstanie na podstawie dostępnych elementów ({len(selected_data)}).")
            top_n = len(selected_data)

        # Hint kategorii do H1
        category_hint = st.text_input(
            "Kategoria/segment (pojawia się w H1 w formie odmienionej, np. „poganiacze elektryczne”):",
            placeholder="np. poganiacze elektryczne"
        )

        # Podgląd
        st.markdown("### Podgląd wybranych pozycji:")
        cols = st.columns(min(4, max(1, len(selected_data))))
        for i, product in enumerate(selected_data):
            with cols[i % len(cols)]:
                st.markdown(f"**{product['nazwa']}**")
                if product.get('cena'):
                    st.write(f"💰 {product.get('cena')}")

        # Kolejność: automatyczna vs ręczna
        ranking_mode = st.radio(
            "Kolejność rankingu:",
            ("🤖 Automatyczna (AI układa narrację i kolejność)", "✋ Ręczna (sam ustalasz kolejność H2)"),
            horizontal=False
        )

        if ranking_mode == "✋ Ręczna (sam ustalasz kolejność H2)":
            st.markdown("### 📝 Ustal kolejność sekcji (od góry do dołu)")
            if st.session_state.manual_ranking_order != selected:
                st.session_state.manual_ranking_order = deepcopy(selected)

            for i, name in enumerate(st.session_state.manual_ranking_order):
                cols = st.columns([0.1, 0.7, 0.1, 0.1])
                with cols[0]:
                    st.markdown(f"**#{i+1}**")
                with cols[1]:
                    st.markdown(f"{name}")
                with cols[2]:
                    if i > 0:
                        st.button("▲", key=f"up_{name}", on_click=move_item_in_list,
                                  args=(st.session_state.manual_ranking_order, name, 'up'))
                with cols[3]:
                    if i < len(st.session_state.manual_ranking_order) - 1:
                        st.button("▼", key=f"down_{name}", on_click=move_item_in_list,
                                  args=(st.session_state.manual_ranking_order, name, 'down'))

            if st.button("🚀 Generuj ranking (artykuł blogowy)", type="primary", use_container_width=True):
                # przytnij do top_n
                ordered_names = st.session_state.manual_ranking_order[:top_n]
                ordered_data = [next(p for p in selected_data if p['nazwa'] == n) for n in ordered_names]

                prompt = generate_ranking_prompt(
                    products_data=ordered_data,
                    top_n=len(ordered_data),
                    listing_type=type_map[listing_type_display],  # czysta etykieta
                    focus_features=focus_features,
                    category_hint=category_hint
                )
                generate_llm_response(prompt, show_prompt=True)

        else:
            if st.button("🚀 Generuj ranking (artykuł blogowy)", type="primary", use_container_width=True):
                auto_data = selected_data[:top_n]
                prompt = generate_ranking_prompt(
                    products_data=auto_data,
                    top_n=len(auto_data),
                    listing_type=type_map[listing_type_display],
                    focus_features=focus_features,
                    category_hint=category_hint
                )
                generate_llm_response(prompt, show_prompt=True)

st.markdown("---")
st.markdown("*Powered by OpenAI GPT-4o | Wersja 3.0 — tylko rankingi, naturalne H1 2025, tabela podsumowująca*")
