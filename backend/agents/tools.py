"""Agent tools: web search, code execution, file writing, data analysis, messaging, and more."""
from __future__ import annotations

import ast
import base64
import contextvars
import csv
import difflib
import hashlib
import html.parser
import io
import ipaddress
import math
import os
import re
import string
import subprocess
import sys
import tempfile
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from urllib.parse import urlparse
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Per-agent workspace via contextvars (concurrent-safe) ──
_workspace_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_workspace_var', default=None
)
_workspace_url_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_workspace_url_var', default=None
)
_agent_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_agent_id_var', default=None
)
# Upstream workspace dirs the current agent can READ (set by graph.py via read_from)
_readable_workspaces_var: contextvars.ContextVar[List[str]] = contextvars.ContextVar(
    '_readable_workspaces_var', default=[]
)

# ── Matplotlib CJK font config (created once, reused) ──
_mpl_config_dir: Optional[str] = None


def _ensure_mpl_config() -> str:
    """Create a matplotlibrc with CJK font support (once per process)."""
    global _mpl_config_dir
    if _mpl_config_dir and os.path.isdir(_mpl_config_dir):
        return _mpl_config_dir

    _mpl_config_dir = os.path.join(
        tempfile.gettempdir(), "agent_mpl_config"
    )
    os.makedirs(_mpl_config_dir, exist_ok=True)
    rc_path = os.path.join(_mpl_config_dir, "matplotlibrc")

    # Fonts available on macOS; falls back gracefully if missing
    rc_content = (
        "font.family: sans-serif\n"
        "font.sans-serif: Heiti TC, STHeiti, PingFang HK, "
        "Songti SC, Arial Unicode MS, sans-serif\n"
        "axes.unicode_minus: False\n"
    )
    with open(rc_path, "w", encoding="utf-8") as f:
        f.write(rc_content)
    return _mpl_config_dir


# Bootstrap code prepended to EVERY agent Python execution.
# Sets CJK fonts before any matplotlib import so Chinese text always renders.
# Guarded: only activates when agent code actually uses matplotlib.
_MPL_CJK_BOOTSTRAP = """\
import sys as _sys
if any("matplotlib" in _l for _l in open(_sys.argv[0], encoding="utf-8")):
    import matplotlib as _mpl
    _mpl.use("Agg")
    _mpl.rcParams["font.sans-serif"] = [
        "Heiti TC", "STHeiti", "PingFang HK",
        "Songti SC", "Arial Unicode MS", "sans-serif",
    ]
    _mpl.rcParams["axes.unicode_minus"] = False
"""


def set_workspace(path: str, url_prefix: str = ""):
    """Set the workspace directory for the current async context."""
    _workspace_var.set(path)
    _workspace_url_var.set(url_prefix)
    logger.info(f"[Workspace] SET path={path}, url_prefix={url_prefix}")


def clear_workspace():
    """Clear the workspace directory reference in the current context."""
    logger.info(f"[Workspace] CLEAR (was: {_workspace_var.get(None)})")
    _workspace_var.set(None)
    _workspace_url_var.set(None)


@tool
def web_search(query: str) -> str:
    """Search the web for information on a given topic.

    Args:
        query: The search query string
    Returns:
        Search results as formatted text
    """
    try:
        tavily_key = os.getenv("TAVILY_API_KEY", "")
        if tavily_key and tavily_key != "your_tavily_api_key_here":
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_key)
            result = client.search(query, max_results=5)
            results_text = f"Search results for: {query}\n\n"
            for i, r in enumerate(result.get("results", []), 1):
                results_text += f"{i}. {r.get('title', '')}\n"
                results_text += f"   URL: {r.get('url', '')}\n"
                results_text += f"   {r.get('content', '')[:300]}...\n\n"
            return results_text
        else:
            # Fallback: return simulated results
            return (
                f"Search results for '{query}':\n\n"
                "Note: Tavily API key not configured. "
                "Please add TAVILY_API_KEY to .env for real web search.\n\n"
                "Simulated result: Based on the query, here are relevant findings...\n"
                "1. General information about the topic\n"
                "2. Key concepts and definitions\n"
                "3. Recent developments and trends"
            )
    except ImportError:
        return (
            f"Web search for '{query}':\n"
            "Tavily package not installed. "
            "Run: pip install tavily-python\n"
            "Returning placeholder results."
        )
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Search failed: {str(e)}"


def _collect_workspace_files(workspace: str) -> set:
    """Collect all relative file paths in workspace using os.walk."""
    result = set()
    for dirpath, _dirnames, filenames in os.walk(workspace):
        for name in filenames:
            fpath = os.path.join(dirpath, name)
            relpath = os.path.relpath(fpath, workspace)
            result.add(relpath)
    return result


