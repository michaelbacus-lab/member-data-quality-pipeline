import re

import numpy as np
import pandas as pd

from paths import RAW_DATA, PROCESSED_DATA, AGGREGATED_DATA, REPORTS

SRC_FEE = RAW_DATA / "membership_fee.csv"
SRC_CUST = PROCESSED_DATA / "customers_info_cleaned.csv"
OUT_CSV = PROCESSED_DATA / "membership_fee_cleaned.csv"
OUT_XLSX = AGGREGATED_DATA / "membership_fee_aggregated.xlsx"
OUT_REPORT = REPORTS / "membership_fee_cleaning_report.txt"
report = []


def log(msg=""):
    report.append(msg)


def clean_control_no(val):
    if pd.isna(val):
        return np.nan
    tokens = [t for t in re.split(r"[\r\n\s]+", str(val).strip()) if re.fullmatch(r"\d+", t)]
    if not tokens:
        return np.nan
    return ",".join(dict.fromkeys(tokens))


def main():
    df = pd.read_csv(SRC_FEE, dtype=str, encoding="utf-8")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from membership fee source.")
    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x,str) else x)
        df[col] = df[col].replace("",np.nan)
    df = df.rename(columns={"Creadted By":"Created By"})

    for col in ["MEMFEE ID","MEMBER","AMOUNT"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["PAYED DATE","DATE Created","Date Updated"]:
        if col in df.columns:
            before=df[col].notna().sum()
            df[col]=pd.to_datetime(df[col],format="%d/%m/%Y",errors="coerce")
            lost=before-df[col].notna().sum()
            if lost:
                log(f"{col}: {lost} value(s) could not be parsed and were blanked.")
            df[col]=df[col].dt.strftime("%Y-%m-%d")

    df["CONTROL NO"] = df["CONTROL NO"].apply(clean_control_no)
    for col in ["Created By","Updated By"]:
        if col in df.columns:
            df[col]=df[col].apply(lambda x:x.title() if isinstance(x,str) else x)
    if "REMARKS" in df.columns:
        df["REMARKS"]=df["REMARKS"].apply(lambda x:re.sub(r"\s+"," ",x).strip() if isinstance(x,str) else x)

    df["FLAG_EMPTY_RECORD"] = df["MEMBER"].isna()
    df["FLAG_MISSING_AMOUNT"] = df["MEMBER"].notna() & df["AMOUNT"].isna()
    df["FLAG_ZERO_AMOUNT"] = df["AMOUNT"] == 0
    df["FLAG_MISSING_PAYED_DATE"] = df["MEMBER"].notna() & (df["AMOUNT"].fillna(0)>0) & df["PAYED DATE"].isna()
    dup_payment_mask=df.duplicated(subset=["MEMBER","AMOUNT","PAYED DATE"],keep=False)&df["MEMBER"].notna()
    df["FLAG_POSSIBLE_DUPLICATE_PAYMENT"] = dup_payment_mask

    if not SRC_CUST.exists():
        raise FileNotFoundError("Run clean_customers.py first (required: data/processed/customers_info_cleaned.csv)")
    cust=pd.read_csv(SRC_CUST,dtype=str)
    cust["MEMBER ID"]=pd.to_numeric(cust["MEMBER ID"],errors="coerce")
    cust_small=cust[["MEMBER ID","FULLNAME","PROJECT"]].rename(columns={"FULLNAME":"MEMBER_FULLNAME","PROJECT":"PROJECT"})
    merged=df.merge(cust_small,how="left",left_on="MEMBER",right_on="MEMBER ID").drop(columns=["MEMBER ID"])
    n_no_match=merged["MEMBER"].notna()&merged["MEMBER_FULLNAME"].isna()
    merged["FLAG_MEMBER_NOT_FOUND"] = n_no_match
    merged.to_csv(OUT_CSV,index=False,encoding="utf-8")

    valid=merged[~merged["FLAG_EMPTY_RECORD"]].copy()
    valid["AMOUNT_FILLED"]=valid["AMOUNT"].fillna(0)
    valid["PAY_YEAR"]=pd.to_datetime(valid["PAYED DATE"],errors="coerce").dt.year
    by_member=valid.groupby(["MEMBER","MEMBER_FULLNAME","PROJECT"],as_index=False,dropna=False).agg(NUM_PAYMENTS=("MEMFEE ID","count"),TOTAL_PAID=("AMOUNT_FILLED","sum"),FIRST_PAYMENT=("PAYED DATE","min"),LAST_PAYMENT=("PAYED DATE","max")).sort_values("MEMBER")
    by_project=valid.groupby("PROJECT",as_index=False,dropna=False).agg(TOTAL_PAID=("AMOUNT_FILLED","sum"),NUM_PAYMENTS=("MEMFEE ID","count"),MEMBER_COUNT=("MEMBER","nunique"))
    by_project["PROJECT"] = by_project["PROJECT"].fillna("(no matching project - member not found)")
    by_year=valid.dropna(subset=["PAY_YEAR"]).groupby("PAY_YEAR",as_index=False).agg(TOTAL_COLLECTED=("AMOUNT_FILLED","sum"),NUM_PAYMENTS=("MEMFEE ID","count"))
    if not by_year.empty:
        by_year["PAY_YEAR"] = by_year["PAY_YEAR"].astype(int)

    flags=merged[merged["FLAG_EMPTY_RECORD"]|merged["FLAG_MISSING_AMOUNT"]|merged["FLAG_MISSING_PAYED_DATE"]|merged["FLAG_POSSIBLE_DUPLICATE_PAYMENT"]|merged["FLAG_MEMBER_NOT_FOUND"]][["MEMFEE ID","MEMBER","MEMBER_FULLNAME","PROJECT","AMOUNT","PAYED DATE","CONTROL NO","FLAG_EMPTY_RECORD","FLAG_MISSING_AMOUNT","FLAG_MISSING_PAYED_DATE","FLAG_POSSIBLE_DUPLICATE_PAYMENT","FLAG_MEMBER_NOT_FOUND"]]
    with pd.ExcelWriter(OUT_XLSX,engine="openpyxl") as writer:
        by_member.to_excel(writer,sheet_name="By Member (with Project)",index=False)
        by_project.to_excel(writer,sheet_name="By Project",index=False)
        by_year.to_excel(writer,sheet_name="By Year",index=False)
        flags.to_excel(writer,sheet_name="Data Quality Flags",index=False)

    grand_total=valid["AMOUNT_FILLED"].sum()
    log(f"Saved cleaned + joined row-level file: {OUT_CSV} ({len(merged)} rows).")
    log(f"GRAND TOTAL membership fees collected: {grand_total:,.2f}")
    OUT_REPORT.write_text("\n".join(report),encoding="utf-8")
    print("\n".join(report))


if __name__=="__main__":
    main()
