"""Read-only MySQL source for the real SSB `fbm_sku` table.

The actual SSB database is MySQL (not Postgres as the brief's wording implied):
db `boxing`, table `fbm_sku`, ~7388 SKUs. Units are implicit in the column
*semantics* (dimensions in inches, weight in pounds) rather than in the value
strings, so we convert explicitly here. `remark` ("PACK OF N" / "COMBO") carries
the pack quantity. Read-only: a read-only session is requested and only SELECT
is ever issued.

A small seed set powers GET /products; any individual SKU (including ones not in
the seed) is fetched on demand by load_product -> fetch_one, so the service is
robust to unseen SKUs.
"""

import re
from urllib.parse import urlparse, unquote

from app.db import Product

INCH_TO_CM = 2.54
LB_TO_G = 453.592
TABLE = "fbm_sku"

# the columns we read (normalized name -> source column)
SELECT_COLS = ("sku, title, brand, sku_category, sku_color, sku_composition, "
               "sku_length, sku_width, sku_height, sku_weight, remark, "
               "image_url, cost, sku_description")


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pack_count(remark) -> int:
    m = re.search(r"pack of\s*(\d+)", str(remark or ""), re.I)
    return int(m.group(1)) if m else 1  # "COMBO" / blank -> 1


def normalize(row: dict) -> Product:
    img = (row.get("image_url") or "").strip()
    return Product(
        sku=str(row.get("sku") or "").strip(),
        title=(row.get("title") or "").strip(),
        brand=(row.get("brand") or "").strip(),
        category=(row.get("sku_category") or "").strip(),
        color=(row.get("sku_color") or "").strip(),
        material=(row.get("sku_composition") or "").strip(),
        unit_count=_pack_count(row.get("remark")),
        length_cm=round(_f(row.get("sku_length")) * INCH_TO_CM, 2),
        width_cm=round(_f(row.get("sku_width")) * INCH_TO_CM, 2),
        height_cm=round(_f(row.get("sku_height")) * INCH_TO_CM, 2),
        weight_g=round(_f(row.get("sku_weight")) * LB_TO_G, 1),
        price=round(_f(row.get("cost")), 2),  # only monetary field; cost (USD)
        image_urls=[img] if img.startswith("http") else [],
        description=(row.get("sku_description") or "").strip(),
    )


def _conn_params(database_url: str) -> dict:
    u = urlparse(database_url)
    return dict(host=u.hostname, port=u.port or 3306,
                user=unquote(u.username or ""), password=unquote(u.password or ""),
                database=(u.path or "/").lstrip("/") or None)


def _connect(database_url: str):
    import pymysql  # lazy: only needed in MySQL mode
    conn = pymysql.connect(charset="utf8mb4", connect_timeout=15, read_timeout=60,
                           cursorclass=pymysql.cursors.DictCursor,
                           **_conn_params(database_url))
    try:  # belt-and-suspenders read-only enforcement
        conn.query("SET SESSION TRANSACTION READ ONLY")
    except Exception:
        pass
    return conn


def load_seed(database_url: str, limit: int = 200) -> dict:
    conn = _connect(database_url)
    products = {}
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {SELECT_COLS} FROM {TABLE} "
                        f"WHERE title IS NOT NULL AND title <> '' LIMIT %s", (limit,))
            for row in cur.fetchall():
                p = normalize(row)
                if p.sku:
                    products[p.sku] = p
    finally:
        conn.close()
    return products


def fetch_one(database_url: str, sku: str):
    conn = _connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {SELECT_COLS} FROM {TABLE} WHERE sku = %s LIMIT 1", (sku,))
            row = cur.fetchone()
    finally:
        conn.close()
    return normalize(row) if row else None


def _jsonable(v):
    """Make a raw DB value JSON-serializable (bytes/bit, Decimal, datetime)."""
    import datetime as _dt
    from decimal import Decimal
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(v, "big") if len(v) == 1 else v.hex()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    return v


def fetch_one_raw(database_url: str, sku: str):
    """Every column of the fbm_sku row, JSON-safe. Read-only SELECT *."""
    conn = _connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {TABLE} WHERE sku = %s LIMIT 1", (sku,))
            row = cur.fetchone()
    finally:
        conn.close()
    return {k: _jsonable(v) for k, v in row.items()} if row else None