@tool
def code_execute(code: str, language: str = "python") -> str:
    """Execute Python code for calculations, data processing, and automation.

    Use this for: simple calculations, data formatting, CSV/JSON processing,
    matplotlib charts, pandas analysis, and general-purpose scripting.
    If a matched skill was pre-loaded in your context, prefer using its
    scripts via shell_execute() instead of writing equivalent code here.

    GOOD uses: simple calculations, data formatting, CSV/JSON processing,
    basic matplotlib charts, text manipulation, pandas aggregation.

    BAD uses (use a skill instead): image generation, PDF creation,
    favicon/OG-image generation, web scraping pipelines, file format
    conversion, complex visualization, anything requiring specialized
    libraries beyond the pre-installed set.

    CRITICAL: Each execution runs in an INDEPENDENT process.
    You MUST include ALL import statements every time.

    Pre-installed libraries (do NOT pip install, just import):
    matplotlib, pandas, numpy, seaborn, scipy, openpyxl, Pillow,
    json, csv, os, math, datetime, re

    For matplotlib: always use matplotlib.use('Agg') before importing pyplot.
    Generated file URLs start with /api/workspaces/... — use them exactly
    as returned, do NOT add any prefix like 'sandbox:' or 'file:'.

    Args:
        code: Python code to execute
        language: Programming language (currently only 'python' supported)
    Returns:
        Execution output and list of any generated files with URLs
    """
    if language != "python":
        return f"Only Python is supported, got: {language}"

    # Security: block system-level operations only
    dangerous = [
        "subprocess", "os.system(", "os.popen(",
        "__import__", "exec(", "eval(",
        "shutil.rmtree", "os.remove(", "os.unlink(",
        "socket", "requests.post(", "requests.get(",
        "urllib", "http.client",
    ]
    for danger in dangerous:
        if danger in code:
            return f"Security error: '{danger}' is not allowed"

    # Use task workspace if set, otherwise temp directory
    workspace = _workspace_var.get(None)
    if not workspace:
        workspace = tempfile.mkdtemp(prefix="agent_code_")
    os.makedirs(workspace, exist_ok=True)

    try:
        # Write code to /tmp/ (NOT workspace) to avoid triggering uvicorn reload
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', prefix='agent_run_',
            delete=False, encoding='utf-8',
        )
        # Prepend matplotlib CJK font bootstrap — runs before any agent code,
        # guarantees Chinese text renders correctly regardless of what the
        # agent writes.  The guard (`if "matplotlib" in ...`) avoids importing
        # matplotlib when the agent code doesn't use it.
        tmp_file.write(_MPL_CJK_BOOTSTRAP)
        tmp_file.write(code)
        tmp_file.close()
        code_path = tmp_file.name

        files_before = _collect_workspace_files(workspace)

        env = os.environ.copy()
        env["MPLCONFIGDIR"] = _ensure_mpl_config()

        result = subprocess.run(
            [sys.executable, code_path],
            capture_output=True, text=True,
            timeout=60,
            cwd=workspace,
            env=env,
        )

        # Clean up temp code file
        try:
            os.unlink(code_path)
        except OSError:
            pass

        output_parts = []
        if result.returncode == 0:
            stdout = result.stdout.strip()
            output_parts.append(stdout if stdout else "Code executed successfully (no output)")
        else:
            output_parts.append(f"Error:\n{result.stderr.strip()}")

        # Report new files with accessible URLs (recursive)
        files_after = _collect_workspace_files(workspace)
        new_files = files_after - files_before - {"_run.py"}
        if new_files:
            _url_pfx = _workspace_url_var.get(None)
            if _url_pfx:
                file_lines = []
                for relpath in sorted(new_files):
                    url = f"{_url_pfx}/{relpath}"
                    file_lines.append(f"  - {relpath}: {url}")
                output_parts.append(
                    "\nGenerated files (use URLs in reports with markdown ![desc](url)):\n"
                    + "\n".join(file_lines)
                )
            else:
                output_parts.append(f"\nGenerated files: {', '.join(sorted(new_files))}")

        return "\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (60s limit)"
    except Exception as e:
        return f"Execution error: {str(e)}"


@tool
def write_document(filename: str, content: str) -> str:
    """Write a document or report to a file.

    Args:
        filename: Name of the file to write (without path)
        content: Content to write to the file
    Returns:
        Success message with file path
    """
    # Sanitize filename
    safe_name = "".join(
        c for c in filename if c.isalnum() or c in "._- "
    ).strip()
    if not safe_name:
        safe_name = "document.md"

    # Write to workspace if available, otherwise fallback to ./outputs
    output_dir = _workspace_var.get(None) or "./outputs"
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, safe_name)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        msg = f"Document written successfully: {safe_name} ({len(content)} chars)"
        _url_pfx = _workspace_url_var.get(None)
        if _url_pfx:
            url = f"{_url_pfx}/{safe_name}"
            msg += f"\nURL: {url}"
        return msg
    except Exception as e:
        return f"Error writing document: {str(e)}"


@tool
def analyze_data(data: str, analysis_type: str = "summary") -> str:
    """Analyze data and produce insights.

    Args:
        data: Data to analyze (JSON, CSV, or plain text)
        analysis_type: Type of analysis: 'summary', 'statistics', 'trends'
    Returns:
        Analysis results as formatted text
    """
    try:
        # Try to parse as JSON
        try:
            parsed = json.loads(data)
            data_type = "JSON"
            items = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            # Treat as plain text
            data_type = "text"
            items = data.split('\n')

        lines = data.split('\n') if data_type == "text" else []

        result = f"Data Analysis Report\n{'='*40}\n"
        result += f"Data Type: {data_type}\n"
        result += f"Analysis Type: {analysis_type}\n\n"

        if analysis_type == "summary":
            result += f"Summary:\n"
            result += f"- Total records: {len(items)}\n"
            result += f"- Data size: {len(data)} characters\n"
            if data_type == "text":
                word_count = len(data.split())
                result += f"- Word count: {word_count}\n"
                result += f"- Line count: {len(lines)}\n"
        elif analysis_type == "statistics":
            # Try numeric analysis
            numbers = []
            for item in items:
                try:
                    if isinstance(item, (int, float)):
                        numbers.append(float(item))
                    elif isinstance(item, str):
                        numbers.append(float(item.strip()))
                except (ValueError, TypeError):
                    pass

            if numbers:
                result += f"Statistics:\n"
                result += f"- Count: {len(numbers)}\n"
                result += f"- Min: {min(numbers):.2f}\n"
                result += f"- Max: {max(numbers):.2f}\n"
                result += f"- Mean: {sum(numbers)/len(numbers):.2f}\n"
                sorted_nums = sorted(numbers)
                mid = len(sorted_nums) // 2
                median = sorted_nums[mid] if len(sorted_nums) % 2 else (
                    sorted_nums[mid-1] + sorted_nums[mid]
                ) / 2
                result += f"- Median: {median:.2f}\n"
            else:
                result += "No numeric data found for statistics.\n"
        elif analysis_type == "trends":
            result += "Trend Analysis:\n"
            result += f"- Data points: {len(items)}\n"
            result += "- Pattern: Further LLM analysis needed for trend identification\n"

        result += "\nConclusion: Analysis complete."
        return result
    except Exception as e:
        return f"Analysis error: {str(e)}"


@tool
def send_message(to_agent_id: str, message: str) -> str:
    """Send a message to another agent (async notification, no response expected).

    Args:
        to_agent_id: The ID of the target agent
        message: Message content to send
    Returns:
        Confirmation of message sent
    """
    # This is handled at the graph level via state
    return f"MESSAGE_SENT|{to_agent_id}|{message}"


@tool
def request_help(to_agent_id: str, question: str) -> str:
    """Ask another agent a question and wait for their response.
    Use this when you need expertise from a specialist agent.

    Args:
        to_agent_id: The ID of the agent to ask
        question: Your question
    Returns:
        The other agent's response
    """
    return f"HELP_REQUEST|{to_agent_id}|{question}"


# ── Helpers ────────────────────────────────────────────────────────────────

def _search_in_dirs(basename: str, dirs: list) -> Optional[str]:
    """Recursively search for *basename* inside allowed workspace dirs."""
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _subdirs, files in os.walk(d):
            if basename in files:
                return os.path.join(root, basename)
    return None


# ── New tools ──────────────────────────────────────────────────────────────

