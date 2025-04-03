import streamlit as st
import pandas as pd
import json
# import os # os was imported but not used
import plotly.express as px
import plotly.graph_objects as go # Needed for Pareto
from plotly.subplots import make_subplots # Needed for Pareto secondary y-axis
from google.cloud import storage
from google.oauth2 import service_account
import traceback # For detailed error logging

# ---- Configuration ----
BUCKET_NAME = "jupiter-quality-audit" # Replace with your bucket name
# !!! IMPORTANT: Replace with your actual credentials file path !!!
# Consider using environment variables or Streamlit secrets for credentials
CREDS_FILE = "vertical-album-455112-i0-9288d1231fb9.json"

# ---- Setup GCS ----
@st.cache_data(show_spinner=False)
def load_data_from_gcs(bucket_name, creds_path):
    """Loads and normalizes audit data from GCS JSON files."""
    all_audit_data = []
    processed_files = set()
    try:
        creds = service_account.Credentials.from_service_account_file(creds_path)
        client = storage.Client(credentials=creds)
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs())

        for blob in blobs:
            if not blob.name or blob.name.startswith('.') or blob.name.endswith('/'): continue

            if blob.name.endswith(".json") and blob.name not in processed_files:
                try:
                    content = blob.download_as_text(encoding='utf-8')
                    record = json.loads(content)
                    # Ensure essential keys exist for normalization later
                    record.setdefault("Parameters", []) # Default to empty list if missing
                    record.setdefault("Total Score", None)
                    record.setdefault("Audit Date", None)
                    record.setdefault("Associate Name", "Unknown")
                    record.setdefault("Team Lead", "Unknown")
                    record.setdefault("Audit Type", "Unknown")
                    record.setdefault("Auditor Name", "Unknown")
                    record.setdefault("ZTP Violation", "No")
                    all_audit_data.append(record)
                    processed_files.add(blob.name)
                except json.JSONDecodeError:
                    st.warning(f"Could not decode JSON: {blob.name}")
                except Exception as e:
                    st.warning(f"Error processing blob {blob.name}: {e}")

        if not all_audit_data:
            st.info("No valid audit records found in the bucket.")
            return pd.DataFrame()

        # Normalize directly from the list of dicts
        df_normalized = pd.json_normalize(all_audit_data)
        st.success(f"Loaded data for {len(df_normalized)} audits.")
        return df_normalized

    except FileNotFoundError:
        st.error(f"GCS Credentials file not found at {creds_path}. Cannot load data.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Failed to initialize GCS client or load data: {e}")
        st.error(traceback.format_exc())
        return pd.DataFrame()

# ---- Load Data ----
st.set_page_config(layout="wide") # Use wide layout for better dashboard view
st.title("📊 Quality Audit Dashboard")

# Load data using the function
with st.spinner("Loading data from GCS..."):
    df_raw = load_data_from_gcs(BUCKET_NAME, CREDS_FILE)

if df_raw.empty:
    st.warning("No audit data found or loaded. Stopping.")
    st.stop()

# ---- Data Cleanup & Initial Processing ----
df = df_raw.copy() # Work with a copy

# Convert types carefully, coercing errors
df["Total Score"] = pd.to_numeric(df["Total Score"], errors="coerce")
df["Audit Date"] = pd.to_datetime(df["Audit Date"], errors="coerce")

# Drop rows essential for filtering/analysis if they are invalid
df = df.dropna(subset=["Audit Date"])
if df.empty:
    st.warning("No audits remaining after removing entries with invalid dates.")
    st.stop()

# ---- Sidebar Filters ----
st.sidebar.header("Filters")

# Date Range Filter
min_date = df["Audit Date"].min().date()
max_date = df["Audit Date"].max().date()
# Handle potential NaT if min/max failed
if pd.isna(min_date) or pd.isna(max_date):
     st.sidebar.error("Could not determine date range.")
     # Set default range or stop
     date_range = []
else:
     date_range = st.sidebar.date_input("Select Date Range", [min_date, max_date], key="date_range_filter")


# Apply Date Filter
if len(date_range) == 2:
    try:
        # Ensure start/end are proper datetimes for comparison
        start_date = pd.to_datetime(date_range[0]).normalize() # Set time to 00:00:00
        end_date = pd.to_datetime(date_range[1]).normalize() + pd.Timedelta(days=1, seconds=-1) # Set time to 23:59:59
        df = df[(df["Audit Date"] >= start_date) & (df["Audit Date"] <= end_date)].copy() # Use .copy()
    except Exception as e:
        st.sidebar.error(f"Invalid date range selected: {e}")

