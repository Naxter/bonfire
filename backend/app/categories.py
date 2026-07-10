"""Single source of truth for the grocery category taxonomy.

Both the categorizer (LLM validation) and the database seeder import from here,
so the seed data can never drift from the set of valid categories again.
"""

# Canonical, highly specific supermarket categories.
VALID_CATEGORIES = [
    "Obst & Gemüse",
    "Molkereiprodukte & Eier",
    "Fleisch, Fisch & Veggie",
    "Backwaren",
    "Tiefkühlprodukte",
    "Nährmittel & Vorrat",          # Rice, Pasta, Flour, Oats, Baking ingredients
    "Gewürze, Saucen & Öle",        # Ketchup, Mayo, Pesto, Salt, Spices, Vinegar
    "Konserven & Fertiggerichte",   # Canned soups, Ravioli, Pickles
    "Süßwaren & Snacks",            # Chips, Chocolate, Nuts, Cookies
    "Getränke",
    "Haushalt & Non-Food",          # Cleaning supplies, Plants, Kitchenware, Candles
    "Drogerie & Kosmetik",          # Tissues, Soap, Hygiene
    "Gutscheine & Rabatte",         # Gift cards, Coupons, Discounts
    "Pfand",
    "Sonstiges",
]

# Seed mapping of common item keywords -> canonical category.
# Every value here MUST be a member of VALID_CATEGORIES (asserted below).
DEFAULT_SEED = {
    "banane": "Obst & Gemüse",
    "apfel": "Obst & Gemüse",
    "milch": "Molkereiprodukte & Eier",
    "butter": "Molkereiprodukte & Eier",
    "käse": "Molkereiprodukte & Eier",
    "brot": "Backwaren",
    "brötchen": "Backwaren",
    "hähnchen": "Fleisch, Fisch & Veggie",
    "hackfleisch": "Fleisch, Fisch & Veggie",
    "cola": "Getränke",
    "wasser": "Getränke",
    "bier": "Getränke",
    "toilettenpapier": "Haushalt & Non-Food",
}

# Fail fast if a seed value is ever mistyped.
_invalid = {v for v in DEFAULT_SEED.values() if v not in VALID_CATEGORIES}
assert not _invalid, f"DEFAULT_SEED contains non-canonical categories: {_invalid}"
