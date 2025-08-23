# app.py - Backend aplikace
import os
import requests
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import time

# Načtení proměnných prostředí ze souboru .env
load_dotenv()

app = Flask(__name__)

# URL pro autocomplete API KalorickýchTabulky.cz
SEARCH_API_URL = "https://www.kaloricketabulky.cz/autocomplete/foodstuff-activity-meal"
# Základní URL pro detailní stránky
BASE_WEB_URL = "https://www.kaloricketabulky.cz"

# Výchozí HTTP hlavičky pro simulaci prohlížeče
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.kaloricketabulky.cz/'
}

# Získání Firebase konfiguračních proměnných z prostředí
app_id = os.getenv('__APP_ID', 'default-app-id')
firebase_config_raw = os.getenv('__FIREBASE_CONFIG', '{}')

# Zpracování firebase_config_raw pro zajištění platného JSONu
firebase_config_json_for_frontend = '{}'
try:
    # Nejprve odstraníme vnější jednoduché uvozovky, pokud existují
    cleaned_config_string = firebase_config_raw
    if cleaned_config_string.startswith("'") and cleaned_config_string.endswith("'"):
        cleaned_config_string = cleaned_config_string[1:-1]

    # Nahraďte neuzavřené klíče uvozovkami a zajistěte, aby hodnoty řetězců byly v dvojitých uvozovkách
    # Regex pro přidání uvozovek kolem klíčů, které nejsou již uzavřeny
    temp_json_string = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', cleaned_config_string)

    # Nahraďte jednoduché uvozovky u hodnot řetězců dvojitými uvozovkami
    temp_json_string = re.sub(r"'([^']*)'", r'"\1"', temp_json_string)

    # Zkontrolujte a případně obalte celý řetězec do složených závorek, pokud to není platný JSON objekt
    if not temp_json_string.strip().startswith('{') or not temp_json_string.strip().endswith('}'):
        # Pokud řetězec nezačíná a nekončí složenými závorkami, přidejte je
        if temp_json_string.strip() != "": # Zabraňte obalení prázdného řetězce
            temp_json_string = "{" + temp_json_string + "}"

    # Nyní se pokuste parsovat (doufejme) platný JSON řetězec
    firebase_config_dict = json.loads(temp_json_string)

    # Zkontrolujte, zda jsou klíče 'apiKey' a 'projectId' přítomny a nejsou prázdné
    if not firebase_config_dict.get('projectId') or not firebase_config_dict.get('apiKey'):
        print("Upozornění: Chybí projectId nebo apiKey ve Firebase konfiguraci. Používám prázdnou konfiguraci.")
        firebase_config_json_for_frontend = '{}'
    else:
        firebase_config_json_for_frontend = json.dumps(firebase_config_dict)
except json.JSONDecodeError as e:
    print(f"Chyba při dekódování JSON Firebase konfigurace: {e}")
    firebase_config_json_for_frontend = '{}'
except Exception as e:
    print(f"Neočekávaná chyba při zpracování Firebase konfigurace: {e}")
    firebase_config_json_for_frontend = '{}'


@app.route('/')
def index():
    """Vykreslí hlavní HTML stránku aplikace."""
    # Předáme Firebase konfiguraci a app_id do šablony
    return render_template('index.html',
                           app_id=app_id,
                           firebase_config_json=firebase_config_json_for_frontend)