if df.empty:
     st.warning("No data available for the selected date range.")
     st.stop()


# Other Filters
agent_options = ["All"] + sorted(df["Associate Name"].dropna().unique().tolist())
selected_agent = st.sidebar.selectbox("Select Agent", options=agent_options, key="agent_filter")

tl_options = ["All"] + sorted(df["Team Lead"].dropna().unique().tolist())
selected_tl = st.sidebar.selectbox("Select Team Lead", options=tl_options, key="tl_filter")

type_options = ["All"] + sorted(df["Audit Type"].dropna().unique().tolist())
selected_type = st.sidebar.selectbox("Select Audit Type", options=type_options, key="type_filter")

# *** FIX: Use a different variable for Auditor Name filter ***
auditor_options = ["All"] + sorted(df["Auditor Name"].dropna().unique().tolist())
selected_auditor = st.sidebar.selectbox("Select Auditor Name", options=auditor_options, key="auditor_filter")


# ---- Apply Filters ----
df_filtered = df.copy() # Start with date-filtered data
if selected_agent != "All":
    df_filtered = df_filtered[df_filtered["Associate Name"] == selected_agent]
if selected_tl != "All":
    df_filtered = df_filtered[df_filtered["Team Lead"] == selected_tl]
if selected_type != "All":
    df_filtered = df_filtered[df_filtered["Audit Type"] == selected_type]
# *** FIX: Apply the auditor filter correctly ***
if selected_auditor != "All":
    df_filtered = df_filtered[df_filtered["Auditor Name"] == selected_auditor]


# Check if data remains after filtering
if df_filtered.empty:
    st.warning("No audit records match your selected filters.")
    st.stop()


# ---- Dashboard Layout ----

# --- Row 1: Summary Metrics ---
st.subheader("📈 Score Summary")
avg_score = df_filtered["Total Score"].mean()
total_audits = len(df_filtered)
# Ensure ZTP column exists before checking
ztp_count = (df_filtered["ZTP Violation"] == "Yes").sum() if "ZTP Violation" in df_filtered.columns else 0

col1, col2, col3 = st.columns(3)
col1.metric("Average Score", f"{avg_score:.2f}%" if pd.notna(avg_score) else "N/A")
col2.metric("Total Audits", total_audits)
col3.metric("ZTP Cases", ztp_count)

st.markdown("---") # Separator

# ---  debugging ---
st.subheader("🕵️‍♀️ Debugging Parameter Data")
st.write("Filtered DataFrame Columns:", df_filtered.columns.tolist())
if "Parameters" in df_filtered.columns:
    st.write("Data types found in 'Parameters' column:")
    st.write(df_filtered["Parameters"].apply(type).value_counts())
    st.write("First 5 entries in 'Parameters' column:")
    st.dataframe(df_filtered[["Parameters"]].head())

    # Try to inspect the structure of the first valid parameter list item
    first_valid_param_list = None
    for item in df_filtered["Parameters"].dropna():
        if isinstance(item, list) and len(item) > 0 and isinstance(item[0], dict):
             first_valid_param_list = item
             break
        elif isinstance(item, str): # Check if it's a string we might parse
             try:
                 parsed_item = json.loads(item.replace("'",'"'))
                 if isinstance(parsed_item, list) and len(parsed_item) > 0 and isinstance(parsed_item[0], dict):
                     first_valid_param_list = parsed_item
                     break
             except:
                 pass # Ignore strings that fail parsing

    if first_valid_param_list:
        st.write("Structure of the first dictionary inside the first valid 'Parameters' list:")
        st.write(first_valid_param_list[0]) # Show the first dictionary
    else:
        st.warning("Could not find a valid list containing dictionaries in the 'Parameters' column.")

st.markdown("---") # Separator before your analysis starts
# --- End of debugging lines ---


# --- Row 2: Parameter Analysis (Moved Up) ---
st.subheader("🧩 Parameter Analysis")

