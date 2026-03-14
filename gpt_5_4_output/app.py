from __future__ import annotations

import hashlib
import io
import os
from html import escape

import pandas as pd
import streamlit as st

from df_schema import make_schema_from_df, preprocess_df
from talk2excel import (
    AppSettings,
    delete_api_key,
    load_api_key,
    load_settings,
    run_analysis,
    save_api_key,
    save_settings,
    test_openai_connection,
)

DEFAULT_MODEL = "gpt-5.4"
MODEL_PRESETS = ["gpt-5.4", "gpt-5.1", "gpt-5-mini"]


@st.cache_data(show_spinner=False)
def load_workbook(file_bytes: bytes) -> tuple[pd.DataFrame, pd.DataFrame, str, pd.DataFrame]:
    raw_df = pd.read_excel(io.BytesIO(file_bytes))
    prepared_df = preprocess_df(raw_df)
    schema_text = make_schema_from_df(raw_df)
    schema_frame = pd.DataFrame(
        {
            "Column": raw_df.columns,
            "dtype": [str(dtype) for dtype in raw_df.dtypes],
            "Non-null": [int(raw_df[column].notna().sum()) for column in raw_df.columns],
        }
    )
    return raw_df, prepared_df, schema_text, schema_frame


def main() -> None:
    st.set_page_config(page_title="Talk2Excel", page_icon=":bar_chart:", layout="wide")
    _inject_styles()
    _initialize_state()

    settings = load_settings()
    api_key_seed = load_api_key() or os.getenv("OPENAI_API_KEY", "")

    with st.sidebar:
        st.markdown("## Talk2Excel")
        st.caption(
            "Local spreadsheet analysis with LLM-generated script. "
            "Your data stays on your computer."
        )
        api_key = st.text_input(
            "OpenAI API Key",
            value=st.session_state.get("api_key_input", api_key_seed),
            type="password",
            help="Stored securely in the system keyring for future sessions.",
        )
        st.session_state.api_key_input = api_key

        current_model = st.session_state.get("selected_model", settings.model or DEFAULT_MODEL)
        preset_value = current_model if current_model in MODEL_PRESETS else DEFAULT_MODEL
        model_choice = st.selectbox(
            "Model",
            MODEL_PRESETS,
            index=MODEL_PRESETS.index(preset_value),
        )
        st.session_state.selected_model = model_choice

        show_raw_output = st.checkbox(
            "Show raw LLM output",
            value=st.session_state.get("show_raw_output", settings.show_raw_output),
        )
        st.session_state.store_api_key = True
        st.session_state.show_raw_output = show_raw_output
        _persist_settings(
            api_key=api_key,
            model=st.session_state.selected_model,
            show_raw_output=show_raw_output,
            store_api_key=True,
        )

        if st.button("Test OpenAI connection", use_container_width=True):
            if not api_key:
                st.error("Enter an OpenAI API key first.")
            else:
                try:
                    message = test_openai_connection(
                        api_key=api_key,
                        model=st.session_state.selected_model,
                    )
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")
                else:
                    st.success(message)

        if st.button("Clear conversation", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()

    st.markdown(
        """
        <div class="hero-card">
          <p class="eyebrow">Talk to your workbook</p>
          <h1>Upload Excel, and ask analytical questions in plain English.</h1>
          <p class="hero-copy">
            The AI model writes Python script against your data locally, then
            Talk2Excel renders the answer as text, tables, and charts.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "Upload an Excel workbook",
        type=["xls", "xlsx"],
        help="Load a spreadsheet before starting the conversation.",
    )

    raw_df: pd.DataFrame | None = None
    prepared_df: pd.DataFrame | None = None
    schema_text = ""
    schema_frame: pd.DataFrame | None = None

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        dataset_hash = hashlib.sha256(file_bytes).hexdigest()

        if st.session_state.get("dataset_hash") != dataset_hash:
            st.session_state.dataset_hash = dataset_hash
            st.session_state.chat_messages = []

        raw_df, prepared_df, schema_text, schema_frame = load_workbook(file_bytes)
        _render_schema_area(
            file_name=uploaded_file.name,
            raw_df=raw_df,
            schema_text=schema_text,
            schema_frame=schema_frame,
        )
    else:
        st.info("Upload an Excel file to enable schema inspection and chat analysis.")

    st.markdown("## Chat")
    st.caption(
        "Ask for totals, rankings, tables, charts, or follow-up questions about the uploaded data."
    )

    chat_ready = uploaded_file is not None and prepared_df is not None and bool(api_key.strip())
    _render_chat(
        st.session_state.chat_messages,
        st.session_state.get("show_raw_output", settings.show_raw_output),
    )
    question = st.chat_input(
        "Ask a question about your spreadsheet",
        disabled=not chat_ready,
    )

    if question and question.strip():
        st.session_state.chat_messages.append({"role": "user", "content": question.strip()})
        history = _conversation_context(st.session_state.chat_messages[:-1])

        try:
            with st.spinner("Running local dataframe analysis..."):
                response = run_analysis(
                    api_key=api_key.strip(),
                    model=st.session_state.selected_model,
                    question=question.strip(),
                    df=prepared_df,
                    schema_text=schema_text,
                    conversation_history=history,
                )
        except Exception as exc:
            st.session_state.chat_messages.append(
                {
                    "role": "assistant",
                    "answer_text": f"Analysis failed: {exc}",
                    "tables": [],
                    "charts": [],
                    "raw_output": "",
                    "executed_code": "",
                    "retries": 0,
                    "error": True,
                }
            )
        else:
            st.session_state.chat_messages.append(
                {
                    "role": "assistant",
                    "answer_text": response.answer_text,
                    "tables": response.tables,
                    "charts": response.charts,
                    "raw_output": response.raw_output,
                    "executed_code": response.executed_code,
                    "retries": response.retries,
                    "error": False,
                }
            )
        st.rerun()

    if not chat_ready:
        if uploaded_file is None:
            st.info("Upload a workbook to unlock the chat interface.")
        elif not api_key.strip():
            st.info("Enter an OpenAI API key in the sidebar to start the conversation.")


def _initialize_state() -> None:
    settings = load_settings()

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    if "show_raw_output" not in st.session_state:
        st.session_state.show_raw_output = settings.show_raw_output

    if "store_api_key" not in st.session_state:
        st.session_state.store_api_key = True

    if "selected_model" not in st.session_state:
        st.session_state.selected_model = settings.model

    if "api_key_input" not in st.session_state:
        st.session_state.api_key_input = load_api_key() or os.getenv("OPENAI_API_KEY", "")


def _persist_settings(
    *,
    api_key: str,
    model: str,
    show_raw_output: bool,
    store_api_key: bool,
) -> None:
    save_settings(
        AppSettings(
            model=model,
            show_raw_output=show_raw_output,
            store_api_key=store_api_key,
        )
    )
    if store_api_key and api_key:
        save_api_key(api_key)
    elif not store_api_key:
        delete_api_key()


def _render_schema_area(
    *,
    file_name: str,
    raw_df: pd.DataFrame,
    schema_text: str,
    schema_frame: pd.DataFrame,
) -> None:
    st.markdown("## Dataset")
    st.success(f"Schema ready for {file_name}")

    metric_one, metric_two = st.columns(2)
    metric_one.metric("Rows", f"{len(raw_df):,}")
    metric_two.metric("Columns", f"{len(raw_df.columns):,}")

    preview_tab, schema_tab = st.tabs(["Preview", "Schema"])
    with preview_tab:
        st.dataframe(raw_df.head(12), use_container_width=True, hide_index=True)
    with schema_tab:
        st.dataframe(schema_frame, use_container_width=True, hide_index=True)
        with st.expander("Schema text", expanded=True):
            st.code(schema_text, language="text")


def _render_chat(chat_messages: list[dict[str, object]], show_raw_output: bool) -> None:
    if not chat_messages:
        return

    assistant_index = 0
    for message in chat_messages:
        role = message["role"]
        if role == "user":
            with st.chat_message("user"):
                st.markdown(
                    f"<div class='question-copy'>{escape(str(message['content']))}</div>",
                    unsafe_allow_html=True,
                )
            continue

        assistant_index += 1
        with st.chat_message("assistant"):
            answer_text = str(message.get("answer_text", "")).strip()
            tables = list(message.get("tables", []))
            charts = list(message.get("charts", []))
            error = bool(message.get("error", False))

            st.markdown(f"### Response {assistant_index}")
            tone_class = "response-error" if error else "response-answer"
            st.markdown(
                (
                    f"<div class='{tone_class}' data-testid='assistant-answer'>"
                    f"<strong>Answer</strong><br>{escape(answer_text)}</div>"
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                (
                    "<div class='artifact-summary' data-testid='artifact-summary'>"
                    f"tables:{len(tables)} | charts:{len(charts)} | "
                    f"first_table_rows:{len(tables[0].dataframe) if tables else 0}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            for table in tables:
                st.markdown(f"**{escape(table.title)}**", unsafe_allow_html=True)
                st.table(_format_dataframe_for_display(table.dataframe))

            for chart in charts:
                st.image(chart.png_bytes, caption=chart.title, use_container_width=True)

            st.caption(f"Repair retries: {int(message.get('retries', 0))}")

            if show_raw_output:
                with st.expander("Raw LLM output", expanded=False):
                    st.code(str(message.get("raw_output", "")).strip() or "No raw output recorded.")


def _conversation_context(messages: list[dict[str, object]]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        if message["role"] == "user":
            history.append({"role": "user", "content": str(message["content"])})
        else:
            history.append({"role": "assistant", "content": str(message.get("answer_text", ""))})
    return history


def _format_dataframe_for_display(dataframe: pd.DataFrame) -> pd.DataFrame:
    formatted = dataframe.copy()
    currency_candidates = {"sales", "profit", "revenue", "amount", "total"}

    for column in formatted.columns:
        series = formatted[column]
        if pd.api.types.is_numeric_dtype(series):
            if any(token in str(column).lower() for token in currency_candidates):
                formatted[column] = series.map(lambda value: f"${value:,.0f}")
            elif pd.api.types.is_float_dtype(series):
                formatted[column] = series.map(lambda value: f"{value:,.2f}")
            else:
                formatted[column] = series.map(lambda value: f"{value:,}")

    return formatted


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
          [data-testid="stAppViewContainer"] {
            background:
              radial-gradient(circle at top left, rgba(207, 232, 255, 0.7), transparent 30%),
              radial-gradient(circle at bottom right, rgba(255, 222, 173, 0.45), transparent 28%),
              linear-gradient(180deg, #f7f3ea 0%, #fffdf8 35%, #f3efe6 100%);
          }
          [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #14213d 0%, #23395b 55%, #0f172a 100%);
          }
          [data-testid="stSidebar"] * {
            color: #f8fafc;
          }
          [data-testid="stSidebar"] label,
          [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: #f8fafc !important;
          }
          [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: #f8fafc;
          }
          [data-testid="stSidebar"] input,
          [data-testid="stSidebar"] textarea {
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            caret-color: #0f172a !important;
            background: #fffdf7 !important;
          }
          [data-testid="stSidebar"] input::placeholder,
          [data-testid="stSidebar"] textarea::placeholder {
            color: #64748b !important;
            opacity: 1 !important;
          }
          [data-testid="stSidebar"] [data-baseweb="input"] > div,
          [data-testid="stSidebar"] [data-baseweb="base-input"] > div,
          [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: #fffdf7 !important;
            border: 1px solid #f59e0b !important;
            box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.12) !important;
          }
          [data-testid="stSidebar"] [data-baseweb="select"] span,
          [data-testid="stSidebar"] [data-baseweb="select"] div,
          [data-testid="stSidebar"] [data-baseweb="select"] input {
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
          }
          [data-testid="stSidebar"] [data-baseweb="select"] svg,
          [data-testid="stSidebar"] [data-baseweb="input"] svg {
            fill: #334155 !important;
            color: #334155 !important;
          }
          [data-testid="stSidebar"] [data-baseweb="checkbox"] label,
          [data-testid="stSidebar"] [data-testid="stCheckbox"] label {
            color: #f8fafc !important;
          }
          [data-testid="stSidebar"] button {
            background: linear-gradient(135deg, #fff7ed, #ffedd5) !important;
            color: #111827 !important;
            border: 1px solid #fb923c !important;
            font-weight: 700 !important;
          }
          [data-testid="stSidebar"] button [data-testid="stMarkdownContainer"],
          [data-testid="stSidebar"] button [data-testid="stMarkdownContainer"] *,
          [data-testid="stSidebar"] button p,
          [data-testid="stSidebar"] button span,
          [data-testid="stSidebar"] button div {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
          }
          [data-testid="stSidebar"] button:hover {
            border-color: #f97316 !important;
            color: #0f172a !important;
          }
          [data-testid="stSidebar"] [aria-disabled="true"] input,
          [data-testid="stSidebar"] [disabled] {
            opacity: 1 !important;
            color: #475569 !important;
            -webkit-text-fill-color: #475569 !important;
            background: #f8fafc !important;
          }
          .hero-card {
            border: 1px solid rgba(15, 23, 42, 0.1);
            border-radius: 22px;
            padding: 1.4rem 1.6rem;
            margin-bottom: 1.2rem;
            background: linear-gradient(135deg, rgba(255,255,255,0.94), rgba(255,248,236,0.92));
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
          }
          .hero-card h1 {
            margin: 0 0 0.4rem 0;
            color: #0f172a;
            font-size: clamp(2rem, 3vw, 3rem);
            line-height: 1.05;
          }
          .eyebrow {
            margin: 0 0 0.5rem 0;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.75rem;
            color: #9a3412;
            font-weight: 700;
          }
          .hero-copy {
            margin: 0;
            max-width: 62rem;
            color: #334155;
            font-size: 1rem;
          }
          .question-copy,
          .response-answer,
          .response-error,
          .artifact-summary {
            border-radius: 18px;
            padding: 0.9rem 1rem;
            border: 1px solid rgba(15, 23, 42, 0.08);
          }
          .question-copy {
            background: rgba(248, 250, 252, 0.9);
          }
          .response-answer {
            background: linear-gradient(135deg, rgba(255,255,255,0.98), rgba(240,249,255,0.95));
          }
          .response-error {
            background: linear-gradient(135deg, rgba(255,241,242,0.98), rgba(255,228,230,0.95));
          }
          .artifact-summary {
            background: rgba(15, 23, 42, 0.04);
            margin-top: 0.6rem;
            margin-bottom: 0.8rem;
            font-family: Consolas, "SFMono-Regular", monospace;
            font-size: 0.92rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
