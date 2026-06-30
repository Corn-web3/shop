"""Lazy settings. Reads .env once at import, then exposes typed getters.

This replaces the slice's import-time module-level env reads (which were
fragile about import ordering) with a single settings object that callers query
at call time.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv():
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _env(*names, default=None):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


class Settings:
    @property
    def llm_base_url(self):
        return _env("LLM_BASE_URL", "OPENAI_BASE_URL")

    @property
    def llm_api_key(self):
        return _env("LLM_API_KEY", "OPENAI_API_KEY")

    @property
    def llm_model(self):
        return _env("LLM_MODEL", default="gpt-5.4-mini")

    @property
    def vision_model(self):
        return _env("VISION_MODEL", default=self.llm_model)

    @property
    def image_base_url(self):
        return _env("IMAGE_BASE_URL", "OPENAI_BASE_URL")

    @property
    def image_api_key(self):
        return _env("IMAGE_API_KEY", "OPENAI_API_KEY")

    @property
    def image_model(self):
        return _env("IMAGE_MODEL", default="gpt-image-2")

    @property
    def search_api_key(self):
        return _env("TAVILY_API_KEY", "SEARCH_API_KEY")

    @property
    def database_url(self):
        return _env("DATABASE_URL")

    @property
    def products_table(self):
        return _env("PRODUCTS_TABLE")  # optional override; else auto-detect

    @property
    def db_ready(self):
        return bool(self.database_url)

    @property
    def llm_ready(self):
        return bool(self.llm_api_key)

    @property
    def image_ready(self):
        return bool(self.image_api_key)

    @property
    def search_ready(self):
        return bool(self.search_api_key)


settings = Settings()
OUT_DIR = os.path.join(_ROOT, "app", "out")
os.makedirs(OUT_DIR, exist_ok=True)

MAX_UNITS = 12  # largest pack we'll render/generate (guards cost + synth blowup)
