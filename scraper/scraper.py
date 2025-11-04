import json
import requests
from bs4 import BeautifulSoup

def get_falabella_offers():
    url = "https://www.falabella.com.pe/falabella-pe/page/ofertas"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    offers = []
    products = soup.select("div.es-product-card-card")

    for product in products[:10]:  # Solo 10 para pruebas
        title_tag = product.select_one("b.es-product-card-name")
        price_tag = product.select_one("span.es-product-card-price__current")
        link_tag = product.find("a")

        title = title_tag.get_text(strip=True) if title_tag else "Sin nombre"
        price = price_tag.get_text(strip=True) if price_tag else "Sin precio"
        link = "https://www.falabella.com.pe" + link_tag["href"] if link_tag else ""

        offers.append({
            "title": title,
            "price": price,
            "link": link
        })

    return offers

# Obtener ofertas y guardar json
offers = get_fa_
