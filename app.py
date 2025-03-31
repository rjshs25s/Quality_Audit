import streamlit as st
import datetime
import urllib.parse
import json
import uuid
import pandas as pd
from google.cloud import storage
from google.oauth2 import service_account
import matplotlib.pyplot as plt 

# Configuration
CREDS_FILE = "vertical-album-455112-i0-9288d1231fb9.json"
BUCKET_NAME = "jupiter-quality-audit"
EMP_CSV = "employee_data.csv"
ACCESS_CSV = "access_control.csv"

# Load data with caching
@st.cache_data(ttl=3600)
def load_data():
    emp_df = pd.read_csv(EMP_CSV)
    access_df = pd.read_csv(ACCESS_CSV)
    return emp_df, access_df

@st.cache_data(ttl=3600)
def load_all_audits(bucket_name, creds_path):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    client = storage.Client(credentials=creds)
    bucket = client.bucket(bucket_name)
    data = []
    for blob in bucket.list_blobs():
        if blob.name.endswith(".json"):
            try:
                content = blob.download_as_text()
                record = json.loads(content)
                data.append(record)
            except:
                continue
    return pd.DataFrame(data)

# Initialize session states
def init_session_state():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'email_sent' not in st.session_state:
        st.session_state.email_sent = False
    if 'entity_check' not in st.session_state:
        st.session_state.entity_check = None
    if 'associate_info' not in st.session_state:
        st.session_state.associate_info = {
            "email": "",
            "name": "",
            "tl_name": "",
            "team_leader_email": "",
            "department": "",
            "lob": ""
        }
    if 'auditor_name' not in st.session_state:
        st.session_state.auditor_name = ""
    if 'form_submitted' not in st.session_state:
        st.session_state.form_submitted = False

init_session_state()

# Load data
try:
    emp_df, access_df = load_data()
except Exception as e:
    st.error(f"Failed to load data files: {e}")
    st.stop()

# Upload to Google Cloud Storage
def upload_to_gcs(bucket_name, destination_blob_name, content, creds_path):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    client = storage.Client(credentials=creds)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(content)

# Show sidebar stats only when needed
def show_sidebar_stats():
    if st.session_state.associate_info["email"]:
        try:
            with st.sidebar:
                all_audits = load_all_audits(BUCKET_NAME, CREDS_FILE)
                df = all_audits.copy()
                df['Audit Date'] = pd.to_datetime(df['Audit Date'], errors='coerce')
                df['Total Score'] = pd.to_numeric(df['Total Score'], errors='coerce')

                user_df = df[df['Associate Email ID'].str.lower() == st.session_state.associate_info["email"].lower()]

                st.markdown("### 📊 Audit Stats")
                if not user_df.empty:
                    current_month = datetime.datetime.today().replace(day=1)
                    this_month_df = user_df[user_df['Audit Date'] >= current_month]

                    st.markdown(f"**This Month Audits:** {len(this_month_df)}")
                    if not this_month_df.empty:
                        avg_score = this_month_df['Total Score'].mean()
                        st.markdown(f"**Average Score:** {avg_score:.2f}%")

                        by_type = this_month_df.groupby('Audit Type')['Total Score'].mean().reset_index()
                        st.markdown("**Audit Type-wise Avg Scores:**")
                        for _, row in by_type.iterrows():
                            st.markdown(f"- {row['Audit Type']}: {row['Total Score']:.2f}%")

                        trend = this_month_df.groupby('Audit Date')['Total Score'].mean().reset_index()
                        fig, ax = plt.subplots()
                        ax.plot(trend['Audit Date'], trend['Total Score'], marker='o')
                        ax.set_title("📈 Daily Avg Score")
                        ax.set_xlabel("Date")
                        ax.set_ylabel("Score (%)")
                        ax.grid(True)
                        st.pyplot(fig)

                    st.markdown("---")
                    st.markdown("### 🕒 Lifetime Stats")
                    st.markdown(f"**Total Audits:** {len(user_df)}")
                    st.markdown(f"**Overall Avg Score:** {user_df['Total Score'].mean():.2f}%")

                    recent = user_df.sort_values(by='Audit Date', ascending=False).head(5)[['Audit Date', 'Audit Type', 'Total Score']]
                    st.markdown("**Last 5 Audits:**")
                    st.dataframe(recent.reset_index(drop=True), use_container_width=True)
                else:
                    st.markdown("No audits found for this associate.")
        except Exception as e:
            st.sidebar.error(f"Error loading audit data: {e}")

