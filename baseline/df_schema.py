import pandas as pd
from datetime import datetime

def infer_col_type(series: pd.Series, col_name: str):
    """Rough type inference + special cases."""
    s = series.dropna()

    if s.empty:
        return "string"

    # Try date (M/D/YY)
    try:
        pd.to_datetime(s, format="%m/%d/%y", errors="raise")
        return "date (M/D/YY)"
    except Exception:
        pass

    # Numeric?
    try:
        pd.to_numeric(s, errors="raise")
        return "number"
    except Exception:
        pass

    # Currency-like? Require full match to avoid misclassifying strings such as "3 - Senior".
    currency_re = r"^\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?$"
    str_values = s.astype(str).str.strip()
    currency_like = str_values.str.fullmatch(currency_re, na=False)
    has_currency_mark = str_values.str.contains(r"[$,\.]", regex=True, na=False)
    if currency_like.mean() > 0.8 and has_currency_mark.any():
        return "currency"

    return "string"


def infer_enum_values(series: pd.Series, max_unique=25, max_len=50):
    """Return small sets of values as enum list, otherwise None."""
    s = series.dropna().astype(str).str.strip()
    uniques = sorted(s.unique())
    if 0 < len(uniques) <= max_unique and all(len(u) <= max_len for u in uniques):
        return uniques
    return None


def make_schema_from_df(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        col_type = infer_col_type(df[col], col)

        # enum detection
        enum_vals = infer_enum_values(df[col])

        if enum_vals:
            enum_str = '", "'.join(enum_vals)
            line = f' - {col} ({col_type}: one of "{enum_str}")'
        else:
            line = f" - {col} ({col_type})"

        lines.append(line)

    return "\n".join(lines)

def preprocess_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocess a DataFrame based on inferred column types.

    - date / date (M/D/YY): parsed to datetime64[ns]
    - number: converted with pd.to_numeric
    - currency: stripped of symbols/commas, converted to numeric
    - string: converted to str and stripped of leading/trailing whitespace
    """
    df = df.copy()

    for col in df.columns:
        col_type = infer_col_type(df[col], col)

        # --- Date handling ---
        if col_type == "date (M/D/YY)":
            # Strict M/D/YY
            df[col] = pd.to_datetime(df[col], format="%m/%d/%y", errors="coerce")

        elif col_type == "date":
            # More flexible parsing
            df[col] = pd.to_datetime(
                df[col].astype(str).str.strip(),
                infer_datetime_format=True,
                errors="coerce"
            )

        # --- Numeric handling ---
        elif col_type == "number":
            df[col] = pd.to_numeric(df[col], errors="coerce")

        elif col_type == "currency":
            # Remove everything except digits, dot, minus
            cleaned = (
                df[col]
                .astype(str)
                .str.strip()
                .str.replace(r"[^\d\.\-]", "", regex=True)
            )
            df[col] = pd.to_numeric(cleaned, errors="coerce")

        # --- String / default handling ---
        else:  # "string"
            df[col] = df[col].astype(str).str.strip()

    return df
