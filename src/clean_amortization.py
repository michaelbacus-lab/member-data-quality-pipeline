"""
Cleans and aggregates the amortization/payment-schedule export.

Key facts discovered about this file (see cleaning_report.txt for details):
- "FULLNAME" actually holds the MEMBER ID (a foreign key into customers_info.csv),
  not a name. Renamed to "MEMBER ID" for clarity; original values are unchanged.
- "YEAR SUM" actually holds the YEAR the row's payment schedule applies to.
  Renamed to "YEAR".
- Each row = one member's monthly payment schedule for one YEAR.
- TOTAL == sum of the 12 month columns for all 483 rows (verified, 0 mismatches).
- TOTAL PENALTY == sum of the 12 penalty columns for all 483 rows (verified, 0
  mismatches) - penalty is a flat monthly amount repeated across all 12 months,
  not a month-varying figure, which is why every month's column total is identical.
- "*_CON NO" (control/OR number) columns sometimes hold more than one receipt
  number per cell (comma-separated), representing multiple payments recorded
  in the same cell. These are left as-is (not split) but flagged.
- "*_PAYED DATE" columns hold only the day-of-month; combined with YEAR and the
  column's month to build a real date. Day "0" or blank means no date recorded.
- 1 row (ID 491) has YEAR=0 and every amount at 0 - an effectively empty/invalid
  record, flagged rather than deleted.
- 40 rows (53 month-cells) have a payment amount but no payment date - flagged
  for manual review rather than guessed at, since in some cases the actual date
  is only recoverable from free-text REMARKS (e.g. "JAN. 11 & JAN. 19").

Because this is real payment data, nothing here silently changes any monetary
value. All arithmetic is verified against the source, and anything that could
not be safely resolved is flagged in a separate sheet/column rather than altered.
"""
import pandas as pd
import numpy as np
import re

SRC = "D:\\Documents Nato\\RAHUR\\ML Foundation Data Cleaning with Python\\raw_data\\amortization.csv"
OUT_CSV = "D:\\Documents Nato\\RAHUR\\ML Foundation Data Cleaning with Python\\processed_data\\amortization_processed.csv"
OUT_XLSX = "D:\\Documents Nato\\RAHUR\\ML Foundation Data Cleaning with Python\\processed_data\\amortization_aggregated.xlsx"
OUT_REPORT = "D:\\Documents Nato\\RAHUR\\ML Foundation Data Cleaning with Python\\processed_data\\amortization_report.txt"

MONTHS = [("JANUARY", "JAN", "JAN", 1), ("FEBRUARY", "FEB", "FEB", 2), ("MARCH", "MAR", "MAR", 3),
          ("APRIL", "APR", "APR", 4), ("MAY", "MAY", "MAY", 5), ("JUNE", "JUN", "JUN", 6),
          ("JULY", "JULY", "JUL", 7), ("AUGUST", "AUG", "AUG", 8), ("SEPTEMBER", "SEP", "SEP", 9),
          ("OCTOBER", "OCT", "OCT", 10), ("NOVEMBER", "NOV", "NOV", 11), ("DECEMBER", "DEC", "DEC", 12)]
# tuple = (month column, PAYED DATE prefix, CON NO/REMARKS prefix, month number)

report = []


def log(msg=""):
    report.append(msg)


def build_date(year, month_num, day):
    if pd.isna(year) or year in (0, "0") or pd.isna(day):
        return np.nan
    try:
        day = int(float(day))
        year = int(float(year))
        if day <= 0:
            return np.nan
        return pd.Timestamp(year=year, month=month_num, day=day).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return np.nan


