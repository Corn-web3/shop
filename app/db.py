"""Product access.

Source is chosen at runtime: if DATABASE_URL is set, introspect & load from the
read-only Postgres (see db_postgres.py); otherwise fall back to the built-in
mock so the service still starts with no DB (a README requirement). The
normalized Product shape is identical either way, so nothing downstream cares.
"""

import threading
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional

from app.config import settings


@dataclass
class Product:
    sku: str
    title: str
    brand: str
    category: str
    color: str
    material: str
    unit_count: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_g: float
    price: float
    image_urls: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_MOCK: Dict[str, Product] = {
    "SSB-001": Product(
        sku="SSB-001", title="Insulated Water Bottle 500ml",
        brand="SuperSonicBrick", category="Sports & Outdoors / Water Bottles",
        color="Matte Black", material="Stainless Steel", unit_count=1,
        length_cm=7.0, width_cm=7.0, height_cm=25.0, weight_g=320.0, price=19.99),
    "SSB-002": Product(
        sku="SSB-002", title="Silicone Travel Cup 350ml",
        brand="SuperSonicBrick", category="Sports & Outdoors / Travel Mugs",
        color="Forest Green", material="Food-Grade Silicone", unit_count=1,
        length_cm=8.0, width_cm=8.0, height_cm=12.0, weight_g=180.0, price=14.99),
    "SSB-003": Product(
        sku="SSB-003", title="Stackable Storage Brick 2L",
        brand="SuperSonicBrick", category="Home & Kitchen / Food Storage",
        color="Sky Blue", material="BPA-Free Polypropylene", unit_count=1,
        length_cm=20.0, width_cm=14.0, height_cm=10.0, weight_g=240.0, price=12.49),
}

_lock = threading.Lock()
_seed: Optional[Dict[str, Product]] = None


def _is_mysql() -> bool:
    return bool(settings.database_url) and settings.database_url.startswith("mysql")


def _load_seed() -> Dict[str, Product]:
    """Load the seed set once: real DB if DATABASE_URL is set, else the mock."""
    global _seed
    with _lock:
        if _seed is not None:
            return _seed
        url = settings.database_url
        if not url:
            _seed = dict(_MOCK)
        elif _is_mysql():
            from app import db_mysql
            _seed = db_mysql.load_seed(url)
        else:
            from app import db_postgres
            _seed = db_postgres.load_all(url, settings.products_table)
        return _seed


def source() -> str:
    if not settings.database_url:
        return "mock"
    return "mysql" if _is_mysql() else "postgres"


def list_skus() -> List[str]:
    return list(_load_seed().keys())


def load_product(sku: str) -> Product:
    seed = _load_seed()
    if sku in seed:
        return seed[sku]
    # not in the seed set — fetch this single SKU directly (robust to unseen SKUs)
    if _is_mysql():
        from app import db_mysql
        p = db_mysql.fetch_one(settings.database_url, sku)
        if p:
            return p
    raise KeyError(sku)
