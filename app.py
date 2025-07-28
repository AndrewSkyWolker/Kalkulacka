# app.py - Backend aplikace
from flask import Flask, render_template, request, jsonify, Response
from bs4 import BeautifulSoup, Tag, NavigableString
import requests
import time
import json
import re
from urllib.parse import urljoin # Import urljoin

# Importy pro Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# Pro automatické stažení ChromeDriveru (volitelné, ale doporučené)
try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Warning: webdriver_manager not installed. Please install it (`pip install webdriver-manager`) or manually provide chromedriver path.")
    ChromeDriverManager = None


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

# Inicializace WebDriveru
driver = None

def initialize_driver():
    """Inicializuje Selenium WebDriver."""
    global driver
    if driver is None:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')  # Spustit prohlížeč v režimu bez hlavy (bez GUI)
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu') # Pro Windows
        options.add_argument('--window-size=1920,1080') # Nastavení velikosti okna
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')

        try:
            if ChromeDriverManager:
                service = Service(ChromeDriverManager().install())
            else:
                # Fallback if webdriver_manager is not available or explicitly provide path
                # IMPORTANT: Replace 'path/to/chromedriver' with the actual path if not using ChromeDriverManager
                service = Service('path/to/chromedriver') # <-- ZDE ZADEJTE CESTU K CHROMEDRIVERU
            driver = webdriver.Chrome(service=service, options=options)
            print("Selenium WebDriver initialized successfully.")
        except WebDriverException as e:
            print(f"Failed to initialize Selenium WebDriver: {e}")
            print("Please ensure ChromeDriver is installed and its path is correctly set or webdriver_manager is installed.")
            driver = None # Ensure driver is None if initialization fails

@app.before_request
def before_first_request():
    """Inicializuje WebDriver před prvním požadavkem."""
    initialize_driver()

@app.teardown_appcontext
def teardown_driver(exception=None):
    """Zavře WebDriver při ukončení kontextu aplikace."""
    global driver
    if driver:
        driver.quit()
        driver = None
        print("Selenium WebDriver closed.")


