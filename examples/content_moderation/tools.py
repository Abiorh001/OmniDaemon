import json
import os
import re
import shutil
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from omnicoreagent import ToolRegistry

from state import (
    STATE_DIR,
    STATE_TRACKER,
    load_state,
    save_state,
    load_directory_snapshot,
    save_directory_snapshot,
)

STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_DB_PATH = STATE_DIR / "moderation.db"

tool_registry = ToolRegistry()

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d{3}[\s-]?){2}\d{4}\b")
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

HATE_SPEECH_TERMS = {
    "racial slur",
    "derogatory",
    "hate",
    "racist",
    "bigot",
    "terrorist",
    "genocide",
}

SUSPICIOUS_DOMAINS = {
    "bit.ly",
    "tinyurl.com",
    "ow.ly",
}


def _ensure_db() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@tool_registry.register_tool("scan_directory_for_new_content")
def scan_directory_for_new_content(directory: str) -> str:
    """Scan directory for new or modified text content files."""
    directory_path = Path(directory).expanduser().resolve()
    if not directory_path.exists():
        return f"Directory not found: {directory_path}"

    state = load_state()
    directory_state = state.get(str(directory_path), {})

    current_snapshot: Dict[str, Dict[str, str]] = {}
    new_files = []
    modified_files = []

    extensions = {
        ".txt",
        ".md",
        ".json",
        ".csv",
        ".log",
        ".py",
        ".js",
        ".html",
        ".xml",
    }

    for root, _, files in os.walk(directory_path):
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() not in extensions:
                continue

            try:
                data = path.read_bytes()
            except OSError:
                continue

            file_hash = hashlib.md5(data).hexdigest()
            file_info = {
                "hash": file_hash,
                "size": str(path.stat().st_size),
            }

            current_snapshot[str(path)] = file_info

            previous = directory_state.get(str(path))
            if previous is None:
                new_files.append(path)
            elif previous["hash"] != file_hash:
                modified_files.append(path)

    state[str(directory_path)] = current_snapshot
    save_state(state)

    if not new_files and not modified_files:
        return f"No new or modified content in {directory_path}"

    lines = [f"Content scan results for {directory_path}:"]

    if new_files:
        lines.append(f"\nNEW FILES ({len(new_files)}):")
        for path in new_files[:10]:
            lines.append(f"  • {path.name} ({path.stat().st_size} bytes)")
        if len(new_files) > 10:
            remaining = len(new_files) - 10
            lines.append(f"  … and {remaining} more")

    if modified_files:
        lines.append(f"\nMODIFIED FILES ({len(modified_files)}):")
        for path in modified_files[:10]:
            lines.append(f"  • {path.name} ({path.stat().st_size} bytes)")
        if len(modified_files) > 10:
            remaining = len(modified_files) - 10
            lines.append(f"  … and {remaining} more")

    return "\n".join(lines)