# Login Section
def login_section():
    st.title("🔐 Quality Audit Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        try:
            match = access_df[
                (access_df['User_Name'].str.strip().str.lower() == username.strip().lower()) & 
                (access_df['Password'] == password)
            ]
            if not match.empty:
                st.session_state.logged_in = True
                st.session_state.auditor_name = username
                st.rerun()
            else:
                st.error("Invalid credentials. Please try again.")
        except Exception as e:
            st.error(f"Login error: {e}")
    st.stop()

# Fetch associate info with caching
@st.cache_data(ttl=3600)
def fetch_associate_info(email, _emp_df):
    """Fetch associate details from employee data"""
    try:
        email = str(email).strip().lower()
        emp_df_clean = _emp_df.copy()
        emp_df_clean['Work Email'] = emp_df_clean['Work Email'].astype(str).str.strip().str.lower()
        emp_df_clean['Full Name'] = emp_df_clean['Full Name'].astype(str).str.strip()
        emp_df_clean['Reporting To'] = emp_df_clean['Reporting To'].astype(str).str.strip()

        match = emp_df_clean[emp_df_clean['Work Email'] == email]
        if not match.empty:
            info = match.iloc[0]
            lead_name = info['Reporting To']
            dept = info.get('Department', '')
            lob = info.get('LOB', '')
            lead_match = emp_df_clean[emp_df_clean['Full Name'] == lead_name]
            lead_email = lead_match['Work Email'].values[0] if not lead_match.empty else ""
            return info['Full Name'], lead_name, lead_email, dept, lob
    except Exception as e:
        st.error(f"Error fetching associate info: {e}")
    return "", "", "", "", ""

# Main form section
def main_form():
    st.title("📄 Quality Audit Form - Inbound")

    # Agent & Call Details
    st.header("Agent & Call Details")
    associate_email_input = st.text_input("Associate Email ID", key="associate_email")

    if associate_email_input and st.button("Lookup Details", key="lookup_details"):
        associate_name, tl_name, team_leader_email, department, lob = fetch_associate_info(associate_email_input, emp_df)
        st.session_state.associate_info = {
            "email": associate_email_input,
            "name": associate_name,
            "tl_name": tl_name,
            "team_leader_email": team_leader_email,
            "department": department,
            "lob": lob
        }
        st.rerun()

    # Form Layout
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        queue = st.selectbox("Queue", ["Inbound", "Outbound"], key="queue")
        call_date = st.date_input("Call Date", key="call_date")
        calling_number = st.text_input("Calling Number", key="calling_number")
    with col2:
        st.text_input("Associate Name", value=st.session_state.associate_info["name"], disabled=True, key="associate_name_display")
        st.text_input("Team Lead", value=st.session_state.associate_info["tl_name"], disabled=True, key="team_lead_display")
        st.text_input("Auditor Name", value=st.session_state.auditor_name, disabled=True, key="auditor_name_display")
    with col3:
        st.text_input("Team Leader Email", value=st.session_state.associate_info["team_leader_email"], disabled=True, key="team_leader_email_display")
        st.text_input("LOB", value=st.session_state.associate_info["lob"], disabled=True, key="lob_display")
        st.text_input("Department", value=st.session_state.associate_info["department"], disabled=True, key="department_display")
    with col4:
        call_duration = st.text_input("Call Duration", key="call_duration")
        hold_duration = st.text_input("Hold Duration", key="hold_duration")
        call_link = st.text_input("Call Link", key="call_link")
    with col5:
        audit_type = st.selectbox("Audit Type", ["Regular Audit", "OJT-Feedback1", "OJT-Feedback2", "Certification1"], key="audit_type")
        
        def is_duplicate_entity(entity_id, bucket_name, creds_path):
            creds = service_account.Credentials.from_service_account_file(creds_path)
            client = storage.Client(credentials=creds)
            bucket = client.bucket(bucket_name)

            for blob in bucket.list_blobs():
                if blob.name.endswith(".json"):
                    content = blob.download_as_text()
                    try:
                        data = json.loads(content)
                        if str(data.get("Entity ID", "")).strip().lower() == entity_id.strip().lower():
                            return True
                    except:
                        continue
            return False

        entity_id = st.text_input("Entity ID", key="entity_id")

        if st.button("Check Entity ID", key="check_entity"):
            if not entity_id.strip():
                st.warning("Please enter an Entity ID before checking.")
            elif is_duplicate_entity(entity_id, BUCKET_NAME, CREDS_FILE):
                st.session_state.entity_check = False
                st.error("🚫 Duplicate Entity ID detected. Please use a unique one.")
            else:
                st.session_state.entity_check = True
                st.success("✅ Entity ID is unique. You may proceed.")

    st.text_input("Audit Date", value=str(datetime.date.today()), disabled=True, key="audit_date_display")
    ztp_flag = st.selectbox("Any ZTP Violation?", ["No", "Yes"], key="ztp_flag")
    observations = st.text_area("Overall Observations", key="observations")
    issue_voc = st.text_area("Issue (VOC)", key="issue_voc")
    resolution = st.text_area("Resolution", key="resolution")

    # Parameters Configuration
    parameters = {
        "Opening and Closing": ["Script & Guidelines adherence", "Further Assistance", "Survey pitch", "Compliant"],
        "Communication and Language": ["Grammar and sentence construction", "Tonality, Fluency and Rate of Speech, Timely response", 
                                    "Appropriate Language & Word Choice", "Active listening/Reading", 
                                    "Interruption/Parallel Talk/Thread Hijacking/Spamming", "False assurance", "Compliant"],
        "Empathy and Professionalism": ["Empathy/Apology/Assurance", "Acknowledgement/Paraphrasing", "Service No", "Compliant"],
        "Correct and Complete Resolution": ["Complete information/resolution", "Correct and accurate information/resolution", 
                                        "Probing and Confirmation", "Compliant"],
        "Proactive Assistance": ["Proactive information", "Self help options", "Alternatives solution", "Compliant"],
        "Hold and Dead air": ["Hold script, Hold threshold, Unnecessary Hold", "Dead air/Multiple mute instances", "Compliant"],
        "Right action taken": ["Incorrect bucket utilization/movement", "Forceful Supervisor transfer", "Supervisor transfer not done",
                            "Ticket not actioned / wrongly actioned", "Escalation not raised when required", "Inaccurate Escalation",
                            "Incorrect /Inappropriate Transfers", "Promised action not taken", "Compliant"],
        "Properties": ["Notes", "FD Properties", "Compliant"]
    }

    parameter_scores = {
        "Opening and Closing": 10, 
        "Communication and Language": 20, 
        "Empathy and Professionalism": 20,
        "Correct and Complete Resolution": 10, 
        "Proactive Assistance": 15, 
        "Hold and Dead air": 10,
        "Right action taken": 0, 
        "Properties": 15
    }

    # Scoring Section
    st.header("Audit Parameters")
    total_score, fatal_error, results = 0, False, []
    for param, sub_params in parameters.items():
        cols = st.columns([2, 3, 1])
        cols[0].write(param)
        selected = cols[1].multiselect("", sub_params, default=["Compliant"], key=f"{param}_reasons")
        score = parameter_scores[param] if "Compliant" in selected else 0
        if param in ["Correct and Complete Resolution", "Right action taken"] and "Compliant" not in selected and selected:
            fatal_error = True
        cols[2].write(f"{score}%")
        total_score += score
        results.append({"Parameter": param, "Selected Reasons": ", ".join(selected), "Score": score})

    final_score_display = 0 if ztp_flag == "Yes" or fatal_error else total_score
    st.metric("Overall Score", "ZTP" if ztp_flag == "Yes" else ("Fatal" if fatal_error else f"{final_score_display}%"))

    # Action Buttons
    col_email, col_submit = st.columns(2)

    with col_email:
        if st.button("Send Email", key="send_email"):
            if not st.session_state.associate_info["email"]:
                st.error("Please lookup associate details first")
            else:
                plain_body = f"""Audit Summary - {audit_type}

Agent & Call Details:
Queue: {queue}
Call Date: {call_date}
Calling Number: {calling_number}
Audit Date: {datetime.date.today()}
Associate Name: {st.session_state.associate_info["name"]}
Associate Email: {st.session_state.associate_info["email"]}
Team Lead: {st.session_state.associate_info["tl_name"]}
Team Leader Email: {st.session_state.associate_info["team_leader_email"]}
Auditor Name: {st.session_state.auditor_name}
Call Duration: {call_duration}
Hold Duration: {hold_duration}
Call Link: {call_link}
Audit Type: {audit_type}
Entity ID: {entity_id}
LOB: {st.session_state.associate_info["lob"]}
Department: {st.session_state.associate_info["department"]}
ZTP Violation: {ztp_flag}

Overall Score: {final_score_display}%

Parameters:"""

                for r in results:
                    plain_body += f"\n- {r['Parameter']}: {r['Selected Reasons']} ({r['Score']}%)"

                plain_body += f"""

Overall Observations:
{observations or 'None'}

Issue (VOC):
{issue_voc or 'None'}

Resolution:
{resolution or 'None'}"""

                mail_url = f"https://mail.google.com/mail/?view=cm&fs=1&tf=1&to={st.session_state.associate_info['email']}&cc={st.session_state.associate_info['team_leader_email']}&su=Audit%20Feedback%20-%20{audit_type.replace(' ', '%20')}&body={urllib.parse.quote(plain_body)}"
                st.markdown(f"[📧 Click here to send email via Gmail]({mail_url})", unsafe_allow_html=True)
                st.session_state.email_sent = True

    with col_submit:
        if st.button("Submit Audit", key="submit_audit"):
            if not st.session_state.email_sent:
                st.error("📧 Please send the email first before submitting.")
            elif st.session_state.get("entity_check") is False:
                st.error("🚫 Duplicate Entity ID detected. Please use a unique one.")
            elif st.session_state.get("entity_check") is None:
                st.warning("🔔 Please check if the Entity ID already exists using the 'Check Entity ID' button.")
            else:
                audit_entry = {
                    "Queue": queue,
                    "Call Date": str(call_date),
                    "Calling Number": calling_number,
                    "Entity ID": entity_id,
                    "Audit Date": str(datetime.date.today()),
                    "Associate Email ID": st.session_state.associate_info["email"],
                    "Team Leader Email": st.session_state.associate_info["team_leader_email"],
                    "Audit Type": audit_type,
                    "Associate Name": st.session_state.associate_info["name"],
                    "Team Lead": st.session_state.associate_info["tl_name"],
                    "LOB": st.session_state.associate_info["lob"],
                    "Department": st.session_state.associate_info["department"],
                    "Auditor Name": st.session_state.auditor_name,
                    "Call Duration": call_duration,
                    "Hold Duration": hold_duration,
                    "Call Link": call_link,
                    "ZTP Violation": ztp_flag,
                    "Total Score": final_score_display,
                    "Issue VOC": issue_voc,
                    "Resolution": resolution,
                    "Parameters": results,
                    "Email Sent": "Yes",
                    "Email Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                json_data = json.dumps(audit_entry, indent=2)
                blob_name = f"audit_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.json"

                try:
                    upload_to_gcs(BUCKET_NAME, blob_name, json_data, CREDS_FILE)
                    st.success("✅ Audit submitted and uploaded to GCS successfully!")
                    st.session_state.form_submitted = True
                    st.session_state.email_sent = False
                    st.session_state.entity_check = None
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to upload audit: {e}")

# Main app flow
if not st.session_state.logged_in:
    login_section()
else:
    show_sidebar_stats()
    if not st.session_state.form_submitted:
        main_form()
    else:
        st.success("Form submitted successfully! Would you like to submit another?")
        if st.button("Submit Another Audit"):
            st.session_state.form_submitted = False
            st.session_state.associate_info = {
                "email": "",
                "name": "",
                "tl_name": "",
                "team_leader_email": "",
                "department": "",
                "lob": ""
            }
            st.session_state.email_sent = False
            st.session_state.entity_check = None
            st.rerun()
