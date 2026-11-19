from pathlib import Path

import numpy as np
import pandas as pd

from paths import RAW_DATA, PROCESSED_DATA, AGGREGATED_DATA, REPORTS

SRC = RAW_DATA / "amortization.csv"
OUT_CSV = PROCESSED_DATA / "amortization_processed.csv"
OUT_XLSX = AGGREGATED_DATA / "amortization_aggregated.xlsx"
OUT_REPORT = REPORTS / "amortization_report.txt"
MONTHS = [("JANUARY","JAN","JAN",1),("FEBRUARY","FEB","FEB",2),("MARCH","MAR","MAR",3),("APRIL","APR","APR",4),("MAY","MAY","MAY",5),("JUNE","JUN","JUN",6),("JULY","JULY","JUL",7),("AUGUST","AUG","AUG",8),("SEPTEMBER","SEP","SEP",9),("OCTOBER","OCT","OCT",10),("NOVEMBER","NOV","NOV",11),("DECEMBER","DEC","DEC",12)]
report = []


def log(msg=""):
    report.append(msg)


def build_date(year, month_num, day):
    if pd.isna(year) or year in (0, "0") or pd.isna(day):
        return np.nan
    try:
        day = int(float(day)); year = int(float(year))
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
    df = df.rename(columns={"FULLNAME":"MEMBER ID", "YEAR SUM":"YEAR", "Date updated":"Date Updated"})

    numeric_cols = ["ID","MEMBER ID","YEAR"] + [m[0] for m in MONTHS] + ["TOTAL"] + [f"{m[0]} PENALTY" for m in MONTHS] + ["TOTAL PENALTY","NOT COUNTED"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    calc_total = df[[m[0] for m in MONTHS]].sum(axis=1)
    mismatch = (calc_total - df["TOTAL"]).abs() > 0.01
    log(f"TOTAL validation: {mismatch.sum()} mismatch(es) out of {len(df)} rows.")

    calc_pen = df[[f"{m[0]} PENALTY" for m in MONTHS]].sum(axis=1)
    mismatch_pen = (calc_pen - df["TOTAL PENALTY"]).abs() > 0.01
    log(f"TOTAL PENALTY validation: {mismatch_pen.sum()} mismatch(es) out of {len(df)} rows.")

    missing_flags = []
    for full, dpref, cpref, mnum in MONTHS:
        dcol = f"{dpref} PAYED DATE"
        df[f"{full}_PAYMENT_DATE"] = [build_date(y,mnum,d) for y,d in zip(df["YEAR"], df[dcol])]
        missing_flags.append(df[dcol].isna() & (df[full].fillna(0) > 0))
    df["FLAG_PAYMENT_MISSING_DATE"] = np.logical_or.reduce(missing_flags)

    con_cols = [f"{cpref} CON NO" for _,_,cpref,_ in MONTHS]
    df["FLAG_MULTIPLE_RECEIPTS"] = df[con_cols].apply(lambda row: any(isinstance(v,str) and "," in v for v in row), axis=1)
    df["FLAG_INVALID_YEAR"] = df["YEAR"].isna() | (df["YEAR"] == 0)

    for col in ["Date Created","Date Updated"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["Created by","Updated By"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.title() if isinstance(x,str) else x)

    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    valid = df[~df["FLAG_INVALID_YEAR"]].copy()
    by_member_year = valid.groupby(["MEMBER ID","PROJECT","YEAR"],as_index=False).agg(TOTAL_PAID=("TOTAL","sum"),TOTAL_PENALTY=("TOTAL PENALTY","sum")).sort_values(["MEMBER ID","YEAR"])
    by_project_year = valid.groupby(["PROJECT","YEAR"],as_index=False).agg(TOTAL_PAID=("TOTAL","sum"),TOTAL_PENALTY=("TOTAL PENALTY","sum"),MEMBER_COUNT=("MEMBER ID","nunique")).sort_values(["PROJECT","YEAR"])
    month_totals = pd.DataFrame({"MONTH":[m[0] for m in MONTHS],"TOTAL_COLLECTED_ALL_YEARS":[valid[m[0]].sum() for m in MONTHS],"TOTAL_PENALTY_ALL_YEARS":[valid[f"{m[0]} PENALTY"].sum() for m in MONTHS]})
    flags_sheet = df[df["FLAG_PAYMENT_MISSING_DATE"] | df["FLAG_MULTIPLE_RECEIPTS"] | df["FLAG_INVALID_YEAR"]][["ID","MEMBER ID","PROJECT","YEAR","TOTAL","FLAG_PAYMENT_MISSING_DATE","FLAG_MULTIPLE_RECEIPTS","FLAG_INVALID_YEAR","NOTES"]]

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        by_member_year.to_excel(writer,sheet_name="By Member-Year",index=False)
        by_project_year.to_excel(writer,sheet_name="By Project-Year",index=False)
        month_totals.to_excel(writer,sheet_name="By Calendar Month",index=False)
        flags_sheet.to_excel(writer,sheet_name="Data Quality Flags",index=False)

    log(f"Saved cleaned row-level file: {OUT_CSV}")
    log(f"Saved aggregation workbook: {OUT_XLSX}")
    OUT_REPORT.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
