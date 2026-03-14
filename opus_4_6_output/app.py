import os
import re
import json
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import streamlit as st  # noqa: E402
from openai import OpenAI  # noqa: E402

from df_schema import make_schema_from_df, preprocess_df  # noqa: E402

# ---------------------------------------------------------------------------
# Persistent API-key storage
# ---------------------------------------------------------------------------
_KEY_FILE = Path.home() / ".talk2excel" / "config.json"


def _load_stored_key() -> str:
    try:
        data = json.loads(_KEY_FILE.read_text())
        return data.get("openai_api_key", "")
    except Exception:
        return ""


def _save_key(key: str) -> None:
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(json.dumps({"openai_api_key": key}))


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def get_llm_response(api_key: str, model: str, prompt: str) -> str:
    client = OpenAI(api_key=api_key)
    response = client.responses.create(model=model, input=prompt)
    return response.output_text


def generate_script(
    query: str, data_schema: str, row_count: int, api_key: str, model: str
) -> str:
    prompt = f"""You are a data analyst. You write Python code to answer questions about a pandas DataFrame.

Return ONLY code wrapped in <execute_python> tags. No explanation.

<execute_python>
# your code here
</execute_python>

DataFrame 'df' has {row_count} rows and these columns:
{data_schema}

IMPORTANT context:
- Each row is one order record/line item. len(df) == {row_count}.
- When asked about "number of orders" or "all orders", count rows with len(df).

User question: {query}

Code requirements:
- df is already loaded. Do NOT load data.
- Store the final answer in a variable called `result` as an HTML string.
- For charts: use matplotlib, save to a BytesIO buffer, base64-encode it, and embed as <img src="data:image/png;base64,..."> in the result HTML. Always call plt.close() after saving.
- For tables: use HTML <table> tags.
- Format currency with $ and commas where appropriate.
- Use case-insensitive string matching for filters.
- Do NOT use f-strings. Use str.format() or string concatenation instead.
- Do NOT use curly braces inside strings except for .format() placeholders.
"""
    return get_llm_response(api_key, model, prompt)


def execute_script(script: str, df: pd.DataFrame) -> str:
    match = re.search(r"<execute_python>([\s\S]*?)</execute_python>", script)
    if not match:
        return "<p>Could not extract executable code from LLM response.</p>"
    code = match.group(1).strip()
    # Strip markdown fences if present
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code).strip()
    exec_globals: dict = {"df": df}
    exec(code, exec_globals)  # noqa: S102
    return exec_globals.get("result", "<p>No result produced.</p>")


# ---------------------------------------------------------------------------
# Streamlit page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Talk2Excel", layout="wide")

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "df" not in st.session_state:
    st.session_state.df = None
if "df_raw" not in st.session_state:
    st.session_state.df_raw = None
if "schema_text" not in st.session_state:
    st.session_state.schema_text = ""

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    stored_key = _load_stored_key()
    api_key = st.text_input(
        "OpenAI API Key",
        value=stored_key,
        type="password",
        help="Your key is never shown in the UI or logs.",
    )

    model = st.selectbox(
        "Model",
        ["gpt-5.4", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"],
        index=0,
    )

    store_key = st.checkbox("Store API key on device", value=bool(stored_key))
    if store_key and api_key:
        _save_key(api_key)

    show_raw = st.toggle("Show raw LLM output", value=False)

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

# ---------------------------------------------------------------------------
# Use env var as fallback
# ---------------------------------------------------------------------------
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Main workspace
# ---------------------------------------------------------------------------
st.title("Talk2Excel")

# --- File upload ---
uploaded_file = st.file_uploader(
    "Upload an Excel file",
    type=["xls", "xlsx"],
    key="excel_upload",
)

if uploaded_file is not None:
    try:
        raw = pd.read_excel(uploaded_file)
        st.session_state.df_raw = raw
        st.session_state.schema_text = make_schema_from_df(raw)
        st.session_state.df = preprocess_df(raw)
    except Exception as exc:
        st.error("Failed to load file: {}".format(exc))

# --- Schema display ---
if st.session_state.schema_text:
    with st.expander("Data Schema", expanded=True):
        st.text(st.session_state.schema_text)

# --- Chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.html(msg["content"])
            if show_raw and msg.get("raw"):
                with st.expander("Raw LLM output"):
                    st.code(msg["raw"], language="python")
        else:
            st.markdown(msg["content"])

# --- Chat input ---
if prompt := st.chat_input("Ask a question about your data"):
    if not api_key:
        st.error("Please enter your OpenAI API key in the sidebar.")
    elif st.session_state.df is None:
        st.error("Please upload an Excel file first.")
    else:
        # Show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate + execute
        with st.chat_message("assistant"):
            with st.spinner("Analyzing..."):
                try:
                    raw_response = generate_script(
                        prompt,
                        st.session_state.schema_text,
                        len(st.session_state.df),
                        api_key,
                        model,
                    )
                    html_result = execute_script(
                        raw_response, st.session_state.df
                    )
                    st.html(html_result)
                    if show_raw:
                        with st.expander("Raw LLM output"):
                            st.code(raw_response, language="python")
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": html_result,
                            "raw": raw_response,
                        }
                    )
                except Exception as exc:
                    error_html = "<p style='color:red;'>Error: {}</p>".format(
                        exc
                    )
                    st.html(error_html)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_html, "raw": ""}
                    )
