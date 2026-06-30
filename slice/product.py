"""Mock product record for the vertical slice.

Mirrors the columns the README says the SSB PostgreSQL table roughly has:
  sku / title / brand / category / color / material / unit_count / dimensions / weight / image_urls / price
Once we get the read-only connection string this gets replaced by a real
introspect + load. The *shape* below is the normalized record the rest of the
pipeline depends on, so swapping the source later is a one-file change.
"""

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Product:
    sku: str
    title: str
    brand: str
    category: str
    color: str
    material: str
    unit_count: int                 # how many physical items in one SKU
    length_cm: float
    width_cm: float
    height_cm: float
    weight_g: float
    price: float
    image_urls: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# A single, discrete product so "3-pack" unambiguously means "3 visible items".
MOCK = Product(
    sku="SSB-001",
    title="Insulated Water Bottle 500ml",
    brand="SuperSonicBrick",
    category="Sports & Outdoors / Water Bottles",
    color="Matte Black",
    material="Stainless Steel",
    unit_count=1,
    length_cm=7.0,
    width_cm=7.0,
    height_cm=25.0,
    weight_g=320.0,
    price=19.99,
    image_urls=[],
)


def load_product(sku: str) -> Product:
    """Stand-in for the real DB load. Only knows one SKU for now."""
    if sku != MOCK.sku:
        raise KeyError(f"slice only has mock SKU {MOCK.sku!r}, got {sku!r}")
    return MOCK
