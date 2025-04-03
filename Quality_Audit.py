import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px
from google.cloud import storage
from google.oauth2 import service_account

# ---- Configuration ----
BUCKET_NAME = "jupiter-quality-audit"
CREDS_FILE = "vertical-album-455112-i0-9288d1231fb9.json"

# ---- Setup GCS ----
@st.cache_data(show_spinner=False)
def load_data_from_gcs(bucket_name, creds_path):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    client = storage.Client(credentials=creds)
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs())

    data = []
    for blob in blobs:
        if blob.name.endswith(".json"):
            try:
                content = blob.download_as_text()
                record = json.loads(content)
                data.append(record)
            except Exception as e:
                st.warning(f"Failed to parse {blob.name}: {e}")
                continue

    if not data:
        return pd.DataFrame()

    return pd.json_normalize(data)

# ---- Load Data ----
st.title("📊 Quality Audit Dashboard")

with st.spinner("Loading data from GCS..."):
    df = load_data_from_gcs(BUCKET_NAME, CREDS_FILE)

if df.empty:
    st.warning("No audit data found.")
    st.stop()

# ---- Data Cleanup ----
df["Total Score"] = pd.to_numeric(df["Total Score"], errors="coerce")
df["Audit Date"] = pd.to_datetime(df["Audit Date"], errors="coerce")
df = df.dropna(subset=["Audit Date"])  # drop invalid dates

# Date Range Filter
min_date = df["Audit Date"].min().date()
max_date = df["Audit Date"].max().date()
date_range = st.sidebar.date_input("Select Date Range", [min_date, max_date])

if len(date_range) == 2:
    start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
    df = df[(df["Audit Date"] >= start_date) & (df["Audit Date"] <= end_date)]


# ---- Filter Sidebar ----
st.sidebar.header("Filters")
selected_agent = st.sidebar.selectbox("Select Agent", options=["All"] + sorted(df["Associate Name"].dropna().unique().tolist()))
selected_tl = st.sidebar.selectbox("Select Team Lead", options=["All"] + sorted(df["Team Lead"].dropna().unique().tolist()))
selected_type = st.sidebar.selectbox("Select Audit Type", options=["All"] + sorted(df["Audit Type"].dropna().unique().tolist()))
selected_type = st.sidebar.selectbox("Select Audit Type", options=["All"] + sorted(df["Auditor Name"].dropna().unique().tolist()))

# ---- Apply Filters ----
if selected_agent != "All":
    df = df[df["Associate Name"] == selected_agent]
if selected_tl != "All":
    df = df[df["Team Lead"] == selected_tl]
if selected_type != "All":
    df = df[df["Audit Type"] == selected_type]
if selected_type != "All":
    df = df[df["Auditor Name"] == selected_type]

if df.empty:
    st.warning("No audit records match your selected filters.")
    st.stop()

# ---- Summary Metrics ----
st.subheader("📈 Score Summary")
avg_score = df["Total Score"].mean()
total_audits = len(df)
ztp_count = (df["ZTP Violation"] == "Yes").sum()

col1, col2, col3 = st.columns(3)
col1.metric("Average Score", f"{avg_score:.2f}%")
col2.metric("Total Audits", total_audits)
col3.metric("ZTP Cases", ztp_count)

st.subheader("🗓️ Time-Based Summary")

# Add columns for groupings
df["Day"] = df["Audit Date"].dt.date
df["Week"] = df["Audit Date"].dt.to_period("W").astype(str)
df["Month"] = df["Audit Date"].dt.to_period("M").astype(str)

# Define a reusable function for summaries
def show_time_summary(time_col, label):
    grouped = df.groupby(time_col)["Total Score"].agg(["count", "mean"]).reset_index()
    grouped.columns = [label, "Total Audits", "Average Score"]
    st.write(f"### {label} Summary")
    st.dataframe(grouped, use_container_width=True)

    fig = px.line(grouped, x=label, y="Average Score", markers=True, title=f"{label} Wise Score Trend")
    st.plotly_chart(fig, use_container_width=True)

# Show summaries
show_time_summary("Day", "Date")
show_time_summary("Week", "Week")
show_time_summary("Month", "Month")


# ---- Score Over Time ----
df = df.sort_values("Audit Date")

fig = px.line(
    df, x="Audit Date", y="Total Score",
    color="Associate Name" if df["Associate Name"].nunique() > 1 else None,
    markers=True,
    title="Score Over Time"
)
st.plotly_chart(fig, use_container_width=True)

# ---- Parameter-wise Breakdown ----
if "Parameters" in df.columns and df["Parameters"].notna().any():
    param_records = []

    for _, row in df.iterrows():
        if isinstance(row["Parameters"], list):
            for p in row["Parameters"]:
                if all(k in p for k in ("Parameter", "Score", "Selected Reasons")):
                    param_records.append({
                        "Agent": row["Associate Name"],
                        "Audit Date": row["Audit Date"],
                        "Parameter": p["Parameter"],
                        "Score": p["Score"],
                        "Reason": p["Selected Reasons"]
                    })

    if param_records:
        param_df = pd.DataFrame(param_records)
        st.subheader("🧩 Parameter Breakdown")
        fig2 = px.box(param_df, x="Parameter", y="Score", points="all", color="Parameter")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No valid parameter breakdown data found.")
else:
    st.info("No parameter data available.")

# ---- Raw Data ----
st.subheader("📋 Raw Audit Entries")
st.dataframe(df.sort_values("Audit Date", ascending=False), use_container_width=True)