@tool
def read_file(filename: str) -> str:
    """Read a file from workspace or upstream agent workspaces.

    Searches: your workspace first, then upstream workspaces from agents
    whose subtasks you depend on (read_from). You can also provide an
    absolute path if given one from the scratchpad.

    Args:
        filename: Plain filename (e.g. 'report.md') or absolute path
    Returns:
        File contents (truncated to 500 KB)
    """
    # Collect all allowed directories once (used by both branches)
    readable_dirs = [_workspace_var.get(None) or "./outputs"] + list(
        _readable_workspaces_var.get([])
    )

    # Allow absolute paths (from scratchpad file references)
    if os.path.isabs(filename):
        # Security: resolve symlinks and normalise before comparison
        resolved = os.path.realpath(filename)
        allowed = any(
            resolved.startswith(os.path.realpath(d))
            for d in readable_dirs if d
        )
        if allowed:
            filepath = resolved
        else:
            # Fallback: LLM may have mangled the directory portion.
            # Try to find the file by basename in allowed directories.
            basename = os.path.basename(filename)
            filepath = _search_in_dirs(basename, readable_dirs)
            if not filepath:
                return f"Error: access denied — path is outside allowed workspaces."
    else:
        # Block path traversal for relative names
        if ".." in filename or "/" in filename or "\\" in filename:
            return "Error: path traversal not allowed. Provide a plain filename or absolute path."

        # Sanitise: keep alphanumeric, CJK, and common filename chars
        safe_name = "".join(
            c for c in filename
            if c.isalnum() or c in "._- " or ('\u4e00' <= c <= '\u9fff')
        ).strip()
        if not safe_name:
            return "Error: invalid filename."

        filepath = None
        search_dirs = readable_dirs

        for d in search_dirs:
            if not d:
                continue
            candidate = os.path.join(d, safe_name)
            if os.path.isfile(candidate):
                filepath = candidate
                break

        if not filepath:
            return f"Error: file '{filename}' not found in workspace or upstream workspaces."

    if not os.path.isfile(filepath):
        return f"Error: file '{filename}' not found."

    try:
        size = os.path.getsize(filepath)
        if size > 500 * 1024:
            return f"Error: file too large ({size} bytes, limit 500KB)."

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        basename = os.path.basename(filepath)
        return f"=== {basename} ({len(content)} chars) ===\n{content}"
    except Exception as e:
        return f"Error reading file: {str(e)}"


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_reserved
    except ValueError:
        # Not an IP literal — resolve it
        import socket as _socket
        try:
            info = _socket.getaddrinfo(hostname, None, _socket.AF_UNSPEC)
            for family, _, _, _, sockaddr in info:
                ip_str = sockaddr[0]
                addr = ipaddress.ip_address(ip_str)
                if addr.is_private or addr.is_loopback or addr.is_reserved:
                    return True
        except _socket.gaierror:
            pass
    return False


@tool
def http_request(
    url: str,
    method: str = "GET",
    body: str = "",
    headers: str = "",
) -> str:
    """Make an HTTP request to an external API.

    Args:
        url: The URL to request (must be https)
        method: HTTP method, GET or POST
        body: Request body (for POST). JSON string.
        headers: Request headers as JSON string, e.g. '{"Authorization":"Bearer ..."}'
    Returns:
        Response status and body (truncated to 10 KB)
    """
    import urllib.request
    import urllib.error

    method = method.upper()
    if method not in ("GET", "POST"):
        return "Error: only GET and POST methods are supported."

    # Parse and validate URL
    try:
        parsed = urlparse(url)
    except Exception:
        return "Error: invalid URL."

    if parsed.scheme not in ("http", "https"):
        return "Error: only http/https URLs are supported."

    hostname = parsed.hostname or ""
    if _is_private_ip(hostname):
        return "Error: requests to private/internal IPs are blocked."

    # Parse headers
    req_headers = {"User-Agent": "PixelAgentOS/1.0"}
    if headers:
        try:
            extra_h = json.loads(headers)
            if isinstance(extra_h, dict):
                req_headers.update(extra_h)
        except json.JSONDecodeError:
            return "Error: headers must be a valid JSON object."

    # Build request
    data_bytes = body.encode("utf-8") if body and method == "POST" else None
    if data_bytes and "Content-Type" not in req_headers:
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            resp_body = resp.read(10 * 1024).decode("utf-8", errors="replace")
            return f"HTTP {status}\n{resp_body}"
    except urllib.error.HTTPError as e:
        body_text = e.read(2048).decode("utf-8", errors="replace") if e.fp else ""
        return f"HTTP {e.code} {e.reason}\n{body_text}"
    except urllib.error.URLError as e:
        return f"Request failed: {str(e.reason)}"
    except Exception as e:
        return f"Request error: {str(e)}"


@tool
def summarize_text(text: str, max_words: int = 150) -> str:
    """Pre-process a long text by extracting key sentences.

    This is a heuristic extractor — the LLM should refine the output.

    Args:
        text: The text to summarize
        max_words: Approximate max words in the summary (default 150)
    Returns:
        Extracted key sentences from the text
    """
    if not text.strip():
        return "Error: empty text provided."

    sentences = re.split(r'(?<=[.!?。！？])\s+', text.strip())
    if len(sentences) <= 3:
        return text.strip()

    # Heuristic: first 2 sentences + last sentence + longest middle sentences
    selected = []
    selected.extend(sentences[:2])

    middle = sentences[2:-1]
    middle_sorted = sorted(middle, key=len, reverse=True)
    selected.extend(middle_sorted[:3])

    selected.append(sentences[-1])

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in selected:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    result = " ".join(unique)

    # Trim to max_words
    words = result.split()
    if len(words) > max_words:
        result = " ".join(words[:max_words]) + "..."

    return f"[Summary extract — {len(words)} words]\n{result}"


@tool
def translate_text(
    text: str,
    target_language: str,
    source_language: str = "auto",
) -> str:
    """Mark text for translation. The LLM should produce the actual translation.

    Args:
        text: Text to translate
        target_language: Target language (e.g. 'en', 'zh', 'es', 'fr')
        source_language: Source language or 'auto' for auto-detect
    Returns:
        A translation request marker for the LLM to process
    """
    if not text.strip():
        return "Error: empty text provided."

    return (
        f"TRANSLATE_REQUEST|{source_language}|{target_language}|{text}\n\n"
        f"Please translate the above text from {source_language} to {target_language}. "
        f"Provide only the translated text in your response."
    )


