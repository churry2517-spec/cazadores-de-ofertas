import json
import requests
from bs4 import BeautifulSoup

# URL de Falabella - Ofertas
url = "https://www.falabella.com.pe/falabella-pe/page/ofertas"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, "html.parser")

offers = []

products = soup.select("div.es-product-card-card")

for product in products[:10]:  # Solo 10 primero para pruebas
    title = product.select_one("b.es-product-card-name").get_text(strip=True) if product.select_one("b.es-product-card-name") else "Sin nombre"
    price = product.select_one("span.es-product-card-price__current").get_text(strip=True) if product.select_one("span.es-product-card-price__current") else "Sin precio"
    link = "https://www.falabella.com.pe" + product.find("a")["href"]

    offers.append({
        "title": title,
        "price": price,
        "link": link
    })

# Guardar JSON
with open("offers.json", "w", encoding="utf-8") as f:
    json.dump(offers, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
