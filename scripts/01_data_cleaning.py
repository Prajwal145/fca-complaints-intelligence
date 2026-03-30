import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# SETTINGS
RAW_FOLDER    = "."
OUTPUT_FOLDER = "./processed"

# Each file and what period it covers
FILES = [
    ("firm-level-complaints-data-2022-h1.xlsx", "H1 2022", 1, "2022-01-01", "2022-06-30"),
    ("firm-level-complaints-data-2022-h2.xlsx", "H2 2022", 2, "2022-07-01", "2022-12-31"),
    ("firm-level-complaints-data-2023-h1.xlsx", "H1 2023", 3, "2023-01-01", "2023-06-30"),
    ("firm-level-complaints-data-2023-h2.xlsx", "H2 2023", 4, "2023-07-01", "2023-12-31"),
    ("firm-level-complaints-data-2024-h1.xlsx", "H1 2024", 5, "2024-01-01", "2024-06-30"),
]

# Consumer Duty came into force July 2023
PRE_DUTY_PERIODS  = ["H1 2022", "H2 2022", "H1 2023"]
POST_DUTY_PERIODS = ["H2 2023", "H1 2024"]

# Product categories used by FCA
PRODUCT_CATS = [
    'Banking & Credit Cards',
    'Decumulation & Pensions',
    'Home Finance',
    'Insurance & Pure Protection',
    'Investments',
]


# FIRM TYPE CLASSIFICATION
def classify_firm_type(firm_name):
    """
    Classify a firm into one of 7 categories based on its name.
    Simple keyword matching - not perfect but works well enough.
    """
    firm = str(firm_name).lower()

    if any(x in firm for x in ['barclays', 'hsbc', 'lloyds', 'natwest',
                                 'santander', 'halifax', 'nationwide',
                                 'monzo', 'starling', 'metro bank',
                                 'bank of scotland', 'tsb', 'virgin money',
                                 'co-operative bank', 'clydesdale',
                                 'royal bank of scotland', 'tesco bank',
                                 'sainsbury', 'marks & spencer financial']):
        return 'Retail Bank / Building Society'

    elif any(x in firm for x in ['aviva insurance', 'axa insurance',
                                   'direct line', 'admiral', 'esure',
                                   'hastings', 'liverpool victoria', 'lv=',
                                   'ageas', 'allianz', 'hiscox',
                                   'uk insurance', 'u k insurance',
                                   'eui limited', 'nfu mutual',
                                   'saga', 'zurich insurance']):
        return 'General Insurance'

    elif any(x in firm for x in ['scottish widows', 'legal & general',
                                   'phoenix life', 'reassure', 'aegon',
                                   'zurich assurance', 'prudential',
                                   'aviva life', 'sun life', 'metlife',
                                   'royal london', 'wesleyan', 'unum',
                                   'vitality life']):
        return 'Life & Pensions'

    elif any(x in firm for x in ['hargreaves lansdown', 'aj bell',
                                   'interactive investor', 'fidelity',
                                   'vanguard', 'nutmeg', 'quilter',
                                   'invesco', 'columbia threadneedle',
                                   'standard life savings']):
        return 'Investment Platform'

    elif any(x in firm for x in ['accord mortgages', 'kensington mortgage',
                                   'platform home loans', 'mortgage works',
                                   'landmark mortgages']):
        return 'Mortgage Lender'

    elif any(x in firm for x in ['american express', 'capital one',
                                   'newday', 'vanquis', 'mbna']):
        return 'Credit Card / Consumer Finance'

    else:
        return 'Other Financial Services'


# SHEET FINDER
def find_sheet(sheet_names, keywords):
    """Find a sheet by looking for keywords in its name."""
    for name in sheet_names:
        name_lower = name.lower().strip()
        for kw in keywords:
            if kw in name_lower:
                return name
    return None


# COLUMN STANDARDISER
def standardise_columns(df):
    """Rename columns to consistent names across all years."""
    rename = {}
    for col in df.columns:
        cl = str(col).lower().strip()
        if cl in ['firm name', 'firm_name']:
            rename[col] = 'firm_name'
        elif cl in ['group', 'group name']:
            rename[col] = 'group'
        elif 'banking' in cl:
            rename[col] = 'Banking & Credit Cards'
        elif 'decumulation' in cl:
            rename[col] = 'Decumulation & Pensions'
        elif 'home finance' in cl:
            rename[col] = 'Home Finance'
        elif 'insurance' in cl and 'pure' in cl:
            rename[col] = 'Insurance & Pure Protection'
        elif cl.startswith('invest'):
            rename[col] = 'Investments'
    return df.rename(columns=rename)


