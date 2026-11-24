"""Verily Product Analytics Agent: chat page.

The user asks a question and it appears in a conversation thread. Answering
is not connected yet, so every reply says so. A "Data connection" dialog shows
which identity the app queries as and checks that it can read a dataset.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

import data

APP_NAME = "Verily Product Analytics Agent"
# Shown beside the Verily icon, which already stands for the word "Verily".
APP_NAME_BESIDE_ICON = APP_NAME.removeprefix("Verily ")

NOT_CONNECTED_REPLY = (
    "I have your question, but I can't answer it yet. "
    "Questions aren't linked to the data or a model yet."
)

# Optional starting value for the dataset box. The dataset is never written in
# this repository; each person enters the one their workspace gives them.
DEFAULT_DATASET = os.environ.get("ASK_WORKBENCH_DATASET", "")

EXAMPLE_QUESTIONS = [
    "How many active users last month?",
    "Busiest week for sign-ups?",
    "Is activity up this quarter?",
]

BRAND_HTML = f"""
<div class="wb-brand">
  <span class="wb-verily-icon" role="img" aria-label="Verily"></span>
  <span class="wb-app-name">{APP_NAME_BESIDE_ICON}</span>
</div>
"""

st.set_page_config(page_title=APP_NAME, layout="centered")
st.html(Path(__file__).with_name("style.css"))


@st.cache_resource
def app_started_at() -> datetime:
    """Time this server process started. It changes only when the app restarts."""
    return datetime.now(timezone.utc)


def version_note() -> str:
    """What launcher.py reported about the copy of the app that is running."""
    version = os.environ.get("ASK_WORKBENCH_VERSION", "")
    problem = os.environ.get("ASK_WORKBENCH_UPDATE_PROBLEM", "")
    if version and problem:
        return f" · version {version} (not updated: {problem})"
    if version:
        return f" · version {version}"
    if problem:
        return f" · built-in version ({problem})"
    return ""


def can_update() -> bool:
    """True when launcher.py started this app and has somewhere to update from."""
    started_by_launcher = (
        "ASK_WORKBENCH_VERSION" in os.environ
        or "ASK_WORKBENCH_UPDATE_PROBLEM" in os.environ
    )
    return started_by_launcher and bool(os.environ.get("ASK_WORKBENCH_REF", "").strip())


def relaunch_with_latest_code() -> None:
    """Replace this server with a fresh run of launcher.py.

    launcher.py downloads the newest code and starts the app again, in the
    same container. The browser reconnects by itself once the app is back.
    """
    launcher = Path(__file__).with_name("launcher.py")
    extra_args = json.loads(os.environ.get("ASK_WORKBENCH_EXTRA_ARGS", "[]"))
    os.execv(sys.executable, [sys.executable, str(launcher), *extra_args])


@st.cache_resource(show_spinner=False)
def data_connection():
    """One BigQuery client for the app. A failure is raised, not remembered."""
    return data.connect()


@st.dialog("Data connection")
def data_connection_dialog() -> None:
    """Show who the app queries as, and check that it can read a dataset."""
    try:
        client, info = data_connection()
    except data.DataError as error:
        st.error(str(error))
        return

    st.text(f"Queries run as: {info.identity}")
    st.text(f"Billed to project: {info.project}")

    dataset = st.text_input(
        "Dataset",
        value=st.session_state.get("dataset", DEFAULT_DATASET),
        placeholder="project.dataset",
        help="The dataset to read, as listed in your workspace's resources.",
        key="dataset_input",
    ).strip()

    if st.button("Check connection", type="primary", key="check_connection"):
        st.session_state.pop("tables", None)
        if not dataset:
            st.info(
                "Enter a dataset first, written as project.dataset. Once the "
                "data has been added to your workspace, its path is listed in "
                "the workspace's resources."
            )
        else:
            try:
                with st.spinner("Checking"):
                    st.session_state.tables = data.list_tables(client, dataset)
                st.session_state.dataset = dataset
            except data.DataError as error:
                st.error(str(error))

    tables = st.session_state.get("tables")
    if tables is None or st.session_state.get("dataset") != dataset:
        return

    if not tables:
        st.warning("Connected, but the dataset has no tables or views.")
        return
    st.success(f"Connected. Found {len(tables)} tables and views.")
    st.dataframe(tables, hide_index=True, height=210)

    table = st.selectbox(
        "Count the rows in", [row["name"] for row in tables], key="count_table"
    )
    if st.button("Count rows", key="count_rows"):
        try:
            with st.spinner("Counting"):
                result = data.count_rows(client, dataset, table)
        except data.DataError as error:
            st.error(str(error))
        else:
            st.metric(f"Rows in {table}", f"{result.rows[0]['row_count']:,}")
            st.caption(f"Query read {result.bytes_processed:,} bytes.")
            st.code(result.sql, language="sql")


def ask(question: str) -> None:
    """Add the question and the placeholder reply to the conversation."""
    question = question.strip()
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.messages.append(
        {"role": "assistant", "content": NOT_CONNECTED_REPLY}
    )


def start_new_chat() -> None:
    st.session_state.messages = []


if "messages" not in st.session_state:
    st.session_state.messages = []

messages = st.session_state.messages

with st.container(horizontal=True, vertical_alignment="center", key="topbar"):
    st.html(BRAND_HTML)
    if st.button("Data connection", key="open_data"):
        data_connection_dialog()
    if messages:
        st.button("New chat", on_click=start_new_chat, key="new_chat")

if not messages:
    # Landing view: greeting, question box and a few example questions.
    with st.container(key="hero"):
        st.html('<p class="wb-eyebrow">Self-serve analytics</p>')
        st.title("What would you like to *know*?", anchor=False)
        st.markdown("Ask about your data in plain language.")
        question = st.chat_input("Ask a question", key="hero_input")
        with st.container(
            horizontal=True, horizontal_alignment="center", key="examples"
        ):
            picked = [
                example
                for index, example in enumerate(EXAMPLE_QUESTIONS)
                if st.button(example, key=f"example_{index}")
            ]
    asked = question or (picked[0] if picked else None)
    if asked:
        ask(asked)
        st.rerun()
else:
    # Conversation view: the thread, with the question box pinned below it.
    for message in messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.text(message["content"])
            else:
                st.markdown(message["content"])
    question = st.chat_input("Ask another question", key="thread_input")
    if question:
        ask(question)
        st.rerun()

with st.container(key="footnote"):
    st.caption(
        f"App started {app_started_at():%Y-%m-%d %H:%M:%S} UTC{version_note()}"
    )
    if can_update():
        if st.session_state.get("updating"):
            st.caption("Updating. This page reconnects in a few seconds.")
            time.sleep(1)  # let the line above reach the browser first
            try:
                relaunch_with_latest_code()
            except OSError as error:
                st.session_state.updating = False
                st.error(f"The update could not start: {error}")
        elif st.button("Update to the latest version", type="tertiary", key="update_app"):
            st.session_state.updating = True
            st.rerun()
