"""SQLite storage. One file, no ORM: the schema is small and stable."""
import os
import sqlite3
import threading

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "local-tracker.db")


def configure(data_dir: str):
    """Points the database somewhere else (used when running inside Home Assistant)."""
    global DATA_DIR, DB_PATH
    DATA_DIR = data_dir
    DB_PATH = os.path.join(data_dir, "local-tracker.db")
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fiber")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    kcal_goal REAL NOT NULL DEFAULT 2000,
    protein_goal REAL NOT NULL DEFAULT 100,
    carbs_goal REAL NOT NULL DEFAULT 250,
    fat_goal REAL NOT NULL DEFAULT 70,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
-- All nutrient values are per 100 g.
CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_alt TEXT,
    brand TEXT,
    barcode TEXT,
    kcal REAL NOT NULL DEFAULT 0,
    protein REAL NOT NULL DEFAULT 0,
    carbs REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    fiber REAL NOT NULL DEFAULT 0,
    serving_g REAL,
    source TEXT NOT NULL DEFAULT 'custom',   -- custom | off | slv | usda | recipe | photo
    source_id TEXT,
    search TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS foods_source ON foods(source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS foods_barcode ON foods(barcode);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    servings REAL NOT NULL DEFAULT 1,
    final_weight_g REAL,                     -- weighed after cooking; NULL = sum of raw ingredients
    food_id INTEGER REFERENCES foods(id),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recipe_items (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    food_id INTEGER NOT NULL REFERENCES foods(id),
    grams REAL NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    meal TEXT NOT NULL,
    food_id INTEGER NOT NULL REFERENCES foods(id),
    grams REAL NOT NULL,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS entries_user_date ON entries(user_id, date);
-- The meal plan is shared by the household.
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    meal TEXT NOT NULL,
    food_id INTEGER NOT NULL REFERENCES foods(id),
    grams REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS plan_date ON plan(date);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        _local.conn = c
    return c


# Columns added after the first release; added to existing databases on start.
MIGRATIONS = [
    ("users", "ha_user_id", "TEXT"),
    ("recipes", "source_url", "TEXT"),
    ("recipes", "mealie_id", "TEXT"),
    ("recipes", "mealie_slug", "TEXT"),
    ("plan", "mealie_id", "INTEGER"),
    ("plan", "origin", "TEXT NOT NULL DEFAULT 'local'"),  # 'local' or 'mealie' (where the item was planned)
]


def init():
    os.makedirs(DATA_DIR, exist_ok=True)
    # The app used to be called Matkoll; pick up a database saved under the old name.
    old = os.path.join(DATA_DIR, "matkoll.db")
    if os.path.exists(old) and not os.path.exists(DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(old + suffix):
                os.rename(old + suffix, DB_PATH + suffix)
    c = conn()
    c.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    c.execute("CREATE INDEX IF NOT EXISTS plan_mealie ON plan(mealie_id)")
    c.execute("UPDATE plan SET origin='local' WHERE origin <> 'mealie' AND origin <> 'local'")
    c.commit()


def q(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql, args=()):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def search_key(*parts) -> str:
    return " ".join(p for p in parts if p).lower()


def upsert_food(f: dict, commit=True) -> int:
    """Insert a food, or update it when (source, source_id) already exists. Returns its id."""
    c = conn()
    vals = {k: round(float(f.get(k) or 0), 2) for k in NUTRIENTS}
    s = search_key(f.get("name"), f.get("name_alt"), f.get("brand"), f.get("barcode"))
    existing = None
    if f.get("source_id") is not None:
        existing = c.execute(
            "SELECT id FROM foods WHERE source=? AND source_id=?", (f["source"], str(f["source_id"]))
        ).fetchone()
    if existing:
        fid = existing["id"]
        c.execute(
            "UPDATE foods SET name=?, name_alt=?, brand=?, barcode=COALESCE(?, barcode), kcal=?, protein=?, "
            "carbs=?, fat=?, fiber=?, serving_g=COALESCE(?, serving_g), search=? WHERE id=?",
            (f["name"], f.get("name_alt"), f.get("brand"), f.get("barcode"), vals["kcal"], vals["protein"],
             vals["carbs"], vals["fat"], vals["fiber"], f.get("serving_g"), s, fid),
        )
    else:
        cur = c.execute(
            "INSERT INTO foods (name, name_alt, brand, barcode, kcal, protein, carbs, fat, fiber, serving_g, "
            "source, source_id, search, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["name"], f.get("name_alt"), f.get("brand"), f.get("barcode"), vals["kcal"], vals["protein"],
             vals["carbs"], vals["fat"], vals["fiber"], f.get("serving_g"), f.get("source", "custom"),
             None if f.get("source_id") is None else str(f["source_id"]), s, f.get("created_by")),
        )
        fid = cur.lastrowid
    if commit:
        c.commit()
    return fid


def get_setting(key, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r and r["value"] not in (None, "") else default


def set_setting(key, value):
    run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