# MELT WIDE TO LONG
def melt_sheet(df, value_name):
    """
    The FCA data is in wide format (one column per product category).
    We need to convert it to long format (one row per firm + category).
    """
    if df is None or 'firm_name' not in df.columns:
        return None

    id_cols = [c for c in ['firm_name', 'group'] if c in df.columns]
    value_cols = [c for c in PRODUCT_CATS if c in df.columns]

    if not value_cols:
        return None

    melted = df[id_cols + value_cols].melt(
        id_vars=id_cols,
        value_vars=value_cols,
        var_name='product_category',
        value_name=value_name
    )

    melted = melted.dropna(subset=[value_name])
    melted[value_name] = pd.to_numeric(melted[value_name], errors='coerce')
    melted = melted.dropna(subset=[value_name])

    return melted


# READ ONE FILE
def read_fca_file(filepath, period_label, period_order, period_start, period_end):
    """Read one FCA complaints Excel file and return a clean dataframe."""
    print(f"\n{'─'*50}")
    print(f"Processing: {os.path.basename(filepath)}")
    print(f"Period:     {period_label}")

    try:
        xl = pd.ExcelFile(filepath)
    except Exception as e:
        print(f"  ERROR opening file: {e}")
        return None

    sheets = xl.sheet_names
    print(f"  Sheets: {sheets}")

    # Find the sheets we need
    opened_sheet   = find_sheet(sheets, ['opened', 'open'])
    closed_sheet   = find_sheet(sheets, ['closed'])
    upheld_sheet   = find_sheet(sheets, ['upheld', '% upheld'])
    threeday_sheet = find_sheet(sheets, ['3 day', '3days', 'closed in 3', 'within 3'])

    if not opened_sheet:
        print(f"  ERROR: Could not find Opened sheet")
        return None

    # Read and standardise each sheet
    def read_and_clean(sheet_name):
        if not sheet_name:
            return None
        try:
            df = pd.read_excel(xl, sheet_name=sheet_name, header=0)
            return standardise_columns(df)
        except Exception as e:
            print(f"  Warning reading {sheet_name}: {e}")
            return None

    df_opened   = read_and_clean(opened_sheet)
    df_closed   = read_and_clean(closed_sheet)
    df_upheld   = read_and_clean(upheld_sheet)
    df_threeday = read_and_clean(threeday_sheet)

    if df_opened is None or 'firm_name' not in df_opened.columns:
        print(f"  ERROR: Could not read Opened sheet properly")
        return None

    # Add group column if missing
    if 'group' not in df_opened.columns:
        df_opened['group'] = ''

    # Melt each sheet from wide to long
    base        = melt_sheet(df_opened,   'complaints_opened')
    closed_long = melt_sheet(df_closed,   'complaints_closed')
    upheld_long = melt_sheet(df_upheld,   'upheld_rate')
    three_long  = melt_sheet(df_threeday, 'pct_closed_3days_raw')

    if base is None:
        print(f"  ERROR: Could not process opened complaints")
        return None

    # Clean firm names
    base = base.dropna(subset=['firm_name'])
    base['firm_name'] = base['firm_name'].astype(str).str.strip()
    base = base[base['firm_name'] != '']
    base = base[base['firm_name'] != 'nan']

    # Convert complaints to integer
    base['complaints_opened'] = (
        pd.to_numeric(base['complaints_opened'], errors='coerce')
        .fillna(0).astype(int)
    )

    merge_keys = [c for c in ['firm_name', 'group', 'product_category']
                  if c in base.columns]

    # Merge closed, upheld, 3-day onto the base
    for df_merge, col_name in [
        (closed_long, 'complaints_closed'),
        (upheld_long, 'upheld_rate'),
        (three_long,  'pct_closed_3days_raw')
    ]:
        if df_merge is not None:
            avail_keys = [k for k in merge_keys if k in df_merge.columns]
            base = base.merge(
                df_merge[avail_keys + [col_name]],
                on=avail_keys,
                how='left'
            )

    # Add period metadata
    base['period_label']  = period_label
    base['period_order']  = period_order
    base['period_start']  = period_start
    base['period_end']    = period_end
    base['year']          = int(period_start[:4])
    base['half']          = 1 if 'H1' in period_label else 2
    base['pre_post_duty'] = (
        'Pre-Duty' if period_label in PRE_DUTY_PERIODS else 'Post-Duty'
    )

    # Convert uphold rate to percentage (FCA stores as 0-1 decimal)
    if 'upheld_rate' in base.columns:
        base['upheld_pct'] = (
            pd.to_numeric(base['upheld_rate'], errors='coerce') * 100
        ).round(1)
    else:
        base['upheld_pct'] = np.nan

    # Convert 3-day close rate to percentage
    if 'pct_closed_3days_raw' in base.columns:
        base['pct_closed_3days'] = (
            pd.to_numeric(base['pct_closed_3days_raw'], errors='coerce') * 100
        ).round(1)
    else:
        base['pct_closed_3days'] = np.nan

    # Classify firm type
    base['firm_type'] = base['firm_name'].apply(classify_firm_type)

    # Clean up group column
    if 'group' in base.columns:
        base['group'] = base['group'].fillna('').astype(str).str.strip()

    print(f"  Result: {len(base)} rows loaded")
    return base


