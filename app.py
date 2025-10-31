import streamlit as st
import json
from copy import deepcopy
from openai import OpenAI
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import io
import matplotlib.pyplot as plt
from typing import List, Dict, Optional

# =========================
#   KONFIGURACJA STRONY
# =========================
st.set_page_config(page_title="Generator Treści AI", layout="wide", page_icon="🤖")
st.title("🤖 Generator Treści AI - Rankingi i Porównania")
st.markdown("*Automatyczna analiza produktów/usług/marek i generowanie profesjonalnych treści*")

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
    st.error("⚠️ UWAGA: Klucz OpenAI API nie został znaleziony. Skonfiguruj go w Streamlit Secrets (OPENAI_API_KEY).", icon="🔑")
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

def ddg_search(query: str, max_results: int = 5) -> List[Dict]:
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

def build_ranking_infographic(ordered_data: List[Dict]) -> str:
    """
    Tworzy prosty wykres (barh) z ocenami. Zwraca ścieżkę do PNG.
    """
    names = [p.get("nazwa", "Pozycja") for p in ordered_data]
    scores = []
    for p in ordered_data:
        try:
            scores.append(float(p.get("ocena", 0)))
        except Exception:
            scores.append(0.0)

    plt.figure(figsize=(8, 0.5 + 0.5 * max(1, len(names))))
    plt.barh(names[::-1], scores[::-1])
    plt.xlabel("Ocena (0–10)")
    plt.title("Infografika: porównanie ocen w rankingu")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    path = "infografika_ranking.png"
    with open(path, "wb") as f:
        f.write(buf.read())
    return path

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
    focus_txt = ", ".join(focus_features) if focus_features else "brak szczególnych priorytetów"
    extraction_prompt = f"""Przeanalizuj zawartość i wyciągnij dane dla typu: {listing_type}.

URL: {url}

PRIORYTETOWE CECHY/FUNKCJE (jeśli występują w treści): {focus_txt}

ZAWARTOŚĆ STRONY (skrócona):
{content}

Zwróć TYLKO poprawny JSON w formacie:
{{
  "nazwa": "Pełna nazwa (zgodna z typem {listing_type})",
  "cena": "Cena w formacie tekstowym lub 'Brak informacji o cenie'",
  "cechy": ["5-10 kluczowych cech/funkcjonalności, preferuj priorytetowe jeśli istnieją"],
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

def generate_comparison_prompt(products_data: List[Dict], listing_type: str, focus_features: Optional[List[str]]) -> str:
    focus_txt = ", ".join(focus_features) if focus_features else "brak szczególnych priorytetów"
    prompt = f"""Jesteś ekspertem tworzącym szczegółowe porównania dla typu: {listing_type}.

PRIORYTETY CECH: {focus_txt}

Oto pozycje do porównania:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

Stwórz profesjonalne porównanie:
1. Wprowadzenie (kontekst dla {listing_type.lower()})
2. Tabela porównawcza kluczowych specyfikacji (tylko jeśli sensownie się różnią)
3. Analiza w kategoriach:
   - Cena i wartość
   - Najważniejsze funkcje/cechy (uwzględnij priorytety)
   - Jakość/doświadczenie użytkownika
   - Opinie użytkowników (jeśli są)
4. Podsumowanie: dla kogo co się nadaje

Użyj Markdown, pisz treściwie i naturalnie."""
    return prompt

def generate_ranking_prompt(
    products_data: List[Dict],
    criterion: str,
    top_n: int,
    listing_type: str,
    focus_features: Optional[List[str]],
    category_hint: Optional[str]
) -> str:
    rok = datetime.now().year
    focus_txt = ", ".join(focus_features) if focus_features else "brak szczególnych priorytetów"
    kategoria = category_hint.strip() if category_hint else listing_type

    prompt = f"""Jesteś redaktorem tworzącym blogowy ranking dla typu: {listing_type}.
Masz dane wejściowe (poniżej). Twoim zadaniem jest napisać KOMPLETNY artykuł blogowy.

WYMOGI FORMATU:
- Tytuł H1: "Ranking {kategoria} — {criterion} — Top {top_n} ({rok})"
- Każda pozycja w rankingu to śródtytuł H2 w formacie: "#1. NAZWA", "#2. NAZWA", "#3. NAZWA", itd. (BEZ EMOJI).
- Pod KAŻDYM H2 napisz co najmniej DWA akapity (naturalny rytm zdań, humanizacja, zero „robotycznych” wyliczanek).
- W treści umieść token [[INFOGRAFIKA_RANKING]] w miejscu, gdzie ma się znaleźć infografika z porównaniem ocen.
- Pisz po polsku, rzeczowo, ale lekko i współcześnie.

KRYTERIUM RANKINGU: {criterion}
PRIORYTETY CECH/FUNKCJI: {focus_txt}

