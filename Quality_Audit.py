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
def load_data_from_gcs(bucket_name, creds_path):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    client = storage.Client(credentials=creds)
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs())

    data = []
    for blob in blobs:
        if blob.name.endswith(".json"):
            content = blob.download_as_text()
            try:
                record = json.loads(content)
                data.append(record)
            except:
                continue
    return pd.json_normalize(data)

# ---- Load Data ----
st.title("📊 Quality Audit Dashboard")

with st.spinner("Loading data from GCS..."):
    df = load_data_from_gcs(BUCKET_NAME, CREDS_FILE)

if df.empty:
    st.warning("No audit data found.")
    st.stop()

# ---- Filter Sidebar ----
st.sidebar.header("Filters")
selected_agent = st.sidebar.selectbox("Select Agent", options=["All"] + sorted(df["Associate Name"].dropna().unique().tolist()))
selected_tl = st.sidebar.selectbox("Select Team Lead", options=["All"] + sorted(df["Team Lead"].dropna().unique().tolist()))
selected_type = st.sidebar.selectbox("Select Audit Type", options=["All"] + sorted(df["Audit Type"].dropna().unique().tolist()))

# ---- Apply Filters ----
if selected_agent != "All":
    df = df[df["Associate Name"] == selected_agent]
if selected_tl != "All":
    df = df[df["Team Lead"] == selected_tl]
if selected_type != "All":
    df = df[df["Audit Type"] == selected_type]

# ---- Summary Metrics ----
st.subheader("📈 Score Summary")
avg_score = df["Total Score"].mean()
total_audits = len(df)
ztp_count = (df["ZTP Violation"] == "Yes").sum()

col1, col2, col3 = st.columns(3)
col1.metric("Average Score", f"{avg_score:.2f}%")
col2.metric("Total Audits", total_audits)
col3.metric("ZTP Cases", ztp_count)

# ---- Score Over Time ----
df["Audit Date"] = pd.to_datetime(df["Audit Date"], errors='coerce')
df = df.sort_values("Audit Date")

fig = px.line(df, x="Audit Date", y="Total Score", color="Associate Name", markers=True, title="Score Over Time")
st.plotly_chart(fig, use_container_width=True)

# ---- Parameter-wise Breakdown ----
if "Parameters" in df.columns:
    param_df = pd.DataFrame([
        {
            "Agent": row["Associate Name"],
            "Audit Date": row["Audit Date"],
            "Parameter": p["Parameter"],
            "Score": p["Score"],
            "Reason": p["Selected Reasons"]
        }
        for _, row in df.iterrows() if isinstance(row["Parameters"], list)
        for p in row["Parameters"]
    ])

    st.subheader("🧩 Parameter Breakdown")
    fig2 = px.box(param_df, x="Parameter", y="Score", points="all", color="Parameter")
    st.plotly_chart(fig2, use_container_width=True)

# ---- Raw Data ----
st.subheader("📋 Raw Audit Entries")
st.dataframe(df.sort_values("Audit Date", ascending=False), use_container_width=True)