def main():
    df = pd.read_csv(SRC, dtype=str, encoding="utf-8")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from source.")

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace("", np.nan)

    df = df.rename(columns={"FULLNAME": "MEMBER ID", "YEAR SUM": "YEAR",
                             "Date updated": "Date Updated"})

    numeric_cols = ["ID", "MEMBER ID", "YEAR"] + [m[0] for m in MONTHS] + ["TOTAL"] + \
                   [f"{m[0]} PENALTY" for m in MONTHS] + ["TOTAL PENALTY", "NOT COUNTED"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- Validate TOTAL and TOTAL PENALTY against the source month columns ---
    calc_total = df[[m[0] for m in MONTHS]].sum(axis=1)
    total_mismatch = (calc_total - df["TOTAL"]).abs() > 0.01
    log(f"TOTAL validation: {total_mismatch.sum()} row(s) where sum(months) != TOTAL "
        f"(out of {len(df)}).")

    calc_pen = df[[f"{m[0]} PENALTY" for m in MONTHS]].sum(axis=1)
    pen_mismatch = (calc_pen - df["TOTAL PENALTY"]).abs() > 0.01
    log(f"TOTAL PENALTY validation: {pen_mismatch.sum()} row(s) where sum(penalty months) "
        f"!= TOTAL PENALTY (out of {len(df)}).")

    # --- Build real payment dates from day + month + YEAR ---
    missing_date_flags = []
    for full, dpref, cpref, mnum in MONTHS:
        dcol = f"{dpref} PAYED DATE"
        newcol = f"{full}_PAYMENT_DATE"
        df[newcol] = [build_date(y, mnum, d) for y, d in zip(df["YEAR"], df[dcol])]
        amt = df[full].fillna(0)
        no_date_has_amt = df[dcol].isna() & (amt > 0)
        missing_date_flags.append(no_date_has_amt)

    missing_date_any = np.logical_or.reduce(missing_date_flags)
    df["FLAG_PAYMENT_MISSING_DATE"] = missing_date_any
    n_flag_rows = missing_date_any.sum()
    n_flag_cells = sum(f.sum() for f in missing_date_flags)
    log(f"\n{n_flag_cells} month-cells across {n_flag_rows} rows have a payment amount "
        f"but no recorded payment day - flagged in FLAG_PAYMENT_MISSING_DATE, not guessed at. "
        f"Check each row's REMARKS column; some (e.g. multiple payments in one month) have "
        f"the real date only in free text.")

    # --- Flag receipt/control-number cells holding more than one number ---
    con_cols = [f"{cpref} CON NO" for _, _, cpref, _ in MONTHS]
    df["FLAG_MULTIPLE_RECEIPTS"] = df[con_cols].apply(
        lambda row: any(isinstance(v, str) and "," in v for v in row), axis=1
    )
    log(f"{df['FLAG_MULTIPLE_RECEIPTS'].sum()} rows have more than one receipt/control number "
        f"in a single month cell (comma-separated) - left as-is, flagged for review.")

    # --- Flag empty/invalid records ---
    df["FLAG_INVALID_YEAR"] = df["YEAR"].isna() | (df["YEAR"] == 0)
    if df["FLAG_INVALID_YEAR"].any():
        bad_ids = df.loc[df["FLAG_INVALID_YEAR"], "ID"].tolist()
        log(f"\n{df['FLAG_INVALID_YEAR'].sum()} row(s) have YEAR = 0/blank (effectively empty "
            f"record): ID {bad_ids}. Kept in output, flagged, excluded from aggregation totals.")

    # --- Standardize audit date columns ---
    for col in ["Date Created", "Date Updated"]:
        df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m-%d")

    for col in ["Created by", "Updated By"]:
        df[col] = df[col].apply(lambda x: x.title() if isinstance(x, str) else x)

    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    log(f"\nSaved cleaned row-level file: {OUT_CSV} ({len(df)} rows).")

    # ---------------- Aggregations ----------------
    valid = df[~df["FLAG_INVALID_YEAR"]].copy()

    by_member_year = (valid.groupby(["MEMBER ID", "PROJECT", "YEAR"], as_index=False)
                       .agg(TOTAL_PAID=("TOTAL", "sum"), TOTAL_PENALTY=("TOTAL PENALTY", "sum")))
    by_member_year = by_member_year.sort_values(["MEMBER ID", "YEAR"])

    by_project_year = (valid.groupby(["PROJECT", "YEAR"], as_index=False)
                        .agg(TOTAL_PAID=("TOTAL", "sum"), TOTAL_PENALTY=("TOTAL PENALTY", "sum"),
                             MEMBER_COUNT=("MEMBER ID", "nunique")))
    by_project_year = by_project_year.sort_values(["PROJECT", "YEAR"])

    month_totals = pd.DataFrame({
        "MONTH": [m[0] for m in MONTHS],
        "TOTAL_COLLECTED_ALL_YEARS": [valid[m[0]].sum() for m in MONTHS],
        "TOTAL_PENALTY_ALL_YEARS": [valid[f"{m[0]} PENALTY"].sum() for m in MONTHS],
    })

    grand_total_paid = valid["TOTAL"].sum()
    grand_total_penalty = valid["TOTAL PENALTY"].sum()
    log(f"\nGRAND TOTAL (valid rows only, ID 491 excluded): "
        f"payments = {grand_total_paid:,.2f}, penalties = {grand_total_penalty:,.2f}.")

    flags_sheet = df[df["FLAG_PAYMENT_MISSING_DATE"] | df["FLAG_MULTIPLE_RECEIPTS"] |
                      df["FLAG_INVALID_YEAR"]][
        ["ID", "MEMBER ID", "PROJECT", "YEAR", "TOTAL",
         "FLAG_PAYMENT_MISSING_DATE", "FLAG_MULTIPLE_RECEIPTS", "FLAG_INVALID_YEAR", "NOTES"]
    ]

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        by_member_year.to_excel(writer, sheet_name="By Member-Year", index=False)
        by_project_year.to_excel(writer, sheet_name="By Project-Year", index=False)
        month_totals.to_excel(writer, sheet_name="By Calendar Month", index=False)
        flags_sheet.to_excel(writer, sheet_name="Data Quality Flags", index=False)

    log(f"Saved aggregation workbook: {OUT_XLSX} "
        f"(sheets: By Member-Year, By Project-Year, By Calendar Month, Data Quality Flags).")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
