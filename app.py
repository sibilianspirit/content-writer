import streamlit as st
import pandas as pd
import json
from copy import deepcopy
from openai import OpenAI
import requests
from bs4 import BeautifulSoup

# --- Inicjalizacja stanu sesji ---
if 'products' not in st.session_state:
    st.session_state.products = []
if 'manual_ranking_order' not in st.session_state:
    st.session_state.manual_ranking_order = []
if 'processing_status' not in st.session_state:
    st.session_state.processing_status = []

# --- Konfiguracja API OpenAI ---
api_key_provided = "OPENAI_API_KEY" in st.secrets

if api_key_provided:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    client = None

# --- Funkcje pomocnicze ---

def fetch_webpage_content(url: str) -> str:
    """
    Pobiera zawartość strony internetowej i zwraca czysty tekst.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Usuń skrypty, style i inne niepotrzebne elementy
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
        
        # Pobierz tekst
        text = soup.get_text(separator='\n', strip=True)
        
        # Ogranicz długość (max ~8000 znaków dla API)
        if len(text) > 8000:
            text = text[:8000] + "..."
        
        return text
    except Exception as e:
        st.error(f"Błąd pobierania strony {url}: {str(e)}")
        return None

def extract_product_data_with_llm(url: str, content: str) -> dict:
    """
    Używa LLM do ekstrakcji danych produktu z zawartości strony.
    """
    if not client:
        st.error("Klucz OpenAI API nie został skonfigurowany.")
        return None
    
    extraction_prompt = f"""Przeanalizuj poniższą zawartość strony internetowej i wyciągnij z niej informacje o produkcie lub usłudze.

URL: {url}

ZAWARTOŚĆ STRONY:
{content}

