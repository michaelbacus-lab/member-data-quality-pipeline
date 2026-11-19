# Member Data Quality Pipeline

A cross-platform Python pipeline that cleans, validates, and aggregates synthetic membership data.

## Requirements

- Python 3.9 or newer
- pip

## Setup

From the repository root:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On systems where `python` is not available, use `python3` instead.

## Run

```bash
python src/run_pipeline.py
```

The pipeline works on Windows, macOS, and Linux. It uses `pathlib` and paths relative to the repository, so no machine-specific absolute paths are required.

Scripts may also be run individually:

```bash
python src/clean_customers.py
python src/clean_amortization.py
python src/clean_membership_fee.py
python src/clean_proc_fee.py
```

Run `clean_customers.py` before `clean_membership_fee.py`, because the membership script joins to its processed output.

## Outputs

- Raw inputs: `data/raw/`
- Processed CSV files: `data/processed/`
- Aggregated Excel workbooks: `data/aggregated-xlsx/`
- Text reports: `reports/`

## Data Notice

This project uses synthetic demonstration data and contains no production datasets, customer records, or financial records.
