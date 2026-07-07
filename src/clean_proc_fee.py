"""
Cleans, transforms, and aggregates the processing-fee (proc_fee) ledger.

Each row = one processing-fee payment/entry for one MEMBER (foreign key into
customers_info.csv). This is money data, so nothing here estimates or fills in
a monetary value that wasn't in the source - anything uncertain is flagged in
its own column instead.

Issues found and handled:
- 7 rows have no MEMBER at all (and usually no AMOUNT/date either) - these are
  empty stub records. Kept in the cleaned file, flagged, excluded from
  aggregation totals.
- 37 rows have a MEMBER but a blank AMOUNT - this means no payment amount was
  ever recorded for that entry (not the same as a genuine 0). Flagged
  separately from the 20 rows that explicitly record AMOUNT = 0.
- CONTROL NO sometimes contains the same number duplicated across line breaks
  (e.g. "008\r\n008"), or one instance of stray garbage characters mixed with
  line breaks. Cleaned to a single de-duplicated value. One row legitimately
  lists two different control numbers ("141,148") - left as-is.
- Created By / Updated By have inconsistent casing (LENCY / lency) - standardized.
- All dates converted from DD/MM/YYYY to ISO YYYY-MM-DD.
"""
import pandas as pd
import numpy as np
import re

SRC = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\datasets\processing_fee.csv"
OUT_CSV = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\processing_fee_processed.csv"
OUT_XLSX = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\processing_fee_aggregated.xlsx"
OUT_REPORT = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\processing_fee_cleaning_report.txt"

report = []


def log(msg=""):
    report.append(msg)


def clean_control_no(val):
    if pd.isna(val):
        return np.nan
    # split on any run of whitespace/newlines
    tokens = re.split(r"[\r\n\s]+", str(val).strip())
    # keep only tokens that look like a control number (digits, at least 1 char)
    tokens = [t for t in tokens if re.fullmatch(r"\d+", t)]
    if not tokens:
        return np.nan
    # de-duplicate while preserving order
    seen = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return ",".join(seen)


