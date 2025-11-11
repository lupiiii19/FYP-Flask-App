from pathlib import Path
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from config import DATA_DIR

# Look for common filenames and finally any CSV in Dataset/
VECT_PATH = DATA_DIR / "tfidf_vectorizer.pkl"
DATA_PATH = DATA_DIR / "cleaned_dataset.pkl"    # pickled DataFrame
COMMON_CSV_NAMES = [
    "data.csv",
    "cleaned_dataset.csv",
    "dataset.csv",
    "items.csv",
]

_vectorizer = None
_df = None
_matrix = None
_text_col = None

def _find_csv_path() -> Path:
    # 1) Try common names
    for name in COMMON_CSV_NAMES:
        p = DATA_DIR / name
        if p.exists():
            return p
    # 2) Any CSV as fallback
    csvs = sorted(DATA_DIR.glob("*.csv"))
    if csvs:
        return csvs[0]
    raise FileNotFoundError(
        f"No CSV found in {DATA_DIR}. Put a CSV there (e.g. data.csv) or provide PKLs: "
        f"{VECT_PATH.name} and {DATA_PATH.name}."
    )

def _detect_text_column(df: pd.DataFrame) -> str:
    candidates = ["text", "content", "description", "clean_text", "title", "review"]
    for c in candidates:
        if c in df.columns:
            return c
    # fallback: if there is any object/string column, use the first
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]):
            return c
    raise KeyError(
        f"Couldn't find a suitable text column in CSV. Columns: {list(df.columns)}"
    )

def _build_from_csv():
    csv_path = _find_csv_path()
    df = pd.read_csv(csv_path)
    text_col = _detect_text_column(df)
    df = df.dropna(subset=[text_col]).reset_index(drop=True)

    vec = TfidfVectorizer(stop_words="english")
    mat = vec.fit_transform(df[text_col].astype(str))

    # Persist for faster next runs (optional but handy)
    try:
        joblib.dump(vec, VECT_PATH)
        joblib.dump(df, DATA_PATH)
    except Exception:
        # do not fail the request if saving is not possible
        pass

    return df, vec, mat, text_col

def ensure_models_loaded():
    """Load vectorizer+data from PKL if present; otherwise build from CSV."""
    global _vectorizer, _df, _matrix, _text_col

    if _vectorizer is not None and _df is not None and _matrix is not None:
        return

    if VECT_PATH.exists() and DATA_PATH.exists():
        _vectorizer = joblib.load(VECT_PATH)
        _df = joblib.load(DATA_PATH)
        # infer text column
        _text_col = _detect_text_column(_df)
        _matrix = _vectorizer.transform(_df[_text_col].astype(str))
    else:
        _df, _vectorizer, _matrix, _text_col = _build_from_csv()

def recommend_topk(query: str, k: int = 5):
    ensure_models_loaded()
    q_vec = _vectorizer.transform([query])
    sims = linear_kernel(q_vec, _matrix).ravel()
    top_idx = sims.argsort()[-k:][::-1]

    results = []
    for i, idx in enumerate(top_idx, start=1):
        row = _df.iloc[int(idx)]
        score = float(sims[int(idx)])
        item = {
            "rank": i,
            "score": round(score, 6),
            "text": str(row.get(_text_col, "")),
        }
        for extra in ["title", "id", "label", "category"]:
            if extra in _df.columns:
                item[extra] = row.get(extra)
        results.append(item)
    return results
