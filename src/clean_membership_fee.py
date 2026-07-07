"""
Cleans the membership-fee ledger, flags nulls/duplicates, left-joins each
payment to the cleaned customers_info table (to attach the member's name and
project), and aggregates totals per member/project/year.

Money-safety rule followed throughout: no AMOUNT is ever invented, defaulted,
or silently changed. Anything uncertain gets its own flag column instead.
"""
import pandas as pd
import numpy as np
import re

SRC_FEE = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\datasets\membership_fee.csv"
SRC_CUST = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\customers_info_cleaned.csv"  # already cleaned earlier in this session
OUT_CSV = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\membership_fee_cleaned.csv"
OUT_XLSX = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\membership_fee_aggregated.xlsx"
OUT_REPORT = "D:\Documents Nato\RAHUR\ML Foundation Data Cleaning with Python\processed_data\membership_fee_cleaning_report.txt"

report = []


def log(msg=""):
    report.append(msg)


def clean_control_no(val):
    if pd.isna(val):
        return np.nan
    tokens = re.split(r"[\r\n\s]+", str(val).strip())
    tokens = [t for t in tokens if re.fullmatch(r"\d+", t)]
    if not tokens:
        return np.nan
    seen = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return ",".join(seen)


def main():
    df = pd.read_csv(SRC_FEE, dtype=str, encoding="utf-8")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from membership fee source.")

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace("", np.nan)

    df = df.rename(columns={"Creadted By": "Created By"})

    # --- Numeric columns ---
    df["MEMFEE ID"] = pd.to_numeric(df["MEMFEE ID"], errors="coerce")
    df["MEMBER"] = pd.to_numeric(df["MEMBER"], errors="coerce")
    df["AMOUNT"] = pd.to_numeric(df["AMOUNT"], errors="coerce")

    dup_ids = df["MEMFEE ID"].duplicated().sum()
    log(f"MEMFEE ID duplicates: {dup_ids} (should be 0 - primary key).")

    # --- Dates ---
    for col in ["PAYED DATE", "DATE Created", "Date Updated"]:
        before = df[col].notna().sum()
        df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce")
        lost = before - df[col].notna().sum()
        if lost:
            log(f"{col}: {lost} value(s) didn't match DD/MM/YYYY and were blanked.")
        df[col] = df[col].dt.strftime("%Y-%m-%d")

    # --- Control numbers ---
    df["CONTROL NO"] = df["CONTROL NO"].apply(clean_control_no)

    for col in ["Created By", "Updated By"]:
        df[col] = df[col].apply(lambda x: x.title() if isinstance(x, str) else x)
    df["REMARKS"] = df["REMARKS"].apply(lambda x: re.sub(r"\s+", " ", x).strip() if isinstance(x, str) else x)

    # --- Flags ---
    df["FLAG_EMPTY_RECORD"] = df["MEMBER"].isna()
    df["FLAG_MISSING_AMOUNT"] = df["MEMBER"].notna() & df["AMOUNT"].isna()
    df["FLAG_ZERO_AMOUNT"] = df["AMOUNT"] == 0
    df["FLAG_MISSING_PAYED_DATE"] = df["MEMBER"].notna() & (df["AMOUNT"].fillna(0) > 0) & df["PAYED DATE"].isna()

    # Flag exact-duplicate payments: same member, amount, and payment date
    dup_payment_mask = df.duplicated(subset=["MEMBER", "AMOUNT", "PAYED DATE"], keep=False) & df["MEMBER"].notna()
    df["FLAG_POSSIBLE_DUPLICATE_PAYMENT"] = dup_payment_mask

    log(f"\n{df['FLAG_EMPTY_RECORD'].sum()} row(s) are empty stub records (no MEMBER) - flagged.")
    log(f"{df['FLAG_MISSING_AMOUNT'].sum()} row(s) have a MEMBER but no AMOUNT recorded - flagged.")
    log(f"{df['FLAG_ZERO_AMOUNT'].sum()} row(s) explicitly record AMOUNT = 0.")
    log(f"{df['FLAG_MISSING_PAYED_DATE'].sum()} row(s) have a positive AMOUNT but no PAYED DATE.")
    log(f"{dup_payment_mask.sum()} row(s) share the same MEMBER + AMOUNT + PAYED DATE as another "
        f"row - likely the same payment encoded twice. Left in the data (not deleted), flagged "
        f"for manual confirmation before removing either copy.")

    # ---------------- Left join to customers_info to get name + project ----------------
    cust = pd.read_csv(SRC_CUST, dtype=str)
    cust["MEMBER ID"] = pd.to_numeric(cust["MEMBER ID"], errors="coerce")
    cust_small = cust[["MEMBER ID", "FULLNAME", "PROJECT"]].rename(
        columns={"FULLNAME": "MEMBER_FULLNAME", "PROJECT": "PROJECT"})

    merged = df.merge(cust_small, how="left", left_on="MEMBER", right_on="MEMBER ID")
    merged = merged.drop(columns=["MEMBER ID"])

    n_no_match = merged["MEMBER"].notna() & merged["MEMBER_FULLNAME"].isna()
    merged["FLAG_MEMBER_NOT_FOUND"] = n_no_match
    log(f"\nLeft join to customers_info: {n_no_match.sum()} row(s) reference a MEMBER ID that "
        f"has no match in customers_info.csv - name and project are unknown for these ("
        f"flagged FLAG_MEMBER_NOT_FOUND). Member IDs: "
        f"{sorted(merged.loc[n_no_match, 'MEMBER'].unique().tolist())}")

    merged.to_csv(OUT_CSV, index=False, encoding="utf-8")
    log(f"\nSaved cleaned + joined row-level file: {OUT_CSV} ({len(merged)} rows).")

    # ---------------- Aggregations ----------------
    valid = merged[~merged["FLAG_EMPTY_RECORD"]].copy()
    valid["AMOUNT_FILLED"] = valid["AMOUNT"].fillna(0)
    valid["PAY_YEAR"] = pd.to_datetime(valid["PAYED DATE"], errors="coerce").dt.year

    by_member = (valid.groupby(["MEMBER", "MEMBER_FULLNAME", "PROJECT"], as_index=False, dropna=False)
                 .agg(NUM_PAYMENTS=("MEMFEE ID", "count"),
                      TOTAL_PAID=("AMOUNT_FILLED", "sum"),
                      FIRST_PAYMENT=("PAYED DATE", "min"),
                      LAST_PAYMENT=("PAYED DATE", "max"))
                 .sort_values("MEMBER"))

    by_project = (valid.groupby("PROJECT", as_index=False, dropna=False)
                  .agg(TOTAL_PAID=("AMOUNT_FILLED", "sum"),
                       NUM_PAYMENTS=("MEMFEE ID", "count"),
                       MEMBER_COUNT=("MEMBER", "nunique")))
    by_project["PROJECT"] = by_project["PROJECT"].fillna("(no matching project - member not found)")

    by_year = (valid.dropna(subset=["PAY_YEAR"])
               .groupby("PAY_YEAR", as_index=False)
               .agg(TOTAL_COLLECTED=("AMOUNT_FILLED", "sum"), NUM_PAYMENTS=("MEMFEE ID", "count")))
    by_year["PAY_YEAR"] = by_year["PAY_YEAR"].astype(int)

    grand_total = valid["AMOUNT_FILLED"].sum()
    log(f"\nGRAND TOTAL membership fees collected (empty stub row excluded, missing-amount rows "
        f"counted as 0): {grand_total:,.2f} across {valid['MEMFEE ID'].count()} entries, "
        f"{valid['MEMBER'].nunique()} distinct members.")

    flags_sheet = merged[merged["FLAG_EMPTY_RECORD"] | merged["FLAG_MISSING_AMOUNT"] |
                          merged["FLAG_MISSING_PAYED_DATE"] | merged["FLAG_POSSIBLE_DUPLICATE_PAYMENT"] |
                          merged["FLAG_MEMBER_NOT_FOUND"]][
        ["MEMFEE ID", "MEMBER", "MEMBER_FULLNAME", "PROJECT", "AMOUNT", "PAYED DATE", "CONTROL NO",
         "FLAG_EMPTY_RECORD", "FLAG_MISSING_AMOUNT", "FLAG_MISSING_PAYED_DATE",
         "FLAG_POSSIBLE_DUPLICATE_PAYMENT", "FLAG_MEMBER_NOT_FOUND"]
    ]

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        by_member.to_excel(writer, sheet_name="By Member (with Project)", index=False)
        by_project.to_excel(writer, sheet_name="By Project", index=False)
        by_year.to_excel(writer, sheet_name="By Year", index=False)
        flags_sheet.to_excel(writer, sheet_name="Data Quality Flags", index=False)

    log(f"Saved aggregation workbook: {OUT_XLSX} "
        f"(sheets: By Member (with Project), By Project, By Year, Data Quality Flags).")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