DANE WEJŚCIOWE:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

WYTYCZNE MERYTORYCZNE:
- Wyjaśnij, dlaczego dany element jest wyżej/niżej od innych, bazując na przekazanych cechach, cenie i opiniach.
- Nie zmyślaj liczb. Jeśli czegoś brakuje, opisz to transparentnie („brak jawnych danych o cenie/ocenie”).
- Końcówka artykułu: zwięzłe podsumowanie (3–5 zdań), komu i w jakich scenariuszach najlepiej służy TOP 3.

ZWRÓĆ WYŁĄCZNIE ARTYKUŁ W MARKDOWN (H1 + H2 + akapity + podsumowanie + token infografiki)."""
    return prompt

def generate_llm_response(prompt: str, show_prompt: bool = True, infographic_path: Optional[str] = None):
    """
    Wysyła prompt do LLM i renderuje odpowiedź. Podmienia [[INFOGRAFIKA_RANKING]] na obraz.
    """
    if show_prompt:
        with st.expander("📋 Zobacz wygenerowany prompt", expanded=False):
            st.text_area("Prompt wysłany do LLM", value=prompt, height=300)

    try:
        with st.spinner("🤖 Model analizuje dane i tworzy treść..."):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Jesteś ekspertem od tworzenia profesjonalnych treści marketingowych i technicznych w języku polskim. Piszesz naturalnie, angażująco i merytorycznie."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )

            content = response.choices[0].message.content

            if infographic_path and '[[INFOGRAFIKA_RANKING]]' in content:
                content = content.replace('[[INFOGRAFIKA_RANKING]]', f'![Infografika rankingu]({infographic_path})')

            st.markdown("---")
            st.subheader("📝 Wygenerowana Treść:")
            st.markdown(content)

            if infographic_path:
                st.download_button(
                    "📊 Pobierz infografikę PNG",
                    data=open(infographic_path, "rb").read(),
                    file_name="infografika_ranking.png",
                    mime="image/png"
                )

            st.download_button(
                label="💾 Pobierz artykuł (TXT)",
                data=content,
                file_name="ranking_blog.txt",
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
    st.header("📊 Krok 1: Dane pozycji (URL / wyszukiwanie / ręcznie)")

    # Ikonki dla typów zestawień w UI (wewnętrznie używamy czystych słów)
    type_options_display = ["📦 Produkt", "🛠 Usługa", "🏷 Marka"]
    type_map = {
        "📦 Produkt": "Produkt",
        "🛠 Usługa": "Usługa",
        "🏷 Marka": "Marka"
    }
    listing_type_display = st.selectbox("Typ zestawienia:", type_options_display, index=0)
    listing_type = type_map[listing_type_display]  # bez emoji

    focus_text = st.text_area(
        "Cechy/funkcje priorytetowe (jedna na linię)",
        placeholder="np.\nczas pracy na baterii\nserwis/gwarancja\nkompatybilność z X\ncertyfikaty",
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
        query = st.text_input("Fraza wyszukiwania", placeholder="np. najlepszy ekspres ciśnieniowy do domu")
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
            price = st.text_input("Cena", placeholder="np. 2999 PLN")
            features = st.text_area("Cechy (każda w nowej linii)", placeholder="Cecha 1\nCecha 2\nCecha 3")
            rating = st.slider("Ocena", 0.0, 10.0, 7.0, 0.5)
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
                st.write(f"**Cena:** {p.get('cena', 'N/A')}")
                st.write(f"**Ocena:** {p.get('ocena', 'N/A')}/10")
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
#   GŁÓWNA CZĘŚĆ UI
# =========================
if not st.session_state.products:
    st.info("👈 **Zacznij od dodania pozycji** w panelu bocznym - wklej linki, wyszukaj lub dodaj ręcznie.", icon="ℹ️")
else:
    st.header("⚙️ Krok 2: Wybierz typ treści")

    content_type = st.selectbox(
        "Typ treści do wygenerowania:",
        ["Wybierz opcję...", "🏆 Ranking", "⚖️ Porównanie"]
    )

    # --- PORÓWNANIE ---
    if content_type == "⚖️ Porównanie":
        st.subheader("⚖️ Porównanie")
        all_names = [p['nazwa'] for p in st.session_state.products]
        selected = st.multiselect(
            "Wybierz pozycje do porównania (2–5):",
            options=all_names,
            default=all_names[:min(3, len(all_names))]
        )

        if len(selected) < 2:
            st.warning("Wybierz przynajmniej 2 pozycje do porównania.")
        elif len(selected) > 5:
            st.warning("Zalecane jest porównanie maks. 5 pozycji jednocześnie.")
        else:
            selected_data = [p for p in st.session_state.products if p['nazwa'] in selected]

            st.markdown("### Podgląd wybranych pozycji:")
            cols = st.columns(len(selected_data))
            for i, product in enumerate(selected_data):
                with cols[i]:
                    st.markdown(f"**{product['nazwa']}**")
                    st.write(f"💰 {product.get('cena', 'N/A')}")
                    st.write(f"⭐ {product.get('ocena', 'N/A')}/10")

            if st.button("🚀 Generuj Porównanie", type="primary", use_container_width=True):
                prompt = generate_comparison_prompt(selected_data, listing_type, focus_features)
                generate_llm_response(prompt)

    # --- RANKING ---
    elif content_type == "🏆 Ranking":
        st.subheader("🏆 Tworzenie Rankingu")

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

            ranking_mode = st.radio(
                "Tryb tworzenia rankingu:",
                ("🤖 Automatyczny (AI decyduje)", "✋ Ręczny (ty ustalasz kolejność)"),
                horizontal=True
            )

            # TRYB AUTOMATYCZNY
            if ranking_mode == "🤖 Automatyczny (AI decyduje)":
                col1, col2 = st.columns(2)
                with col1:
                    criterion = st.selectbox(
                        "Kryterium rankingu:",
                        [
                            "Najlepszy ogólnie",
                            "Najlepszy stosunek jakości do ceny",
                            "Najwyższa wydajność",
                            "Najlepsza jakość wykonania",
                            "Najbardziej innowacyjny",
                            "Własne kryterium"
                        ]
                    )
                    if criterion == "Własne kryterium":
                        criterion = st.text_input("Wpisz swoje kryterium:", placeholder="np. Najlepszy dla graczy")
                with col2:
                    top_n = st.slider(
                        "Liczba pozycji w rankingu (Top N):",
                        min_value=1,
                        max_value=len(selected_data),
                        value=min(5, len(selected_data))
                    )

                category_hint = st.text_input(
                    "Kategoria/segment (opcjonalnie, pojawi się w H1)",
                    placeholder="np. ekspresy ciśnieniowe do domu"
                )

                if st.button("🚀 Generuj Ranking (artykuł blogowy)", type="primary", use_container_width=True):
                    if criterion and criterion != "Własne kryterium":
                        infographic_path = build_ranking_infographic(selected_data)
                        prompt = generate_ranking_prompt(
                            selected_data, criterion, top_n,
                            listing_type=listing_type,
                            focus_features=focus_features,
                            category_hint=category_hint
                        )
                        generate_llm_response(prompt, infographic_path=infographic_path)
                    else:
                        st.error("Proszę określić kryterium rankingu.")

            # TRYB RĘCZNY
            else:
                st.markdown("### 📝 Ustal kolejność w rankingu")
                st.info("Użyj strzałek, aby zmienić kolejność od najlepszego do najsłabszego.")

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

                st.markdown("---")

                if st.button("🚀 Generuj Ranking (artykuł blogowy)", type="primary", use_container_width=True):
                    ordered_data = sorted(selected_data,
                                          key=lambda p: st.session_state.manual_ranking_order.index(p['nazwa']))

                    prompt_parts = []
                    for i, product in enumerate(ordered_data):
                        prompt_parts.append(f"**Miejsce #{i+1}:**\n{json.dumps(product, indent=2, ensure_ascii=False)}")
                    final_order = "\n\n".join(prompt_parts)

                    infographic_path = build_ranking_infographic(ordered_data)
                    rok = datetime.now().year
                    blog_prompt = f"""Jesteś redaktorem tworzącym profesjonalny ranking w formie ARTYKUŁU BLOGOWEGO.