Twoim zadaniem jest zwrócić TYLKO poprawny JSON (bez żadnego dodatkowego tekstu) w następującym formacie:
{{
    "nazwa": "Pełna nazwa produktu/usługi",
    "cena": "Cena w formacie tekstowym (np. '4999 PLN' lub 'od 29.99 USD')",
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
- Jeśli nie znajdziesz ceny, wpisz "Brak informacji o cenie"
- Jeśli nie znajdziesz oceny, wpisz 0
- Wyciągnij 5-10 najważniejszych cech technicznych lub funkcjonalnych
- Jeśli są opinie użytkowników, podsumuj je w 1-2 punktach (pozytywne i negatywne osobno)
- Zwróć TYLKO JSON, bez żadnego komentarza przed lub po nim"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Tańszy model do ekstrakcji
            messages=[
                {"role": "system", "content": "Jesteś specjalistą od ekstrakcji danych produktowych. Zwracasz TYLKO poprawny JSON bez dodatkowych komentarzy."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Usuń markdown jeśli występuje
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        product_data = json.loads(result_text.strip())
        return product_data
        
    except json.JSONDecodeError as e:
        st.error(f"Błąd parsowania JSON: {str(e)}\nOtrzymana odpowiedź: {result_text[:200]}")
        return None
    except Exception as e:
        st.error(f"Błąd podczas ekstrakcji danych: {str(e)}")
        return None

def extract_data_from_urls(urls: list[str]):
    """
    Pobiera dane z URL-i używając web scrapingu i LLM.
    """
    products = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, url in enumerate(urls):
        status_text.text(f"Przetwarzam {i+1}/{len(urls)}: {url}")
        
        # Pobierz zawartość strony
        content = fetch_webpage_content(url)
        
        if content:
            # Wyciągnij dane produktu za pomocą LLM
            product_data = extract_product_data_with_llm(url, content)
            
            if product_data:
                products.append(product_data)
                st.success(f"✓ Pomyślnie przeanalizowano: {product_data.get('nazwa', 'Nieznany produkt')}")
            else:
                st.warning(f"⚠ Nie udało się wyciągnąć danych z: {url}")
        else:
            st.error(f"✗ Nie udało się pobrać strony: {url}")
        
        progress_bar.progress((i + 1) / len(urls))
    
    status_text.empty()
    progress_bar.empty()
    
    return products

def generate_comparison_prompt(products_data: list):
    """
    Generuje prompt dla porównania produktów.
    """
    prompt = f"""Jesteś ekspertem tworzącym szczegółowe porównania produktów. 

Oto produkty do porównania:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

Stwórz profesjonalne porównanie, które zawiera:
1. Wprowadzenie - krótkie przedstawienie porównywanych produktów
2. Tabela porównawcza kluczowych specyfikacji
3. Szczegółowa analiza w kategoriach:
   - Cena i stosunek jakości do ceny
   - Najważniejsze cechy i funkcjonalności
   - Wydajność/jakość (na podstawie dostępnych danych)
   - Opinie użytkowników (jeśli dostępne)
4. Podsumowanie - dla kogo jest każdy produkt

Użyj formatowania Markdown dla lepszej czytelności."""
    
    return prompt

def generate_ranking_prompt(products_data: list, criterion: str, top_n: int):
    """
    Generuje prompt dla automatycznego rankingu.
    """
    prompt = f"""Jesteś redaktorem tworzącym profesjonalne rankingi produktów.

Kryterium rankingu: {criterion}

Produkty do przeanalizowania:
{json.dumps(products_data, indent=2, ensure_ascii=False)}

Twoim zadaniem jest:
1. Przeanalizować wszystkie produkty pod kątem kryterium: "{criterion}"
2. Ocenić każdy produkt biorąc pod uwagę: cechy, cenę, oceny, opinie użytkowników
3. Stworzyć ranking Top {top_n}
4. Dla każdej pozycji napisać szczegółowe uzasadnienie (3-4 zdania)

Format odpowiedzi:
# Top {top_n}: {criterion}

## 🥇 Miejsce 1: [Nazwa produktu]
**Cena:** [cena]
**Dlaczego na podium:** [szczegółowe uzasadnienie]
**Kluczowe zalety:**
- [zaleta 1]
- [zaleta 2]

[Powtórz dla pozostałych miejsc]

## Podsumowanie
[Krótkie podsumowanie rankingu]"""
    
    return prompt

def generate_llm_response(prompt: str, show_prompt: bool = True):
    """
    Wysyła prompt do API OpenAI i wyświetla odpowiedź.
    """
    if show_prompt:
        with st.expander("📋 Zobacz wygenerowany prompt", expanded=False):
            st.text_area("Prompt wysłany do LLM", value=prompt, height=300)
    
    if not client:
        st.error("Klucz OpenAI API nie został skonfigurowany.")
        return

    try:
        with st.spinner("🤖 Model analizuje dane i tworzy treść..."):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Jesteś ekspertem od tworzenia profesjonalnych treści marketingowych i technicznych w języku polskim. Piszesz przejrzyście, angażująco i merytorycznie."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            
            st.markdown("---")
            st.subheader("📝 Wygenerowana Treść:")
            st.markdown(response.choices[0].message.content)
            
            # Opcja kopiowania
            st.download_button(
                label="💾 Pobierz jako TXT",
                data=response.choices[0].message.content,
                file_name="wygenerowana_tresc.txt",
                mime="text/plain"
            )

    except Exception as e:
        st.error(f"Wystąpił błąd podczas komunikacji z API OpenAI: {e}")

def move_item_in_list(list_to_modify, item_to_move, direction):
    """Przesuwa element na liście w górę lub w dół."""
    try:
        current_index = list_to_modify.index(item_to_move)
        if direction == 'up' and current_index > 0:
            list_to_modify.insert(current_index - 1, list_to_modify.pop(current_index))
        elif direction == 'down' and current_index < len(list_to_modify) - 1:
            list_to_modify.insert(current_index + 1, list_to_modify.pop(current_index))
    except (ValueError, IndexError):
        st.error("Wystąpił błąd podczas przesuwania elementu.")

# --- INTERFACE UŻYTKOWNIKA ---

st.set_page_config(page_title="Generator Treści AI", layout="wide", page_icon="🤖")

st.title("🤖 Generator Treści AI - Rankingi i Porównania")
st.markdown("*Automatyczna analiza produktów i generowanie profesjonalnych treści*")

if not api_key_provided:
    st.error("⚠️ UWAGA: Klucz OpenAI API nie został znaleziony. Skonfiguruj go w Streamlit Cloud Secrets.", icon="🔑")
    st.stop()

# --- PANEL BOCZNY ---
with st.sidebar:
    st.header("📊 Krok 1: Dane Produktów")
    
    data_source = st.radio("Wybierz źródło:", ("🔗 Linki URL", "✍️ Ręczne dodanie"))

    if data_source == "🔗 Linki URL":
        st.markdown("Wklej linki do stron produktów (jeden na linię):")
        urls_text = st.text_area(
            "Adresy URL",
            height=150,
            placeholder="https://example.com/produkt1\nhttps://example.com/produkt2",
            label_visibility="collapsed"
        )
        
        if st.button("🔍 Analizuj strony", type="primary", use_container_width=True):
            urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
            if urls:
                st.session_state.products = extract_data_from_urls(urls)
                if st.session_state.products:
                    st.success(f"✅ Przeanalizowano {len(st.session_state.products)} produktów!")
                    st.rerun()
            else:
                st.warning("Proszę wkleić przynajmniej jeden URL.")
    
    else:  # Ręczne dodanie
        with st.form("manual_form", clear_on_submit=True):
            st.subheader("Dodaj produkt ręcznie")
            name = st.text_input("Nazwa produktu*")
            price = st.text_input("Cena", placeholder="np. 2999 PLN")
            features = st.text_area("Cechy (każda w nowej linii)", placeholder="Cecha 1\nCecha 2\nCecha 3")
            rating = st.slider("Ocena", 1.0, 10.0, 7.0, 0.5)
            opinions = st.text_area("Opinie użytkowników (opcjonalnie)", placeholder="Pozytywy\nNegatywy")
            
            if st.form_submit_button("➕ Dodaj produkt", use_container_width=True):
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
                else:
                    st.error("Nazwa produktu jest wymagana!")
    
    st.markdown("---")
    st.subheader("📦 Wczytane produkty")
    
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
            st.rerun()
    else:
        st.info("Brak produktów. Dodaj je powyżej.")

# --- GŁÓWNA TREŚĆ ---

if not st.session_state.products:
    st.info("👈 **Zacznij od dodania produktów** w panelu bocznym - wklej linki lub dodaj ręcznie.", icon="ℹ️")
else:
    st.header("⚙️ Krok 2: Wybierz typ treści")
    
    content_type = st.selectbox(
        "Typ treści do wygenerowania:",
        ["Wybierz opcję...", "🏆 Ranking", "⚖️ Porównanie"]
    )
    
    # --- PORÓWNANIE ---
    if content_type == "⚖️ Porównanie":
        st.subheader("⚖️ Porównanie Produktów")
        
        all_names = [p['nazwa'] for p in st.session_state.products]
        selected = st.multiselect(
            "Wybierz produkty do porównania (2-5):",
            options=all_names,
            default=all_names[:min(3, len(all_names))]
        )
        
        if len(selected) < 2:
            st.warning("Wybierz przynajmniej 2 produkty do porównania.")
        elif len(selected) > 5:
            st.warning("Zalecane jest porównanie max 5 produktów jednocześnie.")
        else:
            selected_data = [p for p in st.session_state.products if p['nazwa'] in selected]
            
            st.markdown("### Podgląd wybranych produktów:")
            cols = st.columns(len(selected_data))
            for i, product in enumerate(selected_data):
                with cols[i]:
                    st.markdown(f"**{product['nazwa']}**")
                    st.write(f"💰 {product.get('cena', 'N/A')}")
                    st.write(f"⭐ {product.get('ocena', 'N/A')}/10")
            
            if st.button("🚀 Generuj Porównanie", type="primary", use_container_width=True):
                prompt = generate_comparison_prompt(selected_data)
                generate_llm_response(prompt)
    
    # --- RANKING ---
    elif content_type == "🏆 Ranking":
        st.subheader("🏆 Tworzenie Rankingu")
        
        all_names = [p['nazwa'] for p in st.session_state.products]
        selected = st.multiselect(
            "Wybierz produkty do rankingu:",
            options=all_names,
            default=all_names
        )
        
        if not selected:
            st.warning("Wybierz przynajmniej jeden produkt.")
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
                
                if st.button("🚀 Generuj Ranking Automatyczny", type="primary", use_container_width=True):
                    if criterion and criterion != "Własne kryterium":
                        prompt = generate_ranking_prompt(selected_data, criterion, top_n)
                        generate_llm_response(prompt)
                    else:
                        st.error("Proszę określić kryterium rankingu.")
            
            # TRYB RĘCZNY
            else:
                st.markdown("### 📝 Ustal kolejność w rankingu")
                st.info("Użyj strzałek, aby zmienić kolejność produktów od najlepszego do najgorszego.")
                
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
                
                if st.button("🚀 Generuj Ranking Ręczny", type="primary", use_container_width=True):
                    ordered_data = sorted(selected_data, 
                                        key=lambda p: st.session_state.manual_ranking_order.index(p['nazwa']))
                    
                    prompt_parts = []
                    for i, product in enumerate(ordered_data):
                        prompt_parts.append(f"**Miejsce #{i+1}:**\n{json.dumps(product, indent=2, ensure_ascii=False)}")
                    
                    final_order = "\n\n".join(prompt_parts)
                    
                    prompt = f"""Jesteś redaktorem tworzącym profesjonalny ranking produktów.

Otrzymałeś ustaloną kolejność rankingu od eksperta. Twoim zadaniem jest napisać angażujący artykuł rankingowy, który uzasadni każde miejsce.

USTALONY RANKING:
{final_order}

Dla każdej pozycji (od #1 do #{len(ordered_data)}):
1. Przedstaw produkt
2. Wyjaśnij jego kluczowe zalety
3. Uzasadnij, dlaczego zasługuje na to konkretne miejsce
4. Dodaj praktyczne wskazówki, dla kogo jest najlepszy

Użyj formatowania Markdown dla lepszej czytelności. Napisz w sposób przekonujący i profesjonalny."""
                    
                    generate_llm_response(prompt)

st.markdown("---")
st.markdown("*Powered by OpenAI GPT-4 | Wersja 2.0*")
