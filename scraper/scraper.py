import json, requests
from bs4 import BeautifulSoup

def get_falabella_offers():
    url = "https://www.falabella.com.pe/falabella-pe/category/cat70062/Tecnologia?sort=discount_DESC"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "https://www.google.com"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    offers = []
    products = soup.select("div.jsx-1833870200")

    for p in products[:12]:
        try:
            title = p.select_one("b.jsx-1833870200").get_text(strip=True)
            price = p.select_one("li.jsx-2835952914.-oldPrice small").get_text(strip=True)
            link = "https://www.falabella.com.pe" + p.select_one("a")["href"]
            
            offers.append({
                "title": title,
                "price": price,
                "link": link
            })
        except:
            continue

    return offers

offers = get_falabella_offers()

with open("offers.json", "w", encoding="utf-8") as f:
    json.dump(offers, f, indent=2, ensure_ascii=False)

print("✅ Scraping completado, ofertas:", len(offers))