Otrzymałeś ustaloną kolejność rankingu od eksperta. Twoim zadaniem jest napisać angażujący artykuł rankingowy, zgodny z poniższymi wymogami.

USTALONY RANKING (od #1 do #{len(ordered_data)}):
{final_order}

WYMOGI FORMATU:
- H1: "Ranking {listing_type if listing_type else 'Produkt'} — Ustalona kolejność ekspercka — Top {len(ordered_data)} ({rok})"
- Każdy punkt jako H2: "#X. NAZWA" (BEZ EMOJI).
- Pod każdym H2 co najmniej DWA akapity, naturalny rytm zdań, humanizacja języka.
- Użyj priorytetów cech (jeśli są): {", ".join(focus_features) if focus_features else "brak"}.
- W treści umieść token [[INFOGRAFIKA_RANKING]] dla miejsca wstawienia infografiki.
- Zakończ krótkim podsumowaniem (3–5 zdań) z rekomendacjami zastosowań.

ZWRÓĆ WYŁĄCZNIE MARKDOWN (H1/H2, akapity, token infografiki)."""
                    generate_llm_response(blog_prompt, infographic_path=infographic_path)

st.markdown("---")
st.markdown("*Powered by OpenAI GPT-4o | Wersja 2.1 — Jina Reader + URL boxy + fokus cech + h2 bez emoji*")
