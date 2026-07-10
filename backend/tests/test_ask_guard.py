"""Tests for the /ask SQL guard.

The LLM generates SQL from natural language; ``_sanitize_sql`` is the only
thing standing between that output and the database, so it gets its own tests.
"""

import pytest
from app.insights import _sanitize_sql


@pytest.mark.parametrize("sql", [
    "SELECT name, price_total FROM item",
    "select sum(total_amount) from receipt where date >= '2026-01-01'",
    "SELECT i.name FROM item i JOIN receipt r ON i.receipt_id = r.id",
    "WITH monthly AS (SELECT total_amount FROM receipt) SELECT * FROM monthly",
])
def test_accepts_read_only_selects(sql):
    assert _sanitize_sql(sql) is not None


def test_strips_markdown_fences_and_semicolon():
    assert _sanitize_sql("```sql\nSELECT 1 FROM item;\n```") == "SELECT 1 FROM item"


@pytest.mark.parametrize("sql", [
    "UPDATE item SET price_total = 0",
    "DELETE FROM receipt",
    "DROP TABLE item",
    "SELECT 1 FROM item; DROP TABLE receipt",          # stacked statements
    "SELECT 1 FROM item -- comment",                   # comment smuggling
    "SELECT 1 FROM item /* comment */",
    "PRAGMA table_info(receipt)",
    "SELECT sql FROM sqlite_master",                   # schema disclosure
    "SELECT * FROM pragma_table_info('receipt')",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "INSERT INTO item (name) VALUES ('x')",
])
def test_rejects_unsafe_sql(sql):
    assert _sanitize_sql(sql) is None


def test_cte_names_are_allowed_but_unknown_tables_are_not():
    assert _sanitize_sql("WITH t AS (SELECT 1 FROM item) SELECT * FROM t") is not None
    assert _sanitize_sql("SELECT * FROM category_map") is None
