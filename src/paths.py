"""Shared project paths for the data quality pipeline."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA = PROJECT_ROOT / "data" / "processed"
AGGREGATED_DATA = PROJECT_ROOT / "data" / "aggregated-xlsx"
REPORTS = PROJECT_ROOT / "reports"

for directory in (PROCESSED_DATA, AGGREGATED_DATA, REPORTS):
    directory.mkdir(parents=True, exist_ok=True)
