import streamlit as st
import pandas as pd
import json
from copy import deepcopy
from openai import OpenAI
import requests
from datetime import datetime

# --- Inicjalizacja stanu sesji ---
if 'products' not in st.session_state:
    st.session_state.products = []
if 'manual_ranking_order' not in st.session_state:
    st.session_state.manual_ranking_order = []
if 'url_inputs' not in st.session_state:
    st.session_state.url_inputs = ['']
if 'focus_features' not in st.session_state:
    st.session_state.focus_features = ''
if 'comparison_type' not in st.session_state:
    st.session_state.comparison_type = 'Produkt'

# --- Konfiguracja API ---
api_key_provided = "OPENAI_API_KEY" in st.secrets

if api_key_provided:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    client = None

# --- Funkcje pomocnicze ---

def fetch_with_jina_reader(url: str, api_key: str = None) -> str:
    """
    Pobiera zawartość strony używając Jina Reader API.
    Zwraca czysty Markdown idealny do przetwarzania przez LLM.
    """
    try:
        headers = {"X-Retain-Images": "none"}
        
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        jina_url = f"https://r.jina.ai/{url}"
        
        response = requests.get(jina_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            st.error(f"Błąd Jina Reader: HTTP {response.status_code}")
            return None
        
        content = response.text
        
        # Jina Reader zwraca treść po markerze "Markdown Content:"
        try:
            content = content.split("Markdown Content:")[1]
        except IndexError:
            pass
        
        content = content.strip()
        
        # Ogranicz długość dla API
        if len(content) > 12000:
            content = content[:12000] + "..."
        
        return content if content else None
        
    except requests.exceptions.Timeout:
        st.error(f"⏱️ Przekroczono limit czasu dla: {url}")
        return None
    except Exception as e:
        st.error(f"Błąd podczas pobierania: {str(e)}")
        return None

def search_product_info(product_name: str) -> str:
    """
    Wyszukuje dodatkowe informacje o produkcie używając Jina Search API.
    """
    try:
        search_query = f"{product_name} opinie recenzja test"
        jina_search_url = f"https://s.jina.ai/?q={requests.utils.quote(search_query)}"
        
        response = requests.get(jina_search_url, timeout=20)
        
        if response.status_code == 200:
            content = response.text[:3000]  # Ogranicz długość
            return content
        return None
    except Exception as e:
        st.warning(f"Nie udało się wyszukać dodatkowych info: {str(e)}")
        return None

def extract_product_data_with_llm(url: str, content: str, focus_features: str = "", comparison_type: str = "Produkt") -> dict:
    """
    Używa LLM do ekstrakcji danych z uwzględnieniem typu zestawienia i kluczowych funkcji.
    """
    if not client:
        st.error("Klucz OpenAI API nie został skonfigurowany.")
        return None
    
    type_instructions = {
        "Produkt": "produktu - skup się na specyfikacji technicznej, cenie, funkcjach",
        "Usługa": "usługi - skup się na zakresie usług, cenniku, warunkach, dostępności",
        "Marka": "marki - skup się na historii, wartościach, portfolio produktów, pozycji rynkowej"
    }
    
    focus_instruction = ""
    if focus_features:
        focus_instruction = f"\n\nSZCZEGÓLNIE ZWRÓĆ UWAGĘ NA: {focus_features}"
    
    extraction_prompt = f"""Przeanalizuj poniższą zawartość strony internetowej i wyciągnij informacje o {type_instructions.get(comparison_type, 'produktu')}.

URL: {url}

ZAWARTOŚĆ STRONY:
{content}
{focus_instruction}

Zwróć TYLKO poprawny JSON w formacie:
{{
    "nazwa": "Pełna nazwa {comparison_type.lower()}",
    "cena": "Cena w formacie tekstowym lub 'Brak informacji o cenie'",
    "cechy": [
        "Kluczowa cecha 1",
        "Kluczowa cecha 2",
        "Kluczowa cecha 3",
        "Kluczowa cecha 4",
        "Kluczowa cecha 5"
    ],
    "ocena": 8.5,
    "opinie_uzytkownikow": [
        "Podsumowanie opinii pozytywnych",
        "Podsumowanie opinii negatywnych"
    ],
    "link": "{url}"
}}

WAŻNE:
- Jeśli brak ceny: "Brak informacji o cenie"
- Jeśli brak oceny: 0
- Wyciągnij 5-10 najważniejszych cech
- Podsumuj opinie w 1-2 punktach
- Zwróć TYLKO JSON"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś specjalistą od ekstrakcji danych. Zwracasz TYLKO poprawny JSON."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Usuń markdown
        if result_text.startswith("```
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```
            result_text = result_text[:-3]
        
        product_data = json.loads(result_text.strip())
        return product_data
        
    except json.JSONDecodeError as e:
        st.error(f"Błąd parsowania JSON: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Błąd ekstrakcji: {str(e)}")
        return None

def extract_data_from_urls(urls: list[str], focus_features: str = "", comparison_type: str = "Produkt"):
    """
    Pobiera dane z URL-i używając Jina Reader i LLM.
    """
    products = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, url in enumerate(urls):
        if not url.strip():
            continue
            
        status_text.text(f"Przetwarzam {i+1}/{len(urls)}: {url}")
        
        # Pobierz treść przez Jina Reader
        content = fetch_with_jina_reader(url)
        
        if content:
            # Wyciągnij dane produktu
            product_data = extract_product_data_with_llm(url, content, focus_features, comparison_type)
            
            if product_data:
                # Opcjonalnie: wyszukaj dodatkowe info
                additional_info = search_product_info(product_data.get('nazwa', ''))
                if additional_info:
                    product_data['dodatkowe_info'] = additional_info[:500]
                
                products.append(product_data)
                st.success(f"✓ Przeanalizowano: {product_data.get('nazwa', 'Nieznany')}")
            else:
                st.warning(f"⚠ Nie udało się wyciągnąć danych z: {url}")
        else:
            st.error(f"✗ Nie udało się pobrać: {url}")
        
        progress_bar.progress((i + 1) / len(urls))
    
    status_text.empty()
    progress_bar.empty()
    
    return products

def generate_ranking_prompt_blog(products_data: list, criterion: str, top_n: int, comparison_type: str = "Produkt"):
    """
    Generuje prompt dla artykułu blogowego w formie rankingu.
    """
    current_year = datetime.now().year
    
    prompt = f"""Jesteś doświadczonym redaktorem blogowym specjalizującym się w tworzeniu profesjonalnych rankingów.

ZADANIE: Napisz kompletny artykuł blogowy w formie rankingu Top {top_n}.

TYP ZESTAWIENIA: {comparison_type}
KRYTERIUM: {criterion}

DANE DO ANALIZY:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

STRUKTURA ARTYKUŁU:

# [H1] Ranking: Top {top_n} - {criterion} - {comparison_type} {current_year}

[Wstęp - 2-3 akapity wprowadzające czytelnika w temat, wyjaśniające znaczenie kryterium i metodologię rankingu]

## [H2] 🥇 1. [Nazwa {comparison_type}]

[Akapit 1: Przedstawienie i kontekst - minimum 4-5 zdań o różnej długości, naturalny rytm narracji]

[Akapit 2: Szczegółowa analiza zalet i uzasadnienie miejsca w rankingu - minimum 4-5 zdań, humanizowana treść z przejściami między zdaniami]

**Kluczowe zalety:**
- [zaleta 1]
- [zaleta 2]
- [zaleta 3]

**Dla kogo:** [szczegółowe określenie grupy docelowej]

***

[Powtórz strukturę H2 dla pozostałych {top_n-1} pozycji rankingu]

## [H2] Jak wybraliśmy zwycięzców?

[Akapit opisujący metodologię i kryteria oceny]

## [H2] Podsumowanie

[2 akapity podsumowujące ranking z praktycznymi wskazówkami]

WYMAGANIA STYLISTYCZNE:
- Używaj naturalnego, ludzkiego języka - unikaj sztuczności AI
- Zróżnicowana długość zdań (krótkie, średnie, długie)
- Naturalne przejścia między myślami
- Minimum 2 pełne akapity przy każdym H2
- Każdy akapit minimum 4-5 zdań
- Humanizacja treści - pisz jak ekspert, nie jak robot
- Unikaj powtórzeń i szablonowych zwrotów
- Używaj konkretnych przykładów i liczb tam gdzie to możliwe

DANE DO INFOGRAFIKI:
Na końcu artykułu zasugeruj dane do stworzenia infografiki porównawczej (np. wykres porównujący ceny, oceny, kluczowe parametry)."""
    
    return prompt

def generate_comparison_prompt_blog(products_data: list, comparison_type: str = "Produkt"):
    """
    Generuje prompt dla artykułu blogowego - porównanie.
    """
    current_year = datetime.now().year
    product_names = [p['nazwa'] for p in products_data]
    
    prompt = f"""Jesteś ekspertem tworzącym szczegółowe porównania w formie artykułów blogowych.

TYP ZESTAWIENIA: {comparison_type}
PRODUKTY DO PORÓWNANIA: {', '.join(product_names)}

DANE:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

STRUKTURA ARTYKUŁU:

# [H1] Porównanie: {' vs '.join(product_names[:3])} - {current_year}

[Wstęp - 2-3 akapity wprowadzające w temat porównania]

## [H2] Specyfikacja i cechy kluczowe

[2 akapity analizujące najważniejsze parametry - naturalny rytm, zróżnicowane zdania]

[Tabela porównawcza w Markdown]

## [H2] Cena i stosunek jakości do ceny

[2 akapity szczegółowej analizy cenowej]

## [H2] Dla kogo jest każdy z {comparison_type.lower()}ów?

[2 akapity z praktycznymi wskazówkami]

## [H2] Werdykt: który wybrać?

[2 akapity podsumowujące z jasną rekomendacją]

WYMAGANIA:
- Naturalny, humanizowany język
- Minimum 2 akapity przy każdym H2
- Każdy akapit 4-5 zdań o różnej długości
- Konkretne dane i przykłady
- Praktyczne wskazówki

INFOGRAFIKA:
Zasugeruj dane do wizualizacji porównawczej."""
    
    return prompt

def generate_llm_response(prompt: str, show_prompt: bool = True):
    """
    Wysyła prompt do OpenAI i wyświetla odpowiedź.
    """
    if show_prompt:
        with st.expander("📋 Zobacz wygenerowany prompt", expanded=False):
            st.text_area("Prompt", value=prompt, height=300)
    
    if not client:
        st.error("Klucz OpenAI API nie został skonfigurowany.")
        return

    try:
        with st.spinner("🤖 Tworzę artykuł blogowy..."):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Jesteś ekspertem SEO i content marketingu tworzącym profesjonalne artykuły blogowe w języku polskim. Piszesz naturalnie, angażująco i humanizowanie - jak doświadczony redaktor, nie jak AI."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            st.markdown("---")
            st.subheader("📝 Wygenerowany Artykuł Blogowy:")
            st.markdown(response.choices.message.content)
            
            # Opcje pobierania
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="💾 Pobierz jako TXT",
                    data=response.choices.message.content,
                    file_name=f"artykul_ranking_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain"
                )
            with col2:
                st.download_button(
                    label="📄 Pobierz jako MD",
                    data=response.choices.message.content,
                    file_name=f"artykul_ranking_{datetime.now().strftime('%Y%m%d')}.md",
                    mime="text/markdown"
                )

    except Exception as e:
        st.error(f"Błąd API OpenAI: {e}")

def add_url_input():
    """Dodaje nowe pole URL."""
    st.session_state.url_inputs.append('')

def remove_url_input(index):
    """Usuwa pole URL."""
    if len(st.session_state.url_inputs) > 1:
        st.session_state.url_inputs.pop(index)

def move_item_in_list(list_to_modify, item_to_move, direction):
    """Przesuwa element na liście."""
    try:
        current_index = list_to_modify.index(item_to_move)
        if direction == 'up' and current_index > 0:
            list_to_modify.insert(current_index - 1, list_to_modify.pop(current_index))
        elif direction == 'down' and current_index < len(list_to_modify) - 1:
            list_to_modify.insert(current_index + 1, list_to_modify.pop(current_index))
    except (ValueError, IndexError):
        st.error("Błąd podczas przesuwania.")

# --- INTERFACE ---

st.set_page_config(page_title="Generator Artykułów Rankingowych AI", layout="wide", page_icon="📝")

st.title("📝 Generator Artykułów Rankingowych AI")
st.markdown("*Tworzenie profesjonalnych artykułów blogowych z rankingami i porównaniami*")

if not api_key_provided:
    st.error("⚠️ Skonfiguruj klucz OpenAI API w Streamlit Secrets", icon="🔑")
    st.stop()

# --- PANEL BOCZNY ---
with st.sidebar:
    st.header("⚙️ Konfiguracja")
    
    # Typ zestawienia
    st.session_state.comparison_type = st.selectbox(
        "🏷️ Typ zestawienia:",
        ["Produkt", "Usługa", "Marka"]
    )
    
    # Kluczowe funkcje
    st.session_state.focus_features = st.text_area(
        "🎯 Na czym się skupić? (opcjonalnie)",
        placeholder="np. wydajność, cena, łatwość obsługi, design...",
        height=80,
        help="Określ kluczowe aspekty, na których ma się skupić analiza"
    )
    
    st.markdown("---")
    st.header("📊 Dane")
    
    data_source = st.radio("Źródło danych:", ("🔗 Linki URL", "✍️ Ręczne"))

    if data_source == "🔗 Linki URL":
        st.markdown("### 🔗 Adresy URL")
        st.info("💡 Każdy URL w osobnym polu. Jina Reader automatycznie pobierze treść.")
        
        # Dynamiczne pola URL
        for i, url in enumerate(st.session_state.url_inputs):
            col1, col2 = st.columns()[5][1]
            with col1:
                st.session_state.url_inputs[i] = st.text_input(
                    f"URL #{i+1}",
                    value=url,
                    key=f"url_input_{i}",
                    placeholder="https://example.com/produkt"
                )
            with col2:
                if len(st.session_state.url_inputs) > 1:
                    st.button("🗑️", key=f"remove_{i}", on_click=remove_url_input, args=(i,))
        
        st.button("➕ Dodaj URL", on_click=add_url_input, use_container_width=True)
        
        st.markdown("---")
        
        if st.button("🔍 Analizuj wszystkie URL", type="primary", use_container_width=True):
            valid_urls = [url.strip() for url in st.session_state.url_inputs if url.strip()]
            if valid_urls:
                st.session_state.products = extract_data_from_urls(
                    valid_urls, 
                    st.session_state.focus_features,
                    st.session_state.comparison_type
                )
                if st.session_state.products:
                    st.success(f"✅ Przeanalizowano {len(st.session_state.products)} pozycji!")
                    st.rerun()
            else:
                st.warning("Dodaj przynajmniej jeden URL.")
    
    else:  # Ręczne dodanie
        with st.form("manual_form", clear_on_submit=True):
            st.subheader(f"Dodaj {st.session_state.comparison_type.lower()}")
            name = st.text_input("Nazwa*")
            price = st.text_input("Cena", placeholder="np. 2999 PLN")
            features = st.text_area("Cechy (każda w nowej linii)", placeholder="Cecha 1\nCecha 2")
            rating = st.slider("Ocena", 1.0, 10.0, 7.0, 0.5)
            opinions = st.text_area("Opinie", placeholder="Pozytywy\nNegatywy")
            
            if st.form_submit_button("➕ Dodaj", use_container_width=True):
                if name:
                    product = {
                        "nazwa": name,
                        "cena": price if price else "Brak informacji",
                        "cechy": [f.strip() for f in features.split('\n') if f.strip()],
                        "ocena": rating,
                        "opinie_uzytkownikow": [o.strip() for o in opinions.split('\n') if o.strip()] if opinions else [],
                        "link": ""
                    }
                    st.session_state.products.append(product)
                    st.success(f"✅ Dodano: {name}")
                    st.rerun()
    
    st.markdown("---")
    st.subheader("📦 Wczytane pozycje")
    
    if st.session_state.products:
        for i, p in enumerate(st.session_state.products):
            with st.expander(f"{i+1}. {p['nazwa']}", expanded=False):
                st.write(f"**Cena:** {p.get('cena', 'N/A')}")
                st.write(f"**Ocena:** {p.get('ocena', 'N/A')}/10")
                st.write(f"**Cechy:** {len(p.get('cechy', []))} poz.")
        
        if st.button("🗑️ Wyczyść wszystko", use_container_width=True):
            st.session_state.products = []
            st.session_state.manual_ranking_order = []
            st.rerun()
    else:
        st.info("Brak danych")

# --- GŁÓWNA TREŚĆ ---

if not st.session_state.products:
    st.info("👈 **Zacznij od dodania danych** w panelu bocznym", icon="ℹ️")
else:
    st.header("📝 Generowanie Artykułu")
    
    content_type = st.selectbox(
        "Typ artykułu:",
        ["Wybierz...", "🏆 Ranking (artykuł blogowy)", "⚖️ Porównanie (artykuł blogowy)"]
    )
    
    # --- PORÓWNANIE ---
    if content_type == "⚖️ Porównanie (artykuł blogowy)":
        st.subheader("⚖️ Artykuł Porównawczy")
        
        all_names = [p['nazwa'] for p in st.session_state.products]
        selected = st.multiselect(
            "Wybierz pozycje do porównania (2-5):",
            options=all_names,
            default=all_names[:min(3, len(all_names))]
        )
        
        if len(selected) < 2:
            st.warning("Wybierz minimum 2 pozycje")
        elif len(selected) > 5:
            st.warning("Maksymalnie 5 pozycji")
        else:
            selected_data = [p for p in st.session_state.products if p['nazwa'] in selected]
            
            st.markdown("### Podgląd wybranych:")
            cols = st.columns(len(selected_data))
            for i, product in enumerate(selected_data):
                with cols[i]:
                    st.markdown(f"**{product['nazwa']}**")
                    st.write(f"💰 {product.get('cena', 'N/A')}")
                    st.write(f"⭐ {product.get('ocena', 'N/A')}/10")
            
            if st.button("🚀 Generuj Artykuł Porównawczy", type="primary", use_container_width=True):
                prompt = generate_comparison_prompt_blog(selected_data, st.session_state.comparison_type)
                generate_llm_response(prompt)
    
    # --- RANKING ---
    elif content_type == "🏆 Ranking (artykuł blogowy)":
        st.subheader("🏆 Artykuł Rankingowy")
        
        all_names = [p['nazwa'] for p in st.session_state.products]
        selected = st.multiselect(
            "Wybierz pozycje do rankingu:",
            options=all_names,
            default=all_names
        )
        
        if not selected:
            st.warning("Wybierz przynajmniej jedną pozycję")
        else:
            selected_data = [p for p in st.session_state.products if p['nazwa'] in selected]
            
            ranking_mode = st.radio(
                "Tryb rankingu:",
                ("🤖 Automatyczny (AI ustala kolejność)", "✋ Ręczny (ty ustalasz)"),
                horizontal=True
            )
            
            # AUTOMATYCZNY
            if ranking_mode == "🤖 Automatyczny (AI ustala kolejność)":
                col1, col2 = st.columns(2)
                
                with col1:
                    criterion = st.selectbox(
                        "Kryterium:",
                        [
                            "Najlepszy ogólnie",
                            "Najlepszy stosunek jakości do ceny",
                            "Najwyższa wydajność",
                            "Najlepsza jakość wykonania",
                            "Najbardziej innowacyjny",
                            "Najlepszy dla początkujących",
                            "Własne"
                        ]
                    )
                    
                    if criterion == "Własne":
                        criterion = st.text_input("Własne kryterium:", placeholder="np. Najlepszy dla profesjonalistów")
                
                with col2:
                    top_n = st.slider(
                        "Top N:",
                        min_value=1,
                        max_value=len(selected_data),
                        value=min(5, len(selected_data))
                    )
                
                if st.button("🚀 Generuj Ranking Automatyczny", type="primary", use_container_width=True):
                    if criterion and criterion != "Własne":
                        prompt = generate_ranking_prompt_blog(
                            selected_data, 
                            criterion, 
                            top_n,
                            st.session_state.comparison_type
                        )
                        generate_llm_response(prompt)
                    else:
                        st.error("Określ kryterium")
            
            # RĘCZNY
            else:
                st.markdown("### 📝 Ustal kolejność")
                
                if st.session_state.manual_ranking_order != selected:
                    st.session_state.manual_ranking_order = deepcopy(selected)
                
                for i, name in enumerate(st.session_state.manual_ranking_order):
                    cols = st.columns([0.1, 0.7, 0.1, 0.1])
                    with cols:
                        st.markdown(f"#{i+1}")
                    with cols:[1]
                        st.markdown(f"{name}")
                    with cols:[2]
                        if i > 0:
                            st.button("▲", key=f"up_{name}", 
                                    on_click=move_item_in_list,
                                    args=(st.session_state.manual_ranking_order, name, 'up'))
                    with cols:[6]
                        if i < len(st.session_state.manual_ranking_order) - 1:
                            st.button("▼", key=f"down_{name}",
                                    on_click=move_item_in_list,
                                    args=(st.session_state.manual_ranking_order, name, 'down'))
                
                st.markdown("---")
                
                if st.button("🚀 Generuj Ranking Ręczny", type="primary", use_container_width=True):
                    ordered_data = sorted(
                        selected_data,
                        key=lambda p: st.session_state.manual_ranking_order.index(p['nazwa'])
                    )
                    
                    current_year = datetime.now().year
                    
                    prompt = f"""Jesteś doświadczonym redaktorem blogowym.

ZADANIE: Napisz kompletny artykuł blogowy w formie rankingu Top {len(ordered_data)}.

TYP: {st.session_state.comparison_type}
KOLEJNOŚĆ USTALONA PRZEZ EKSPERTA:

{json.dumps([{"miejsce": i+1, "dane": p} for i, p in enumerate(ordered_data)], indent=2, ensure_ascii=False)}

STRUKTURA:

# [H1] Ranking: Top {len(ordered_data)} - {st.session_state.comparison_type} {current_year}

[Wstęp - 2-3 akapity]

## [H2] 🥇 1. [Nazwa]

[Akapit 1: Przedstawienie - min 4-5 zdań, naturalny rytm]

[Akapit 2: Szczegółowa analiza - min 4-5 zdań, humanizacja]

**Kluczowe zalety:**
- [zaleta]

**Dla kogo:** [grupa docelowa]

---

[Powtórz dla wszystkich pozycji]

## [H2] Metodologia

[Akapit o kryteriach oceny]

## [H2] Podsumowanie

[2 akapity z praktyycznymi wskazówkami]

WYMAGANIA:
- Naturalny język - pisz jak człowiek
- Min 2 akapity przy H2
- Każdy akapit min 4-5 zdań różnej długości
- Konkretne dane
- Unikaj AI-speak

INFOGRAFIKA:
Zasugeruj dane do wizualizacji."""
                    
                    generate_llm_response(prompt)

st.markdown("---")
st.markdown("*Powered by OpenAI GPT-4o + Jina Reader API | SEO-Optimized Content Generator*")
