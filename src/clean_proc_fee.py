import re

import pandas as pd

from paths import RAW_DATA, PROCESSED_DATA, AGGREGATED_DATA, REPORTS

SRC=RAW_DATA/"processing_fee.csv"
OUT_CSV=PROCESSED_DATA/"processing_fee_processed.csv"
OUT_XLSX=AGGREGATED_DATA/"processing_fee_aggregated.xlsx"
OUT_REPORT=REPORTS/"processing_fee_cleaning_report.txt"
report=[]


def log(msg=""):
    report.append(msg)


def clean_control_no(val):
    if pd.isna(val):
        return None
    tokens=[t for t in re.split(r"[\r\n\s]+",str(val).strip()) if re.fullmatch(r"\d+",t)]
    return ",".join(dict.fromkeys(tokens)) if tokens else None


def main():
    df=pd.read_csv(SRC,dtype=str,encoding="utf-8")
    log(f"Loaded {len(df)} rows, {len(df.columns)} columns from source.")
    for col in df.columns:
        df[col]=df[col].apply(lambda x:x.strip() if isinstance(x,str) else x)
        df[col]=df[col].replace("",None)

    for col in ["MEMFEE ID","MEMBER","AMOUNT"]:
        df[col]=pd.to_numeric(df[col],errors="coerce")
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
    df["FLAG_MISSING_PAYED_DATE"] = df["MEMBER"].notna() & df["AMOUNT"].notna() & (df["AMOUNT"]>0) & df["PAYED DATE"].isna()
    df.to_csv(OUT_CSV,index=False,encoding="utf-8")

    valid=df[~df["FLAG_EMPTY_RECORD"]].copy()
    valid["AMOUNT_FILLED"] = valid["AMOUNT"].fillna(0)
    valid["PAY_YEAR"] = pd.to_datetime(valid["PAYED DATE"],errors="coerce").dt.year
    valid["PAY_MONTH"] = pd.to_datetime(valid["PAYED DATE"],errors="coerce").dt.month
    by_member=valid.groupby("MEMBER",as_index=False).agg(NUM_PAYMENTS=("MEMFEE ID","count"),TOTAL_PAID=("AMOUNT_FILLED","sum"),FIRST_PAYMENT=("PAYED DATE","min"),LAST_PAYMENT=("PAYED DATE","max")).sort_values("MEMBER")
    by_year_month=valid.dropna(subset=["PAY_YEAR"]).groupby(["PAY_YEAR","PAY_MONTH"],as_index=False).agg(TOTAL_COLLECTED=("AMOUNT_FILLED","sum"),NUM_PAYMENTS=("MEMFEE ID","count")).sort_values(["PAY_YEAR","PAY_MONTH"])
    by_year=valid.dropna(subset=["PAY_YEAR"]).groupby("PAY_YEAR",as_index=False).agg(TOTAL_COLLECTED=("AMOUNT_FILLED","sum"),NUM_PAYMENTS=("MEMFEE ID","count"))
    if not by_year_month.empty:
        by_year_month["PAY_YEAR"] = by_year_month["PAY_YEAR"].astype(int)
        by_year_month["PAY_MONTH"] = by_year_month["PAY_MONTH"].astype(int)
    if not by_year.empty:
        by_year["PAY_YEAR"] = by_year["PAY_YEAR"].astype(int)

    flags=df[df["FLAG_EMPTY_RECORD"]|df["FLAG_MISSING_AMOUNT"]|df["FLAG_MISSING_PAYED_DATE"]][["MEMFEE ID","MEMBER","AMOUNT","PAYED DATE","CONTROL NO","REMARKS","FLAG_EMPTY_RECORD","FLAG_MISSING_AMOUNT","FLAG_MISSING_PAYED_DATE"]]
    with pd.ExcelWriter(OUT_XLSX,engine="openpyxl") as writer:
        by_member.to_excel(writer,sheet_name="By Member",index=False)
        by_year_month.to_excel(writer,sheet_name="By Year-Month",index=False)
        by_year.to_excel(writer,sheet_name="By Year",index=False)
        flags.to_excel(writer,sheet_name="Data Quality Flags",index=False)

    grand_total=valid["AMOUNT_FILLED"].sum()
    log(f"Saved cleaned row-level file: {OUT_CSV} ({len(df)} rows).")
    log(f"GRAND TOTAL processing fees collected: {grand_total:,.2f}")
    OUT_REPORT.write_text("\n".join(report),encoding="utf-8")
    print("\n".join(report))


if __name__=="__main__":
    main()
