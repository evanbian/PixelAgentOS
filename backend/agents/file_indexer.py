"""File structure extractor: builds lightweight indexes for scratchpad metadata."""
from __future__ import annotations

import re
from typing import Optional


def extract_file_index(content: str, file_type: str) -> dict:
    """Extract a structured index from file content.

    Returns:
        {
            "summary": str,          # first paragraph, max 200 chars
            "sections": [            # heading/definition list
                {"heading": str, "line_start": int, "line_end": int, "keywords": [str]}
            ],
            "key_data_points": [     # numeric data found in content
                {"label": str, "value": str, "line": int}
            ],
        }
    """
    lines = content.split("\n")
    summary = _extract_summary(content)
    sections = _extract_sections(lines, file_type)
    key_data_points = _extract_key_data_points(lines)

    return {
        "summary": summary,
        "sections": sections,
        "key_data_points": key_data_points[:20],  # cap at 20
    }


def _extract_summary(content: str) -> str:
    """First non-empty paragraph, stripped of markdown formatting, max 200 chars."""
    # Skip leading headings / blank lines
    for para in re.split(r"\n\s*\n", content):
        text = para.strip()
        if not text:
            continue
        # Skip lines that are purely headings
        if text.startswith("#") and "\n" not in text:
            continue
        # Strip markdown formatting
        clean = re.sub(r"[#*_`>\[\]!]", "", text).strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            return clean[:200]
    return content[:200].replace("\n", " ").strip()


def _extract_sections(lines: list, file_type: str) -> list:
    """Extract section headings with line ranges and keywords."""
    sections: list[dict] = []

    if file_type in ("markdown", "text", "document"):
        _extract_markdown_sections(lines, sections)
    elif file_type in ("python", "javascript", "typescript"):
        _extract_code_sections(lines, sections)
    elif file_type == "csv":
        _extract_csv_sections(lines, sections)
    else:
        # Generic: try markdown first, then code
        _extract_markdown_sections(lines, sections)
        if not sections:
            _extract_code_sections(lines, sections)

    # Fill in line_end for each section (runs until next section or EOF)
    for i, sec in enumerate(sections):
        if i + 1 < len(sections):
            sec["line_end"] = sections[i + 1]["line_start"] - 1
        else:
            sec["line_end"] = len(lines)

    return sections[:30]  # cap at 30 sections


def _extract_markdown_sections(lines: list, sections: list) -> None:
    """Extract markdown headings."""
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$")
    for i, line in enumerate(lines):
        m = heading_re.match(line.strip())
        if m:
            heading = m.group(2).strip()
            # Extract keywords from the heading line and nearby lines
            keywords = _extract_line_keywords(lines, i, window=5)
            sections.append({
                "heading": heading,
                "line_start": i + 1,  # 1-indexed
                "line_end": 0,
                "keywords": keywords[:8],
            })


def _extract_code_sections(lines: list, sections: list) -> None:
    """Extract function/class definitions."""
    code_re = re.compile(
        r"^\s*(?:def|class|function|const|let|var|export\s+(?:default\s+)?(?:function|class))\s+(\w+)"
    )
    for i, line in enumerate(lines):
        m = code_re.match(line)
        if m:
            name = m.group(1)
            sections.append({
                "heading": name,
                "line_start": i + 1,
                "line_end": 0,
                "keywords": [name],
            })


def _extract_csv_sections(lines: list, sections: list) -> None:
    """Extract CSV column names and row count."""
    if lines:
        header = lines[0].strip()
        cols = [c.strip().strip('"') for c in header.split(",")]
        sections.append({
            "heading": f"CSV: {len(lines) - 1} rows, columns: {', '.join(cols[:10])}",
            "line_start": 1,
            "line_end": len(lines),
            "keywords": cols[:10],
        })


def _extract_line_keywords(lines: list, center: int, window: int = 5) -> list:
    """Extract meaningful keywords from lines around a given position."""
    start = max(0, center)
    end = min(len(lines), center + window)
    text = " ".join(lines[start:end])
    # Find words that look like domain terms (not stopwords, >= 4 chars)
    words = re.findall(r"\b[a-zA-Z\u4e00-\u9fff]{4,}\b", text)
    _stop = {
        "this", "that", "with", "from", "have", "been", "will", "would",
        "could", "should", "about", "which", "their", "these", "those",
        "then", "than", "when", "what", "there", "here", "were", "they",
        "some", "into", "also", "more", "very", "just", "only", "each",
    }
    seen: set = set()
    result: list = []
    for w in words:
        wl = w.lower()
        if wl not in _stop and wl not in seen:
            seen.add(wl)
            result.append(wl)
    return result


# Regex for numeric values with units: $180B, 25%, 1.5M, etc.
_DATA_POINT_RE = re.compile(
    r"(?:[$￥€])\s*(\d[\d,.]*\s*[BMKTbmkt]?)"   # currency amounts
    r"|(\d[\d,.]*\s*%)"                           # percentages
    r"|(\d[\d,.]*\s*[BMKTbmkt]\b)"                # numbers with magnitude suffix
)


def _extract_key_data_points(lines: list) -> list:
    """Extract numeric data points (currency, percentages, magnitudes)."""
    results: list[dict] = []
    for i, line in enumerate(lines):
        for m in _DATA_POINT_RE.finditer(line):
            value = m.group(0).strip()
            # Build a label from surrounding context
            label = _label_from_context(line, m.start())
            results.append({
                "label": label,
                "value": value,
                "line": i + 1,  # 1-indexed
            })
    return results


def _label_from_context(line: str, pos: int) -> str:
    """Extract a short label from the text before the data point."""
    prefix = line[:pos].strip()
    # Take last ~40 chars, trim to word boundary
    if len(prefix) > 40:
        prefix = prefix[-40:]
        space_idx = prefix.find(" ")
        if space_idx > 0:
            prefix = prefix[space_idx + 1:]
    # Clean markdown/punctuation
    prefix = re.sub(r"[#*_`|>\[\]:：，。]", "", prefix).strip()
    return prefix if prefix else "value"
