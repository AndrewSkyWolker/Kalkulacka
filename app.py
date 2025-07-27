# app.py - Backend aplikace
from flask import Flask, render_template, request, jsonify, Response
from bs4 import BeautifulSoup, Tag, NavigableString # Importujeme Tag a NavigableString pro kontrolu typu
import requests
import time
import json
import re # Importujeme regulární výrazy

app = Flask(__name__)

# URL pro autocomplete API KalorickýchTabulky.cz
SEARCH_API_URL = "https://www.kaloricketabulky.cz/autocomplete/foodstuff-activity-meal"
# Základní URL pro detailní stránky potravin
DETAIL_BASE_URL = "https://www.kaloricketabulky.cz/potraviny/"
# Základní URL pro detailní stránky receptů
RECIPE_BASE_URL = "https://www.kaloricketabulky.cz/recepty/"

# Výchozí HTTP hlavičky pro simulaci prohlížeče
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.kaloricketabulky.cz/'
}

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
                # food_type = item.get('foodType') # Tato hodnota se zdá být často None

                # Alternativní detekce tekutin na základě názvu
                # Přidány běžné české výrazy pro tekutiny
                is_liquid = False
                liquid_keywords = ['mléko', 'kefír', 'jogurtový nápoj', 'džus', 'šťáva', 'voda', 'nápoj', 'limonáda', 'sirup', 'polévka', 'vývar']
                for keyword in liquid_keywords:
                    if keyword in food_name.lower():
                        is_liquid = True
                        break

                # Určení jednotky na základě detekce
                energy_unit_suffix = "kcal" # Výchozí jednotka
                if is_liquid:
                    energy_unit_suffix = "kcal/100 ml"
                else:
                    energy_unit_suffix = "kcal/100 g"
                
                food_calories = f"{food_value} {energy_unit_suffix}"
                
                print(f"DEBUG: Food Name: {food_name}, Is Liquid (inferred): {is_liquid}, Food Calories String: {food_calories}") # Debugging log

                food_has_image = item.get('hasImage', False)
                food_url_slug = item.get('url')

                image_url = None

                # Krok 2: Pokud má potravina obrázek a platný slug, zkusíme ho scrapovat z detailní stránky
                if food_has_image and food_url_slug:
                    detail_page_url_food = f"{DETAIL_BASE_URL}{food_url_slug}"
                    detail_page_url_recipe = f"{RECIPE_BASE_URL}{food_url_slug}"

                    try:
                        time.sleep(0.5)
                        detail_response = requests.get(detail_page_url_food, headers=DEFAULT_HEADERS, timeout=10)
                        detail_response.raise_for_status()

                        detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

                        img_tag = detail_soup.find('img', src=lambda src: src and src.startswith('/file/image/'))

                        if img_tag and img_tag.get('src'):
                            image_url = f"https://www.kaloricketabulky.cz{img_tag['src']}?w=100"

                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 404:
                            try:
                                time.sleep(0.5)
                                detail_response = requests.get(detail_page_url_recipe, headers=DEFAULT_HEADERS, timeout=10)
                                detail_response.raise_for_status()

                                detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
                                img_tag = detail_soup.find('img', src=lambda src: src and src.startswith('/file/image/'))

                                if img_tag and img_tag.get('src'):
                                    image_url = f"https://www.kaloricketabulky.cz{img_tag['src']}?w=100"

                            except requests.exceptions.HTTPError as e_recipe:
                                print(f"Stránka receptu {detail_page_url_recipe} také vrátila chybu: {e_recipe}")
                            except requests.exceptions.RequestException as e_recipe:
                                print(f"Síťová chyba při stahování detailní stránky receptu {detail_page_url_recipe}: {e_recipe}")
                            except Exception as e_recipe:
                                print(f"Neočekávaná chyba při zpracování detailní stránky receptu {detail_page_url_recipe}: {e_recipe}")
                        else:
                            print(f"Chyba při stahování detailní stránky potravin {detail_page_url_food}: {e}")

                    except requests.exceptions.RequestException as e:
                        print(f"Síťová chyba při stahování detailní stránky potravin {detail_page_url_food}: {e}")
                    except Exception as e:
                        print(f"Neočekávaná chyba při zpracování detailní stránky potravin {detail_page_url_food}: {e}")
                else:
                    pass

                yield json.dumps({
                    "name": food_name,
                    "calories": food_calories,
                    "image_url": image_url,
                    "slug": food_url_slug
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
    Pokusí se najít detaily nejprve na stránce potraviny, poté na stránce receptu.
    """
    slug = request.json.get('slug')
    if not slug:
        return jsonify({"error": "Chybí slug pro získání detailů."}), 400

    details = {
        "total_kcal": "N/A",
        "total_kj": "N/A",
        "protein": "N/A",
        "protein_rdi": "N/A", # Recommended Daily Intake
        "carbs": "N/A",
        "carbs_rdi": "N/A",
        "sugar": "N/A",
        "fat": "N/A",
        "fat_rdi": "N/A",
        "saturated_fat": "N/A",
        "trans_fat": "N/A",
        "monounsaturated_fat": "N/A",
        "polyunsaturated_fat": "N/A",
        "cholesterol": "N/A",
        "fiber": "N/A",
        "fiber_rdi": "N/A",
        "salt": "N/A",
        "calcium": "N/A",
        "sodium": "N/A",
        "water": "N/A",
        "phe": "N/A",
        "source_url": None
    }

    # Funkce pro scrapování nutričních hodnot z HTML
    def scrape_nutrients(soup_obj, url_type):
        current_details = {key: "N/A" for key in details.keys() if key != "source_url"} # Inicializace N/A

        print(f"Pokouším se scrapovat nutriční hodnoty z {url_type} stránky...")

        # Pomocná funkce pro extrakci hodnoty a jednotky z daného BeautifulSoup Tagu
        def extract_value_and_unit_from_tag(tag_obj):
            # Get the full text content of the tag, stripping whitespace
            full_text = str(tag_obj.get_text(strip=True)) if isinstance(tag_obj, Tag) else str(tag_obj).strip()

            # Regex to find a number (with comma or dot as decimal) and an optional unit
            # It's flexible to catch various number formats and common units
            match = re.search(r'(\d+[,.]?\d*)\s*([kK]cal|[kK]J|[gG]|[mM]g|%)?', full_text, re.IGNORECASE)

            if match:
                value_part_raw = match.group(1) # Get the raw value part (e.g., "4,29" or "73.2")
                unit_part = match.group(2) if match.group(2) else ''

                # Just replace the decimal dot with a comma if present, otherwise keep as is
                formatted_value = value_part_raw.replace('.', ',')

                return f"{formatted_value} {unit_part}".strip()
            else:
                # If no number+unit pattern found, just return the stripped text with decimal comma applied
                return full_text.replace('.', ',')

        # --- Energetická hodnota (kcal, kJ) ---
        # Pokus 1: Z hidden inputů (spolehlivější, pokud existují)
        calculated_energy_kcal_input = soup_obj.find('input', id='calculatedEnergyValueInit')
        if calculated_energy_kcal_input and calculated_energy_kcal_input.get('value'):
            # The input value already has a comma, so just append " kcal"
            current_details["total_kcal"] = calculated_energy_kcal_input['value'] + " kcal"
            print(f"  Nalezeno Celkové kcal z inputu: {current_details['total_kcal']}")

        # Pokus 2: Zobrazené textové hodnoty (záložní)
        if current_details["total_kcal"] == "N/A":
            energy_sum_div = soup_obj.find('div', class_=lambda x: x and ('text-sum' in x or 'text-sum-xs' in x))
            if energy_sum_div:
                current_details["total_kcal"] = extract_value_and_unit_from_tag(energy_sum_div)
                print(f"  Nalezeno Celkové kcal z divu (fallback): {current_details['total_kcal']}")
            else:
                print("  Div s třídou 'text-sum' nebo 'text-sum-xs' pro kcal nenalezen (fallback).")

        # Pro kJ
        # Find all divs with class 'text-subtitle' and then check their text content for 'kJ'
        subtitle_divs = soup_obj.find_all('div', class_='text-subtitle')
        kj_subtitle_div = None
        for div in subtitle_divs:
            if 'kJ' in div.get_text(strip=True):
                kj_subtitle_div = div
                break

        if kj_subtitle_div:
            print(f"  Found kJ subtitle div: {kj_subtitle_div.prettify()}") # Log the found div
            extracted_kj_value = extract_value_and_unit_from_tag(kj_subtitle_div)
            current_details["total_kj"] = extracted_kj_value
            print(f"  Nalezeno Celkové kJ z divu: {current_details['total_kj']}")
        else:
            print("  Div s třídou 'text-subtitle' pro kJ nenalezen.")


        # --- Hledání všech živin (hlavních i podkategorií) ---
        # Collect all potential nutrient rows (main and nested) by class
        # These are the divs that contain the label and the value in their children/siblings
        nutrient_rows = soup_obj.find_all('div', class_=['text-subtitle', 'text-nutrient'])

        for row_div in nutrient_rows:
            if not isinstance(row_div, Tag):
                print(f"  Skipping non-Tag row_div: {repr(row_div)}")
                continue

            print(f"\nProcessing row_div:\n{row_div.prettify()}") # Added for debugging

            label_div = row_div.find('div', attrs={'layout': 'row', 'flex': 'auto'})
            if not label_div:
                print(f"  No label_div found in this row_div.")
                continue

            # Simplified name_text extraction: get all text from label_div
            name_text = label_div.get_text(strip=True)

            if not name_text:
                print(f"  No name_text extracted from label_div: {label_div.prettify()}")
                continue
            print(f"  Extracted name_text: '{repr(name_text)}'") # Added for debugging

            value_div = label_div.find_next_sibling('div')
            if not value_div or not isinstance(value_div, Tag):
                print(f"    Následující sourozenec divu pro hodnotu '{name_text}' nenalezen nebo není Tag. value_div: {repr(value_div)}")
                continue
            print(f"    Found value_div: {value_div.prettify()}") # Added for debugging
            print(f"    Raw text from value_div: '{repr(value_div.get_text(strip=True))}'") # Added for debugging

            main_value = extract_value_and_unit_from_tag(value_div)
            print(f"  Processing nutrient: '{name_text}', Value: '{main_value}'")

            # RDI is typically a 'text-desc' sibling of the current row_div
            rdi_element = row_div.find_next_sibling('div', class_='text-desc')
            rdi_value = "N/A"
            if rdi_element and isinstance(rdi_element, Tag) and 'Doporučený denní příjem' in rdi_element.get_text(strip=True):
                print(f"    Found RDI element for '{name_text}': {rdi_element.prettify()}") # Added for debugging
                rdi_value = extract_value_and_unit_from_tag(rdi_element)
                rdi_value = rdi_value.replace('Doporučený denní příjem:', '').strip()
                print(f"    Nalezeno RDI pro '{name_text}': {rdi_value}")
            else:
                print(f"    RDI element for '{name_text}' not found or not text-desc.")

            # Assign values based on name_text
            if "Bílkoviny" in name_text:
                current_details["protein"] = main_value
                current_details["protein_rdi"] = rdi_value
            elif "Sacharidy" in name_text:
                current_details["carbs"] = main_value
                current_details["carbs_rdi"] = rdi_value
            elif "Cukry" in name_text:
                current_details["sugar"] = main_value
            elif "Tuky" in name_text:
                current_details["fat"] = main_value
                current_details["fat_rdi"] = rdi_value
            elif "Nasycené mastné kyseliny" in name_text:
                current_details["saturated_fat"] = main_value
            elif "Trans mastné kyseliny" in name_text:
                current_details["trans_fat"] = main_value
            elif "Mononenasycené" in name_text:
                current_details["monounsaturated_fat"] = main_value
            elif "Polynenasycené" in name_text:
                current_details["polyunsaturated_fat"] = main_value
            elif "Cholesterol" in name_text:
                current_details["cholesterol"] = main_value
            elif "Vláknina" in name_text:
                current_details["fiber"] = main_value
                current_details["fiber_rdi"] = rdi_value
            elif "Sůl" in name_text:
                current_details["salt"] = main_value
            elif "Vápník" in name_text:
                current_details["calcium"] = main_value
            elif "Sodík" in name_text:
                current_details["sodium"] = main_value
            elif "Voda" in name_text:
                current_details["water"] = main_value
            elif "PHE" in name_text:
                current_details["phe"] = main_value


        return current_details

    # Zkusíme nejprve URL pro potraviny
    try:
        time.sleep(0.5)
        detail_response = requests.get(f"{DETAIL_BASE_URL}{slug}", headers=DEFAULT_HEADERS, timeout=10)
        detail_response.raise_for_status()
        detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

        # Získání nutričních hodnot z HTML
        scraped_details = scrape_nutrients(detail_soup, "potraviny")
        details.update(scraped_details)
        details["source_url"] = f"{DETAIL_BASE_URL}{slug}"
        return jsonify(details)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # Pokud 404 pro potraviny, zkusíme URL pro recepty
            try:
                time.sleep(0.5)
                detail_response = requests.get(f"{RECIPE_BASE_URL}{slug}", headers=DEFAULT_HEADERS, timeout=10)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

                # Získání nutričních hodnot z HTML receptu
                scraped_details = scrape_nutrients(detail_soup, "receptu")
                details.update(scraped_details)
                details["source_url"] = f"{RECIPE_BASE_URL}{slug}"
                return jsonify(details)
            except requests.exceptions.RequestException as e_recipe:
                print(f"Chyba při stahování detailů receptu pro {slug}: {e_recipe}")
                return jsonify({"error": f"Nepodařilo se získat detaily pro {slug} ani jako recept."}), 500
        else:
            print(f"Chyba při stahování detailů potraviny pro {slug}: {e}")
            return jsonify({"error": f"Nepodařilo se získat detaily pro {slug} (HTTP chyba)."}), 500
    except requests.exceptions.RequestException as e:
        print(f"Síťová chyba při stahování detailů pro {slug}: {e}")
        return jsonify({"error": f"Síťová chyba při získávání detailů pro {slug}."}), 500
    except Exception as e:
        print(f"Neočekávaná chyba při zpracování detailů pro {slug}: {e}")
        return jsonify({"error": f"Nastala neočekávaná chyba při získávání detailů pro {slug}."}), 500

if __name__ == '__main__':
    app.run(debug=True)
