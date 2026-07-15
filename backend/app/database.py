import logging
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from .categories import DEFAULT_SEED
from .meal_profiles import BUILTIN_MEAL_PROFILES
from .models import CategoryMap, Item, MealProfile, Product

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = DATA_DIR / "bonfire.db"

# The database used to be named rewe.db (from before multi-store support).
# Adopt an existing one — including its WAL/SHM sidecars — on first start.
if not SQLITE_PATH.exists() and (DATA_DIR / "rewe.db").exists():
    for suffix in ("", "-wal", "-shm"):
        legacy = DATA_DIR / f"rewe.db{suffix}"
        if legacy.exists():
            legacy.rename(DATA_DIR / f"bonfire.db{suffix}")

sqlite_url = f"sqlite:///{SQLITE_PATH}"

# timeout: how long a connection waits on a locked database (seconds).
engine = create_engine(sqlite_url, connect_args={"timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """Per-connection pragmas: four processes (API, watcher, backup,
    recategorize) share this file, so WAL + a busy timeout make concurrent
    read/write graceful instead of 'database is locked'."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")  # WAL-safe, far fewer fsyncs
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    seed_categories()
    seed_meal_profiles()
    _backfill_products()
    _backfill_source_paths()
    _backfill_product_sizes()


def get_session():
    with Session(engine) as session:
        yield session


def _run_migrations():
    """Idempotent, additive schema evolution — runs at every startup.
    create_all() only creates missing TABLES; new columns/indexes on existing
    tables land here."""
    inspector = inspect(engine)
    if "receipt" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("receipt")}
    with engine.begin() as conn:
        if "store_key" not in columns:
            logger.info("Migrating: adding receipt.store_key column")
            conn.execute(text("ALTER TABLE receipt ADD COLUMN store_key VARCHAR DEFAULT 'other'"))
            conn.execute(text("UPDATE receipt SET store_key = 'rewe' WHERE lower(store_name) LIKE '%rewe%'"))
            conn.execute(text("UPDATE receipt SET store_key = 'dm' WHERE lower(store_name) LIKE '%dm%'"))
            conn.execute(text(
                "UPDATE receipt SET store_key = 'other' WHERE store_key IS NULL OR store_key = ''"
            ))
        if "content_hash" not in columns:
            logger.info("Migrating: adding receipt.content_hash column")
            conn.execute(text("ALTER TABLE receipt ADD COLUMN content_hash VARCHAR"))
        if "review_status" not in columns:
            logger.info("Migrating: adding receipt review/trust columns")
            conn.execute(text("ALTER TABLE receipt ADD COLUMN review_status VARCHAR DEFAULT 'ok'"))
            conn.execute(text("ALTER TABLE receipt ADD COLUMN source_path VARCHAR"))
            conn.execute(text("ALTER TABLE receipt ADD COLUMN parse_warnings JSON DEFAULT '[]'"))
            conn.execute(text(
                "ALTER TABLE receipt ADD COLUMN extraction_source VARCHAR DEFAULT 'pdf_adapter'"
            ))
            # Photographed receipts carry a synthesized "photo-…" transaction id;
            # tag them as vision imports so the review UI can say so.
            conn.execute(text(
                "UPDATE receipt SET extraction_source = 'vision_llm' "
                "WHERE transaction_id LIKE 'photo-%'"
            ))

    item_columns = {col["name"] for col in inspector.get_columns("item")}
    with engine.begin() as conn:
        if "product_id" not in item_columns:
            logger.info("Migrating: adding item.product_id column")
            conn.execute(text("ALTER TABLE item ADD COLUMN product_id INTEGER REFERENCES product(id)"))

    if "product" in inspector.get_table_names():
        product_columns = {col["name"] for col in inspector.get_columns("product")}
        with engine.begin() as conn:
            if "brand" not in product_columns:
                logger.info("Migrating: adding product identity columns")
                conn.execute(text("ALTER TABLE product ADD COLUMN brand VARCHAR"))
                conn.execute(text("ALTER TABLE product ADD COLUMN size_value FLOAT"))
                conn.execute(text("ALTER TABLE product ADD COLUMN size_unit VARCHAR"))

    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receipt_store_key ON receipt (store_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receipt_date ON receipt (date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receipt_review_status ON receipt (review_status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_item_receipt_id ON item (receipt_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_item_name ON item (name)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_item_category ON item (category)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_item_product_id ON item (product_id)"))
        # NULLs don't collide in SQLite unique indexes, so pre-backfill rows are fine.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_receipt_content_hash ON receipt (content_hash)"
        ))


def seed_categories():
    with Session(engine) as session:
        if session.query(CategoryMap).first():
            return
        for name, cat in DEFAULT_SEED.items():
            session.add(CategoryMap(item_key=name, category=cat, is_locked=False))
        session.commit()


def seed_meal_profiles():
    """Insert missing built-in meal profiles (never overwrites user edits).

    Profiles that were seeded as built-ins by an older version but are no
    longer shipped get demoted to regular user profiles: the row (and any
    edits) survives, it just becomes editable/deletable like any other."""
    with Session(engine) as session:
        rows = session.exec(select(MealProfile)).all()
        existing = {p.key for p in rows}
        changed = False
        for key in BUILTIN_MEAL_PROFILES:
            if key not in existing:
                name, prompt = BUILTIN_MEAL_PROFILES[key]
                session.add(MealProfile(key=key, name=name, prompt=prompt, is_builtin=True))
                changed = True
        for row in rows:
            if row.is_builtin and row.key not in BUILTIN_MEAL_PROFILES:
                row.is_builtin = False
                changed = True
        if changed:
            session.commit()


def _backfill_products():
    """One-time: build the product table from existing items and link them.
    No-op once products exist (new items are linked at ingest time)."""
    with Session(engine) as session:
        if session.exec(select(Product).limit(1)).first():
            return
        rows = session.exec(select(Item.name, Item.category)).all()
        if not rows:
            return

        logger.info("Backfilling product table from %s item rows…", len(rows))
        by_key: dict[str, tuple[str, str]] = {}
        for name, cat in rows:
            by_key.setdefault(name.lower().strip(), (name, cat))

        # CategoryMap is the curated name→category source; prefer it.
        cmap = {m.item_key: m.category for m in session.exec(select(CategoryMap)).all()}
        for key, (display, cat) in by_key.items():
            session.add(Product(name_key=key, display_name=display, category=cmap.get(key, cat)))
        session.commit()

        products = {p.name_key: p.id for p in session.exec(select(Product)).all()}
        linked = 0
        for item in session.exec(select(Item)).all():
            pid = products.get(item.name.lower().strip())
            if pid and item.product_id != pid:
                item.product_id = pid
                linked += 1
        session.commit()
        logger.info("Product backfill done: %s products, %s items linked.", len(by_key), linked)


def _backfill_source_paths():
    """One-time: point pre-existing receipts at their archived source file.

    Receipts imported before source tracking existed were still archived under
    ``archive/<store_key>/<pdf_filename>`` — if that file is present, record
    it so the review UI can show the original."""
    from .models import Receipt  # local import to keep module import cheap

    archive = DATA_DIR / "archive"
    if not archive.exists():
        return
    with Session(engine) as session:
        rows = session.exec(select(Receipt).where(Receipt.source_path == None)).all()  # noqa: E711
        if not rows:
            return
        fixed = 0
        for receipt in rows:
            candidate = archive / (receipt.store_key or "unmatched") / receipt.pdf_filename
            if candidate.exists():
                receipt.source_path = f"archive/{receipt.store_key or 'unmatched'}/{receipt.pdf_filename}"
                fixed += 1
        if fixed:
            session.commit()
            logger.info("Backfilled source_path on %s receipts.", fixed)


def _backfill_product_sizes():
    """One-time-ish: parse package sizes out of product names (cheap regex).

    Only touches products that have no size yet, so user edits are never
    overwritten. Runs at every startup but no-ops once everything parseable
    is filled."""
    from .products import parse_size

    with Session(engine) as session:
        rows = session.exec(
            select(Product).where(Product.size_value == None)  # noqa: E711
        ).all()
        changed = 0
        for product in rows:
            size = parse_size(product.display_name)
            if size is not None:
                product.size_value, product.size_unit = size
                changed += 1
        if changed:
            session.commit()
            logger.info("Parsed package size for %s products.", changed)