# Check if 'Parameters' column exists and has data
if "Parameters" in df_filtered.columns and df_filtered["Parameters"].notna().any():
    param_records = []
    failure_reasons_list = [] # For Pareto

    # Iterate through audits to extract parameter details
    for _, row in df_filtered.iterrows():
        # Handle potential variations in how Parameters are stored (list vs. maybe stringified list?)
        parameters_data = row["Parameters"]
        if isinstance(parameters_data, str):
             try:
                 parameters_data = json.loads(parameters_data.replace("'", '"')) # Basic handling for stringified lists
             except:
                 parameters_data = [] # Skip if parsing fails

        if isinstance(parameters_data, list):
            for p in parameters_data:
                # Check if 'p' is a dictionary and has required keys
                if isinstance(p, dict) and all(k in p for k in ("Parameter", "Score", "Selected Reasons Scored")):
                    param_records.append({
                        "Agent": row.get("Associate Name", "N/A"), # Use .get for safety
                        "Audit Date": row.get("Audit Date"),
                        "Parameter": p["Parameter"],
                        "Score": p.get("Score"), # Use .get
                        "Reason": p.get("Selected Reasons Scored", "Compliant") # Use scored reasons
                    })
                    # --- Pareto Data Extraction ---
                    # Check if not compliant based on the reasons used for scoring
                    reasons_scored = p.get("Selected Reasons Scored", "Compliant")
                    is_compliant_scored = "Compliant" in reasons_scored.split(", ") if isinstance(reasons_scored, str) else "Compliant" in reasons_scored

                    if not is_compliant_scored and isinstance(reasons_scored, str):
                         # Split comma-separated reasons and add non-compliant ones
                         individual_reasons = [r.strip() for r in reasons_scored.split(",") if r.strip() and r.strip().lower() != "compliant"]
                         failure_reasons_list.extend(individual_reasons)

    if param_records:
        param_df = pd.DataFrame(param_records)
        param_df["Score"] = pd.to_numeric(param_df["Score"], errors="coerce") # Ensure score is numeric

        # --- Parameter Box Plot ---
        st.markdown("#### Score Distribution by Parameter")
        fig_box = px.box(param_df.dropna(subset=['Score']), # Ensure no NaN scores for plotting
                         x="Parameter", y="Score", points="all", color="Parameter",
                         title="Parameter Score Distribution")
        fig_box.update_layout(xaxis_tickangle=-45) # Improve label readability
        st.plotly_chart(fig_box, use_container_width=True)

        # --- Pareto Chart for Failure Reasons ---
        st.markdown("#### Pareto Analysis of Non-Compliant Reasons")
        if failure_reasons_list:
            reason_counts = pd.Series(failure_reasons_list).value_counts()
            if not reason_counts.empty:
                pareto_df = pd.DataFrame({'Reason': reason_counts.index, 'Count': reason_counts.values})
                pareto_df = pareto_df.sort_values(by='Count', ascending=False)
                pareto_df['Cumulative Percentage'] = (pareto_df['Count'].cumsum() / pareto_df['Count'].sum()) * 100

                # Create figure with secondary y-axis
                fig_pareto = make_subplots(specs=[[{"secondary_y": True}]])

                # Add Bar chart for counts
                fig_pareto.add_trace(
                    go.Bar(x=pareto_df['Reason'], y=pareto_df['Count'], name='Failure Count'),
                    secondary_y=False,
                )

                # Add Line chart for cumulative percentage
                fig_pareto.add_trace(
                    go.Scatter(x=pareto_df['Reason'], y=pareto_df['Cumulative Percentage'], name='Cumulative %', mode='lines+markers'),
                    secondary_y=True,
                )

                # Add figure title and labels
                fig_pareto.update_layout(
                    title_text="Pareto Chart of Non-Compliant Reasons",
                    xaxis_tickangle=-45
                )
                fig_pareto.update_xaxes(title_text="Reason")
                fig_pareto.update_yaxes(title_text="<b>Count</b>", secondary_y=False)
                fig_pareto.update_yaxes(title_text="<b>Cumulative Percentage (%)</b>", secondary_y=True, range=[0, 105]) # Range slightly > 100

                st.plotly_chart(fig_pareto, use_container_width=True)
            else:
                 st.info("No specific non-compliant reasons found to generate Pareto chart.")
        else:
            st.info("No non-compliant reasons extracted for Pareto analysis.")

    else:
        st.info("No valid parameter breakdown data found in selected audits.")
else:
    st.info("Parameter breakdown data ('Parameters' column) not available in the loaded files.")

st.markdown("---") # Separator


# --- Row 3: Time-Based Summaries (Using Tabs) ---
st.subheader("🗓️ Time-Based Summary")

# Add time grouping columns if they don't exist
if "Audit Date" in df_filtered.columns:
     try:
          # Ensure Audit Date is datetime
          df_filtered["Audit Date"] = pd.to_datetime(df_filtered["Audit Date"])
          # Create grouping columns
          df_filtered["Day"] = df_filtered["Audit Date"].dt.date
          # Use dt accessor for period conversion
          df_filtered["Week"] = df_filtered["Audit Date"].dt.to_period("W").astype(str)
          df_filtered["Month"] = df_filtered["Audit Date"].dt.to_period("M").astype(str)
          time_cols_available = True
     except Exception as e:
          st.warning(f"Could not create time groupings: {e}")
          time_cols_available = False
