from __future__ import annotations

import ast
import io
import re
import textwrap
from dataclasses import dataclass
from typing import Any

import pandas as pd
from matplotlib import figure as mpl_figure
from matplotlib import pyplot as plt
from openai import OpenAI

EXECUTE_PATTERN = re.compile(r"<execute_python>\s*([\s\S]*?)\s*</execute_python>", re.IGNORECASE)
FORBIDDEN_CALLS = {"__import__", "compile", "eval", "exec", "input", "open"}
FORBIDDEN_ROOT_NAMES = {
    "builtins",
    "importlib",
    "os",
    "pathlib",
    "pickle",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


@dataclass(slots=True)
class TableArtifact:
    title: str
    dataframe: pd.DataFrame


@dataclass(slots=True)
class ChartArtifact:
    title: str
    png_bytes: bytes


@dataclass(slots=True)
class AnalysisResponse:
    answer_text: str
    tables: list[TableArtifact]
    charts: list[ChartArtifact]
    raw_output: str
    executed_code: str
    retries: int


class GeneratedCodeError(RuntimeError):
    pass


class CodeSafetyVisitor(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        raise GeneratedCodeError("Generated code may not import modules.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise GeneratedCodeError("Generated code may not import modules.")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise GeneratedCodeError("Generated code may not define classes.")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        raise GeneratedCodeError("Generated code may not define functions.")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise GeneratedCodeError("Generated code may not define functions.")

    def visit_Global(self, node: ast.Global) -> None:
        raise GeneratedCodeError("Generated code may not use global statements.")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        raise GeneratedCodeError("Generated code may not use nonlocal statements.")

    def visit_With(self, node: ast.With) -> None:
        raise GeneratedCodeError("Generated code may not use context managers.")

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        raise GeneratedCodeError("Generated code may not use context managers.")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise GeneratedCodeError("Dunder names are not allowed.")
        if node.id in FORBIDDEN_ROOT_NAMES:
            raise GeneratedCodeError(f"'{node.id}' is not allowed.")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise GeneratedCodeError("Dunder attributes are not allowed.")

        root_name = _root_name(node)
        if root_name in FORBIDDEN_ROOT_NAMES:
            raise GeneratedCodeError(f"'{root_name}' is not allowed.")

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callable_name = _callable_name(node.func)
        if callable_name in FORBIDDEN_CALLS:
            raise GeneratedCodeError(f"Calling '{callable_name}' is not allowed.")

        root_name = _root_name(node.func)
        if root_name in FORBIDDEN_ROOT_NAMES:
            raise GeneratedCodeError(f"Calling '{root_name}' is not allowed.")

        self.generic_visit(node)


def test_openai_connection(api_key: str, model: str) -> str:
    client = OpenAI(api_key=api_key)
    available_models = {item.id for item in client.models.list().data}

    if model not in available_models:
        raise RuntimeError(f"Model '{model}' is not available for this API key.")

    return f"Connected to OpenAI. Model '{model}' is available."


def run_analysis(
    *,
    api_key: str,
    model: str,
    question: str,
    df: pd.DataFrame,
    schema_text: str,
    conversation_history: list[dict[str, str]] | None = None,
    max_attempts: int = 3,
) -> AnalysisResponse:
    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(
        question=question,
        df=df,
        schema_text=schema_text,
        conversation_history=conversation_history or [],
    )
    last_error = "No attempts were made."
    last_raw_output = ""
    last_code = ""

    for attempt in range(max_attempts):
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=1800,
        )
        raw_output = (response.output_text or "").strip()
        code = _extract_code(raw_output)

        try:
            tables, charts, answer_text = _execute_generated_code(code, df)
            return AnalysisResponse(
                answer_text=answer_text,
                tables=tables,
                charts=charts,
                raw_output=raw_output,
                executed_code=code,
                retries=attempt,
            )
        except Exception as exc:
            last_error = str(exc)
            last_raw_output = raw_output
            last_code = code
            prompt = _build_repair_prompt(
                question=question,
                df=df,
                schema_text=schema_text,
                conversation_history=conversation_history or [],
                failed_code=code,
                error_message=last_error,
            )

    raise RuntimeError(
        "The analysis could not be completed after "
        f"{max_attempts} attempts. Last error: {last_error}\n\n"
        f"Last model output:\n{last_raw_output}\n\n"
        f"Last generated code:\n{last_code}"
    )


def _build_prompt(
    *,
    question: str,
    df: pd.DataFrame,
    schema_text: str,
    conversation_history: list[dict[str, str]],
) -> str:
    data_preview = df.head(5).to_string(index=False)
    history_text = _history_text(conversation_history)
    dataset_notes = _dataset_notes(df)

    return textwrap.dedent(
        f"""
        You are a data analyst writing Python that runs locally against a pandas DataFrame named df.

        Return your answer strictly in this format:

        <execute_python>
        answer_text = \"\"\"A concise plain-English answer.\"\"\"
        result_tables = []
        result_charts = []
        # additional analysis code here
        </execute_python>

        Hard rules:
        - Return only the code block wrapped in <execute_python> tags.
        - Do not import modules.
        - Do not read or write files.
        - Do not call network services.
        - Do not mutate df in place.
        - Use only the already-available objects: df, pd, plt.
        - answer_text must always be set to a non-empty string.
        - result_tables must be a list of pandas DataFrames or (title, DataFrame) tuples.
        - result_charts must be a list of matplotlib Figure objects or (title, Figure) tuples.
        - If the user explicitly asks for a table, include a table.
        - If the user explicitly asks for a chart, include a chart.
        - Filtering on string columns must be case-insensitive.
        - If a question asks for the number/count of all orders or records without saying distinct
          or unique, count rows.
        - When ranking customers, group by Customer Name unless the user says otherwise.
        - When ranking products, group by Product Name unless the user says otherwise.
        - When ranking sub-categories, group by Sub-Category unless the user says otherwise.
        - Format totals in answer_text with comma separators and round to whole numbers unless the
          user asks for more precision.
        - For each matplotlib figure, append it to result_charts and then call plt.close(fig).
        - Prefer concise code that uses pandas aggregations.

        Dataset schema:
        {schema_text}

        Dataset notes:
        {dataset_notes}

        Sample rows:
        {data_preview}

        Recent conversation:
        {history_text}

        User question:
        {question}
        """
    ).strip()


def _build_repair_prompt(
    *,
    question: str,
    df: pd.DataFrame,
    schema_text: str,
    conversation_history: list[dict[str, str]],
    failed_code: str,
    error_message: str,
) -> str:
    base_prompt = _build_prompt(
        question=question,
        df=df,
        schema_text=schema_text,
        conversation_history=conversation_history,
    )

    return (
        f"{base_prompt}\n\n"
        "The previous code failed. Rewrite it and fix the issue.\n\n"
        f"Execution error:\n{error_message}\n\n"
        f"Previous code:\n{failed_code}"
    )


def _dataset_notes(df: pd.DataFrame) -> str:
    lines = [f"- Rows: {len(df)}", f"- Columns: {len(df.columns)}"]

    if "Order ID" in df.columns:
        unique_orders = df["Order ID"].nunique(dropna=True)
        lines.append(f"- Unique Order ID values: {unique_orders}")
        if unique_orders < len(df):
            lines.append(
                "- Rows represent order line items, so row count can exceed unique Order ID count."
            )

    numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    if numeric_columns:
        lines.append(f"- Numeric columns: {', '.join(numeric_columns)}")

    return "\n".join(lines)


def _history_text(conversation_history: list[dict[str, str]]) -> str:
    if not conversation_history:
        return "- No prior conversation."

    lines: list[str] = []
    for message in conversation_history[-6:]:
        role = message.get("role", "assistant").title()
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"- {role}: {content}")

    return "\n".join(lines) if lines else "- No prior conversation."


def _extract_code(raw_output: str) -> str:
    text = raw_output.strip()
    text = re.sub(r"^```(?:python)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    match = EXECUTE_PATTERN.search(text)
    if match:
        return match.group(1).strip()

    if text:
        return text

    raise GeneratedCodeError("The model returned an empty response.")


def _execute_generated_code(
    code: str,
    df: pd.DataFrame,
) -> tuple[list[TableArtifact], list[ChartArtifact], str]:
    tree = ast.parse(code, mode="exec")
    CodeSafetyVisitor().visit(tree)
    compiled = compile(tree, "<talk2excel-generated>", "exec")
    scope: dict[str, Any] = {
        "__builtins__": SAFE_BUILTINS,
        "df": df.copy(deep=True),
        "pd": pd,
        "plt": plt,
    }
    plt.close("all")
    exec(compiled, scope, scope)

    answer_text = str(scope.get("answer_text", "")).strip()
    if not answer_text:
        raise GeneratedCodeError("Generated code did not set answer_text.")

    tables = _normalize_tables(scope.get("result_tables"))
    charts = _normalize_charts(scope.get("result_charts"))

    if not charts:
        charts = _normalize_charts([plt.figure(number) for number in plt.get_fignums()])

    return tables, charts, answer_text


def _normalize_tables(raw_tables: Any) -> list[TableArtifact]:
    if raw_tables is None:
        return []

    if isinstance(raw_tables, (pd.DataFrame, pd.Series, tuple, dict)):
        candidates = [raw_tables]
    elif isinstance(raw_tables, list):
        candidates = raw_tables
    else:
        raise GeneratedCodeError("result_tables must be a list, DataFrame, Series, tuple, or dict.")

    normalized: list[TableArtifact] = []
    for index, item in enumerate(candidates, start=1):
        title = f"Table {index}"
        dataframe: pd.DataFrame | None = None

        if isinstance(item, pd.DataFrame):
            dataframe = item.copy()
        elif isinstance(item, pd.Series):
            dataframe = item.to_frame().reset_index()
        elif isinstance(item, tuple) and len(item) == 2:
            title = str(item[0]) or title
            dataframe = _coerce_to_dataframe(item[1])
        elif isinstance(item, dict):
            title = str(item.get("title", title))
            data = item.get("data", item.get("df"))
            dataframe = _coerce_to_dataframe(data)
        else:
            dataframe = _coerce_to_dataframe(item)

        if dataframe is None:
            raise GeneratedCodeError(
                "One of the result_tables items could not be converted to a DataFrame."
            )

        normalized.append(TableArtifact(title=title, dataframe=dataframe.reset_index(drop=True)))

    return normalized


def _normalize_charts(raw_charts: Any) -> list[ChartArtifact]:
    if raw_charts is None:
        return []

    if isinstance(raw_charts, (mpl_figure.Figure, tuple)):
        candidates = [raw_charts]
    elif isinstance(raw_charts, list):
        candidates = raw_charts
    else:
        raise GeneratedCodeError("result_charts must be a list, Figure, or (title, Figure) tuple.")

    normalized: list[ChartArtifact] = []
    for index, item in enumerate(candidates, start=1):
        title = f"Chart {index}"
        figure: mpl_figure.Figure

        if isinstance(item, tuple) and len(item) == 2:
            title = str(item[0]) or title
            figure = item[1]
        else:
            figure = item

        if not isinstance(figure, mpl_figure.Figure):
            raise GeneratedCodeError("Each chart item must be a matplotlib Figure.")

        normalized.append(ChartArtifact(title=title, png_bytes=_figure_to_png_bytes(figure)))

    return normalized


def _coerce_to_dataframe(value: Any) -> pd.DataFrame | None:
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, pd.Series):
        return value.to_frame().reset_index()
    if isinstance(value, list):
        return pd.DataFrame(value)
    if isinstance(value, dict):
        return pd.DataFrame(value)
    return None


def _figure_to_png_bytes(figure: mpl_figure.Figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    buffer.seek(0)
    return buffer.getvalue()


def _callable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None
