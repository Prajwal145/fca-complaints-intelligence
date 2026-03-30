import sqlite3
import pandas as pd
import os
import sys

# SETTINGS
MASTER_CSV    = "./processed/fca_complaints_master.csv"
OUTPUT_FOLDER = "./processed/sql_outputs"
DB_PATH       = "./processed/fca_complaints.db"


# LOAD DATA INTO SQLITE
def load_data(csv_path, db_path):
    print("=" * 60)
    print("LOADING DATA INTO SQLITE")
    print("=" * 60)

    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found.")
        print("Run 01_data_cleaning.py first.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"  Loaded: {len(df):,} rows x {len(df.columns)} columns")

    conn = sqlite3.connect(db_path)
    df.to_sql("complaints", conn, if_exists="replace", index=False)

    count = conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    print(f"  SQLite table ready: {count:,} rows")

    return conn


# RUN A QUERY AND SAVE IT
def run_query(conn, query_name, title, sql, output_folder):
    print(f"\n  {title}")
    try:
        df = pd.read_sql_query(sql, conn)
        path = os.path.join(output_folder, f"{query_name}.csv")
        df.to_csv(path, index=False)
        print(f"  {len(df)} rows saved to {path}")
        if len(df) > 0:
            print(df[df.columns[:5]].head(3).to_string(index=False))
        return df
    except Exception as e:
        print(f"  ERROR: {e}")
        return pd.DataFrame()


# SQL QUERIES

# MODULE A: Volume and Trend
SQL_A1 = """
SELECT
    firm_name,
    firm_type,
    COUNT(DISTINCT period_label)        AS periods_reported,
    SUM(complaints_opened)              AS total_complaints,
    ROUND(AVG(complaints_opened), 0)    AS avg_per_period,
    ROUND(AVG(upheld_pct), 1)           AS avg_upheld_pct,
    RANK() OVER (
        ORDER BY SUM(complaints_opened) DESC
    ) AS volume_rank
FROM complaints
GROUP BY firm_name, firm_type
ORDER BY total_complaints DESC
LIMIT 30
"""

SQL_A2 = """
WITH period_totals AS (
    SELECT
        firm_name, firm_type,
        period_label, period_order, pre_post_duty,
        SUM(complaints_opened) AS total_opened
    FROM complaints
    GROUP BY firm_name, firm_type, period_label, period_order, pre_post_duty
),
with_lag AS (
    SELECT *,
        LAG(total_opened) OVER (
            PARTITION BY firm_name ORDER BY period_order
        ) AS prev_opened,
        LAG(period_label) OVER (
            PARTITION BY firm_name ORDER BY period_order
        ) AS prev_label
    FROM period_totals
)
SELECT
    firm_name, firm_type,
    period_label        AS current_period,
    pre_post_duty,
    total_opened        AS complaints_this_period,
    prev_label,
    prev_opened         AS complaints_prev_period,
    total_opened - prev_opened AS change_absolute,
    ROUND(
        CAST(total_opened - prev_opened AS FLOAT) / prev_opened * 100, 1
    ) AS change_pct
FROM with_lag
WHERE prev_opened IS NOT NULL
ORDER BY change_pct DESC
"""

SQL_A3 = """
WITH firm_periods AS (
    SELECT firm_name, firm_type, period_order, period_label, pre_post_duty,
           SUM(complaints_opened) AS total_opened
    FROM complaints
    GROUP BY firm_name, firm_type, period_order, period_label, pre_post_duty
),
first_last AS (
    SELECT firm_name, firm_type,
           MIN(period_order) AS first_ord,
           MAX(period_order) AS last_ord,
           COUNT(DISTINCT period_order) AS periods_present
    FROM firm_periods
    GROUP BY firm_name, firm_type
    HAVING COUNT(DISTINCT period_order) >= 2
),
combined AS (
    SELECT fl.firm_name, fl.firm_type, fl.periods_present,
           fp1.total_opened AS first_vol, fp1.period_label AS first_label,
           fp2.total_opened AS last_vol, fp2.period_label AS last_label,
           fp2.pre_post_duty AS latest_duty
    FROM first_last fl
    JOIN firm_periods fp1
        ON fl.firm_name = fp1.firm_name AND fl.first_ord = fp1.period_order
    JOIN firm_periods fp2
        ON fl.firm_name = fp2.firm_name AND fl.last_ord = fp2.period_order
)
SELECT
    firm_name, firm_type, first_label, last_label,
    latest_duty, periods_present, first_vol, last_vol,
    last_vol - first_vol AS absolute_growth,
    ROUND(CAST(last_vol - first_vol AS FLOAT) / first_vol * 100, 1) AS growth_pct,
    CASE
        WHEN last_vol > first_vol AND latest_duty = 'Post-Duty'
        THEN 'GROWING POST-DUTY - HIGH RISK'
        WHEN last_vol > first_vol THEN 'GROWING'
        ELSE 'DECLINING OR STABLE'
    END AS trend_flag
FROM combined
WHERE first_vol > 500
ORDER BY growth_pct DESC
LIMIT 15
"""

SQL_A4 = """
SELECT
    pre_post_duty, period_label, period_order,
    COUNT(DISTINCT firm_name)       AS firms_reporting,
    SUM(complaints_opened)          AS total_opened,
    ROUND(AVG(upheld_pct), 1)       AS avg_upheld_pct,
    ROUND(AVG(pct_closed_3days), 1) AS avg_pct_closed_3days
FROM complaints
GROUP BY pre_post_duty, period_label, period_order
ORDER BY period_order
"""

# MODULE B: Product Categories
SQL_B1 = """
SELECT
    product_category,
    COUNT(DISTINCT firm_name)   AS firms_in_category,
    SUM(complaints_opened)      AS total_opened,
    ROUND(AVG(upheld_pct), 1)   AS avg_upheld_pct,
    SUM(CASE WHEN pre_post_duty = 'Pre-Duty'
        THEN complaints_opened END) AS total_pre_duty,
    SUM(CASE WHEN pre_post_duty = 'Post-Duty'
        THEN complaints_opened END) AS total_post_duty
FROM complaints
GROUP BY product_category
ORDER BY total_opened DESC
"""

SQL_B2 = """
WITH cat_duty AS (
    SELECT product_category, pre_post_duty,
           SUM(complaints_opened)    AS total_opened,
           ROUND(AVG(upheld_pct), 1) AS avg_upheld
    FROM complaints
    GROUP BY product_category, pre_post_duty
)
SELECT
    pre.product_category,
    pre.total_opened    AS pre_duty_opened,
    post.total_opened   AS post_duty_opened,
    post.total_opened - pre.total_opened AS volume_change,
    ROUND(CAST(post.total_opened - pre.total_opened AS FLOAT)
          / pre.total_opened * 100, 1) AS volume_change_pct,
    pre.avg_upheld      AS pre_duty_upheld,
    post.avg_upheld     AS post_duty_upheld,
    ROUND(post.avg_upheld - pre.avg_upheld, 1) AS upheld_change_ppts,
    CASE
        WHEN post.total_opened > pre.total_opened
         AND post.avg_upheld > pre.avg_upheld
        THEN 'WORSENED - Volume and uphold rate both increased'
        WHEN post.total_opened < pre.total_opened
         AND post.avg_upheld < pre.avg_upheld
        THEN 'IMPROVED - Volume and uphold rate both decreased'
        WHEN post.total_opened > pre.total_opened
        THEN 'MIXED - More complaints but lower uphold rate'
        ELSE 'MIXED - Signal unclear'
    END AS consumer_duty_verdict
FROM cat_duty pre
JOIN cat_duty post
    ON pre.product_category = post.product_category
    AND pre.pre_post_duty = 'Pre-Duty'
    AND post.pre_post_duty = 'Post-Duty'
ORDER BY upheld_change_ppts DESC
"""

# MODULE C: Uphold Rate Analysis
SQL_C1 = """
SELECT
    firm_name, firm_type,
    COUNT(DISTINCT period_label)    AS periods_reported,
    ROUND(AVG(upheld_pct), 1)       AS avg_upheld_pct,
    ROUND(MIN(upheld_pct), 1)       AS min_upheld_pct,
    ROUND(MAX(upheld_pct), 1)       AS max_upheld_pct,
    SUM(complaints_opened)          AS total_complaints,
    CASE
        WHEN AVG(upheld_pct) >= 70 THEN 'VERY HIGH RISK - 70 percent or above'
        WHEN AVG(upheld_pct) >= 50 THEN 'HIGH RISK - 50 to 70 percent'
        WHEN AVG(upheld_pct) >= 35 THEN 'MODERATE - 35 to 50 percent'
        ELSE 'LOWER RISK - Below 35 percent'
    END AS risk_band
FROM complaints
WHERE upheld_pct IS NOT NULL
GROUP BY firm_name, firm_type
HAVING COUNT(DISTINCT period_label) >= 2
   AND SUM(complaints_opened) > 1000
ORDER BY avg_upheld_pct DESC
LIMIT 25
"""

SQL_C2 = """
WITH period_uphold AS (
    SELECT firm_name, firm_type, period_label, period_order,
           ROUND(AVG(upheld_pct), 1) AS avg_upheld
    FROM complaints
    WHERE upheld_pct IS NOT NULL
    GROUP BY firm_name, firm_type, period_label, period_order
),
with_lag AS (
    SELECT *,
        LAG(avg_upheld) OVER (
            PARTITION BY firm_name ORDER BY period_order
        ) AS prev_upheld,
        LAG(period_label) OVER (
            PARTITION BY firm_name ORDER BY period_order
        ) AS prev_label
    FROM period_uphold
),
summary AS (
    SELECT firm_name, firm_type,
           MIN(prev_label)   AS earliest_period,
           MAX(period_label) AS latest_period,
           MIN(prev_upheld)  AS upheld_start,
           MAX(avg_upheld)   AS upheld_latest,
           ROUND(AVG(avg_upheld - prev_upheld), 2) AS avg_change
    FROM with_lag
    WHERE prev_upheld IS NOT NULL
    GROUP BY firm_name, firm_type
)
SELECT
    firm_name, firm_type, earliest_period, latest_period,
    ROUND(upheld_start, 1)            AS upheld_pct_start,
    ROUND(upheld_latest, 1)           AS upheld_pct_latest,
    ROUND(upheld_latest - upheld_start, 1) AS total_change_ppts,
    ROUND(avg_change, 2)              AS avg_change_per_period,
    CASE
        WHEN upheld_latest - upheld_start > 10
        THEN 'SHARP DETERIORATION - Over 10 percentage points'
        WHEN upheld_latest - upheld_start > 5
        THEN 'MODERATE DETERIORATION - 5 to 10 percentage points'
        WHEN upheld_latest - upheld_start > 0
        THEN 'SLIGHT INCREASE - 0 to 5 percentage points'
        ELSE 'STABLE OR IMPROVING'
    END AS trend_verdict
FROM summary
WHERE upheld_latest - upheld_start > 0
ORDER BY total_change_ppts DESC
LIMIT 20
"""

SQL_C3 = """
WITH firm_summary AS (
    SELECT firm_name, firm_type,
           SUM(complaints_opened)    AS total_opened,
           ROUND(AVG(upheld_pct), 1) AS avg_upheld_pct,
           COUNT(DISTINCT period_label) AS periods_reported
    FROM complaints
    WHERE upheld_pct IS NOT NULL
    GROUP BY firm_name, firm_type
    HAVING SUM(complaints_opened) > 1000
),
with_quartiles AS (
    SELECT *,
        NTILE(4) OVER (ORDER BY total_opened ASC)   AS volume_quartile,
        NTILE(4) OVER (ORDER BY avg_upheld_pct ASC) AS uphold_quartile
    FROM firm_summary
)
SELECT
    firm_name, firm_type, total_opened, avg_upheld_pct,
    periods_reported, volume_quartile, uphold_quartile,
    volume_quartile + uphold_quartile AS combined_risk_score,
    CASE
        WHEN volume_quartile = 4 AND uphold_quartile = 4
        THEN 'DANGER QUADRANT - Highest risk'
        WHEN volume_quartile = 4 AND uphold_quartile >= 3
        THEN 'HIGH RISK - High volume, elevated uphold rate'
        WHEN volume_quartile >= 3 AND uphold_quartile = 4
        THEN 'HIGH RISK - High uphold rate, significant volume'
        WHEN volume_quartile = 4
        THEN 'ELEVATED - High volume, acceptable uphold rate'
        WHEN uphold_quartile = 4
        THEN 'ELEVATED - High uphold rate, lower volume'
        ELSE 'ACCEPTABLE - Within normal parameters'
    END AS quadrant_classification
FROM with_quartiles
ORDER BY combined_risk_score DESC, total_opened DESC
"""

SQL_C4 = """
WITH pre_post AS (
    SELECT firm_name, firm_type, pre_post_duty,
           ROUND(AVG(upheld_pct), 1) AS avg_upheld,
           SUM(complaints_opened)    AS total_opened
    FROM complaints
    WHERE upheld_pct IS NOT NULL
    GROUP BY firm_name, firm_type, pre_post_duty
),
pivoted AS (
    SELECT firm_name, firm_type,
        MAX(CASE WHEN pre_post_duty = 'Pre-Duty'
            THEN avg_upheld END) AS pre_upheld,
        MAX(CASE WHEN pre_post_duty = 'Post-Duty'
            THEN avg_upheld END) AS post_upheld,
        MAX(CASE WHEN pre_post_duty = 'Pre-Duty'
            THEN total_opened END) AS pre_volume,
        MAX(CASE WHEN pre_post_duty = 'Post-Duty'
            THEN total_opened END) AS post_volume
    FROM pre_post
    GROUP BY firm_name, firm_type
    HAVING pre_upheld IS NOT NULL AND post_upheld IS NOT NULL
)
SELECT
    firm_name, firm_type, pre_upheld, post_upheld,
    ROUND(post_upheld - pre_upheld, 1) AS change_ppts,
    pre_volume, post_volume,
    CASE
        WHEN post_upheld - pre_upheld > 5
        THEN 'WORSENED SIGNIFICANTLY - Over 5 points'
        WHEN post_upheld - pre_upheld > 0
        THEN 'WORSENED SLIGHTLY - 0 to 5 points'
        WHEN post_upheld - pre_upheld > -5
        THEN 'MINIMAL IMPROVEMENT - 0 to 5 points'
        ELSE 'CLEAR IMPROVEMENT - Over 5 points'
    END AS consumer_duty_response
FROM pivoted
ORDER BY change_ppts DESC
"""

# MODULE D: Resolution Speed
SQL_D1 = """
SELECT
    firm_name, firm_type,
    COUNT(DISTINCT period_label)        AS periods_reported,
    ROUND(AVG(pct_closed_3days), 1)     AS avg_pct_closed_3days,
    ROUND(AVG(upheld_pct), 1)           AS avg_upheld_pct,
    SUM(complaints_opened)              AS total_opened,
    CASE
        WHEN AVG(pct_closed_3days) >= 70
        THEN 'FAST RESOLVER - 70 percent or more in 3 days'
        WHEN AVG(pct_closed_3days) >= 40
        THEN 'MODERATE RESOLVER - 40 to 70 percent in 3 days'
        ELSE 'SLOW RESOLVER - Under 40 percent in 3 days'
    END AS resolution_band
FROM complaints
WHERE pct_closed_3days IS NOT NULL
GROUP BY firm_name, firm_type
HAVING SUM(complaints_opened) > 1000
ORDER BY avg_pct_closed_3days DESC
LIMIT 25
"""

SQL_D2 = """
SELECT
    firm_type, pre_post_duty,
    COUNT(DISTINCT firm_name)           AS firms_count,
    ROUND(AVG(pct_closed_3days), 1)     AS avg_pct_closed_3days,
    ROUND(AVG(upheld_pct), 1)           AS avg_upheld_pct,
    SUM(complaints_opened)              AS total_opened
FROM complaints
WHERE pct_closed_3days IS NOT NULL AND upheld_pct IS NOT NULL
GROUP BY firm_type, pre_post_duty
ORDER BY firm_type, pre_post_duty
"""


# KEY FINDINGS SUMMARY
def print_key_findings(conn, output_folder):
    print("\n" + "=" * 60)
    print("KEY FINDINGS")
    print("=" * 60)

    findings = {}

    # Industry overview
    q = pd.read_sql_query("""
        SELECT pre_post_duty,
               SUM(complaints_opened)     AS total_opened,
               ROUND(AVG(upheld_pct), 1)  AS avg_upheld_pct,
               COUNT(DISTINCT firm_name)  AS unique_firms
        FROM complaints
        GROUP BY pre_post_duty
    """, conn)
    findings['industry_overview'] = q
    print("\n1. Industry Overview:")
    print(q.to_string(index=False))

    # Danger quadrant firms
    q2 = pd.read_sql_query("""
        WITH fs AS (
            SELECT firm_name, firm_type,
                   SUM(complaints_opened)    AS total_opened,
                   ROUND(AVG(upheld_pct), 1) AS avg_upheld
            FROM complaints WHERE upheld_pct IS NOT NULL
            GROUP BY firm_name, firm_type
            HAVING SUM(complaints_opened) > 1000
        ),
        wq AS (
            SELECT *,
                NTILE(4) OVER (ORDER BY total_opened ASC) AS vq,
                NTILE(4) OVER (ORDER BY avg_upheld ASC)   AS uq
            FROM fs
        )
        SELECT firm_name, firm_type, total_opened, avg_upheld
        FROM wq WHERE vq = 4 AND uq = 4
        ORDER BY avg_upheld DESC
    """, conn)
    findings['danger_quadrant'] = q2
    print(f"\n2. Danger Quadrant Firms ({len(q2)} firms):")
    print(q2.to_string(index=False))

    # Consumer Duty uphold shift
    q3 = pd.read_sql_query("""
        SELECT pre_post_duty,
               ROUND(AVG(upheld_pct), 2) AS avg_upheld_pct,
               COUNT(DISTINCT firm_name) AS firms
        FROM complaints WHERE upheld_pct IS NOT NULL
        GROUP BY pre_post_duty
    """, conn)
    findings['duty_uphold_shift'] = q3
    print(f"\n3. Consumer Duty Uphold Rate Shift:")
    print(q3.to_string(index=False))

    # Firms worsened post duty
    q4 = pd.read_sql_query("""
        WITH pp AS (
            SELECT firm_name, pre_post_duty,
                   ROUND(AVG(upheld_pct), 1) AS avg_upheld
            FROM complaints WHERE upheld_pct IS NOT NULL
            GROUP BY firm_name, pre_post_duty
        )
        SELECT p.firm_name,
            MAX(CASE WHEN p.pre_post_duty = 'Pre-Duty'
                THEN p.avg_upheld END) AS pre_upheld,
            MAX(CASE WHEN p.pre_post_duty = 'Post-Duty'
                THEN p.avg_upheld END) AS post_upheld,
            ROUND(
                MAX(CASE WHEN p.pre_post_duty = 'Post-Duty'
                    THEN p.avg_upheld END)
                - MAX(CASE WHEN p.pre_post_duty = 'Pre-Duty'
                    THEN p.avg_upheld END)
            , 1) AS change_ppts
        FROM pp p
        GROUP BY p.firm_name
        HAVING pre_upheld IS NOT NULL
           AND post_upheld IS NOT NULL
           AND change_ppts > 5
        ORDER BY change_ppts DESC
        LIMIT 10
    """, conn)
    findings['worsened_post_duty'] = q4
    print(f"\n4. Firms Worsened Over 5pts Post-Duty:")
    print(q4.to_string(index=False))

    # Save findings to text file
    findings_path = os.path.join(output_folder, "KEY_FINDINGS.txt")
    with open(findings_path, "w", encoding="utf-8") as f:
        f.write("FCA COMPLAINTS INTELLIGENCE - KEY FINDINGS\n")
        f.write("=" * 60 + "\n\n")
        f.write("USE THESE NUMBERS IN YOUR README AND LINKEDIN POST\n\n")
        for name, df in findings.items():
            f.write(f"\n{'─'*50}\n{name.upper()}\n{'─'*50}\n")
            f.write(df.to_string(index=False) + "\n")

    print(f"\n  Saved: {findings_path}")


# MAIN
def main():
    conn = load_data(MASTER_CSV, DB_PATH)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    print("\n" + "=" * 60)
    print("RUNNING SQL QUERIES")
    print("=" * 60)

    # Run all 12 queries
    queries = [
        ("A1_volume_by_firm",          "A1 - Total Volume by Firm",              SQL_A1),
        ("A2_period_on_period",         "A2 - Period on Period Change",           SQL_A2),
        ("A3_fastest_growing",          "A3 - Fastest Growing Firms",            SQL_A3),
        ("A4_pre_vs_post_industry",     "A4 - Industry Pre vs Post Duty",        SQL_A4),
        ("B1_volume_by_category",       "B1 - Volume by Product Category",       SQL_B1),
        ("B2_category_post_duty",       "B2 - Category Shift Post Duty",         SQL_B2),
        ("C1_uphold_rate_ranked",       "C1 - Firms Ranked by Uphold Rate",      SQL_C1),
        ("C2_rising_uphold_firms",      "C2 - Firms with Rising Uphold Rate",    SQL_C2),
        ("C3_danger_quadrant",          "C3 - Danger Quadrant Analysis",         SQL_C3),
        ("C4_uphold_pre_post_duty",     "C4 - Uphold Rate Pre vs Post Duty",     SQL_C4),
        ("D1_resolution_speed",         "D1 - Resolution Speed by Firm",         SQL_D1),
        ("D2_resolution_pre_post",      "D2 - Resolution Speed Pre vs Post",     SQL_D2),
    ]

    successful = 0
    for query_name, title, sql in queries:
        result = run_query(conn, query_name, title, sql, OUTPUT_FOLDER)
        if len(result) > 0:
            successful += 1

    print_key_findings(conn, OUTPUT_FOLDER)

    conn.close()

    print("\n" + "=" * 60)
    print("SQL ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"\nQueries run:    {len(queries)}")
    print(f"Successful:     {successful}")
    print(f"Output folder:  {OUTPUT_FOLDER}/")
    print("\nOpen KEY_FINDINGS.txt for the headline numbers.")
    print("Next step: open 03_eda_notebook.ipynb")


if __name__ == "__main__":
    main()
