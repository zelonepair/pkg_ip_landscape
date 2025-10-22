"""Project-level configuration constants."""

from __future__ import annotations

from datetime import datetime, timezone

BIGQUERY_TABLE = "patents-public-data.patents.publications"

_CURRENT_YEAR = datetime.now(timezone.utc).year
DEFAULT_START_YEAR = _CURRENT_YEAR - 3
DEFAULT_END_YEAR = _CURRENT_YEAR
DEFAULT_LIMIT = 100
DEFAULT_DESCRIPTION_WORD_LIMIT = 800
DEFAULT_GCP_PROJECT_ID = "axial-analyzer-475800-v4"

CPC_PREFIXES = [
    "b65d25/14",
    "c09d7/65",
    "c09d163",
    "c09d167",
]

KEYWORD_PHRASES = [
    "food can",
    "beverage can",
    "food container",
    "beverage container",
    "metal can",
    "metal container",
    "can liner",
    "can coating",
]

COATING_CHOICES = [
    "Epoxy (BPA)",
    "Epoxy (BPF)",
    "Polyester",
    "Acrylic",
    "PVC",
    "Polyolefin",
    "Oleoresin/Phenolic",
    "Hybrid",
    "BPA-Free (Unspecified)",
]

DEFAULT_OPENROUTER_MODEL = "x-ai/grok-4-fast"
DEFAULT_OPENROUTER_TIMEOUT = 30.0
DEFAULT_OPENROUTER_DELAY = 1.0
DEFAULT_MAX_RETRIES = 3

ENV_OPENROUTER_API_KEY = "OPENROUTER_API_KEY"
ENV_OPENROUTER_APP_URL = "OPENROUTER_APP_URL"
ENV_OPENROUTER_TITLE = "OPENROUTER_TITLE"
ENV_GCP_PROJECT_ID = "GOOGLE_CLOUD_PROJECT"
