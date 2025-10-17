# main.py

import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import json
import os

# Function to connect to Google Sheets
@st.cache_resource
def get_gsheet_connection():
    # Load credentials from Streamlit secrets
    if 'google_credentials' in st.secrets:
        creds_dict = json.loads(st.secrets['google_credentials'])
    else:
        # For local testing, load from environment or file
        creds_dict = json.loads(os.environ.get('GOOGLE_CREDENTIALS', '{}'))
    
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# Load data from Google Sheet
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_data(sheet_name='Master Data'):
    client = get_gsheet_connection()
    sheet = client.open('JWP_Master').worksheet(sheet_name)
    data = sheet.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    # Convert types
    df['End date'] = pd.to_datetime(df['End date'], errors='coerce')
    df['Spending as of Oct 2025 (USD)'] = pd.to_numeric(df['Spending as of Oct 2025 (USD)'], errors='coerce')
    df['Last Updated'] = pd.to_datetime(df.get('Last Updated', pd.Series()), errors='coerce')
    return df, sheet

# Save edits to Google Sheet
def save_edits(edited_df, original_df, user_name, user_email, user_agency, sheet):
    now = datetime.datetime.now()
    updates = []
    for idx, row in edited_df.iterrows():
        orig_row = original_df.iloc[idx]
        if not row.equals(orig_row):
            # Update only editable columns
            sheet.update_cell(idx + 2, 5, row['End date'].strftime('%Y-%m-%d') if pd.notnull(row['End date']) else '')  # End date
            sheet.update_cell(idx + 2, 6, str(row['Spending as of Oct 2025 (USD)']) if pd.notnull(row['Spending as of Oct 2025 (USD)']) else '')  # Spending
            sheet.update_cell(idx + 2, 7, row['Progress as of Oct 2025'])  # Progress
            # Update last updated if column exists
            if 'Last Updated' in edited_df.columns:
                sheet.update_cell(idx + 2, edited_df.columns.get_loc('Last Updated') + 1, now.strftime('%Y-%m-%d %H:%M:%S'))
            updates.append((idx, now))
    
    # Log to audit sheet
    audit_sheet = get_gsheet_connection().open('JWP_Master').worksheet('Audit Log')
    for idx, timestamp in updates:
        audit_sheet.append_row([user_name, user_email, user_agency, idx, timestamp.strftime('%Y-%m-%d %H:%M:%S'), 'Row edited'])

# Load audit log
@st.cache_data(ttl=300)
def load_audit_log():
    client = get_gsheet_connection()
    try:
        audit_sheet = client.open('JWP_Master').worksheet('Audit Log')
        data = audit_sheet.get_all_values()
        df = pd.DataFrame(data[1:], columns=data[0])
    except:
        df = pd.DataFrame(columns=['Name', 'Email', 'Agency', 'Row Index', 'Timestamp', 'Action'])
    return df

# App configuration
st.set_page_config(page_title="JWP Editor", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #f0f2f6;
        color: #333;
    }
    h1, h2, h3 {
        color: #003366;  /* UN blue */
    }
    .stButton > button {
        background-color: #003366;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# Admin password from secrets
ADMIN_PASSWORD = st.secrets.get('admin_password', os.environ.get('ADMIN_PASSWORD', 'admin123'))

# Session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False

# Login form
if not st.session_state.logged_in:
    st.title("JWP Stakeholder Login")
    with st.form("login_form"):
        name = st.text_input("Name")
        email = st.text_input("Email")
        agency = st.selectbox("Agency Name", options=['FAO', 'ILO', 'IOM', 'UN Habitat', 'UN Women', 'UNDP', 'UNEP', 'UNESCO', 'UNFPA', 'UNHCR', 'UNICEF', 'UNOPS', 'WFP', 'WHO'])  # From CSV agencies
        submit = st.form_submit_button("Login")
        if submit and name and email and agency:
            st.session_state.logged_in = True
            st.session_state.user = {'name': name, 'email': email, 'agency': agency}
            st.rerun()

# Main app
if st.session_state.logged_in:
    user = st.session_state.user
    st.title(f"Welcome, {user['name']} ({user['agency']})")
    
    # Load data
    df, sheet = load_data()
    
    # Filter by agency
    agency_df = df[df['Agency'] == user['agency']].copy()
    if agency_df.empty:
        st.warning("No activities found for your agency.")
    else:
        st.info("You can edit only End Date, Spending, and Progress columns. The first 4 columns are locked. Only admins can download the full CSV.")
        
        # Make first 4 columns non-editable
        editable_cols = {'End date': st.column_config.DateColumn(), 
                         'Spending as of Oct 2025 (USD)': st.column_config.NumberColumn(), 
                         'Progress as of Oct 2025': st.column_config.TextColumn()}
        if 'Last Updated' in agency_df.columns:
            editable_cols['Last Updated'] = st.column_config.DatetimeColumn(disabled=True)
        
        edited_df = st.data_editor(
            agency_df,
            column_config={
                'Outcome': st.column_config.TextColumn(disabled=True),
                'Sub-Output': st.column_config.TextColumn(disabled=True),
                'Agency': st.column_config.TextColumn(disabled=True),
                'Activity': st.column_config.TextColumn(disabled=True),
                **editable_cols
            },
            hide_index=False,
            use_container_width=True
        )
        
        if st.button("Save Updates"):
            save_edits(edited_df, agency_df, user['name'], user['email'], user['agency'], sheet)
            st.success("Updates saved successfully!")
            st.cache_data.clear()  # Clear cache to refresh data

# Admin section
st.sidebar.title("Admin Access")
admin_pass = st.sidebar.text_input("Admin Password", type="password")
if admin_pass == ADMIN_PASSWORD:
    st.session_state.is_admin = True
if st.session_state.is_admin:
    st.sidebar.success("Admin logged in.")
    with st.expander("Admin Dashboard"):
        st.subheader("Full Dataset")
        full_df, _ = load_data()
        st.dataframe(full_df)
        
        csv = full_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Full CSV", csv, "jwp_full_updated.csv", "text/csv")
        
        st.subheader("Audit Log")
        audit_df = load_audit_log()
        st.dataframe(audit_df)

# Optional: Switch to SQLite (comment out Google Sheets code and use this)
# import sqlite3
# def init_db():
#     conn = sqlite3.connect('jwp.db')
#     # Create tables: master_data and audit_log
#     conn.execute('''CREATE TABLE IF NOT EXISTS master_data (...)''')  # Define schema
#     conn.execute('''CREATE TABLE IF NOT EXISTS audit_log (...)''')
#     return conn
# # Then load/save using SQL queries
# # Tradeoffs: Google Sheets is collaborative/cloud-based; SQLite is local/simple but needs hosting for multi-user.