def main():
    df = pd.read_csv(SRC, dtype=str, encoding="utf-8")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from source.")

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace("", np.nan)

    # --- Numeric columns ---
    df["MEMFEE ID"] = pd.to_numeric(df["MEMFEE ID"], errors="coerce")
    df["MEMBER"] = pd.to_numeric(df["MEMBER"], errors="coerce")
    df["AMOUNT"] = pd.to_numeric(df["AMOUNT"], errors="coerce")

    dup_ids = df["MEMFEE ID"].duplicated().sum()
    log(f"MEMFEE ID duplicates: {dup_ids} (should be 0 - it's the row's primary key).")

    # --- Dates ---
    for col in ["PAYED DATE", "DATE Created", "Date Updated"]:
        before = df[col].notna().sum()
        df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce")
        lost = before - df[col].notna().sum()
        if lost:
            log(f"{col}: {lost} value(s) didn't match DD/MM/YYYY and were blanked.")
        df[col] = df[col].dt.strftime("%Y-%m-%d")

    # --- Control numbers ---
    before_notna = df["CONTROL NO"].notna().sum()
    df["CONTROL NO"] = df["CONTROL NO"].apply(clean_control_no)
    log(f"CONTROL NO: cleaned duplicated/garbled entries "
        f"({before_notna} non-null before -> {df['CONTROL NO'].notna().sum()} after; "
        f"drops are cells that contained only stray characters, no real number).")

    # --- Names / free text casing ---
    for col in ["Created By", "Updated By"]:
        df[col] = df[col].apply(lambda x: x.title() if isinstance(x, str) else x)

    df["REMARKS"] = df["REMARKS"].apply(lambda x: re.sub(r"\s+", " ", x).strip() if isinstance(x, str) else x)

    # --- Flags (no monetary value is invented; everything uncertain is flagged) ---
    df["FLAG_EMPTY_RECORD"] = df["MEMBER"].isna()
    df["FLAG_MISSING_AMOUNT"] = df["MEMBER"].notna() & df["AMOUNT"].isna()
    df["FLAG_ZERO_AMOUNT"] = df["AMOUNT"] == 0
    df["FLAG_MISSING_PAYED_DATE"] = df["MEMBER"].notna() & df["AMOUNT"].notna() & df["AMOUNT"] > 0
    df["FLAG_MISSING_PAYED_DATE"] = df["FLAG_MISSING_PAYED_DATE"] & df["PAYED DATE"].isna()

    log(f"\n{df['FLAG_EMPTY_RECORD'].sum()} row(s) are empty stub records (no MEMBER) - "
        f"flagged, excluded from aggregation.")
    log(f"{df['FLAG_MISSING_AMOUNT'].sum()} row(s) have a MEMBER but no AMOUNT recorded - "
        f"flagged, treated as 0 in aggregation totals but kept visibly separate from real "
        f"zero-amount entries.")
    log(f"{df['FLAG_ZERO_AMOUNT'].sum()} row(s) explicitly record AMOUNT = 0.")
    log(f"{df['FLAG_MISSING_PAYED_DATE'].sum()} row(s) have a positive AMOUNT but no PAYED DATE.")

    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    log(f"\nSaved cleaned row-level file: {OUT_CSV} ({len(df)} rows).")

    # ---------------- Transformations / Aggregations ----------------
    valid = df[~df["FLAG_EMPTY_RECORD"]].copy()
    valid["AMOUNT_FILLED"] = valid["AMOUNT"].fillna(0)  # for summation only; original AMOUNT untouched
    valid["PAY_YEAR"] = pd.to_datetime(valid["PAYED DATE"], errors="coerce").dt.year
    valid["PAY_MONTH"] = pd.to_datetime(valid["PAYED DATE"], errors="coerce").dt.month

    by_member = (valid.groupby("MEMBER", as_index=False)
                 .agg(NUM_PAYMENTS=("MEMFEE ID", "count"),
                      TOTAL_PAID=("AMOUNT_FILLED", "sum"),
                      FIRST_PAYMENT=("PAYED DATE", "min"),
                      LAST_PAYMENT=("PAYED DATE", "max"))
                 .sort_values("MEMBER"))

    by_year_month = (valid.dropna(subset=["PAY_YEAR"])
                     .groupby(["PAY_YEAR", "PAY_MONTH"], as_index=False)
                     .agg(TOTAL_COLLECTED=("AMOUNT_FILLED", "sum"),
                          NUM_PAYMENTS=("MEMFEE ID", "count"))
                     .sort_values(["PAY_YEAR", "PAY_MONTH"]))
    by_year_month["PAY_YEAR"] = by_year_month["PAY_YEAR"].astype(int)
    by_year_month["PAY_MONTH"] = by_year_month["PAY_MONTH"].astype(int)

    by_year = (valid.dropna(subset=["PAY_YEAR"])
               .groupby("PAY_YEAR", as_index=False)
               .agg(TOTAL_COLLECTED=("AMOUNT_FILLED", "sum"), NUM_PAYMENTS=("MEMFEE ID", "count")))
    by_year["PAY_YEAR"] = by_year["PAY_YEAR"].astype(int)

    grand_total = valid["AMOUNT_FILLED"].sum()
    log(f"\nGRAND TOTAL processing fees collected (empty stub rows excluded, "
        f"missing-amount rows counted as 0): {grand_total:,.2f} across "
        f"{valid['MEMFEE ID'].count()} entries, {by_member.shape[0]} distinct members.")

    flags_sheet = df[df["FLAG_EMPTY_RECORD"] | df["FLAG_MISSING_AMOUNT"] |
                      df["FLAG_MISSING_PAYED_DATE"]][
        ["MEMFEE ID", "MEMBER", "AMOUNT", "PAYED DATE", "CONTROL NO", "REMARKS",
         "FLAG_EMPTY_RECORD", "FLAG_MISSING_AMOUNT", "FLAG_MISSING_PAYED_DATE"]
    ]

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        by_member.to_excel(writer, sheet_name="By Member", index=False)
        by_year_month.to_excel(writer, sheet_name="By Year-Month", index=False)
        by_year.to_excel(writer, sheet_name="By Year", index=False)
        flags_sheet.to_excel(writer, sheet_name="Data Quality Flags", index=False)

    log(f"Saved aggregation workbook: {OUT_XLSX} "
        f"(sheets: By Member, By Year-Month, By Year, Data Quality Flags).")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
