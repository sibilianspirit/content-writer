import streamlit as st
import pandas as pd
import json
from copy import deepcopy
from openai import OpenAI # <--- NOWA LINIA

# --- Inicjalizacja stanu sesji ---
if 'products' not in st.session_state:
    st.session_state.products = []
if 'manual_ranking_order' not in st.session_state:
    st.session_state.manual_ranking_order = []

# --- Konfiguracja API OpenAI ---
api_key_provided = "OPENAI_API_KEY" in st.secrets

if api_key_provided:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    client = None

# --- Funkcje pomocnicze ---

def extract_data_from_urls(urls: list[str]):
    """
    Placeholder dla funkcji, która pobiera dane z URL-i.
    W rzeczywistej aplikacji tutaj nastąpiłoby wywołanie narzędzia browse,
    a następnie wysłanie treści do LLM w celu ekstrakcji danych do formatu JSON.
    """
    st.info(f"Rozpoczynam analizę {len(urls)} adresów URL...")
    
    mock_data = [
        {
            "nazwa": "Laptop XYZ Pro", "cena": "8999 PLN",
            "cechy": ["Procesor: UltraChip X1", "RAM: 32 GB DDR5", "Ekran: 14 cali, 4K OLED"],
            "ocena": 9.5, "link": urls[0] if urls else ""
        },
        {
            "nazwa": "Laptop ABC Air", "cena": "6499 PLN",
            "cechy": ["Procesor: EcoChip Z2", "RAM: 16 GB DDR5", "Waga: 0.9 kg"],
            "ocena": 9.1, "link": urls[1] if len(urls) > 1 else ""
        },
        {
            "nazwa": "Gamingowy Potwór G1", "cena": "14999 PLN",
            "cechy": ["Procesor: Core i9 Extreme", "RAM: 64 GB DDR5", "Grafika: RTX 9090"],
            "ocena": 9.8, "link": urls[2] if len(urls) > 2 else ""
        }
    ]
    return mock_data[:len(urls)]

def generate_llm_response(prompt: str):
    """
    Wysyła prompt do API OpenAI i wyświetla odpowiedź.
    """
    st.subheader("Wygenerowany Prompt dla LLM:")
    st.text_area("Prompt", value=prompt, height=300)
    
    # Sprawdzenie, czy klucz API jest dostępny
    if not client:
        st.error("Klucz OpenAI API nie został skonfigurowany. Dodaj go w ustawieniach aplikacji w Streamlit Cloud.")
        return

    try:
        with st.spinner("🤖 Model myśli... Proszę czekać..."):
            # Wywołanie API OpenAI
            response = client.chat.completions.create(
                model="gpt-4o",  # Możesz zmienić model, np. na "gpt-3.5-turbo"
                messages=[
                    {"role": "system", "content": "Jesteś pomocnym asystentem, który tworzy angażujące treści marketingowe po polsku."},
                    {"role": "user", "content": prompt}
                ]
            )
            # Wyświetlenie odpowiedzi
            st.subheader("Odpowiedź od GPT:")
            st.markdown(response.choices[0].message.content)

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

# --- Interfejs Użytkownika (UI) ---
# (Reszta kodu pozostaje bez zmian)

st.set_page_config(layout="wide")
st.title("🤖 Generator Treści AI")

# --- PANEL BOCZNY (SIDEBAR) ---
st.sidebar.header("Krok 1: Wprowadź Dane")
data_source = st.sidebar.radio("Wybierz źródło danych:", ("Adresy URL", "Wprowadź ręcznie"))

if data_source == "Adresy URL":
    urls_text = st.sidebar.text_area("Wklej adresy URL (jeden na linię):", height=150, help="Symulacja: Wklej 1, 2 lub 3 linki, aby zobaczyć przykładowe dane.")
    if st.sidebar.button("Pobierz i przeanalizuj dane"):
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        if urls:
            with st.spinner("Przetwarzanie... (To jest symulacja)"):
                st.session_state.products = extract_data_from_urls(urls)
            st.sidebar.success(f"Pomyślnie przetworzono {len(st.session_state.products)} produkty!")
        else:
            st.sidebar.warning("Proszę wkleić przynajmniej jeden adres URL.")

elif data_source == "Wprowadź ręcznie":
    with st.sidebar.form("manual_add_form", clear_on_submit=True):
        st.subheader("Dodaj produkt/usługę")
        name = st.text_input("Nazwa produktu")
        price = st.text_input("Cena")
        features = st.text_area("Cechy (każda w nowej linii)")
        rating = st.slider("Ocena (1-10)", 1.0, 10.0, 5.0, 0.1)
        
        submitted = st.form_submit_button("Dodaj produkt do listy")
        if submitted and name:
            product_data = {
                "nazwa": name,
                "cena": price,
                "cechy": [f.strip() for f in features.split('\n') if f.strip()],
                "ocena": rating
            }
            st.session_state.products.append(product_data)
            st.sidebar.success(f"Dodano '{name}'!")

# Wyświetlanie listy wczytanych produktów
st.sidebar.header("Wczytane Produkty")
if st.session_state.products:
    for i, p in enumerate(st.session_state.products):
        st.sidebar.markdown(f"- **{p['nazwa']}** (Ocena: {p.get('ocena', 'N/A')})")
    if st.sidebar.button("Wyczyść listę produktów"):
        st.session_state.products = []
        st.rerun()