@app.route('/')
def index():
    """Vykreslí hlavní HTML stránku aplikace."""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_food():
    """
    Zpracovává vyhledávací požadavek z frontendu a streamuje výsledky.
    Nejprve volá autocomplete API a poté se pokouší scrapovat obrázky z detailních stránek potravin nebo receptů.
    """
    query = request.form.get('query')
    if not query:
        return jsonify({"error": "Prosím, zadejte hledaný výraz."}), 400

    def generate_results():
        """Generátorová funkce pro postupné odesílání výsledků."""
        try:
            params = {'query': query}

            # Krok 1: Vyhledání pomocí autocomplete API
            time.sleep(0.5)
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
                    
                    if image_url is None:
                        pass # Suppress this log as it's common for items without images
                else:
                    pass # Suppress this log

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
    Získá detailní nutriční hodnoty (bílkoviny, sacharidy, tuky) pro daný slug pomocí Selenium.
    Slug již obsahuje plnou cestu (/potraviny/ nebo /recepty/).
    """
    slug = request.json.get('slug')
    food_type_from_frontend = request.json.get('food_type') # Get food_type from frontend
    if not slug:
        return jsonify({"error": "Chybí slug pro získání detailů."}), 400

    global driver
    if driver is None:
        initialize_driver() # Pokusíme se inicializovat ovladač, pokud ještě není
        if driver is None:
            return jsonify({"error": "Selenium WebDriver není inicializován. Zkontrolujte logy serveru."}), 500

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
            print(f"  extract_value_and_unit_from_text received non-string: {text_content}")
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
                print(f"  extract_value_and_unit_from_text matched non-percentage value: '{value_part_cleaned}', unit: '{unit_part}' (from raw: '{value_part_raw}')")
                return {"value": value_part_cleaned, "unit": unit_part}
            except ValueError:
                print(f"  extract_value_and_unit_from_text: Cleaned value '{value_part_cleaned}' is not a valid number.")
                pass # Not a valid number, fall through to percentage or N/A

        # If not a g/mg/kJ/kcal unit, check for percentage (as before)
        match_percentage = re.search(r'(\d+\.?\d*)\s*(%)', text_content, re.IGNORECASE)
        if match_percentage:
            value_part = match_percentage.group(1)
            unit_part = match_percentage.group(2)
            print(f"  extract_value_and_unit_from_text matched percentage value: '{value_part}', unit: '{unit_part}'")
            return {"value": "N/A", "unit": ""} # Changed to N/A for % values as per user's previous request to only show g/mg/kJ/kcal

        print(f"  extract_value_and_unit_from_text: No number/unit pattern found in '{text_content}'.")
        return {"value": "N/A", "unit": ""}


    def scrape_with_selenium(url, is_recipe_flag):
        """Načte stránku pomocí Selenium a počká na načtení dynamického obsahu."""
        print(f"Navigating to {url} using Selenium...")
        try:
            driver.get(url)
            time.sleep(1) # Přidání krátké prodlevy pro usazení stránky

            # Čekání na plné načtení dokumentu (DOM a všechny zdroje)
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == 'complete'
            )
            print(f"Stránka {url} úspěšně načtena (document.readyState == 'complete').")

            # Po načtení dokumentu přidáme krátké (5s) volitelné čekání na dynamický obsah
            try:
                if is_recipe_flag:
                    WebDriverWait(driver, 5).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.recipe-energy-value')),
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[ng-bind="model.recipe.energyValue"]'))
                        )
                    )
                else: # Pro potraviny
                    WebDriverWait(driver, 5).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.ID, 'calculatedEnergyValueInit')),
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.text-sum, div.text-sum-xs'))
                        )
                    )
                print(f"Doplňková kontrola dynamického obsahu pro {url} prošla.")
            except TimeoutException:
                print(f"Varování: Specifický dynamický obsah nebyl nalezen do 5 sekund pro {url}, přesto pokračuji.")

            return driver.page_source
        except TimeoutException:
            print(f"Vypršel časový limit při čekání na document.readyState == 'complete' pro {url}.")
            print(f"Current page source (for debugging): {driver.page_source[:2000]}...")
            return driver.page_source # Return what we have, for further inspection
        except WebDriverException as e:
            print(f"WebDriver error while loading page {url}: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred with Selenium for {url}: {e}")
            return None


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

            print(f"  Scraped total_kcal: {scraped_data['total_kcal']}")
            print(f"  Scraped total_kj: {scraped_data['total_kj']}")
        except Exception as e:
            print(f"Error scraping total_kcal/kj: {e}")


        # --- Hledání všech živin (hlavních i podkategorií) ---
        # Find the main content block where nutrients are listed
        main_nutrient_block = soup_obj.find('div', class_='block-background', attrs={'flex': '50'})
        if not main_nutrient_block:
            print("Main nutrient block not found. Cannot parse detailed nutrients.")
            return scraped_data # Return what we have (energy values)

        # Find all direct children of this block that are potential nutrient rows
        # These are divs with classes 'text-subtitle', 'text-nutrient', or 'text-desc'
        # We need to be careful with text-desc as it can be RDI or a sub-nutrient value
        nutrient_rows = main_nutrient_block.find_all('div', recursive=False, class_=lambda x: x and any(cls in x for cls in ['text-subtitle', 'text-nutrient', 'text-desc']))
        
        temp_nutrients = {} # Store {nutrient_name: {value_text, rdi_text}}
        current_main_nutrient = None # To link RDI to the correct main nutrient
        
        for i, row in enumerate(nutrient_rows):
            row_text_raw = row.get_text(strip=True)
            print(f"  Processing row HTML (index {i}): {row}")
            print(f"  Processing row text: '{row_text_raw}'")

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
                    print(f"    Identified main nutrient: '{current_main_nutrient}', Value: '{value_text}'")
                else:
                    print(f"    Skipping text-subtitle row: '{row_text_raw}' (not a main nutrient)")
                    pass

            # Check if it's a sub-nutrient (text-nutrient)
            elif 'text-nutrient' in row.get('class', []):
                sub_nutrient_name_div = row.find('div', class_='flex-auto')
                if sub_nutrient_name_div:
                    sub_nutrient_name = sub_nutrient_name_div.get_text(strip=True)
                    # The value is typically in the last div child of this row
                    value_div_candidate = row.find_all('div')[-1]
                    value_text = "N/A"
                    if value_div_candidate:
                        # Get all text content from the value_div_candidate
                        value_text = value_div_candidate.get_text(strip=True)
                    
                    temp_nutrients[sub_nutrient_name] = {"value": value_text, "rdi": "N/A"}
                    print(f"    Identified sub-nutrient: '{sub_nutrient_name}', Value: '{value_text}'")
                else:
                    print(f"    Skipping text-nutrient row: '{row_text_raw}' (no sub-nutrient name div found)")
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
                            print(f"    Identified RDI for '{current_main_nutrient}': '{rdi_value_text}'")
                    else:
                        print(f"    Skipping RDI row: '{row_text_raw}' (no current main nutrient to assign RDI to)")
                        pass
                else:
                    # This might be another type of text-desc, just log it for now if not an RDI
                    print(f"    Skipping text-desc row (not RDI): '{row_text_raw}'")
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

    # Define scrape_and_parse_attempt as a nested helper to avoid code duplication
    def scrape_and_parse_attempt(full_url, is_recipe_flag): # Modified signature
        """Načte stránku pomocí Selenium a parsuje nutriční hodnoty."""
        print(f"Attempting to scrape URL: {full_url} (is_recipe_flag: {is_recipe_flag})")
        page_source = scrape_with_selenium(full_url, is_recipe_flag)
        if page_source:
            soup = BeautifulSoup(page_source, 'html.parser')
            scraped_data = parse_nutrients_from_soup(soup, is_recipe_page=is_recipe_flag)
            scraped_data["source_url"] = full_url # Set source_url to the successful URL
            return scraped_data
        return None

    scraped_data = None

    if food_type_from_frontend == 'potravina':
        full_url = urljoin(BASE_WEB_URL, '/potraviny/' + slug.lstrip('/'))
        scraped_data = scrape_and_parse_attempt(full_url, False)
    elif food_type_from_frontend == 'recept':
        full_url = urljoin(BASE_WEB_URL, '/recepty/' + slug.lstrip('/'))
        scraped_data = scrape_and_parse_attempt(full_url, True)
    else:
        # Fallback if food_type_from_frontend is not explicitly 'potravina' or 'recept' (or is None)
        # Try /potraviny/ first
        potraviny_url = urljoin(BASE_WEB_URL, '/potraviny/' + slug.lstrip('/'))
        scraped_data = scrape_and_parse_attempt(potraviny_url, False)

        # If total_kcal is still N/A, try /recepty/
        if scraped_data is None or scraped_data.get("total_kcal") == "N/A":
            recepty_url = urljoin(BASE_WEB_URL, '/recepty/' + slug.lstrip('/'))
            scraped_data = scrape_and_parse_attempt(recepty_url, True)


    if scraped_data and scraped_data.get("total_kcal") != "N/A": # Ensure we have valid scraped data
        details.update(scraped_data)
        print(f"DEBUG: Details to be sent to frontend: {json.dumps(details, indent=2)}")
        return jsonify(details)
    else:
        print(f"Failed to get details after all attempts for slug: {slug}")
        return jsonify({"error": f"Nepodařilo se získat detaily pro {slug} po všech pokusech."}), 500

if __name__ == '__main__':
    initialize_driver() # Inicializovat ovladač při spuštění aplikace
    app.run(debug=True)
