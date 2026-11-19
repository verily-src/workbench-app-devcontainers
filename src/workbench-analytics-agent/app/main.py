"""Workbench Analytics Agent: question page.

A single page with a question box and an Ask button. Answering is not
connected yet, so the page only confirms what was asked.
"""

from datetime import datetime, timezone

import streamlit as st

st.set_page_config(page_title="Workbench Analytics Agent")


@st.cache_resource
def app_started_at() -> datetime:
    """Time this server process started. It changes only when the app restarts."""
    return datetime.now(timezone.utc)


st.title("Workbench Analytics Agent")
st.write("Ask a question about your data in plain language.")

with st.form("question_form"):
    question = st.text_input(
        "Your question",
        placeholder="For example: How many users were active last month?",
    )
    asked = st.form_submit_button("Ask")

if asked:
    question = question.strip()
    if question:
        st.success("Question received.")
        st.text(question)
        st.info("Answering is not connected yet, so there is no result to show.")
    else:
        st.warning("Type a question, then select Ask.")

st.caption(f"App started {app_started_at():%Y-%m-%d %H:%M:%S} UTC")
