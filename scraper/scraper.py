# scraper/scraper.py
import json, re, time, sys
from typing import List, Dict
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.timeout = 25

# ---------- Utilidades ----------
def pct_off(list_price: float, price: float) -> float:
    try:
        if list_price and list_price > 0 and price and price < list_price:
            return round(100 * (1 - price / list_price), 2)
    except Exception:
        pass
    return 0.0

def norm_price(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^\d,\.]", "", str(x))
    s = s.replace(".", "").replace(",", ".")  # 1.299,90 -> 1299.90
    try:
        return float(s)
    except Exception:
        return None

def keep_top_n(items: List[Dict], n=50) -> List[Dict]:
    items = sorted(items, key=lambda r: r.get("discount_pct", 0), reverse=True)
    return items[:n]

def save_offers(rows: List[Dict], path="offers.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"[OK] Guardadas {len(rows)} ofertas en {path}")

# ---------- Parsers genéricos ----------
def parse_ldjson_products(html: str) -> List[Dict]:
    """Extrae productos desde bloques application/ld+json (cuando existen)."""
    out = []
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                continue
            for block in data:
                # buscamos Product
                if isinstance(block, dict) and block.get("@type") in ("Product", ["Product"]):
                    name = (block.get("name") or "").strip()
                    url = block.get("url") or block.get("@id")
                    offers = block.get("offers") or {}
                    if isinstance(offers, list):  # a veces viene lista
                        offers = offers[0] if offers else {}
                    price = norm_price(offers.get("price"))
                    list_price = norm_price(offers.get("highPrice") or offers.get("listPrice") or offers.get("price"))
                    # si hay priceSpecification
                    if not list_price and isinstance(offers, dict) and "priceSpecification" in offers:
                        ps = offers["priceSpecification"]
                        if isinstance(ps, list):
                            ps = ps[0] if ps else {}
                        list_price = norm_price(ps.get("price"))
                    # fallback: a veces el listprice viene en 'price' y el real en 'lowPrice'
                    low_price = norm_price(offers.get("lowPrice"))
                    if low_price and (not price or low_price < price):
                        price = low_price
                    if price and list_price and list_price >= price:
                        out.append({
                            "title": name[:200],
                            "current_price": price,
                            "old_price": list_price,
                            "url": url,
                        })
        except Exception:
            continue
    return out

def generic_html_prices(url: str) -> List[Dict]:
    """Parsers muy genérico como último recurso: busca elementos con clases típicas."""
    res = SESSION.get(url)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "lxml")
    rows = []
    cards = soup.find_all(attrs={"data-product-id": True}) or soup.find_all("article") or soup.select("[data-testid*=product]")
    for card in cards[:80]:
        title = None
        a = card.find("a", href=True)
        if a and a.text.strip():
            title = a.text.strip()
        elif card.find("h3"):
            title = card.find("h3").get_text(strip=True)
        cur_el = card.select_one(".price, .final, .best-price, .precio, .price__current, [data-testid*=price]")
        old_el = card.select_one(".old, .list-price, .price-old, .precio-antes, .price__old")
        price = norm_price(cur_el.get_text() if cur_el else None)
        list_price = norm_price(old_el.get_text() if old_el else None)
        href = (a["href"] if a else None)
        if href and href.startswith("//"):
            href = "https:" + href
        if href and href.startswith("/"):
            href = requests.compat.urljoin(url, href)
        if title and price and list_price:
            rows.append({
                "title": title[:200],
                "current_price": price,
                "old_price": list_price,
                "url": href or url
            })
    # añade también lo que se encuentre en ld+json
    rows.extend(parse_ldjson_products(res.text))
    return rows

# ---------- VTEX ----------
def vtex_search(domain: str, term="oferta", start=0, end=60) -> List[Dict]:
    """
    Consulta el API público de VTEX.
    - domain: ej. https://www.plazavea.com.pe
    - term: ft= {texto}
    """
    params = {"ft": term, "_from": start, "_to": end}
    url = f"{domain}/api/catalog_system/pub/products/search/?{urlencode(params)}"
    r = SESSION.get(url)
    if r.status_code != 200:
        return []
    data = r.json()
    out = []
    for prod in data:
        name = prod.get("productName") or prod.get("productTitle")
        link = prod.get("link") or prod.get("linkText") or prod.get("url")
        if link and link.startswith("/"):
            link = domain + link
        # tomamos el primer sku/seller
        try:
            item = prod["items"][0]
            seller = item["sellers"][0]
            offer = seller.get("commertialOffer", {})
            price = norm_price(offer.get("Price") or offer.get("price"))
            list_price = norm_price(offer.get("ListPrice") or offer.get("listPrice"))
            if price and list_price and list_price >= price:
                out.append({
                    "title": str(name)[:200],
                    "current_price": price,
                    "old_price": list_price,
                    "url": link,
                })
        except Exception:
            continue
    return out

