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

    item_columns = {col["name"] for col in inspector.get_columns("item")}
    with engine.begin() as conn:
        if "product_id" not in item_columns:
            logger.info("Migrating: adding item.product_id column")
            conn.execute(text("ALTER TABLE item ADD COLUMN product_id INTEGER REFERENCES product(id)"))

    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receipt_store_key ON receipt (store_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_receipt_date ON receipt (date)"))
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
    """Insert missing built-in meal profiles (never overwrites user edits)."""
    with Session(engine) as session:
        existing = {p.key for p in session.exec(select(MealProfile)).all()}
        missing = [key for key in BUILTIN_MEAL_PROFILES if key not in existing]
        for key in missing:
            name, prompt = BUILTIN_MEAL_PROFILES[key]
            session.add(MealProfile(key=key, name=name, prompt=prompt, is_builtin=True))
        if missing:
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