else:
    st.sidebar.info("Brak wczytanych produktów.")

# --- GŁÓWNY OBSZAR APLIKACJI ---

if not api_key_provided:
    st.warning("Uwaga: Klucz OpenAI API nie został znaleziony. Generowanie treści nie będzie działać. Proszę skonfiguruj go w ustawieniach aplikacji.", icon="⚠️")

if not st.session_state.products:
    st.info("👈 Zacznij od dodania produktów w panelu bocznym.")
else:
    st.header("Krok 2: Wygeneruj Treść")
    content_type = st.selectbox(
        "Wybierz typ treści do wygenerowania:",
        ["Wybierz opcję...", "Zestawienie", "Porównanie", "Ranking"]
    )

    if content_type == "Ranking":
        st.subheader("Konfiguracja Rankingu")
        all_product_names = [p['nazwa'] for p in st.session_state.products]
        selected_products_names = st.multiselect(
            "Wybierz produkty/usługi do rankingu:",
            options=all_product_names,
            default=all_product_names
        )
        selected_products_data = [p for p in st.session_state.products if p['nazwa'] in selected_products_names]

        if not selected_products_data:
            st.warning("Wybierz przynajmniej jeden produkt do rankingu.")
        else:
            ranking_mode = st.radio(
                "Wybierz sposób tworzenia rankingu:",
                ("Automatyczny (LLM decyduje o kolejności)", "Ręczny (sam ustalam kolejność)"),
                horizontal=True
            )

            if ranking_mode == "Automatyczny (LLM decyduje o kolejności)":
                st.markdown("##### Opcje trybu automatycznego")
                ranking_criterion = st.selectbox(
                    "Ranking według kryterium:",
                    ["Najlepszy ogólnie", "Najlepszy stosunek ceny do jakości", "Najwyższa wydajność", "Inne (wpisz własne)"]
                )
                if ranking_criterion == "Inne (wpisz własne)":
                    ranking_criterion = st.text_input("Wpisz własne kryterium:")
                top_n = st.slider(
                    "Pokaż Top N:", min_value=1, max_value=len(selected_products_data), value=min(3, len(selected_products_data))
                )

                if st.button("🚀 Generuj Ranking Automatyczny"):
                    prompt = f"""Jesteś redaktorem rankingu technologicznego. Twoim zadaniem jest stworzyć ranking 'Top {top_n}' na podstawie kryterium: '{ranking_criterion}'.
Oto lista produktów do analizy wraz z ich danymi w formacie JSON:
{json.dumps(selected_products_data, indent=2, ensure_ascii=False)}
Przeanalizuj wszystkie produkty, posortuj je od najlepszego do najgorszego według podanego kryterium, a następnie napisz artykuł rankingowy. Dla każdej pozycji w rankingu (od #1 do #{top_n}) przedstaw produkt i napisz szczegółowe uzasadnienie, dlaczego zajął właśnie to miejsce, opierając się wyłącznie na dostarczonych danych."""
                    generate_llm_response(prompt)

            elif ranking_mode == "Ręczny (sam ustalam kolejność)":
                st.markdown("##### Ustal kolejność w rankingu")
                if st.session_state.manual_ranking_order != selected_products_names:
                     st.session_state.manual_ranking_order = deepcopy(selected_products_names)
                if not st.session_state.manual_ranking_order:
                    st.warning("Brak produktów do ustalenia kolejności.")
                else:
                    for i, name in enumerate(st.session_state.manual_ranking_order):
                        cols = st.columns([0.8, 0.1, 0.1])
                        with cols[0]: st.markdown(f"### #{i+1}: {name}")
                        with cols[1]: st.button("▲", key=f"up_{name}", on_click=move_item_in_list, args=(st.session_state.manual_ranking_order, name, 'up'))
                        with cols[2]: st.button("▼", key=f"down_{name}", on_click=move_item_in_list, args=(st.session_state.manual_ranking_order, name, 'down'))
                    
                    if st.button("🚀 Generuj Ranking Ręczny"):
                        ordered_products_data = sorted(selected_products_data, key=lambda p: st.session_state.manual_ranking_order.index(p['nazwa']))
                        prompt_parts = []
                        for i, product in enumerate(ordered_products_data):
                            prompt_parts.append(f"Miejsce #{i+1}: {json.dumps(product, indent=2, ensure_ascii=False)}")
                        final_order_str = "\n".join(prompt_parts)
                        prompt = f"""Jesteś redaktorem tworzącym treść na stronę. Twoim zadaniem jest napisać artykuł rankingowy na podstawie przygotowanej przeze mnie kolejności. Musisz uzasadnić, dlaczego każdy z produktów zasłużył na swoje miejsce, bazując wyłącznie na dostarczonych danych.
Oto ostateczna, ustalona kolejność rankingu oraz dane produktów:
{final_order_str}
Napisz angażujący artykuł. Dla każdej pozycji w rankingu przedstaw jej zalety i wyjaśnij, co czyni ją wyjątkową, tak aby czytelnik zrozumiał, dlaczego znalazła się na tym konkretnym miejscu."""
                        generate_llm_response(prompt)
    elif content_type in ["Zestawienie", "Porównanie"]:
        st.info(f"Opcje dla '{content_type}' pojawią się tutaj. Można je zaimplementować w analogiczny sposób jak rankingi.")
