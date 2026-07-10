"""Re-run categorization over items already in the database.

Use after you improve the prompt, switch LLM provider/model, or edit the
taxonomy — the CategoryMap cache means existing items are otherwise never
re-evaluated. Manual (locked) overrides are preserved.

    python recategorize.py            # only Uncategorized / Sonstiges items
    python recategorize.py --all      # every item (slower, one LLM call per name)
"""

import argparse
import logging

import app.config  # noqa: F401  (loads repo-root .env)
from app.categorizer import recategorize
from app.database import create_db_and_tables

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recategorize stored items via the LLM.")
    parser.add_argument("--all", action="store_true", help="revisit every item, not just uncategorized ones")
    args = parser.parse_args()

    create_db_and_tables()
    summary = recategorize(scope="all" if args.all else "missing")
    print(
        f"Processed {summary['names_processed']} name(s): "
        f"{summary['names_updated']} changed, {summary['items_updated']} item row(s) updated, "
        f"{summary['skipped_locked']} locked name(s) skipped."
    )


if __name__ == "__main__":
    main()