@app.route('/search', methods=['POST'])
def search_food():
    """
    Zpracovává vyhledávací požadavek z frontendu a streamuje výsledky.
    Nejprve volá autocomplete API a poté se pokouší scrapovat obrázky z detailních stránek potravin nebo receptů.
    """
    # Přidejte podporu pro přímé předání názvu bez formuláře
    if request.is_json:
        query = request.json.get('query')
    else:
        query = request.form.get('query')
    
    if not query:
        return jsonify({"error": "Prosím, zadejte hledaný výraz."}), 400

    def generate_results():
        """Generátorová funkce pro postupné odesílání výsledků."""
        try:
            params = {'query': query}

            # Krok 1: Vyhledání pomocí autocomplete API
            # time.sleep(0.5)
            # Přidejte timeout a opakování při chybě:
            max_retries = 3
            retry_delay = 0.5  # sekundy

            for attempt in range(max_retries):
                try:
                    autocomplete_response = requests.get(SEARCH_API_URL, headers=DEFAULT_HEADERS, params=params, timeout=10)
                    autocomplete_response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == max_retries - 1:
                        yield json.dumps({"error": f"Chyba při komunikaci s API: {str(e)}"}) + '\n'
                        return
                    time.sleep(retry_delay)
            autocomplete_response = requests.get(SEARCH_API_URL, headers=DEFAULT_HEADERS, params=params, timeout=10)
            autocomplete_response.raise_for_status()
            autocomplete_data = autocomplete_response.json()

            if not isinstance(autocomplete_data, list):
                yield json.dumps({"error": "Server vrátil neočekávaný formát autocomplete dat (není seznam)."}) + '\n'
                return

            # Procházení výsledků z autocomplete API
            for item in autocomplete_data:
                food_name = item.get("title", "Neznámá potravina")
                food_value = item.get('value', 'N/A')

                is_liquid = False
                liquid_keywords = ['mléko', 'kefír', 'jogurtový nápoj', 'džus', 'šťáva', 'voda', 'nápoj', 'limonáda', 'sirup', 'polévka', 'vývar']
                for keyword in liquid_keywords:
                    if keyword in food_name.lower():
                        is_liquid = True
                        break

                energy_unit_suffix = "kcal"
                if is_liquid:
                    energy_unit_suffix = "kcal/100 ml"
                else:
                    energy_unit_suffix = "kcal/100 g"

                food_calories = f"{food_value} {energy_unit_suffix}"

                food_has_image = item.get('hasImage', False)
                food_url_slug = item.get('url') # This already contains /potraviny/ or /recepty/

                image_url = None
                food_type = None # Initialize food_type

                if food_has_image and food_url_slug:
                    potential_image_urls_and_types = []

                    # Priorita: 1. /recepty/, 2. /potraviny/
                    potential_image_urls_and_types.append((urljoin(BASE_WEB_URL, '/recepty/' + food_url_slug.lstrip('/')), 'recept'))
                    potential_image_urls_and_types.append((urljoin(BASE_WEB_URL, '/potraviny/' + food_url_slug.lstrip('/')), 'potravina'))

                    # Remove duplicates while preserving order
                    unique_urls_and_types = []
                    seen_urls = set()
                    for url, type_val in potential_image_urls_and_types:
                        if url not in seen_urls:
                            unique_urls_and_types.append((url, type_val))
                            seen_urls.add(url)

                    for current_image_fetch_url, current_food_type in unique_urls_and_types:
                        try:
                            time.sleep(0.5)
                            detail_response = requests.get(current_image_fetch_url, headers=DEFAULT_HEADERS, timeout=10)
                            detail_response.raise_for_status()

                            detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
                            img_tag = detail_soup.find('img', src=lambda src: src and src.startswith('/file/image/'))

                            if img_tag and img_tag.get('src'):
                                image_url = f"https://www.kaloricketabulky.cz{img_tag['src']}?w=100"
                                food_type = current_food_type # Set food_type based on successful URL
                                break # Image found, exit loop
                        except requests.exceptions.HTTPError as e:
                            pass # Suppress detailed error for 404s during image search
                        except requests.exceptions.RequestException as e:
                            pass
                        except Exception as e:
                            pass

                yield json.dumps({
                    "name": food_name,
                    "calories": food_calories,
                    "image_url": image_url,
                    "slug": food_url_slug, # Still send the original slug for get_details
                    "food_type": food_type # Send the determined food_type
                }) + '\n'

        except requests.exceptions.RequestException as e:
            yield json.dumps({"error": f"Chyba při komunikaci s autocomplete API: {e}"}) + '\n'
        except ValueError as e:
            yield json.dumps({"error": f"Chyba při parsování JSON odpovědi z autocomplete API: {e}"}) + '\n'
        except Exception as e:
            yield json.dumps({"error": f"Nastala neočekávaná chyba: {e}"}) + '\n'

    return Response(generate_results(), mimetype='application/json-stream')


