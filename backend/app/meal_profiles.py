"""Built-in meal profiles.

Seeded into the ``mealprofile`` table on startup (see ``database``) and used
as a last-resort fallback if the table is empty. A profile's ``prompt`` is
only the persona/instruction block — the ingredient list, constraints and the
JSON output schema are appended in code (``insights.meal_suggestions``), so
user-edited prompts can't break response parsing.
"""

# key -> (display name, prompt)
BUILTIN_MEAL_PROFILES = {
    "adult": (
        "Adults",
        "Suggest simple, tasty dinners for adults.",
    ),
    "toddler": (
        "1-year-old",
        "Suggest meals suitable for a 1-year-old (12+ months). Follow these safety "
        "rules STRICTLY:\n"
        "- NO added salt and NO added sugar (a baby's kidneys can't handle much salt).\n"
        "- No honey.\n"
        "- Avoid choking hazards: quarter grapes and cherry tomatoes lengthwise, no "
        "whole nuts (only smooth nut butter thinly spread), no hard raw chunks — cook "
        "vegetables until soft.\n"
        "- Soft, mashable or easy-to-chew, finger-food-friendly textures.\n"
        "Favour iron-rich, nutrient-dense ingredients and keep it very simple. In each "
        "meal's note, give a short prep/safety tip (texture, how to cut) and flag common "
        "allergens (egg, dairy, wheat, nuts, fish) if the meal contains them.",
    ),
    "family": (
        "Whole family",
        "Suggest meals the whole family can eat together, easily adapted for a "
        "1-year-old. Cook once. For the baby's portion: set some aside BEFORE adding "
        "salt, sugar or spicy seasoning, and mash or cut it into soft small pieces; "
        "avoid choking hazards (quarter grapes/tomatoes, no whole nuts). Use the "
        "baby_adaptation field to explain briefly how to adapt each meal.",
    ),
}