@tool_registry.register_tool("analyze_content_file")
def analyze_content_file(filepath: str) -> str:
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"File not found: {path}"

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return f"Error reading file: {exc}"

    words = content.split()
    word_count = len(words)
    char_count = len(content)
    line_count = content.count("\n") + 1

    flags = []
    risk_notes: List[str] = []

    spam_keywords = {
        "buy now",
        "click here",
        "limited time",
        "act now",
        "free money",
        "make money fast",
        "guaranteed",
        "no risk",
        "order now",
    }
    spam_hits = sum(1 for keyword in spam_keywords if keyword in content.lower())
    if spam_hits >= 3:
        flags.append(f"SPAM: contains {spam_hits} promotional phrases")

    profanity_list = {
        "damn",
        "hell",
        "crap",
        "shit",
        "fuck",
        "bitch",
        "ass",
    }
    profanity_hits = sum(1 for word in profanity_list if word in content.lower())
    if profanity_hits:
        flags.append(f"LANGUAGE: {profanity_hits} potentially offensive terms")

    url_count = content.count("http://") + content.count("https://")
    if url_count > 10:
        flags.append("SUSPICIOUS: excessive URLs detected")

    if content.count("@") > 20:
        flags.append("SUSPICIOUS: excessive email addresses")

    caps_words = [word for word in words if word.isupper() and len(word) > 3]
    if words and len(caps_words) > word_count * 0.3:
        flags.append("STYLE: excessive use of ALL CAPS")

    unique_ratio = len(set(words)) / word_count if word_count else 1.0
    if unique_ratio < 0.3:
        flags.append("QUALITY: high repetition detected")

    # Additional detectors
    pii_hits = detect_pii(content)
    if pii_hits:
        flags.append(f"PII: {', '.join(pii_hits)} detected")

    hate_hits = detect_hate_speech(content)
    if hate_hits:
        flags.append(f"HATE SPEECH: {', '.join(sorted(set(hate_hits)))}")

    suspicious_hits = detect_suspicious_links(content)
    if suspicious_hits:
        flags.append(f"SUSPICIOUS LINKS: {', '.join(sorted(set(suspicious_hits)))}")

    risk_level, risk_reason = score_content_risk(flags)
    if risk_reason:
        risk_notes.append(risk_reason)

    # Build report
    report = f"Content Analysis: {os.path.basename(filepath)}\n\n"
    report += f"Statistics:\n"
    report += f"  Words: {word_count}\n"
    report += f"  Characters: {char_count}\n"
    report += f"  Lines: {line_count}\n\n"

    if flags:
        report += f"⚠️  FLAGS DETECTED ({len(flags)}):\n"
        for flag in flags:
            report += f"  • {flag}\n"
        if risk_level:
            report += f"\nRisk Score: {risk_level.upper()}\n"
        report += "\nRecommendation: REVIEW REQUIRED\n"
    else:
        report += "✓ No policy violations detected\n"
        report += "Recommendation: APPROVED\n"

    return report


# Helper detection utilities


def detect_pii(content: str) -> List[str]:
    hits = []
    if EMAIL_REGEX.search(content):
        hits.append("Email address")
    if PHONE_REGEX.search(content):
        hits.append("Phone number")
    if SSN_REGEX.search(content):
        hits.append("SSN")
    if CREDIT_CARD_REGEX.search(content):
        hits.append("Credit card")
    return hits


def detect_hate_speech(content: str) -> List[str]:
    lowered = content.lower()
    return [term for term in HATE_SPEECH_TERMS if term in lowered]


def detect_suspicious_links(content: str) -> List[str]:
    urls = re.findall(r"https?://[^\s]+", content)
    hits = []
    for url in urls:
        for domain in SUSPICIOUS_DOMAINS:
            if domain in url:
                hits.append(domain)
    return hits


def score_content_risk(flags: List[str]) -> Tuple[Optional[str], Optional[str]]:
    if not flags:
        return None, None

    severity_order = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
    }

    inferred_severity = "LOW"
    reason = []
    for flag in flags:
        if flag.startswith("PII"):
            inferred_severity = "HIGH"
            reason.append("PII detected")
        if flag.startswith("HATE SPEECH"):
            inferred_severity = "CRITICAL"
            reason.append("Hate speech")
        if flag.startswith("SUSPICIOUS LINKS"):
            current_rank = severity_order[inferred_severity]
            desired_rank = severity_order["MEDIUM"]
            if desired_rank > current_rank:
                inferred_severity = "MEDIUM"
            reason.append("Suspicious links")

    unique_reason = ", ".join(sorted(set(reason))) if reason else None
    return inferred_severity, unique_reason


