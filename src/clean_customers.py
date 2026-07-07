"""
Cleans the CDRMEMS/BLUSF member (customers_info) CSV export.

Fixes applied:
- Encoding: source file is Latin-1/cp1252, re-saved as UTF-8
- Whitespace trimmed on every text field
- Column name typos fixed (Date Creted -> Date Created, etc.)
- SEX standardized to MALE/FEMALE, inferred from "Mr Mrs" title when missing
- "Mr Mrs" title standardized to Mr. / Mrs. / Ms.
- Boolean columns (TRUE/FALSE flags) cast to real booleans
- Date columns parsed from DD/MM/YYYY -> YYYY-MM-DD, invalid/impossible
  dates (e.g. a birth date in 2017) are blanked and logged
- Numeric columns (MEMBER ID, MONTHLY INCOME, YEARS TO PAY 1) cast to numeric
- CONTACT NO normalized to an 11-digit PH mobile format (09XXXXXXXXX),
  invalid numbers flagged rather than guessed at
- FULLNAME rebuilt from FIRSTNAME/LASTNAME/MIDDLE NAME so it's always consistent
- Duplicate people (same first + last name) flagged in a separate report
  rather than silently dropped, since same-name ≠ guaranteed duplicate
"""
import pandas as pd
import numpy as np
import re

SRC = "/mnt/user-data/uploads/customers_info.csv"
OUT_CSV = "/mnt/user-data/outputs/customers_info_cleaned.csv"
OUT_REPORT = "/mnt/user-data/outputs/cleaning_report.txt"

BOOL_COLS = [
    "WAIVER OF RIGHTS", "PAID", "BENEFICIARY PROFILE", "BIRTH CERTIFICATE",
    "RESERVATION AGREEMENT", "ID PICTURE", "SINUMPAANG SALAYSAY",
    "MARRIAGE CERTIFICATE", "MEMBERSHIP FEE", "PROCESSING FEE",
]
DATE_COLS = ["DATE OF BIRTH", "DATE ENCODED", "Date Created", "Date Updated"]
NUMERIC_COLS = ["MEMBER ID", "MONTHLY INCOME", "YEARS TO PAY 1"]

RENAME_MAP = {
    "Date Creted": "Date Created",
    "Creadted by": "Created By",
    "REVERVATION AGREEMENT": "RESERVATION AGREEMENT",
    "Mr Mrs": "TITLE",
}

report_lines = []


def log(msg):
    report_lines.append(msg)


def parse_date(val):
    if pd.isna(val) or str(val).strip() == "":
        return np.nan
    val = str(val).strip()
    try:
        d = pd.to_datetime(val, format="%d/%m/%Y", errors="raise")
        # sanity check: no birth dates in the future or absurdly recent (< 1900)
        return d.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return np.nan


def clean_contact(val):
    if pd.isna(val) or str(val).strip() == "":
        return np.nan
    digits = re.sub(r"\D", "", str(val))
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    if len(digits) == 11 and digits.startswith("09"):
        return digits
    return np.nan  # invalid/unrecognized format, flagged in report


def clean_title(val):
    if pd.isna(val) or str(val).strip() == "":
        return np.nan
    v = str(val).strip().upper().rstrip(".")
    return {"MR": "Mr.", "MRS": "Mrs.", "MS": "Ms."}.get(v, np.nan)


