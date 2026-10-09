"""Shared utilities for the marketing agents: web research + knowledge base."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; MarketingAgents/1.0)"

# Repository root — the folder that holds knowledge_base.json / app.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _TextExtractor(HTMLParser):
    """Strip scripts/styles and collect visible text from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.chunks.append(text)


def fetch_url(url: str, timeout: int = 8) -> dict[str, Any]:
    """Fetch a URL and return extracted text. Raises on network failure."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(500_000)
    html = raw.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = " ".join(parser.chunks)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": url, "title": parser.title or "", "text": text[:20000]}


INDUSTRY_KEYWORDS = {
    "technology": ["software", "cloud", "AI", "platform", "SaaS", "API", "data"],
    "finance": ["bank", "fintech", "payments", "insurance", "investment", "lending"],
    "healthcare": ["health", "medical", "clinic", "pharma", "patient", "care"],
    "retail": ["shop", "store", "e-commerce", "retail", "brand", "products"],
    "manufacturing": ["factory", "production", "industrial", "machinery", "supply"],
    "education": ["school", "learning", "course", "training", "academy", "university"],
    "marketing": ["agency", "media", "advertising", "campaign", "content", "SEO"],
    "hospitality": ["hotel", "restaurant", "travel", "booking", "guest", "tour"],
}

VALUE_PROP_PATTERNS = [
    r"(help(?:s|ing)? (?:companies|businesses|teams|brands)[^.]{5,120})",
    r"(we (?:build|make|offer|provide|deliver)[^.]{5,120})",
    r"(the (?:leading|best|#1|fastest-growing)[^.]{5,120})",
    r"([A-Z][^.]{10,90}\b(?:solution|platform|service)\b[^.]{0,40})",
]


def analyze_text(text: str) -> dict[str, Any]:
    """Heuristic NLP-lite analysis of page/company text."""
    lower = text.lower()
    scores: dict[str, int] = {}
    for industry, kws in INDUSTRY_KEYWORDS.items():
        scores[industry] = sum(lower.count(k.lower()) for k in kws)
    best_industry = max(scores, key=lambda k: scores[k]) if scores else "unknown"
    if scores.get(best_industry, 0) == 0:
        best_industry = "unknown"

    value_props: list[str] = []
    for pat in VALUE_PROP_PATTERNS:
        for m in re.finditer(pat, text):
            vp = m.group(1).strip()
            if vp not in value_props:
                value_props.append(vp)
            if len(value_props) >= 3:
                break
        if len(value_props) >= 3:
            break

    tone = "formal"
    if any(w in lower for w in ["fun", "playful", "awesome", "love", "delight"]):
        tone = "friendly"
    elif any(w in lower for w in ["innovative", "disrupt", "bold", "revolution"]):
        tone = "energetic"

    total_hits = sum(scores.values())
    confidence = min(0.9, 0.3 + total_hits / 100.0) if best_industry != "unknown" else 0.25

    return {
        "industry_guess": best_industry,
        "value_props": value_props,
        "tone": tone,
        "keyword_scores": {k: v for k, v in scores.items() if v > 0},
        "confidence": round(confidence, 2),
    }


def search_duckduckgo(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Best-effort lightweight web search via DuckDuckGo HTML endpoint."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        data = fetch_url(url, timeout=8)["text"]
    except Exception:
        return []
    # The text extraction flattens the result markup, so rank the surviving
    # sentences by length and return them as snippets.
    results = []
    snippets = [s.strip() for s in re.split(r"(?<=[.!?])\s+", data) if 40 < len(s.strip()) < 300]
    for s in snippets[:max_results]:
        results.append({"query": query, "snippet": s})
    return results


# The knowledge base ships with the repository next to app.py. The absolute
# /workspace path is kept as a fallback for the original HF Space layout, and
# KNOWLEDGE_BASE lets a deployment point somewhere else entirely.
_KB_PATH_CANDIDATES = (
    os.environ.get("KNOWLEDGE_BASE"),
    os.path.join(REPO_ROOT, "knowledge_base.json"),
    "/workspace/knowledge_base.json",
)

# path -> (mtime, parsed document); keeps repeated calls cheap while still
# picking up edits made to the file while the server is running.
_kb_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def knowledge_base_path() -> str | None:
    """Return the first existing knowledge_base.json candidate, or None."""
    for candidate in _KB_PATH_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def load_knowledge_base() -> dict[str, Any]:
    """Load frameworks / tones / goals / benchmarks.

    Returns {} when no knowledge base is present so callers can fall back to
    their own defaults instead of crashing.
    """
    path = knowledge_base_path()
    if path is None:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _kb_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        return {"_error": f"knowledge_base.json is corrupt: {e}"}
    if isinstance(data, dict):
        _kb_cache[path] = (mtime, data)
    return data if isinstance(data, dict) else {}

