import streamlit as st
import pandas as pd
from fuzzywuzzy import fuzz
from datetime import datetime
import streamlit.components.v1 as components

# 📄 Load allowed users
@st.cache_data
def load_allowed_users():
    return pd.read_csv("allowed_users.csv")

allowed_users_df = load_allowed_users()
user_credentials = dict(zip(allowed_users_df["email"], allowed_users_df["password"]))

# 🔐 Session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = ""
if 'selected_question' not in st.session_state:
    st.session_state.selected_question = ""

# 🔐 Login
if not st.session_state.authenticated:
    st.title("🔐 Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if email in user_credentials and user_credentials[email] == password:
            st.session_state.authenticated = True
            st.session_state.user_email = email
            st.success("Login successful ✅")
            st.rerun()
        else:
            st.error("Invalid email or password ❌")
    st.stop()

# ✅ Load Q&A data
@st.cache_data
def load_qa_data():
    df = pd.read_csv("data.csv", encoding="cp1252")
    df.replace({
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-"
    }, regex=True, inplace=True)
    return df

df = load_qa_data()

# 🧠 Q&A Interface
st.title("🪐 GuruCool Chatbot")
user_input = st.text_input("Ask a question:")

if user_input and not st.session_state.selected_question:
    matches = []
    for _, row in df.iterrows():
        score = fuzz.partial_ratio(user_input.lower(), str(row["Question"]).lower())
        matches.append((row["Question"], score))

    top_matches = sorted(matches, key=lambda x: x[1], reverse=True)[:5]

    if top_matches and top_matches[0][1] > 50:
        st.info("Did you mean one of these?")
        selected = st.radio("Select the closest match:", [q for q, _ in top_matches], key="question_selector")
        if st.button("Show Answer"):
            st.session_state.selected_question = selected
            st.session_state.user_question = user_input
            st.rerun()
    else:
        st.warning("❌ Sorry, I couldn’t find a good match. Try rephrasing your question.")

# ✅ Show selected answer and details
elif st.session_state.selected_question:
    if st.button("🔄 New Question"):
        st.session_state.selected_question = ""
        st.session_state.user_question = ""
        st.rerun()

    matched_q = st.session_state.selected_question
    matched_row = df[df["Question"] == matched_q].iloc[0]
    faq_id = matched_row.get('FAQID', '')

    # 🔢 Unified layout (stacked)
    st.success(f"**{faq_id} - Matched Question:** {matched_q}")
    st.markdown(f"**Answer:** {matched_row.get('Answer', '')}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 💬 Chat Script")
        st.markdown(matched_row.get('Chat Scripts', ''))
    with col2:
        st.markdown("### 📧 Email Script")
        st.markdown(matched_row.get('Email Scripts', ''))
    with col3:
        st.markdown("### 📞 Voice Script")
        st.markdown(matched_row.get('Voice Scripts', ''))

    # 📄 Gurucool Article Section
    link = str(matched_row.get("Gurucool Link", "")).strip()
    if link.lower() != "gurucool link" and link:
        st.markdown("---")
        st.markdown("### 🧠 Related Gurucool Article")
        st.markdown(f"[🔗 View Gurucool SOP]({link})")

    # 📌 PCIR Info
    pcir = str(matched_row.get('PCIR', '')).strip()
    if pcir:
        st.markdown(
            f"""
            <div style='
                background-color: #2F4F4F;
                padding: 10px;
                margin-top: 10px;
                border-left: 5px solid #4CAF50;
                border-radius: 4px;
                font-size: 15px;
            '>
                <strong>📌 PCIR:</strong> {pcir}
            </div>
            """, unsafe_allow_html=True
        )

    # 🛠️ Freshdesk Properties
    freshdesk_props = str(matched_row.get('Freshdesk Properties', '')).strip()
    if freshdesk_props:
        st.markdown(
            f"""
            <div style='
                background-color: #00008B;
                padding: 10px;
                margin-top: 10px;
                border-left: 5px solid #2196F3;
                border-radius: 4px;
                font-size: 15px;
            '>
                <strong>🛠️ Freshdesk Properties:</strong> {freshdesk_props}
            </div>
            """, unsafe_allow_html=True
        )

    # 📅 Log
    log_entry = {
        "Email": st.session_state.user_email,
        "Typed Question": st.session_state.user_question,
        "FAQID": faq_id,
        "Matched Question": matched_q,
        "Answer": matched_row.get('Answer', ''),
        "Chat Script": matched_row.get('Chat Scripts', ''),
        "Email Script": matched_row.get('Email Scripts', ''),
        "Voice Script": matched_row.get('Voice Scripts', ''),
        "Gurucool Link": matched_row.get('Gurucool Link', ''),
        "PCIR": matched_row.get('PCIR', ''),
        "Freshdesk Properties": matched_row.get('Freshdesk Properties', ''),
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    pd.DataFrame([log_entry]).to_csv("chat_logs.csv", mode='a', header=not pd.io.common.file_exists("chat_logs.csv"), index=False)
