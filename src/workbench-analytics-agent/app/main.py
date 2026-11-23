"""Workbench Analytics Agent: chat page.

The user asks a question and it appears in a conversation thread. Answering
is not connected yet, so every reply says so.
"""

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

APP_NAME = "Workbench Analytics Agent"

NOT_CONNECTED_REPLY = (
    "I have your question, but I can't answer it yet. "
    "This app isn't connected to data or a model."
)

EXAMPLE_QUESTIONS = [
    "How many active users last month?",
    "Which week had most sign-ups?",
    "Is activity up this quarter?",
]

BRAND_HTML = f"""
<div class="wb-brand">
  <span class="wb-mark" aria-hidden="true"></span>
  <span>{APP_NAME}</span>
</div>
"""

st.set_page_config(page_title=APP_NAME, layout="centered")
st.html(Path(__file__).with_name("style.css"))


@st.cache_resource
def app_started_at() -> datetime:
    """Time this server process started. It changes only when the app restarts."""
    return datetime.now(timezone.utc)


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
    if messages:
        st.button("New chat", on_click=start_new_chat, key="new_chat")

if not messages:
    # Landing view: greeting, question box and a few example questions.
    with st.container(key="hero"):
        st.title("What would you like to *know?*", anchor=False)
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
    st.caption(f"App started {app_started_at():%Y-%m-%d %H:%M:%S} UTC")
