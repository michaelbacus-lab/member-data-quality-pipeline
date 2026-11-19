from pathlib import Path

import numpy as np
import pandas as pd
import re

from paths import RAW_DATA, PROCESSED_DATA, REPORTS

SRC = RAW_DATA / "customers_info.csv"
OUT_CSV = PROCESSED_DATA / "customers_info_cleaned.csv"
OUT_REPORT = REPORTS / "customers_info_report.txt"

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
    try:
        d = pd.to_datetime(str(val).strip(), format="%d/%m/%Y", errors="raise")
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
    return np.nan


def clean_title(val):
    if pd.isna(val) or str(val).strip() == "":
        return np.nan
    v = str(val).strip().upper().rstrip(".")
    return {"MR": "Mr.", "MRS": "Mrs.", "MS": "Ms."}.get(v, np.nan)


def main():
    df = pd.read_csv(SRC, dtype=str, encoding="latin1")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from source (latin1 encoding).")

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        df[col] = df[col].replace("", np.nan)

    df = df.rename(columns=RENAME_MAP)
    if "TITLE" not in df.columns:
        df["TITLE"] = np.nan
    df["TITLE"] = df["TITLE"].apply(clean_title)
    if "SEX" not in df.columns:
        df["SEX"] = np.nan
    df["SEX"] = df["SEX"].apply(lambda x: str(x).strip().upper() if pd.notna(x) else np.nan)
    df["SEX"] = df["SEX"].where(df["SEX"].isin(["MALE", "FEMALE"]), np.nan)

    title_to_sex = {"Mr.": "MALE", "Mrs.": "FEMALE", "Ms.": "FEMALE"}
    inferred = 0
    for i, row in df.iterrows():
        if pd.isna(row["SEX"] ) and row["TITLE"] in title_to_sex:
            df.at[i, "SEX"] = title_to_sex[row["TITLE"]]
            inferred += 1
    log(f"Inferred SEX from title for {inferred} rows.")

    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].map({"TRUE": True, "FALSE": False})

    for col in DATE_COLS:
        if col not in df.columns:
            continue
        before_non_null = df[col].notna().sum()
        parsed = df[col].apply(parse_date)
        if col == "DATE OF BIRTH":
            bad = parsed.notna() & (pd.to_datetime(parsed) > pd.Timestamp("2015-01-01"))
            if bad.any():
                log(f"WARNING: {bad.sum()} rows have an implausible DATE OF BIRTH (after 2015).")
        lost = before_non_null - parsed.notna().sum()
        if lost:
            log(f"{col}: {lost} value(s) could not be parsed as DD/MM/YYYY and were blanked.")
        df[col] = parsed

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "CONTACT NO" in df.columns:
        before = df["CONTACT NO"].notna().sum()
        df["CONTACT NO"] = df["CONTACT NO"].apply(clean_contact)
        after = df["CONTACT NO"].notna().sum()
        if before - after:
            log(f"CONTACT NO: {before - after} value(s) did not match a valid PH mobile format and were blanked.")

    text_cols = ["FIRSTNAME", "LASTNAME", "MIDDLE NAME", "ADDRESS", "ENCODED BY", "Created By", "Updated By", "OCCUPATION", "RELIGION", "Company Name", "Office Address", "NOTES"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: re.sub(r"\s+", " ", x).strip() if isinstance(x, str) else x)
    for col in ["ENCODED BY", "Updated By", "Created By"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.title() if isinstance(x, str) else x)

    def build_fullname(row):
        parts = [row.get("LASTNAME"), row.get("FIRSTNAME")]
        parts = [p for p in parts if pd.notna(p) and str(p).strip()]
        return " ".join(parts) if parts else np.nan

    df["FULLNAME"] = df.apply(build_fullname, axis=1)
    dup_mask = df.duplicated(subset=["FIRSTNAME", "LASTNAME"], keep=False) & df["FIRSTNAME"].notna()
    df["POSSIBLE_DUPLICATE"] = dup_mask
    if dup_mask.any():
        log(f"{dup_mask.sum()} rows share a FIRSTNAME+LASTNAME and were flagged, not removed.")

    if "MEMBER ID" in df.columns:
        df = df.sort_values("MEMBER ID").reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    log(f"Saved cleaned file: {OUT_CSV} ({len(df)} rows, {len(df.columns)} columns).")
    OUT_REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    print("\n".join(report_lines))


if __name__ == "__main__":
    main()
