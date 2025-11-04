import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------
# Configuración
# ---------------------------

# Páginas públicas (aproximadas) donde suelen listar ofertas.
# Si una 404/403, el scraper la salta; luego la afinamos con la URL correcta.
STORE_PAGES = [
    ("Plaza Vea", "https://www.plazavea.com.pe/ofertas"),
    ("Wong", "https://www.wong.pe/ofertas"),
    ("Oechsle", "https://www.oechsle.pe/ofertas"),
    ("Ripley", "https://simple.ripley.com.pe/"),
    ("Falabella", "https://www.falabella.com.pe/falabella-pe/page/ofertas"),
    ("Tottus", "https://www.tottus.com.pe/"),
    ("MiFarma", "https://www.mifarma.com.pe/"),
]

# Umbral de descuento mínimo a guardar
MIN_DISCOUNT = 50  # puedes subirlo a 80 si quieres estrictamente 80%+

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

CURRENCY_REGX = re.compile(r"(S/\.?\s?)(\d+(?:[\.,]\d{2})?)", re.IGNORECASE)
PERCENT_REGX = re.compile(r"(\d{1,3})\s*%")
SPACES = re.compile(r"\s+")


def clean_text(t: str) -> str:
    return SPACES.sub(" ", t).strip()


def to_float(s: str) -> float | None:
    """
    Convierte 'S/ 1,599.90' o 'S/1599' a 1599.90
    """
    try:
        s = s.replace("S/", "").replace("s/", "").replace("S/.", "")
        s = s.replace(".", "").replace(",", ".")
        return float(s.strip())
    except Exception:
        return None


def fetch(url: str, timeout=20) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code >= 400:
            return None
        return BeautifulSoup(r.text, "lxml")
    except Exception:
        return None


def nearest_anchor(el) -> str | None:
    """
    Busca el enlace (href) más cercano (ascendente) a un elemento con % de descuento.
    """
    node = el
    for _ in range(5):
        if not node:
            break
        if node.name == "a" and node.get("href"):
            return node["href"]
        node = node.parent
    # como fallback, busca un <a> descendiente
    a = el.find("a", href=True)
    if a:
        return a["href"]
    return None


def find_near_prices(block_text: str) -> tuple[float | None, float | None]:
    """
    Busca dentro de texto cercano dos precios: el actual y el anterior.
    No es perfecto, pero ayuda como heurística genérica.
    """
    prices = [to_float(m.group(0)) for m in CURRENCY_REGX.finditer(block_text)]
    prices = [p for p in prices if p is not None]
    if len(prices) >= 2:
        # asume precio_actual = menor, precio_antes = mayor
        prices.sort()
        return prices[0], prices[-1]
    elif len(prices) == 1:
        return prices[0], None
    else:
        return None, None


def absolute(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    try:
        return urljoin(base_url, href)
    except Exception:
        return href


def normalize_title(el) -> str:
    """
    Busca un título cercano; si no, usa el texto del elemento de descuento.
    """
    # intenta hermanos/ancestros con algún texto de producto
    candidates = []
    # a veces el texto del card completo:
    candidates.append(el.get_text(" ", strip=True))
    for up in el.parents:
        if not up:
            break
        txt = clean_text(up.get_text(" ", strip=True))
        if txt:
            candidates.append(txt)
        # corta si ya es demasiado grande
        if len(" ".join(candidates)) > 1000:
            break
    # elige un texto corto y con sentido
    candidates = sorted(set(candidates), key=len)
    for c in candidates:
        # preferimos algo que no sea sólo números ni % ni puro precio
        if len(c) >= 10 and sum(ch.isalpha() for ch in c) >= 5:
            return c[:180]
    return el.get_text(" ", strip=True)[:180]


def parse_store(store_name: str, url: str) -> list[dict]:
    """
    Intenta encontrar tarjetas con % y precios cercanos.
    """
    soup = fetch(url)
    if not soup:
        return []
    results = []
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

    # busca elementos que contengan algún "%"
    percent_nodes = [t for t in soup.find_all(text=PERCENT_REGX) if t and t.strip()]
    # también busca nodos con texto y no sólo strings
    for node in soup.find_all():
        txt = node.get_text(" ", strip=True)
        if txt and PERCENT_REGX.search(txt):
            percent_nodes.append(node)

    seen_links = set()
    for n in percent_nodes:
        # Node puede ser NavigableString o Tag
        el = n if hasattr(n, "name") else getattr(n, "parent", None)
        if el is None:
            continue

        txt = clean_text(el.get_text(" ", strip=True))
        m = PERCENT_REGX.search(txt)
        if not m:
            continue

        try:
            pct = int(m.group(1))
        except Exception:
            continue

        if pct < MIN_DISCOUNT:
            continue

        href = nearest_anchor(el)
        link = absolute(base, href)
        if not link or link in seen_links:
            continue

        # Busca precios cercanos en texto de ancestros inmediatos
        block_text = txt
        # agrega texto ascendiendo un poco
        up = el.parent
        steps = 0
        while up and steps < 2:
            block_text += " " + clean_text(up.get_text(" ", strip=True))
            up = up.parent
            steps += 1

        price, original = find_near_prices(block_text)

        # Intenta un "título" simple
        title = normalize_title(el)

        results.append(
            {
                "store": store_name,
                "title": title,
                "price": price,
                "original_price": original,
                "discount_percent": pct,
                "link": link,
                "found_on": url,
            }
        )
        seen_links.add(link)

    return results


def main():
    all_offers: list[dict] = []

    for store, url in STORE_PAGES:
        try:
            print(f"[+] Scrape {store}: {url}")
            offers = parse_store(store, url)
            print(f"    -> {len(offers)} ofertas encontradas (>= {MIN_DISCOUNT}%)")
            all_offers.extend(offers)
        except Exception as e:
            print(f"    ! Error con {store}: {e}")
        # respirito humilde para no golpear las webs
        time.sleep(2)

    # Ordena por % desc
    all_offers.sort(key=lambda x: (x.get("discount_percent") or 0), reverse=True)

    # Escribe el JSON (aunque esté vacío)
    with open("offers.json", "w", encoding="utf-8") as f:
        json.dump(all_offers, f, ensure_ascii=False, indent=2)

    print(f"[OK] Guardado offers.json con {len(all_offers)} entradas")


if __name__ == "__main__":
    main()