@tool
def transform_data(
    data: str,
    input_format: str = "json",
    output_format: str = "csv",
) -> str:
    """Convert data between JSON, CSV, and Markdown table formats.

    Args:
        data: The data string to convert
        input_format: Input format: 'json', 'csv', or 'markdown_table'
        output_format: Output format: 'json', 'csv', or 'markdown_table'
    Returns:
        The converted data string
    """
    valid_formats = ("json", "csv", "markdown_table")
    if input_format not in valid_formats:
        return f"Error: input_format must be one of {valid_formats}"
    if output_format not in valid_formats:
        return f"Error: output_format must be one of {valid_formats}"
    if input_format == output_format:
        return data

    # Parse input
    rows: List[dict] = []
    try:
        if input_format == "json":
            parsed = json.loads(data)
            if isinstance(parsed, list):
                rows = [r if isinstance(r, dict) else {"value": r} for r in parsed]
            elif isinstance(parsed, dict):
                rows = [parsed]
            else:
                return "Error: JSON must be an array or object."

        elif input_format == "csv":
            reader = csv.DictReader(io.StringIO(data))
            rows = list(reader)

        elif input_format == "markdown_table":
            lines = [ln.strip() for ln in data.strip().split("\n") if ln.strip()]
            if len(lines) < 2:
                return "Error: markdown table needs at least header + separator rows."
            headers = [h.strip() for h in lines[0].strip("|").split("|")]
            for line in lines[2:]:  # skip separator row
                vals = [v.strip() for v in line.strip("|").split("|")]
                row = dict(zip(headers, vals))
                rows.append(row)
    except Exception as e:
        return f"Error parsing {input_format}: {str(e)}"

    if not rows:
        return "Error: no data rows found."

    # Produce output
    try:
        if output_format == "json":
            return json.dumps(rows, ensure_ascii=False, indent=2)

        elif output_format == "csv":
            keys = list(rows[0].keys())
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
            return buf.getvalue()

        elif output_format == "markdown_table":
            keys = list(rows[0].keys())
            header = "| " + " | ".join(keys) + " |"
            sep = "| " + " | ".join(["---"] * len(keys)) + " |"
            body_lines = []
            for row in rows:
                vals = [str(row.get(k, "")) for k in keys]
                body_lines.append("| " + " | ".join(vals) + " |")
            return "\n".join([header, sep] + body_lines)

    except Exception as e:
        return f"Error producing {output_format}: {str(e)}"

    return "Error: unexpected conversion failure."


@tool
def create_plan(
    title: str,
    phases: str,
    timeline: str = "",
    risks: str = "",
) -> str:
    """Create a structured project plan in Markdown format.

    Args:
        title: Plan title
        phases: JSON array of phases, each with 'name', 'tasks' (list), 'duration'
        timeline: Optional overall timeline description
        risks: Optional JSON array of risk strings
    Returns:
        Formatted Markdown project plan
    """
    # Parse phases
    try:
        phase_list = json.loads(phases)
        if not isinstance(phase_list, list):
            return "Error: phases must be a JSON array."
    except json.JSONDecodeError as e:
        return f"Error parsing phases JSON: {str(e)}"

    # Parse risks
    risk_list: List[str] = []
    if risks:
        try:
            risk_list = json.loads(risks)
            if not isinstance(risk_list, list):
                risk_list = [str(risk_list)]
        except json.JSONDecodeError:
            risk_list = [risks]

    # Build Markdown
    lines = [f"# {title}", ""]
    if timeline:
        lines.append(f"**Timeline**: {timeline}")
        lines.append("")

    lines.append("## Phases")
    lines.append("")
    for i, phase in enumerate(phase_list, 1):
        name = phase.get("name", f"Phase {i}")
        duration = phase.get("duration", "TBD")
        tasks = phase.get("tasks", [])
        lines.append(f"### Phase {i}: {name}")
        lines.append(f"**Duration**: {duration}")
        lines.append("")
        if tasks:
            for task in tasks:
                lines.append(f"- [ ] {task}")
            lines.append("")

    if risk_list:
        lines.append("## Risks")
        lines.append("")
        for risk in risk_list:
            lines.append(f"- ⚠️ {risk}")
        lines.append("")

    return "\n".join(lines)


# ── Utility tools ─────────────────────────────────────────────────────────


class _HTMLTextExtractor(html.parser.HTMLParser):
    """Minimal HTML-to-text extractor using stdlib."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._pieces.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        # Collapse whitespace but keep newlines
        lines = [" ".join(ln.split()) for ln in raw.split("\n")]
        return "\n".join(ln for ln in lines if ln).strip()


@tool
def scrape_webpage(url: str) -> str:
    """Fetch a webpage and return its text content (HTML stripped).

    Args:
        url: The URL to fetch (must be http/https)
    Returns:
        Plain-text content of the page (truncated to 15 KB)
    """
    import urllib.request
    import urllib.error

    try:
        parsed = urlparse(url)
    except Exception:
        return "Error: invalid URL."
    if parsed.scheme not in ("http", "https"):
        return "Error: only http/https URLs are supported."
    hostname = parsed.hostname or ""
    if _is_private_ip(hostname):
        return "Error: requests to private/internal IPs are blocked."

    req = urllib.request.Request(url, headers={"User-Agent": "PixelAgentOS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(200 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return f"Fetch error: {str(e)}"

    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(raw)
    except Exception:
        pass
    text = extractor.get_text()

    if len(text) > 15000:
        text = text[:15000] + "\n...(truncated)"
    return text if text else "No text content extracted."


@tool
def diff_texts(text_a: str, text_b: str, label_a: str = "before", label_b: str = "after") -> str:
    """Show a unified diff between two texts.

    Args:
        text_a: The original text
        text_b: The modified text
        label_a: Label for original (default 'before')
        label_b: Label for modified (default 'after')
    Returns:
        Unified diff output
    """
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    diff = difflib.unified_diff(lines_a, lines_b, fromfile=label_a, tofile=label_b, lineterm="")
    result = "\n".join(diff)
    return result if result else "No differences found."


@tool
def zip_files(filenames: str, archive_name: str = "archive.zip") -> str:
    """Create a ZIP archive from workspace files.

    Args:
        filenames: Comma-separated list of filenames to include
        archive_name: Name of the output ZIP file (default 'archive.zip')
    Returns:
        Success message with file path
    """
    workspace = _workspace_var.get(None) or "./outputs"
    names = [n.strip() for n in filenames.split(",") if n.strip()]
    if not names:
        return "Error: no filenames provided."

    safe_archive = "".join(c for c in archive_name if c.isalnum() or c in "._- ").strip()
    if not safe_archive.endswith(".zip"):
        safe_archive += ".zip"

    archive_path = os.path.join(workspace, safe_archive)
    added = []
    missing = []

    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                if ".." in name or "/" in name or "\\" in name:
                    missing.append(f"{name} (path traversal blocked)")
                    continue
                fpath = os.path.join(workspace, name)
                if not os.path.isfile(fpath):
                    missing.append(name)
                    continue
                zf.write(fpath, name)
                added.append(name)
    except Exception as e:
        return f"Error creating archive: {str(e)}"

    parts = [f"Created {safe_archive} with {len(added)} files: {', '.join(added)}"]
    if missing:
        parts.append(f"Missing/skipped: {', '.join(missing)}")
    _url_pfx = _workspace_url_var.get(None)
    if _url_pfx:
        parts.append(f"URL: {_url_pfx}/{safe_archive}")
    return "\n".join(parts)


@tool
def regex_extract(text: str, pattern: str, group: int = 0) -> str:
    """Extract all matches of a regex pattern from text.

    Args:
        text: The text to search
        pattern: Regular expression pattern
        group: Capture group number to return (0 = full match)
    Returns:
        All matches, one per line
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern — {str(e)}"

    matches = []
    for m in compiled.finditer(text):
        try:
            matches.append(m.group(group))
        except IndexError:
            matches.append(m.group(0))

    if not matches:
        return "No matches found."
    return f"Found {len(matches)} match(es):\n" + "\n".join(matches)