@tool_registry.register_tool("flag_content")
def flag_content(
    filepath: str, reason: str | list[str], severity: str = "medium"
) -> str:
    path = Path(filepath).expanduser().resolve()
    if isinstance(reason, str):
        reason = [reason]
    if not isinstance(reason, list):
        reason = [reason]
    if not isinstance(severity, str):
        severity = "medium"
    if severity not in ["low", "medium", "high", "critical"]:
        severity = "medium"

    reason_str = ", ".join(sorted(set(reason)))

    conn = _ensure_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS flagged_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            reason TEXT,
            severity TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            flagged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            reviewed_at DATETIME,
            reviewer_notes TEXT
        )
        """
    )

    cursor.execute(
        'SELECT id FROM flagged_content WHERE filepath = ? AND status = "pending"',
        (str(path),),
    )
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return f"Content already flagged: {path} (flag ID: {existing[0]})"

    cursor.execute(
        "INSERT INTO flagged_content (filepath, reason, severity) VALUES (?, ?, ?)",
        (str(path), reason_str, severity),
    )
    flag_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return f"Content flagged for review (flag ID: {flag_id})\n  File: {path}\n  Reason: {reason_str}\n  Severity: {severity}"


@tool_registry.register_tool("approve_content")
def approve_content(filepath: str, notes: str | list[str] = "") -> str:
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        notes = [notes]
    notes_str = ", ".join(sorted(set(notes)))

    path = Path(filepath).expanduser().resolve()

    conn = _ensure_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS approved_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            notes TEXT,
            approved_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        "INSERT INTO approved_content (filepath, notes) VALUES (?, ?)",
        (str(path), notes_str),
    )
    approval_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return f"Content approved (ID: {approval_id}): {path.name}"


@tool_registry.register_tool("get_flagged_content")
def get_flagged_content(status: str = "pending", limit: int = 10) -> str:
    if not STATE_DB_PATH.exists():
        return "No moderation database found."

    conn = _ensure_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, filepath, reason, severity, flagged_at
        FROM flagged_content
        WHERE status = ?
        ORDER BY 
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
            END,
            flagged_at DESC
        LIMIT ?
        """,
        (status, limit),
    )
    items = cursor.fetchall()
    conn.close()

    if not items:
        return f"No {status} flagged content."

    lines = [f"Flagged Content ({status.upper()}) - {len(items)} items:\n"]
    for flag_id, filepath, reason, severity, flagged_at in items:
        lines.append(f"Flag #{flag_id} [{severity.upper()}]")
        lines.append(f"  File: {Path(filepath).name}")
        lines.append(f"  Reason: {reason}")
        lines.append(f"  Flagged: {flagged_at}\n")

    return "\n".join(lines)


@tool_registry.register_tool("get_moderation_stats")
def get_moderation_stats() -> str:
    if not STATE_DB_PATH.exists():
        return "No moderation database found."

    conn = _ensure_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM flagged_content")
    total_flagged = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM flagged_content WHERE status = "pending"')
    pending = cursor.fetchone()[0]

    cursor.execute(
        'SELECT severity, COUNT(*) FROM flagged_content WHERE status = "pending" GROUP BY severity'
    )
    severity_breakdown = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM approved_content")
    total_approved = cursor.fetchone()[0]

    cursor.execute(
        'SELECT COUNT(*) FROM flagged_content WHERE date(flagged_at) = date("now")'
    )
    today_flags = cursor.fetchone()[0]

    conn.close()

    lines = ["Content Moderation Statistics:", ""]
    lines.append(f"  Total Flagged: {total_flagged}")
    lines.append(f"  Pending Review: {pending}")
    lines.append(f"  Total Approved: {total_approved}")
    lines.append(f"  Flagged Today: {today_flags}\n")

    lines.append("  Pending by Severity:")
    if severity_breakdown:
        for severity, count in severity_breakdown:
            lines.append(f"    {severity}: {count}")
    else:
        lines.append("    None")

    return "\n".join(lines)


@tool_registry.register_tool("remove_violating_content")
def remove_violating_content(filepath: str, reason: str | list[str]) -> str:
    if isinstance(reason, str):
        reason = [reason]
    if not isinstance(reason, list):
        reason = [reason]
    reason_str = ", ".join(sorted(set(reason)))

    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"File not found: {path}"

    quarantine_dir = STATE_DIR / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine_path = quarantine_dir / f"{timestamp}_{path.name}"
    try:
        shutil.move(str(path), quarantine_path)
    except (OSError, shutil.Error) as exc:
        return f"Error moving file to quarantine: {exc}"

    conn = _ensure_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS removed_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path TEXT NOT NULL,
            quarantine_path TEXT NOT NULL,
            reason TEXT,
            removed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        "INSERT INTO removed_content (original_path, quarantine_path, reason) VALUES (?, ?, ?)",
        (str(path), str(quarantine_path), reason_str),
    )
    conn.commit()
    conn.close()
    return f"Content moved to quarantine:\n  From: {path}\n  To: {quarantine_path}\n  Reason: {reason_str}"


