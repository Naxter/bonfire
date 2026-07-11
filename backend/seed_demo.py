"""Seed the database with synthetic receipts, so you can explore the dashboard
without importing your own data first.

    cd backend && python seed_demo.py

Creates ~6 months of plausible REWE / DM / Aldi shopping (with price drift so
the volatility and inflation views have something to show). Goes through the
real persistence path — dedupe, product table — but stubs out the LLM, so no
API key is needed. Safe to re-run: everything dedupes. Delete data/bonfire.db
to start fresh.
"""

import random
from datetime import datetime, timedelta

from app import ingest
from app.database import create_db_and_tables
from app.stores.base import ParsedItem, ParsedReceipt

random.seed(42)

# name -> (category, base price)
REWE_PRODUCTS = {
    "Bio Bananen": ("Obst & Gemüse", 1.79),
    "Äpfel Braeburn 1kg": ("Obst & Gemüse", 2.49),
    "Rispentomaten": ("Obst & Gemüse", 2.99),
    "Salatgurke": ("Obst & Gemüse", 0.89),
    "Paprika rot": ("Obst & Gemüse", 1.99),
    "Vollmilch 3,5%": ("Molkereiprodukte & Eier", 1.19),
    "Butter mild": ("Molkereiprodukte & Eier", 2.29),
    "Gouda jung 400g": ("Molkereiprodukte & Eier", 3.49),
    "Eier Freiland 10er": ("Molkereiprodukte & Eier", 3.19),
    "Naturjoghurt 500g": ("Molkereiprodukte & Eier", 1.09),
    "Hähnchenbrustfilet": ("Fleisch, Fisch & Veggie", 6.99),
    "Rinderhackfleisch 500g": ("Fleisch, Fisch & Veggie", 4.99),
    "Lachsfilet 250g": ("Fleisch, Fisch & Veggie", 5.99),
    "Tofu Natur": ("Fleisch, Fisch & Veggie", 1.99),
    "Vollkornbrot": ("Backwaren", 2.19),
    "Brötchen 6er": ("Backwaren", 1.49),
    "Pizza Margherita TK": ("Tiefkühlprodukte", 2.79),
    "Spinat TK 450g": ("Tiefkühlprodukte", 1.59),
    "Spaghetti 500g": ("Nährmittel & Vorrat", 1.29),
    "Basmati Reis 1kg": ("Nährmittel & Vorrat", 3.49),
    "Haferflocken kernig": ("Nährmittel & Vorrat", 1.19),
    "Olivenöl nativ 500ml": ("Gewürze, Saucen & Öle", 6.49),
    "Tomatensauce Basilikum": ("Gewürze, Saucen & Öle", 1.79),
    "Kichererbsen Dose": ("Konserven & Fertiggerichte", 0.99),
    "Paprikachips": ("Süßwaren & Snacks", 2.19),
    "Zartbitterschokolade": ("Süßwaren & Snacks", 1.49),
    "Mineralwasser 6x1,5L": ("Getränke", 3.29),
    "Apfelschorle 1,5L": ("Getränke", 0.99),
    "Kaffee gemahlen 500g": ("Getränke", 5.99),
    "Spülmittel": ("Haushalt & Non-Food", 1.29),
    "Müllbeutel 20L": ("Haushalt & Non-Food", 1.99),
    "PFAND 0,25 EUR": ("Pfand", 0.25),
}

DM_PRODUCTS = {
    "Duschgel Sensitive": ("Drogerie & Kosmetik", 1.95),
    "Sonnencreme LSF 50": ("Drogerie & Kosmetik", 6.45),
    "Vitamintabletten": ("Drogerie & Kosmetik", 3.15),
    "Shampoo sensitiv": ("Drogerie & Kosmetik", 2.45),
    "Zahnpasta": ("Drogerie & Kosmetik", 1.75),
    "Handseife Nachfüller": ("Drogerie & Kosmetik", 1.95),
    "Waschmittel flüssig": ("Haushalt & Non-Food", 4.95),
    "Küchenrolle 4er": ("Haushalt & Non-Food", 2.75),
}

ALDI_PRODUCTS = {
    "Bio Vollmilch": ("Molkereiprodukte & Eier", 1.09),
    "Nussmischung 200g": ("Süßwaren & Snacks", 2.49),
    "Ciabatta": ("Backwaren", 1.29),
    "Orangensaft 1L": ("Getränke", 1.89),
}

_ALL_SOURCES = (REWE_PRODUCTS, DM_PRODUCTS, ALDI_PRODUCTS)
CATEGORIES = {name: cat for src in _ALL_SOURCES for name, (cat, _) in src.items()}

# Demo data comes pre-categorized — bypass the LLM entirely.
ingest.get_category = lambda name, session=None: CATEGORIES.get(name, "Sonstiges")


def make_receipt(store_key, store_name, products, date, n_items, tx):
    names = random.sample(list(products), min(n_items, len(products)))
    items = []
    for name in names:
        _, base = products[name]
        qty = random.choice([1, 1, 1, 2]) if name != "PFAND 0,25 EUR" else 1
        # Prices drift over time so volatility/price-history views have data.
        price = base if name == "PFAND 0,25 EUR" else round(base * random.uniform(0.92, 1.14), 2)
        items.append(ParsedItem(name=name, price_total=round(price * qty, 2), quantity=qty))
    total = round(sum(i.price_total for i in items), 2)
    return ParsedReceipt(
        store_key=store_key, store_name=store_name, date=date, total=total,
        items=items, transaction_id=tx,
        store_address="Musterstraße 1, 50667 Köln" if store_key == "rewe" else None,
    )


def main():
    create_db_and_tables()
    now = datetime.now()
    count = 0

    # ~6 months of weekly REWE shops (plus the occasional midweek top-up)
    for week in range(26):
        date = now - timedelta(days=week * 7 + random.randint(0, 2), hours=random.randint(1, 9))
        receipt = make_receipt("rewe", "REWE Markt", REWE_PRODUCTS, date,
                               random.randint(9, 15), f"demo-rewe-{week}")
        count += ingest._persist(receipt, f"demo_rewe_{week}.pdf", content_hash=f"demo-hash-rewe-{week}")
        if week % 3 == 0:
            topup_date = date + timedelta(days=3)
            if topup_date < now:
                topup = make_receipt("rewe", "REWE Markt", REWE_PRODUCTS, topup_date,
                                     random.randint(4, 7), f"demo-rewe-top-{week}")
                count += ingest._persist(topup, f"demo_rewe_top_{week}.pdf",
                                         content_hash=f"demo-hash-rewe-top-{week}")

    # DM roughly every 3 weeks
    for i in range(9):
        date = now - timedelta(days=i * 21 + random.randint(0, 4))
        receipt = make_receipt("dm", "dm-drogerie markt", DM_PRODUCTS, date,
                               random.randint(3, 6), f"demo-dm-{i}")
        count += ingest._persist(receipt, f"demo_dm_{i}.pdf", content_hash=f"demo-hash-dm-{i}")

    # A few photographed Aldi receipts (the vision-ingest path's store)
    for i in range(4):
        date = now - timedelta(days=i * 40 + 5)
        receipt = make_receipt("aldi", "ALDI SÜD", ALDI_PRODUCTS, date, 3, f"demo-aldi-{i}")
        count += ingest._persist(receipt, f"demo_aldi_{i}.jpg", content_hash=f"demo-hash-aldi-{i}")

    print(f"Seeded {count} new demo receipt(s).")


if __name__ == "__main__":
    main()