class _SafeMathEvaluator(ast.NodeVisitor):
    """Evaluate math expressions safely using AST."""

    _ALLOWED_NAMES = {
        "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "len": len,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "ceil": math.ceil, "floor": math.floor, "pow": math.pow,
        "True": True, "False": False,
    }

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")

    def visit_Name(self, node):
        if node.id in self._ALLOWED_NAMES:
            return self._ALLOWED_NAMES[node.id]
        raise ValueError(f"Unknown name: {node.id}")

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        ops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a ** b,
        }
        op_fn = ops.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_fn(left, right)

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            cmp_ops = {
                ast.Lt: lambda a, b: a < b,
                ast.LtE: lambda a, b: a <= b,
                ast.Gt: lambda a, b: a > b,
                ast.GtE: lambda a, b: a >= b,
                ast.Eq: lambda a, b: a == b,
                ast.NotEq: lambda a, b: a != b,
            }
            cmp_fn = cmp_ops.get(type(op))
            if cmp_fn is None:
                raise ValueError(f"Unsupported comparator: {type(op).__name__}")
            if not cmp_fn(left, right):
                return False
            left = right
        return True

    def visit_Call(self, node):
        func = self.visit(node.func)
        args = [self.visit(a) for a in node.args]
        if not callable(func):
            raise ValueError(f"Not callable: {func!r}")
        return func(*args)

    def visit_List(self, node):
        return [self.visit(el) for el in node.elts]

    def visit_Tuple(self, node):
        return tuple(self.visit(el) for el in node.elts)

    def generic_visit(self, node):
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


@tool
def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression.

    Supports: +, -, *, /, //, %, **, comparisons, sqrt, log, sin, cos, tan,
    ceil, floor, abs, round, min, max, pi, e.

    Args:
        expression: Mathematical expression to evaluate (e.g. 'sqrt(144) + 2 * pi')
    Returns:
        The result of the expression
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _SafeMathEvaluator().visit(tree)
        return f"{expression.strip()} = {result}"
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
        return f"Error: {str(e)}"
    except SyntaxError:
        return f"Error: invalid expression syntax."