else:
     st.warning("Audit Date column missing, cannot create time-based summaries.")
     time_cols_available = False


if time_cols_available:
     tab_day, tab_week, tab_month = st.tabs(["Daily Summary", "Weekly Summary", "Monthly Summary"])

     # Define a reusable plotting function
     def plot_time_trend(df_grouped, x_col, y_col="Average Score", title="Score Trend"):
          if not df_grouped.empty and y_col in df_grouped.columns:
               # Drop rows where score is NaN before plotting trend
               df_plot = df_grouped.dropna(subset=[y_col])
               if not df_plot.empty:
                    fig = px.line(df_plot, x=x_col, y=y_col, markers=True, title=title)
                    fig.update_layout(xaxis_title=x_col)
                    st.plotly_chart(fig, use_container_width=True)
               else:
                    st.caption(f"No valid score data to plot {title}.")
          else:
               st.caption(f"Not enough data or missing '{y_col}' column for {title}.")

     with tab_day:
          st.markdown("#### Daily Scores")
          # Ensure 'Total Score' is numeric before aggregation
          df_filtered["Total Score"] = pd.to_numeric(df_filtered["Total Score"], errors="coerce")
          grouped_day = df_filtered.groupby("Day")["Total Score"].agg(["count", "mean"]).reset_index()
          grouped_day.columns = ["Date", "Total Audits", "Average Score"]
          grouped_day["Average Score"] = grouped_day["Average Score"].round(2) # Round for display
          st.dataframe(grouped_day.sort_values("Date", ascending=False), use_container_width=True)
          plot_time_trend(grouped_day, "Date", title="Daily Score Trend")

     with tab_week:
          st.markdown("#### Weekly Scores")
          df_filtered["Total Score"] = pd.to_numeric(df_filtered["Total Score"], errors="coerce")
          grouped_week = df_filtered.groupby("Week")["Total Score"].agg(["count", "mean"]).reset_index()
          grouped_week.columns = ["Week", "Total Audits", "Average Score"]
          grouped_week["Average Score"] = grouped_week["Average Score"].round(2)
          st.dataframe(grouped_week.sort_values("Week", ascending=False), use_container_width=True)
          plot_time_trend(grouped_week, "Week", title="Weekly Score Trend")

     with tab_month:
          st.markdown("#### Monthly Scores")
          df_filtered["Total Score"] = pd.to_numeric(df_filtered["Total Score"], errors="coerce")
          grouped_month = df_filtered.groupby("Month")["Total Score"].agg(["count", "mean"]).reset_index()
          grouped_month.columns = ["Month", "Total Audits", "Average Score"]
          grouped_month["Average Score"] = grouped_month["Average Score"].round(2)
          st.dataframe(grouped_month.sort_values("Month", ascending=False), use_container_width=True)
          plot_time_trend(grouped_month, "Month", title="Monthly Score Trend")

st.markdown("---") # Separator


# --- Row 4: Score Over Time (Individual Audits) ---
# This might become noisy with many audits, consider alternatives if needed
st.subheader("⏱️ Audit Score Trend")
# Ensure df_filtered has the necessary columns and sort
if "Audit Date" in df_filtered.columns and "Total Score" in df_filtered.columns:
     df_trend = df_filtered.dropna(subset=["Audit Date", "Total Score"]).sort_values("Audit Date")
     if not df_trend.empty:
          # Determine color based on number of unique agents after filtering
          color_dim = "Associate Name" if df_trend["Associate Name"].nunique() > 1 and df_trend["Associate Name"].nunique() < 30 else None # Limit colors

          fig_trend = px.line(
              df_trend, x="Audit Date", y="Total Score",
              color=color_dim,
              markers=True,
              title="Individual Audit Scores Over Time" + (f" (Colored by {color_dim})" if color_dim else "")
          )
          st.plotly_chart(fig_trend, use_container_width=True)
     else:
          st.info("No valid audit data points to plot score trend.")
else:
     st.info("Missing 'Audit Date' or 'Total Score' for score trend plot.")


st.markdown("---") # Separator


# --- Row 5: Raw Data ---
st.subheader("📋 Filtered Audit Data")
# Select and rename columns for display clarity if needed
# cols_to_display = ['Audit Date', 'Associate Name', 'Team Lead', 'Audit Type', 'Total Score', 'ZTP Violation', ...]
# st.dataframe(df_filtered[cols_to_display].sort_values("Audit Date", ascending=False), use_container_width=True)
# Or show all columns:
st.dataframe(df_filtered.sort_values("Audit Date", ascending=False), use_container_width=True)