def scrape_vtex(domain: str, fallback_urls: List[str]) -> List[Dict]:
    # 1) Intento API por términos comunes
    all_rows = []
    for t in ("oferta", "descuento", "promo"):
        try:
            rows = vtex_search(domain, term=t, start=0, end=80)
            all_rows.extend(rows)
            time.sleep(0.7)
        except Exception:
            pass
    # 2) Fallback a HTML en páginas de ofertas
    for u in fallback_urls:
        try:
            rows = generic_html_prices(u)
            all_rows.extend(rows)
            time.sleep(0.7)
        except Exception:
            pass
    return all_rows

# ---------- RIPLEY / FALABELLA / TOTTUS ----------
def scrape_generic_with_ld(domain_url: str, landing_urls: List[str]) -> List[Dict]:
    rows = []
    for u in landing_urls:
        try:
            res = SESSION.get(u)
            res.raise_for_status()
            html = res.text
            rows.extend(parse_ldjson_products(html))
            if not rows:  # intento súper genérico
                rows.extend(generic_html_prices(u))
            time.sleep(0.7)
        except Exception:
            continue
    return rows

# ---------- Orquestador ----------
def clean_and_filter(rows: List[Dict], min_pct=80.0, add_store=None) -> List[Dict]:
    out = []
    seen = set()
    for r in rows:
        price = norm_price(r.get("current_price"))
        list_price = norm_price(r.get("old_price"))
        if not (price and list_price and list_price > 0):
            continue
        d = pct_off(list_price, price)
        if d >= min_pct:
            url = r.get("url")
            key = (r.get("title"), url, price, list_price)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": r.get("title")[:200],
                "current_price": round(price, 2),
                "old_price": round(list_price, 2),
                "discount_pct": d,
                "store": add_store,
                "url": url,
            })
    return out

def main():
    print("== Scraper ofertas Perú (>=80%) ==")
    all_results: List[Dict] = []

    # --- VTEX (Plaza Vea, Wong, Oechsle)
    vtex_sites = [
        {
            "store": "Plaza Vea",
            "domain": "https://www.plazavea.com.pe",
            "fallback": [
                "https://www.plazavea.com.pe/busca?ft=oferta",
                "https://www.plazavea.com.pe/busca?ft=descuento",
            ],
        },
        {
            "store": "Wong",
            "domain": "https://www.wong.pe",
            "fallback": [
                "https://www.wong.pe/busca?ft=oferta",
                "https://www.wong.pe/busca?ft=descuento",
            ],
        },
        {
            "store": "Oechsle",
            "domain": "https://www.oechsle.pe",
            "fallback": [
                "https://www.oechsle.pe/busca?ft=oferta",
                "https://www.oechsle.pe/busca?ft=descuento",
            ],
        },
    ]
    for site in vtex_sites:
        print(f"-> {site['store']}")
        rows = scrape_vtex(site["domain"], site["fallback"])
        rows = clean_and_filter(rows, min_pct=80.0, add_store=site["store"])
        print(f"   {len(rows)} ofertas >=80%")
        all_results.extend(rows)

    # --- Ripley
    print("-> Ripley")
    ripley_rows = scrape_generic_with_ld(
        "https://simple.ripley.com.pe",
        [
            "https://simple.ripley.com.pe/tecno/ofertas",
            "https://simple.ripley.com.pe/promociones",
            "https://simple.ripley.com.pe/busca?Ntt=oferta",
        ],
    )
    ripley_rows = clean_and_filter(ripley_rows, 80.0, "Ripley")
    print(f"   {len(ripley_rows)} ofertas >=80%")
    all_results.extend(ripley_rows)

    # --- Falabella
    print("-> Falabella")
    falabella_rows = scrape_generic_with_ld(
        "https://www.falabella.com.pe",
        [
            "https://www.falabella.com.pe/falabella-pe/page/ofertas",
            "https://www.falabella.com.pe/falabella-pe/search?Ntt=oferta",
        ],
    )
    falabella_rows = clean_and_filter(falabella_rows, 80.0, "Falabella")
    print(f"   {len(falabella_rows)} ofertas >=80%")
    all_results.extend(falabella_rows)

    # --- Tottus
    print("-> Tottus")
    tottus_rows = scrape_generic_with_ld(
        "https://www.tottus.com.pe",
        [
            "https://www.tottus.com.pe/tottus-pe/search?Ntt=oferta",
            "https://www.tottus.com.pe/tottus-pe/page/ofertas",
        ],
    )
    tottus_rows = clean_and_filter(tottus_rows, 80.0, "Tottus")
    print(f"   {len(tottus_rows)} ofertas >=80%")
    all_results.extend(tottus_rows)

    # Top 50 mejores descuentos
    all_results = keep_top_n(all_results, n=50)
    save_offers(all_results, "offers.json")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[ERROR]", e)
        sys.exit(1)
