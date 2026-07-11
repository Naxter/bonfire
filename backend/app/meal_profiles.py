"""Built-in meal profiles.

Seeded into the ``mealprofile`` table on startup (see ``database``) and used
as a last-resort fallback if the table is empty. A profile's ``prompt`` is
only the persona/instruction block — the ingredient list, constraints and the
JSON output schema are appended in code (``insights.meal_suggestions``), so
user-edited prompts can't break response parsing.

These are deliberately generic starting points: edit them or add your own in
the dashboard (household-specific needs — diets, allergies, small children —
belong in your own profiles, not in the code).
"""

# key -> (display name, prompt)
BUILTIN_MEAL_PROFILES = {
    "adult": (
        "Adults",
        "Suggest simple, tasty dinners for adults.",
    ),
    "family": (
        "Whole family",
        "Suggest meals the whole family can eat together — broadly liked, easy "
        "to scale up, nothing too spicy. Use the adaptation field to note how "
        "to tweak a meal for picky eaters or different portions.",
    ),
}