@tool
def json_path_query(data: str, path: str) -> str:
    """Query a JSON document using dot-notation path.

    Supports dot notation and array indexing: 'users[0].name', 'config.db.host'

    Args:
        data: JSON string to query
        path: Dot-notation path (e.g. 'results[0].title', 'config.database.host')
    Returns:
        The value at the given path
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {str(e)}"

    # Parse path: split on dots, handle array indices like 'items[0]'
    tokens = []
    for part in path.split("."):
        # Handle array indexing: 'items[0]' -> 'items', 0
        idx_match = re.match(r'^(\w+)\[(\d+)\]$', part)
        if idx_match:
            tokens.append(idx_match.group(1))
            tokens.append(int(idx_match.group(2)))
        else:
            tokens.append(part)

    current = obj
    for token in tokens:
        try:
            if isinstance(token, int):
                current = current[token]
            elif isinstance(current, dict):
                current = current[token]
            elif isinstance(current, list) and token.isdigit():
                current = current[int(token)]
            else:
                return f"Error: cannot access '{token}' on {type(current).__name__}"
        except (KeyError, IndexError, TypeError) as e:
            return f"Error: path '{path}' failed at '{token}' — {str(e)}"

    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False, indent=2)
    return str(current)


@tool
def render_template(template: str, variables: str) -> str:
    """Render a template string with variable substitution.

    Uses $variable or ${variable} syntax.

    Args:
        template: Template string with $variable placeholders
        variables: JSON object of variable name-value pairs
    Returns:
        Rendered text with variables substituted
    """
    try:
        var_dict = json.loads(variables)
        if not isinstance(var_dict, dict):
            return "Error: variables must be a JSON object."
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON variables — {str(e)}"

    try:
        tmpl = string.Template(template)
        result = tmpl.safe_substitute(var_dict)
        return result
    except Exception as e:
        return f"Error rendering template: {str(e)}"


@tool
def hash_and_encode(text: str, operation: str = "md5") -> str:
    """Hash or encode/decode text.

    Args:
        text: Input text to process
        operation: One of 'md5', 'sha256', 'sha1', 'base64_encode',
                   'base64_decode', 'url_encode', 'url_decode'
    Returns:
        The hashed or encoded/decoded result
    """
    import urllib.parse as _up

    op = operation.lower().strip()
    try:
        if op == "md5":
            return hashlib.md5(text.encode()).hexdigest()
        elif op == "sha256":
            return hashlib.sha256(text.encode()).hexdigest()
        elif op == "sha1":
            return hashlib.sha1(text.encode()).hexdigest()
        elif op == "base64_encode":
            return base64.b64encode(text.encode()).decode()
        elif op == "base64_decode":
            return base64.b64decode(text.encode()).decode("utf-8", errors="replace")
        elif op == "url_encode":
            return _up.quote(text, safe="")
        elif op == "url_decode":
            return _up.unquote(text)
        else:
            return (
                f"Error: unknown operation '{op}'. "
                "Supported: md5, sha256, sha1, base64_encode, base64_decode, "
                "url_encode, url_decode"
            )
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def datetime_calculate(operation: str, date: str = "", offset: str = "") -> str:
    """Perform date/time calculations.

    Args:
        operation: One of 'now', 'parse', 'add', 'diff', 'format', 'weekday'
        date: Date string (ISO format: '2024-01-15' or '2024-01-15T10:30:00')
              For 'diff', use two dates separated by ' | '
        offset: For 'add': offset like '7d', '3h', '30m', '2w'
                For 'format': strftime format string
    Returns:
        Result of the date/time operation
    """
    op = operation.lower().strip()

    def _parse_dt(s: str) -> datetime:
        s = s.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: '{s}'")

    def _parse_offset(o: str) -> timedelta:
        o = o.strip().lower()
        m = re.match(r'^(-?\d+)\s*(d|h|m|s|w)$', o)
        if not m:
            raise ValueError(f"Invalid offset: '{o}'. Use format like '7d', '3h', '30m', '2w'")
        val = int(m.group(1))
        unit = m.group(2)
        return {"d": timedelta(days=val), "h": timedelta(hours=val),
                "m": timedelta(minutes=val), "s": timedelta(seconds=val),
                "w": timedelta(weeks=val)}[unit]

    try:
        if op == "now":
            now = datetime.now()
            return f"{now.isoformat()} ({now.strftime('%A')})"

        elif op == "parse":
            dt = _parse_dt(date)
            return f"{dt.isoformat()} ({dt.strftime('%A')})"

        elif op == "add":
            dt = _parse_dt(date) if date else datetime.now()
            delta = _parse_offset(offset)
            result = dt + delta
            return f"{dt.isoformat()} + {offset} = {result.isoformat()} ({result.strftime('%A')})"

        elif op == "diff":
            if "|" not in date:
                return "Error: for 'diff', provide two dates separated by ' | '"
            parts = date.split("|", 1)
            dt_a = _parse_dt(parts[0])
            dt_b = _parse_dt(parts[1])
            delta = dt_b - dt_a
            days = delta.days
            hours = delta.seconds // 3600
            mins = (delta.seconds % 3600) // 60
            return f"Difference: {days} days, {hours} hours, {mins} minutes (total: {delta.total_seconds():.0f}s)"

        elif op == "format":
            dt = _parse_dt(date)
            fmt = offset if offset else "%Y-%m-%d %H:%M:%S"
            return dt.strftime(fmt)

        elif op == "weekday":
            dt = _parse_dt(date) if date else datetime.now()
            return f"{dt.isoformat()} is a {dt.strftime('%A')}"

        else:
            return "Error: unknown operation. Use: now, parse, add, diff, format, weekday"
    except (ValueError, OverflowError) as e:
        return f"Error: {str(e)}"


@tool
def list_workspace_files(pattern: str = "") -> str:
    """List files in the workspace directory (recursive, includes subdirectories).

    Args:
        pattern: Optional glob-like filter (e.g. '*.csv', '*.py'). Empty = all files.
    Returns:
        List of files with sizes and URLs
    """
    workspace = _workspace_var.get(None) or "./outputs"
    if not os.path.isdir(workspace):
        return "Workspace directory is empty or not found."

    try:
        _url_pfx = _workspace_url_var.get(None)
        entries = []
        for dirpath, _dirnames, filenames in os.walk(workspace):
            for name in sorted(filenames):
                if name.startswith("_"):
                    continue
                fpath = os.path.join(dirpath, name)
                relpath = os.path.relpath(fpath, workspace)
                # Simple pattern matching against relative path
                if pattern:
                    pat = pattern.strip().replace("*", "")
                    if pat and not relpath.endswith(pat) and pat not in relpath:
                        continue
                size = os.path.getsize(fpath)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                url = f"{_url_pfx}/{relpath}" if _url_pfx else relpath
                entries.append(f"  {relpath}  ({size_str})  {url}")

        if not entries:
            return "No files found" + (f" matching '{pattern}'" if pattern else "") + "."
        return f"Workspace files ({len(entries)}):\n" + "\n".join(entries)
    except Exception as e:
        return f"Error listing files: {str(e)}"


@tool
def validate_data(data: str, rules: str) -> str:
    """Validate data against a set of rules.

    Args:
        data: JSON string to validate
        rules: JSON object with validation rules. Keys are field paths,
               values are rule strings: 'required', 'type:string', 'type:number',
               'type:array', 'min:N', 'max:N', 'minlen:N', 'maxlen:N', 'regex:PATTERN'
    Returns:
        Validation result: PASS or list of failures
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON data — {str(e)}"
    try:
        rule_dict = json.loads(rules)
        if not isinstance(rule_dict, dict):
            return "Error: rules must be a JSON object."
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON rules — {str(e)}"

    errors = []
    for field, rule_str in rule_dict.items():
        # Get field value via dot path
        val = obj
        found = True
        for key in field.split("."):
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                val = None
                found = False
                break

        rule_parts = [r.strip() for r in str(rule_str).split(",")]
        for rule in rule_parts:
            if rule == "required":
                if not found or val is None:
                    errors.append(f"{field}: required but missing")
            elif rule.startswith("type:"):
                expected = rule.split(":", 1)[1]
                type_map = {"string": str, "number": (int, float), "array": list,
                            "object": dict, "boolean": bool}
                if found and val is not None:
                    expected_type = type_map.get(expected)
                    if expected_type and not isinstance(val, expected_type):
                        errors.append(f"{field}: expected {expected}, got {type(val).__name__}")
            elif rule.startswith("min:"):
                limit = float(rule.split(":", 1)[1])
                if found and isinstance(val, (int, float)) and val < limit:
                    errors.append(f"{field}: value {val} < min {limit}")
            elif rule.startswith("max:"):
                limit = float(rule.split(":", 1)[1])
                if found and isinstance(val, (int, float)) and val > limit:
                    errors.append(f"{field}: value {val} > max {limit}")
            elif rule.startswith("minlen:"):
                limit = int(rule.split(":", 1)[1])
                if found and hasattr(val, "__len__") and len(val) < limit:
                    errors.append(f"{field}: length {len(val)} < minlen {limit}")
            elif rule.startswith("maxlen:"):
                limit = int(rule.split(":", 1)[1])
                if found and hasattr(val, "__len__") and len(val) > limit:
                    errors.append(f"{field}: length {len(val)} > maxlen {limit}")
            elif rule.startswith("regex:"):
                pat = rule.split(":", 1)[1]
                if found and isinstance(val, str) and not re.match(pat, val):
                    errors.append(f"{field}: does not match pattern '{pat}'")

    if not errors:
        return "PASS: all validation rules satisfied."
    return f"FAIL: {len(errors)} error(s):\n" + "\n".join(f"  - {e}" for e in errors)


@tool
def compare_options(options: str, criteria: str) -> str:
    """Generate a structured comparison table for multiple options.

    Args:
        options: JSON array of option objects, each with 'name' and other properties
        criteria: Comma-separated list of criteria/properties to compare
    Returns:
        Markdown comparison table
    """
    try:
        opt_list = json.loads(options)
        if not isinstance(opt_list, list) or len(opt_list) < 2:
            return "Error: need at least 2 options (JSON array)."
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON options — {str(e)}"

    crit_list = [c.strip() for c in criteria.split(",") if c.strip()]
    if not crit_list:
        # Auto-detect criteria from option keys
        all_keys = set()
        for opt in opt_list:
            if isinstance(opt, dict):
                all_keys.update(opt.keys())
        all_keys.discard("name")
        crit_list = sorted(all_keys) if all_keys else ["value"]

    # Build table
    headers = ["Criteria"] + [opt.get("name", f"Option {i+1}") if isinstance(opt, dict) else str(opt)
                               for i, opt in enumerate(opt_list)]
    sep = ["---"] * len(headers)
    rows = []
    for crit in crit_list:
        row = [crit]
        for opt in opt_list:
            if isinstance(opt, dict):
                row.append(str(opt.get(crit, "—")))
            else:
                row.append("—")
        rows.append(row)

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ── Skill discovery tool ──────────────────────────────────────────────────