# MAIN
def main():
    print("=" * 60)
    print("FCA COMPLAINTS DATA - CLEANING PIPELINE")
    print("=" * 60)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    all_dfs = []

    for filename, period_label, period_order, period_start, period_end in FILES:
        filepath = os.path.join(RAW_FOLDER, filename)

        if not os.path.exists(filepath):
            print(f"\nWARNING: File not found - {filename} - skipping")
            continue

        result = read_fca_file(
            filepath, period_label, period_order, period_start, period_end
        )

        if result is not None:
            all_dfs.append(result)

    if not all_dfs:
        print("\nERROR: No data loaded. Check file paths.")
        return

    # Combine all periods into one dataset
    master = pd.concat(all_dfs, ignore_index=True)

    # Remove duplicates (just in case)
    before = len(master)
    master = master.drop_duplicates(
        subset=['firm_name', 'product_category', 'period_label']
    )
    if len(master) < before:
        print(f"\nRemoved {before - len(master)} duplicate rows")

    # Sort by firm, category, period
    master = master.sort_values(
        ['firm_name', 'product_category', 'period_order']
    ).reset_index(drop=True)

    master['record_id'] = range(1, len(master) + 1)

    # Period-on-period change metrics
    grp = master.groupby(['firm_name', 'product_category'])

    master['prev_complaints_opened'] = grp['complaints_opened'].shift(1)
    master['complaints_change_abs']  = (
        master['complaints_opened'] - master['prev_complaints_opened']
    ).round(0)
    master['complaints_change_pct']  = np.where(
        master['prev_complaints_opened'] > 0,
        ((master['complaints_opened'] - master['prev_complaints_opened'])
         / master['prev_complaints_opened'] * 100).round(1),
        np.nan
    )

    master['prev_upheld_pct']    = grp['upheld_pct'].shift(1)
    master['upheld_change_ppts'] = (
        master['upheld_pct'] - master['prev_upheld_pct']
    ).round(1)

    # Simple risk flags
    master['high_uphold_flag'] = (master['upheld_pct'] >= 50).astype(int)

    def uphold_band(pct):
        if pd.isna(pct):
            return 'Unknown'
        if pct >= 70:
            return 'Very High (70%+)'
        if pct >= 50:
            return 'High (50-70%)'
        if pct >= 35:
            return 'Moderate (35-50%)'
        return 'Lower (<35%)'

    master['upheld_band'] = master['upheld_pct'].apply(uphold_band)

    # Drop helper columns
    drop_cols = ['upheld_rate', 'pct_closed_3days_raw',
                 'prev_complaints_opened', 'prev_upheld_pct']
    master = master.drop(
        columns=[c for c in drop_cols if c in master.columns]
    )

    # Save CSV
    csv_path = os.path.join(OUTPUT_FOLDER, "fca_complaints_master.csv")
    master.to_csv(csv_path, index=False)

    # Save Excel (multiple sheets for Power BI)
    xlsx_path = os.path.join(OUTPUT_FOLDER, "fca_complaints_master.xlsx")
    with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:

        master.to_excel(writer, sheet_name='All Data', index=False)

        # Volume pivot table
        vol_pivot = master.pivot_table(
            index=['firm_name', 'firm_type'],
            columns='period_label',
            values='complaints_opened',
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        vol_pivot.to_excel(
            writer, sheet_name='Volume by Firm x Period', index=False
        )

        # Uphold rate pivot table
        upheld_pivot = master.pivot_table(
            index=['firm_name', 'firm_type'],
            columns='period_label',
            values='upheld_pct',
            aggfunc='mean'
        ).round(1).reset_index()
        upheld_pivot.to_excel(
            writer, sheet_name='Upheld% by Firm x Period', index=False
        )

        # Category summary
        cat_summary = master.groupby(
            ['period_label', 'product_category', 'pre_post_duty']
        ).agg(
            total_opened=('complaints_opened', 'sum'),
            avg_upheld_pct=('upheld_pct', 'mean'),
            firm_count=('firm_name', 'nunique')
        ).round(1).reset_index()
        cat_summary.to_excel(
            writer, sheet_name='Category Summary', index=False
        )

    # Print summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\nRows:         {len(master):,}")
    print(f"Unique firms: {master['firm_name'].nunique():,}")
    print(f"Periods:      {sorted(master['period_label'].unique())}")
    print(f"\nSaved: {csv_path}")
    print(f"Saved: {xlsx_path}")
    print(f"\nNext step: run 02_sql_analysis.py")


if __name__ == "__main__":
    main()
