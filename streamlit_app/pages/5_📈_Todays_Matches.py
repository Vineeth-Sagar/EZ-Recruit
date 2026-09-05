"""
5_📈_Todays_Matches.py
Live, filterable view of the latest (or any past) job report — the point
is you shouldn't need to download an Excel file just to see what matched
today. Excel stays available as an export, not the only output.
"""
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from utils.secrets_helper import get_secret
from utils.theme import inject_base_css

sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(page_title="Today's Matches — OpportunityBot", page_icon="📈", layout="wide")

inject_base_css()

st.title("📈 Today's Matches")
st.caption("Browse, filter, and apply — right here, no Excel download required.")

ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = ROOT / "data" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

SHEET_NAME = "📋 Today's Jobs"
COMPANY_COL, ROLE_COL, MATCH_COL, URGENCY_COL, APPLY_COL = (
    "🏢 Company", "💼 Role", "🎯 Match %", "🌟 Urgency", "🔗 Apply Link",
)


@st.cache_data(show_spinner=False)
def _read_report(data: bytes) -> pd.DataFrame:
    return pd.read_excel(BytesIO(data), sheet_name=SHEET_NAME, engine="openpyxl")


def _gather_reports():
    """(date_str -> raw bytes loader) for every report we can find, local
    reports first (mirrors the History page's own preference)."""
    reports = {}
    for p in sorted(REPORTS_DIR.glob("*.xlsx"), reverse=True):
        date_str = p.stem.replace("jobs_", "")
        reports[date_str] = p.read_bytes

    if not reports:
        try:
            pat = get_secret("GH_PAT", "")
            repo = get_secret("GITHUB_REPO", "")
            if pat and repo:
                import requests
                from utils.github_sync import list_reports
                for r in list_reports(pat, repo):
                    date_str = r["name"].replace("jobs_", "").replace(".xlsx", "")
                    url = r.get("download_url", "")
                    if url:
                        reports[date_str] = lambda u=url: requests.get(u, timeout=15).content
        except Exception:
            pass

    return reports


reports = _gather_reports()

if not reports:
    st.info(
        "📭 No reports yet. Run the bot once (🧪 Test Run page, or wait for "
        "tomorrow's schedule) and matched jobs will show up here."
    )
    st.stop()

date_options = sorted(reports.keys(), reverse=True)
selected_date = st.selectbox("📅 Report date", date_options, index=0)

with st.spinner("Loading report…"):
    try:
        raw_bytes = reports[selected_date]()
        df = _read_report(raw_bytes)
    except Exception as e:
        st.error(f"Could not load this report: {e}")
        st.stop()

if df.empty or MATCH_COL not in df.columns:
    st.info("This report has no matched jobs.")
    st.stop()

df["_match_pct"] = df[MATCH_COL].astype(str).str.rstrip("%").astype(int)

# ── Stats row ────────────────────────────────────────────────
total = len(df)
high = int((df["_match_pct"] >= 80).sum())
urgent = int(df[URGENCY_COL].astype(str).str.contains("Apply Today").sum()) if URGENCY_COL in df.columns else 0
best = int(df["_match_pct"].max())

c1, c2, c3, c4 = st.columns(4)
for col, num, label in zip(
    (c1, c2, c3, c4),
    (total, high, urgent, f"{best}%"),
    ("Jobs Found", "80%+ Match 🟢", "Apply Today 🔴", "Best Match"),
):
    with col:
        st.markdown(
            f'<div class="stat-card"><div class="number">{num}</div>'
            f'<div class="label">{label}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Filters ──────────────────────────────────────────────────
f1, f2, f3 = st.columns([2, 2, 3])
with f1:
    min_match = st.slider("Minimum match %", 0, 100, 0, step=5)
with f2:
    urgency_opts = sorted(df[URGENCY_COL].dropna().unique()) if URGENCY_COL in df.columns else []
    picked_urgency = st.multiselect("Urgency", urgency_opts, default=urgency_opts)
with f3:
    search = st.text_input("🔍 Search company or role", "")

filtered = df[df["_match_pct"] >= min_match]
if picked_urgency and URGENCY_COL in df.columns:
    filtered = filtered[filtered[URGENCY_COL].isin(picked_urgency)]
if search:
    company_match = filtered.get(COMPANY_COL, pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
    role_match = filtered.get(ROLE_COL, pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
    filtered = filtered[company_match | role_match]

filtered = filtered.sort_values("_match_pct", ascending=False)

st.caption(f"Showing {len(filtered)} of {total} jobs")

display_cols = [c for c in [
    COMPANY_COL, ROLE_COL, MATCH_COL, URGENCY_COL, "📍 Location", APPLY_COL,
    "✅ Matched Skills", "❌ Missing Skills", "📌 Source",
] if c in filtered.columns]

st.dataframe(
    filtered[display_cols],
    use_container_width=True,
    hide_index=True,
    height=560,
    column_config={
        APPLY_COL: st.column_config.LinkColumn("Apply", display_text="Apply →"),
    },
)

st.download_button(
    "⬇️ Download full Excel report",
    data=raw_bytes,
    file_name=f"jobs_{selected_date}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