@app.route('/get_details', methods=['POST'])
def get_details():
    """
    Získá detailní nutriční hodnoty (bílkoviny, sacharidy, tuky) pro daný slug.
    Používá requests/BeautifulSoup4.
    """
    slug = request.json.get('slug')
    food_type_from_frontend = request.json.get('food_type')
    if not slug:
        return jsonify({"error": "Chybí slug pro získání detailů."}), 400

    details = {
        "total_kcal": "N/A", "total_kj": "N/A", "protein": "N/A", "protein_rdi": "N/A",
        "carbs": "N/A", "carbs_rdi": "N/A", "sugar": "N/A", "fat": "N/A", "fat_rdi": "N/A",
        "saturated_fat": "N/A", "trans_fat": "N/A", "monounsaturated_fat": "N/A",
        "polyunsaturated_fat": "N/A", "cholesterol": "N/A", "fiber": "N/A", "fiber_rdi": "N/A",
        "salt": "N/A", "calcium": "N/A", "sodium": "N/A", "water": "N/A", "phe": "N/A",
        "source_url": None
    }

    def extract_value_and_unit_from_text(text_content):
        """
        Pomocná funkce pro extrakci číselné hodnoty a jednotky z textového řetězce.
        Odstraní mezery a nahradí desetinnou čárku tečkou.
        Prioritizuje jednotky hmotnosti/energie před procenty.
        """
        if not isinstance(text_content, str):
            return {"value": "N/A", "unit": ""}

        # Regex to find a number which can include spaces as thousand separators
        # and a comma or dot as a decimal separator, followed by a unit.
        # \d+ : one or more digits
        # (?:[\s\u00A0]\d{3})* : non-capturing group for optional thousand separators (space or non-breaking space followed by 3 digits)
        # (?:[.,]\d+)? : non-capturing group for optional decimal part (comma or dot followed by digits)
        # \s* : optional whitespace before unit
        # (g|mg|kJ|kcal) : the unit
        match_non_percentage = re.search(r'(\d+(?:[\s\u00A0]\d{3})*(?:[.,]\d+)?)\s*(g|mg|kJ|kcal)', text_content, re.IGNORECASE)

        if match_non_percentage:
            value_part_raw = match_non_percentage.group(1)
            unit_part = match_non_percentage.group(2)

            # Clean the raw value part: remove all spaces (thousand separators) and replace comma with dot for float conversion
            value_part_cleaned = value_part_raw.replace(' ', '').replace('\u00A0', '').replace(',', '.')

            # Validate if it's actually a number after cleaning
            try:
                float(value_part_cleaned) # Try converting to float to ensure it's a valid number
                return {"value": value_part_cleaned, "unit": unit_part}
            except ValueError:
                pass # Not a valid number, fall through to percentage or N/A

        # If not a g/mg/kJ/kcal unit, check for percentage (as before)
        match_percentage = re.search(r'(\d+\.?\d*)\s*(%)', text_content, re.IGNORECASE)
        if match_percentage:
            value_part = match_percentage.group(1)
            unit_part = match_percentage.group(2)
            return {"value": "N/A", "unit": ""} # Changed to N/A for % values as per user's previous request to only show g/mg/kJ/kcal

        return {"value": "N/A", "unit": ""}


    def parse_nutrients_from_soup(soup_obj, is_recipe_page=False):
        """Parsuje nutriční hodnoty z BeautifulSoup objektu."""
        scraped_data = {key: "N/A" for key in details.keys() if key not in ["source_url", "total_kcal", "total_kj"]}

        # --- Energetická hodnota (kcal, kJ) ---
        try:
            if is_recipe_page:
                # Pro recepty: Hledáme span s ng-if="data.energy==null" pro kcal
                kcal_span = soup_obj.find('span', attrs={'ng-if': 'data.energy==null'})
                if kcal_span:
                    parent_div = kcal_span.find_parent('div')
                    if parent_div:
                        full_kcal_text = parent_div.get_text(strip=True)
                        parsed_kcal = extract_value_and_unit_from_text(full_kcal_text)
                        if parsed_kcal["value"] != "N/A":
                            scraped_data["total_kcal"] = f"{parsed_kcal['value'].replace('.', ',')} kcal"
                        else:
                            scraped_data["total_kcal"] = "N/A"
                    else:
                        scraped_data["total_kcal"] = "N/A"
                else:
                    scraped_data["total_kcal"] = "N/A"

                # Pro recepty: Hledáme span s ng-if="data.energyAlt==null" pro kJ
                kj_span = soup_obj.find('span', attrs={'ng-if': 'data.energyAlt==null'})
                if kj_span:
                    parent_div = kj_span.find_parent('div')
                    if parent_div:
                        full_kj_text = parent_div.get_text(strip=True)
                        parsed_kj = extract_value_and_unit_from_text(full_kj_text)
                        if parsed_kj["value"] != "N/A":
                            scraped_data["total_kj"] = f"{parsed_kj['value'].replace('.', ',')} kJ"
                        else:
                            scraped_data["total_kj"] = "N/A"
                    else:
                        scraped_data["total_kj"] = "N/A"
                else:
                    scraped_data["total_kj"] = "N/A"

            else: # Pro potraviny
                kcal_input = soup_obj.find('input', id='calculatedEnergyValueInit')
                if kcal_input and kcal_input.get('value'):
                    scraped_data["total_kcal"] = f"{kcal_input['value']} kcal"
                else:
                    energy_sum_div = soup_obj.find('div', class_=lambda x: x and ('text-sum' in x or 'text-sum-xs' in x))
                    if energy_sum_div:
                        scraped_data["total_kcal"] = energy_sum_div.get_text(strip=True)

                kj_div = None
                all_subtitle_divs = soup_obj.find_all('div', class_='text-subtitle')
                for div in all_subtitle_divs:
                    if 'kJ' in div.get_text() or 'Energetická hodnota' in div.get_text():
                        kj_div = div
                        break

                if kj_div:
                    kj_text_raw = kj_div.get_text(strip=True)
                    parsed_kj = extract_value_and_unit_from_text(kj_text_raw)
                    if parsed_kj["value"] != "N/A":
                        scraped_data["total_kj"] = f"{parsed_kj['value'].replace('.', ',')} kJ"
                    else:
                        scraped_data["total_kj"] = "N/A"
                else:
                    scraped_data["total_kj"] = "N/A"

        except Exception as e:
            pass


        # --- Hledání všech živin (hlavních i podkategorií) ---
        # Find the main content block where nutrients are listed
        main_nutrient_block = soup_obj.find('div', class_='block-background', attrs={'flex': '50'})
        if not main_nutrient_block:
            return scraped_data # Return what we have (energy values)

        # Find all direct children of this block that are potential nutrient rows
        # These are divs with classes 'text-subtitle', 'text-nutrient', or 'text-desc'
        # We need to be careful with text-desc as it can be RDI or a sub-nutrient value
        nutrient_rows = main_nutrient_block.find_all('div', recursive=False, class_=lambda x: x and any(cls in x for cls in ['text-subtitle', 'text-nutrient', 'text-desc']))

        temp_nutrients = {} # Store {nutrient_name: {value_text, rdi_text}}
        current_main_nutrient = None # To link RDI to the correct main nutrient

        for i, row in enumerate(nutrient_rows):
            row_text_raw = row.get_text(strip=True)

            # Check if it's a main nutrient label (text-subtitle with an icon or specific keywords)
            if 'text-subtitle' in row.get('class', []):
                # Remove md-icon tag before getting text to clean nutrient name
                icon_tag = row.find('md-icon', class_='material-icons')
                if icon_tag:
                    icon_tag.extract() # Remove the icon tag from the soup object

                nutrient_name = row.find('div', class_='flex-auto').get_text(strip=True) if row.find('div', class_='flex-auto') else row_text_raw.strip()

                # Check for specific keywords to confirm it's a main nutrient label
                if any(k in nutrient_name for k in ['Bílkoviny', 'Sacharidy', 'Tuky', 'Vláknina', 'Sůl', 'Vápník', 'Sodík', 'Voda', 'PHE']):
                    current_main_nutrient = nutrient_name

                    # The value is typically in the last div child of this row
                    value_div_candidate = row.find_all('div')[-1]
                    value_text = "N/A"
                    if value_div_candidate:
                        # Get all text content from the value_div_candidate
                        value_text = value_div_candidate.get_text(strip=True)

                    temp_nutrients[current_main_nutrient] = {"value": value_text, "rdi": "N/A"}
                else:
                    pass

            # Check if it's a sub-nutrient (text-nutrient)
            elif 'text-nutrient' in row.get('class', []):
                # Find all direct div children of the current row
                direct_div_children = row.find_all('div', recursive=False)

                sub_nutrient_name = "N/A"
                value_text = "N/A"

                if len(direct_div_children) >= 2:
                    # The first div child should contain the name
                    sub_nutrient_name = direct_div_children[0].get_text(strip=True)
                    # The last div child should contain the value
                    value_text = direct_div_children[-1].get_text(strip=True)

                if sub_nutrient_name and sub_nutrient_name != "N/A": # Ensure we actually got a name
                    temp_nutrients[sub_nutrient_name] = {"value": value_text, "rdi": "N/A"}
                else:
                    pass

            # Check if it's an RDI (text-desc)
            elif 'text-desc' in row.get('class', []): # Removed "Doporučený denní příjem" from condition to catch all text-desc
                # Check if it's an RDI row
                if 'Doporučený denní příjem' in row_text_raw:
                    if current_main_nutrient and current_main_nutrient in temp_nutrients:
                        # The RDI value is usually directly within this 'text-desc' div, or its last child div
                        rdi_value_text = row_text_raw.replace('Doporučený denní příjem:', '').strip()
                        if rdi_value_text:
                            temp_nutrients[current_main_nutrient]["rdi"] = rdi_value_text
                    else:
                        pass
                else:
                    pass


        # Now, populate scraped_data from temp_nutrients
        for nutrient_name, data in temp_nutrients.items():
            parsed_value = extract_value_and_unit_from_text(data['value'])
            display_value = f"{parsed_value['value'].replace('.', ',')} {parsed_value['unit']}".strip() if parsed_value['value'] != "N/A" else "N/A"

            parsed_rdi = extract_value_and_unit_from_text(data['rdi'])
            rdi_display_value = f"{parsed_rdi['value'].replace('.', ',')} {parsed_rdi['unit']}".strip() if parsed_rdi['value'] != "N/A" else "N/A"


            # Assign values based on name_text
            if "Bílkoviny" in nutrient_name:
                scraped_data["protein"] = display_value
                scraped_data["protein_rdi"] = rdi_display_value
            elif "Sacharidy" in nutrient_name:
                scraped_data["carbs"] = display_value
                scraped_data["carbs_rdi"] = rdi_display_value
            elif "Cukry" in nutrient_name:
                scraped_data["sugar"] = display_value
            elif "Tuky" in nutrient_name:
                scraped_data["fat"] = display_value
                scraped_data["fat_rdi"] = rdi_display_value
            elif "Nasycené mastné kyseliny" in nutrient_name:
                scraped_data["saturated_fat"] = display_value
            elif "Trans mastné kyseliny" in nutrient_name:
                scraped_data["trans_fat"] = display_value
            elif "Mononenasycené" in nutrient_name:
                scraped_data["monounsaturated_fat"] = display_value
            elif "Polynenasycené" in nutrient_name:
                scraped_data["polyunsaturated_fat"] = display_value
            elif "Cholesterol" in nutrient_name:
                scraped_data["cholesterol"] = display_value
            elif "Vláknina" in nutrient_name:
                scraped_data["fiber"] = display_value
                scraped_data["fiber_rdi"] = rdi_display_value
            elif "Sůl" in nutrient_name:
                scraped_data["salt"] = display_value
            elif "Vápník" in nutrient_name:
                scraped_data["calcium"] = display_value
            elif "Sodík" in nutrient_name:
                scraped_data["sodium"] = display_value
            elif "Voda" in nutrient_name:
                scraped_data["water"] = display_value
            elif "PHE" in nutrient_name:
                scraped_data["phe"] = display_value

        return scraped_data

    def scrape_with_requests_only(url, is_recipe_flag):
        """Načte stránku pomocí requests a parsuje nutriční hodnoty."""
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            scraped_data = parse_nutrients_from_soup(soup, is_recipe_page=is_recipe_flag)
            scraped_data["source_url"] = url
            return scraped_data
        except requests.exceptions.RequestException as e:
            return None
        except Exception as e:
            return None

    scraped_data = None
    target_url = None
    is_recipe_flag = False

    if food_type_from_frontend == 'potravina':
        target_url = urljoin(BASE_WEB_URL, '/potraviny/' + slug.lstrip('/'))
        is_recipe_flag = False
    elif food_type_from_frontend == 'recept':
        target_url = urljoin(BASE_WEB_URL, '/recepty/' + slug.lstrip('/'))
        is_recipe_flag = True
    else:
        # Fallback if food_type_from_frontend is not explicitly provided or recognized
        # Try /potraviny/ first
        target_url = urljoin(BASE_WEB_URL, '/potraviny/' + slug.lstrip('/'))
        is_recipe_flag = False

    # Attempt with requests/BeautifulSoup4
    scraped_data = scrape_with_requests_only(target_url, is_recipe_flag)

    # If requests failed to get total_kcal and food_type was not explicit, try the other type with requests
    if (scraped_data is None or scraped_data.get("total_kcal") == "N/A") and food_type_from_frontend not in ['potravina', 'recept']:
        if is_recipe_flag: # If current attempt was recipe, try foodstuff
            target_url_alt = urljoin(BASE_WEB_URL, '/potraviny/' + slug.lstrip('/'))
            scraped_data = scrape_with_requests_only(target_url_alt, False)
        else: # If current attempt was foodstuff, try recipe
            target_url_alt = urljoin(BASE_WEB_URL, '/recepty/' + slug.lstrip('/'))
            scraped_data = scrape_with_requests_only(target_url_alt, True)

        # Update target_url and is_recipe_flag if the alternative scrape was successful
        if scraped_data and scraped_data.get("total_kcal") != "N/A":
            target_url = target_url_alt
            is_recipe_flag = not is_recipe_flag # Flip the flag

    if scraped_data and scraped_data.get("total_kcal") != "N/A":
        details.update(scraped_data)
        return jsonify(details)
    else:
        return jsonify({"error": f"Nepodařilo se získat detaily pro {slug} po všech pokusech pouze s requests."}), 500