@tool
def read_skill(skill_name: str) -> str:
    """Load a skill's full instructions — commands, scripts, and workflows.

    Call this when you need detailed instructions for a specific skill.
    NOTE: If the planning phase already pre-loaded a skill's instructions
    in the context above, you do NOT need to call this again for that skill.

    Only call read_skill when:
    - You installed a new skill and need its instructions
    - A skill was NOT pre-loaded by the planning phase
    - You need to refresh/re-read a skill's instructions

    Args:
        skill_name: The skill name (e.g., 'image-processing', 'web-asset-generator')
    """
    from agents.skill_loader import (
        _resolve_skill_id, load_merged_skills, _load_all_skills,
        resolve_skill_content,
    )

    resolved = _resolve_skill_id(skill_name)

    # Use merged skills if agent context is available, otherwise shared only
    agent_id = _agent_id_var.get(None)
    if agent_id:
        skills = load_merged_skills(agent_id)
    else:
        skills = _load_all_skills()

    skill = skills.get(resolved)
    if not skill:
        available = ", ".join(sorted(skills.keys()))
        return f"Unknown skill: '{skill_name}'. Available: {available}"

    # Use canonical content resolver: regex path fix + explicit script listing
    content = resolve_skill_content(skill)

    return f"# {skill.name}\n{skill.description}\n\n{content}"


# ── Shell / Skill Ecosystem tools ──────────────────────────────────────────

# Command blacklist for shell_execute safety
_SHELL_BLACKLIST = [
    "rm -rf /", "rm -rf /*", "sudo ", "mkfs", "dd if=",
    ":(){ :|:& };:", "fork()", "> /dev/sd",
    "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    "curl|sh", "curl|bash", "wget|sh", "wget|bash",
]


@tool
def shell_execute(command: str, timeout_seconds: int = 30) -> str:
    """Execute a bash command in your workspace directory.

    Use this for installing packages, running scripts, processing files,
    or any shell operation needed for your task.

    Args:
        command: The bash command to execute
        timeout_seconds: Max execution time (default 30, max 60)
    Returns:
        Command output (stdout + stderr)
    """
    # Safety: command blacklist
    cmd_lower = command.lower().strip()
    for blocked in _SHELL_BLACKLIST:
        if blocked in cmd_lower:
            return f"Error: command blocked for safety — contains '{blocked}'"

    timeout_seconds = max(1, min(timeout_seconds, 60))

    workspace = _workspace_var.get(None)
    if not workspace:
        return "Error: no workspace available. This tool requires an active task context."
    os.makedirs(workspace, exist_ok=True)

    # Create .tmp inside workspace for temp files
    tmp_dir = os.path.join(workspace, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = workspace
    env["TMPDIR"] = tmp_dir

    # Prepend venv bin to PATH so `python` resolves to the venv interpreter
    # (which has Pillow, pilmoji, etc. installed).
    venv_bin = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".venv", "bin")
    if os.path.isdir(venv_bin):
        env["PATH"] = venv_bin + ":" + env.get("PATH", "")
        env["VIRTUAL_ENV"] = os.path.dirname(venv_bin)

    # TODO: future Docker sandbox — run inside container instead
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True,
            timeout=timeout_seconds,
            cwd=workspace,
            env=env,
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        if result.returncode != 0:
            parts.append(f"Exit code: {result.returncode}")
        return "\n".join(parts) if parts else "Command completed (no output)."
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout_seconds}s."
    except Exception as e:
        return f"Error executing command: {str(e)}"


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def _translate_query_to_english(query: str) -> str:
    """Translate non-English skill search query to English keywords.

    Internal helper — NOT an agent-facing tool.
    The skills registry only supports English queries. If the query
    contains non-ASCII characters, use a cheap LLM call to translate.
    """
    if query.isascii():
        return query

    try:
        from litellm import completion
        resp = completion(
            model="deepseek/deepseek-chat",
            messages=[{
                "role": "user",
                "content": (
                    "Translate this skill search query to concise English keywords "
                    "(reply ONLY with the English keywords, nothing else):\n"
                    f"{query}"
                ),
            }],
            max_tokens=50,
            temperature=0,
        )
        translated = resp.choices[0].message.content.strip().strip('"\'')
        if translated:
            logger.info(f"[find_skill] Translated query: '{query}' → '{translated}'")
            return translated
    except Exception as e:
        logger.warning(f"[find_skill] Translation failed, using original query: {e}")

    return query


@tool
def find_skill(query: str) -> str:
    """Search the open-source skill ecosystem for skills matching a query.

    This searches the npx skills registry (2000+ community skills).
    After finding a skill, use install_skill(package=...) to install it.

    IMPORTANT: The registry only supports English. If your query is in
    another language it will be auto-translated.

    Args:
        query: Search query in English (e.g., 'data visualization', 'web scraping')
    Returns:
        List of matching skills with install instructions
    """
    # Translate non-English queries to English keywords
    search_query = _translate_query_to_english(query)

    try:
        result = subprocess.run(
            ["npx", "-y", "skills", "find", search_query],
            capture_output=True, text=True,
            timeout=30,
        )
        raw = _strip_ansi(result.stdout + result.stderr).strip()
        translated_hint = f" (searched as '{search_query}')" if search_query != query else ""
        if not raw:
            return f"No skills found for '{query}'{translated_hint}. Try a different search term."

        # Parse output lines — format: "owner/repo@skill  N installs"
        # Filter out ASCII art banners and decorative lines
        skills_found = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Skip ASCII art, banner lines, header text
            if any(ch in line for ch in "█╗╔╝═║╚"):
                continue
            if line.startswith("Install with") or line.startswith("Searching") or line.startswith("Found"):
                continue
            if line.startswith("└"):
                continue  # tree-style URL lines
            skills_found.append(line)

        if not skills_found:
            return f"No skills found for '{query}'{translated_hint}."

        output = f"Found skills for '{query}'{translated_hint}:\n"
        for s in skills_found[:10]:  # limit to 10 results
            output += f"  - {s}\n"
        output += (
            "\nTo install a skill, use: install_skill(package=\"owner/repo@skill\")\n"
            "After installing, use read_skill(name) to learn how to use it."
        )
        return output
    except FileNotFoundError:
        return "Error: 'npx' not found. Node.js must be installed."
    except subprocess.TimeoutExpired:
        return "Error: skill search timed out after 30s."
    except Exception as e:
        return f"Error searching skills: {str(e)}"