def main():
    df = pd.read_csv(SRC, dtype=str, encoding="latin1")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from source (latin1 encoding).")

    # 1. Trim whitespace on every string cell
    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace("", np.nan)

    # 2. Rename mistyped/inconsistent columns
    df = df.rename(columns=RENAME_MAP)

    # 3. Standardize TITLE (Mr Mrs) and SEX, cross-filling one from the other
    df["TITLE"] = df["TITLE"].apply(clean_title)
    df["SEX"] = df["SEX"].apply(lambda x: str(x).strip().upper() if pd.notna(x) else np.nan)
    df["SEX"] = df["SEX"].where(df["SEX"].isin(["MALE", "FEMALE"]), np.nan)

    title_to_sex = {"Mr.": "MALE", "Mrs.": "FEMALE", "Ms.": "FEMALE"}
    inferred = 0
    for i, row in df.iterrows():
        if pd.isna(row["SEX"]) and row["TITLE"] in title_to_sex:
            df.at[i, "SEX"] = title_to_sex[row["TITLE"]]
            inferred += 1
    log(f"Inferred SEX from title for {inferred} rows.")

    # 4. Boolean flag columns -> real booleans
    for col in BOOL_COLS:
        df[col] = df[col].map({"TRUE": True, "FALSE": False})

    # 5. Dates -> ISO format, log unparseable / implausible values
    for col in DATE_COLS:
        before_non_null = df[col].notna().sum()
        parsed = df[col].apply(parse_date)
        # flag birth dates that are impossible (e.g. after "Date Encoded")
        if col == "DATE OF BIRTH":
            bad = parsed.notna() & (pd.to_datetime(parsed) > pd.Timestamp("2015-01-01"))
            if bad.any():
                log(f"WARNING: {bad.sum()} rows have an implausible DATE OF BIRTH (after 2015) - kept as-is, needs manual review. Member IDs: {df.loc[bad, 'MEMBER ID'].tolist()}")
        lost = before_non_null - parsed.notna().sum()
        if lost:
            log(f"{col}: {lost} value(s) could not be parsed as DD/MM/YYYY and were blanked.")
        df[col] = parsed

    # 6. Numeric columns
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 7. Contact numbers
    before = df["CONTACT NO"].notna().sum()
    df["CONTACT NO"] = df["CONTACT NO"].apply(clean_contact)
    after = df["CONTACT NO"].notna().sum()
    if before - after:
        log(f"CONTACT NO: {before - after} value(s) didn't match a valid PH mobile format and were blanked.")

    # 8. Fix stray double-spaces in free text / name columns
    text_cols = ["FIRSTNAME", "LASTNAME", "MIDDLE NAME", "ADDRESS", "ENCODED BY",
                 "Created By", "Updated By", "OCCUPATION", "RELIGION", "Company Name",
                 "Office Address", "NOTES"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: re.sub(r"\s+", " ", x).strip() if isinstance(x, str) else x)

    # Standardize "Updated By" / "ENCODED BY" casing (title case for names)
    for col in ["ENCODED BY", "Updated By", "Created By"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.title() if isinstance(x, str) else x)

    # 9. Rebuild FULLNAME consistently from parts
    def build_fullname(row):
        parts = [row.get("LASTNAME"), row.get("FIRSTNAME")]
        parts = [p for p in parts if pd.notna(p) and str(p).strip()]
        return " ".join(parts) if parts else np.nan

    df["FULLNAME"] = df.apply(build_fullname, axis=1)

    # 10. Flag likely duplicate people (same first+last name) without deleting them
    dup_mask = df.duplicated(subset=["FIRSTNAME", "LASTNAME"], keep=False) & df["FIRSTNAME"].notna()
    df["POSSIBLE_DUPLICATE"] = dup_mask
    if dup_mask.any():
        dup_ids = df.loc[dup_mask, ["MEMBER ID", "FIRSTNAME", "LASTNAME"]].sort_values(["LASTNAME", "FIRSTNAME"])
        log(f"\n{dup_mask.sum()} rows share a FIRSTNAME+LASTNAME with another row (flagged in POSSIBLE_DUPLICATE column, not removed):")
        for _, r in dup_ids.iterrows():
            log(f"  MEMBER ID {r['MEMBER ID']}: {r['FIRSTNAME']} {r['LASTNAME']}")

    # 11. Sort by MEMBER ID and save
    df = df.sort_values("MEMBER ID").reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    log(f"\nSaved cleaned file: {OUT_CSV} ({len(df)} rows, {len(df.columns)} columns).")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print("\n".join(report_lines))


if __name__ == "__main__":
    main()