@app.route('/search_by_barcode', methods=['POST'])
def search_by_barcode():
    """
    Vyhledá potravinu podle čárového kódu (EAN)
    """
    barcode = request.json.get('barcode')
    if not barcode:
        return jsonify({"error": "Chybí čárový kód pro vyhledávání."}), 400
    
    # Můžete implementovat vlastní logiku pro mapování EAN kódů na názvy potravin
    # Toto je příklad - můžete použít externí API nebo vlastní databázi
    
    # Příklad mapování běžných EAN kódů na názvy potravin
    ean_to_food_mapping = {
        '8594001000108': 'Tatranka čokoládová',
        '8594001000207': 'Tatranka oříšková',
        '8594001000306': 'Tatranka kokosová',
        '8594001000405': 'Tatranka lískooříšková',
        # Přidejte další mapping podle potřeby
    }
    
    food_name = ean_to_food_mapping.get(barcode)
    
    if food_name:
        # Pokud najdeme mapování, použijeme ho pro vyhledávání
        return search_food_by_name(food_name)
    else:
        # Pokud nemáme mapování, zkusíme vyhledat přímo podle EAN
        return search_food_by_name(barcode)

def search_food_by_name(food_name):
    """
    Pomocná funkce pro vyhledávání potraviny podle názvu
    """
    # Simulujeme POST požadavek na /search s názvem potraviny
    with app.test_request_context('/search', method='POST', data={'query': food_name}):
        return search_food()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)