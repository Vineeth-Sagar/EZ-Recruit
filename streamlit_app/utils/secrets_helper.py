"""
secrets_helper.py
Safe access to st.secrets.

Bare `st.secrets.get(...)` throws FileNotFoundError the moment no
secrets.toml exists at all anywhere Streamlit looks for one — not just
when a specific key is missing — and it renders an st.error() banner as a
side effect of parsing, before the exception even reaches caller code. On
Streamlit Cloud that's a non-issue (secrets are always configured there),
but it means `streamlit run streamlit_app/app.py` crashes (and, even if
you catch the exception yourself, still paints an error banner) for
anyone running it locally without first creating a secrets.toml.

st.secrets.load_if_toml_exists() is Streamlit's own public API for this
exact case — it suppresses that banner and returns False instead of
raising when no file exists at all. get_secret() uses it so local dev
without secrets stays quiet.
"""
import streamlit as st


def get_secret(key: str, default: str = "") -> str:
    if not st.secrets.load_if_toml_exists():
        return default
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default
