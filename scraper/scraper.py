import json

# Ejemplo — luego lo reemplazamos por scraping real
offers = [
    {"title": "Producto ejemplo", "price": "S/10", "link": "https://ejemplo.com"}
]

with open("offers.json", "w") as f:
    json.dump(offers, f, indent=2)