@tool_registry.register_tool("record_moderation_result")
def record_moderation_result(result_json: str) -> str:
    """Persist a moderation result JSON payload into the moderation_reviews table."""
    result = result_json
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            return f"Invalid JSON payload: {exc}"
    if not isinstance(result, dict):
        result = result_json

    conn = _ensure_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS moderation_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_event_id TEXT,
            source_file TEXT,
            status TEXT,
            severity TEXT,
            raw_response TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_moderation_reviews_status ON moderation_reviews(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_moderation_reviews_file ON moderation_reviews(source_file)"
    )

    source_event_id = result.get("source_event_id") or result.get("event_id")
    agent_response = result.get("agent_response") or result.get("response")

    if isinstance(agent_response, dict):
        source_file = agent_response.get("file_path") or agent_response.get("path")
        status = agent_response.get("status") or agent_response.get("decision")
        severity = agent_response.get("severity")
    else:
        source_file = result.get("file_path")
        status = result.get("status")
        severity = result.get("severity")

    cursor.execute(
        """
        INSERT INTO moderation_reviews (
            source_event_id,
            source_file,
            status,
            severity,
            raw_response
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            source_event_id,
            source_file,
            status,
            severity,
            json.dumps(result, indent=2, default=str),
        ),
    )
    conn.commit()
    conn.close()

    return "Moderation result stored successfully."


@tool_registry.register_tool("create_moderation_report")
def create_moderation_report() -> str:
    if not STATE_DB_PATH.exists():
        return "No moderation data available."

    conn = _ensure_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM flagged_content")
    total_flagged = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM approved_content")
    total_approved = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM removed_content")
    total_removed = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT filepath, reason, severity, flagged_at
        FROM flagged_content
        ORDER BY flagged_at DESC
        LIMIT 5
        """
    )
    recent_flags = cursor.fetchall()
    conn.close()

    lines = [
        "╔════════════════════════════════════════════════════════════════╗",
        "║           CONTENT MODERATION REPORT                            ║",
        f"║           Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                      ║",
        "╚════════════════════════════════════════════════════════════════╝",
        "",
        "SUMMARY METRICS:",
        f"  Total Content Flagged:    {total_flagged}",
        f"  Total Content Approved:   {total_approved}",
        f"  Total Content Removed:    {total_removed}",
        "",
        "  Current Status:",
        f"    Pending Review:         {max(total_flagged - total_removed, 0)}",
        f"    Action Rate:            {(total_removed / max(total_flagged, 1) * 100):.1f}%",
        "",
        "RECENT FLAGGED CONTENT:",
    ]

    if recent_flags:
        for filepath, reason, severity, flagged_at in recent_flags:
            lines.append(f"  • {Path(filepath).name} [{severity}]")
            lines.append(f"    Reason: {reason}")
            lines.append(f"    Time: {flagged_at}\n")
    else:
        lines.append("  No recent flags\n")

    lines.append("=" * 64)
    return "\n".join(lines)


@tool_registry.register_tool("summarize_moderation_decision")
def summarize_moderation_decision(result_json: str) -> str:
    try:
        decision = json.loads(result_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON payload: {exc}"

    status = decision.get("status", "unknown")
    severity = decision.get("severity", "unknown")
    file_path = decision.get("file_path", "unknown")
    notes = decision.get("notes")

    summary = [
        f"Decision: {status.upper()} (severity={severity})",
        f"File: {file_path}",
    ]
    if notes:
        if isinstance(notes, list):
            summary.extend(f"- {item}" for item in notes)
        elif isinstance(notes, str):
            summary.append(f"- {notes}")
    return "\n".join(summary)


__all__ = ["tool_registry", "STATE_DB_PATH"]