@tool
def install_skill(package: str) -> str:
    """Install a skill from the open-source ecosystem to your personal library.

    After installing, use read_skill(name) to get usage instructions.

    Args:
        package: Skill package identifier (e.g., 'owner/repo@skill-name')
    Returns:
        Installation result
    """
    agent_id = _agent_id_var.get(None)
    workspace = _workspace_var.get(None)
    if not agent_id or not workspace:
        return "Error: no agent/workspace context. This tool requires an active task."

    # Install into agent-level _skills/ (shared across subtasks of same agent).
    # Workspace is {task}/{agent}/{subtask}, so go up to agent level.
    agent_level_dir = os.path.dirname(workspace)
    skills_home = os.path.join(agent_level_dir, "_skills")
    os.makedirs(skills_home, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = skills_home

    try:
        result = subprocess.run(
            ["npx", "-y", "skills", "add", package, "-y"],
            capture_output=True, text=True,
            timeout=60,
            cwd=skills_home,
            env=env,
        )
        raw = _strip_ansi(result.stdout + result.stderr).strip()

        if result.returncode != 0:
            return f"Installation failed:\n{raw}"

        # Extract skill name from package (last segment after @)
        skill_id = package.split("@")[-1] if "@" in package else package.split("/")[-1]

        # Persist to agent_homes so this skill survives across tasks.
        # Copy installed skill to agent_homes/{id}/skills/ for reuse.
        try:
            from agents.agent_home import get_agent_skills_dir, record_installed_skill
            persistent_skills_dir = get_agent_skills_dir(agent_id)

            # Find the installed skill directory (check common locations)
            installed_skill_dir = None
            for search_root in [
                os.path.join(skills_home, "skills", skill_id),
                os.path.join(skills_home, ".agents", "skills", skill_id),
            ]:
                if os.path.isdir(search_root):
                    installed_skill_dir = search_root
                    break

            if installed_skill_dir:
                target_dir = os.path.join(persistent_skills_dir, skill_id)
                if not os.path.isdir(target_dir):
                    import shutil as _shutil
                    _shutil.copytree(installed_skill_dir, target_dir)
                    logger.info(
                        f"[Skills] Persisted '{skill_id}' to agent_homes "
                        f"for agent {agent_id[:8]}"
                    )
                record_installed_skill(agent_id, package, skill_id)
        except Exception as persist_err:
            logger.warning(
                f"[Skills] Failed to persist '{skill_id}' to agent_homes: "
                f"{persist_err}"
            )

        # Clean up platform scaffolding dirs created by npx skills add.
        # It creates .crush/, .junie/, .windsurf/ etc. for every AI platform.
        # We only need .agents/skills/ — remove the rest.
        _KEEP_DIRS = {".agents", ".npm", "skills", "memory", ".installed_skills.json"}
        for entry in os.listdir(skills_home):
            if entry.startswith(".") and entry not in _KEEP_DIRS:
                dirpath = os.path.join(skills_home, entry)
                if os.path.isdir(dirpath):
                    # Only remove if it just contains a skills/ subdir (scaffolding)
                    children = os.listdir(dirpath)
                    if children == ["skills"] or children == []:
                        import shutil
                        shutil.rmtree(dirpath, ignore_errors=True)

        return (
            f"Skill '{skill_id}' installed successfully.\n"
            f"Use read_skill('{skill_id}') to learn how to use it.\n"
            f"Output: {raw[:500]}"
        )
    except FileNotFoundError:
        return "Error: 'npx' not found. Node.js must be installed."
    except subprocess.TimeoutExpired:
        return "Error: installation timed out after 60s."
    except Exception as e:
        return f"Error installing skill: {str(e)}"


# ── Tool registry ─────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "web_search": web_search,
    "code_execute": code_execute,
    "write_document": write_document,
    "analyze_data": analyze_data,
    "send_message": send_message,
    "request_help": request_help,
    "read_file": read_file,
    "http_request": http_request,
    "summarize_text": summarize_text,
    "translate_text": translate_text,
    "transform_data": transform_data,
    "create_plan": create_plan,
    "scrape_webpage": scrape_webpage,
    "diff_texts": diff_texts,
    "zip_files": zip_files,
    "regex_extract": regex_extract,
    "calculate": calculate,
    "json_path_query": json_path_query,
    "render_template": render_template,
    "hash_and_encode": hash_and_encode,
    "datetime_calculate": datetime_calculate,
    "list_workspace_files": list_workspace_files,
    "validate_data": validate_data,
    "compare_options": compare_options,
    "read_skill": read_skill,
    "shell_execute": shell_execute,
    "find_skill": find_skill,
    "install_skill": install_skill,
}


# PM Agent tool IDs — supervisor-level tools for all PM phases
PM_TOOL_IDS = [
    "web_search",
    "scrape_webpage",
    "code_execute",
    "read_file",
    "list_workspace_files",
    "write_document",
]


def get_pm_tools(extra_tools: Optional[list] = None) -> list:
    """Get tools available to PM Agent."""
    tool_list = [TOOL_REGISTRY[tid] for tid in PM_TOOL_IDS if tid in TOOL_REGISTRY]
    if extra_tools:
        seen = {t.name for t in tool_list}
        for t in extra_tools:
            if t.name not in seen:
                tool_list.append(t)
    tool_names = [t.name for t in tool_list]
    logger.info(f"[Tools] PM tools mounted: {tool_names} ({len(tool_names)} total)")
    return tool_list


def get_tools_for_agent(
    skills: List[str], role: str, extra_tools: Optional[list] = None
) -> list:
    """Get tools for an agent: ALL registered tools + extras.

    Standard approach: skill = knowledge, tool = capability.
    All agents get all tools; skills guide *when* to use them.
    """
    tool_set: set = set()
    tool_list: list = []

    # All registered tools available to all agents
    for tid, t in TOOL_REGISTRY.items():
        if tid not in tool_set:
            tool_set.add(tid)
            tool_list.append(t)

    # Extra tools (scratchpad, memory, etc.)
    extra_names = []
    if extra_tools:
        for t in extra_tools:
            if t.name not in tool_set:
                tool_set.add(t.name)
                tool_list.append(t)
                extra_names.append(t.name)

    logger.info(
        f"[Tools] Agent tools mounted: role={role}, skills={skills}, "
        f"registry={len(TOOL_REGISTRY)}, extras={extra_names}, "
        f"total={len(tool_list)}"
    )
    return tool_list
