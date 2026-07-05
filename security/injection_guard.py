"""
Prompt-Injection Defence Layer (Code-Enforced)
===============================================

This module provides a **code-level** defence against prompt injection attacks
that arrive via tool outputs (the "Day 4" threat model: adversarial content
embedded in scraped web pages or API responses that attempt to hijack agent
reasoning).

Defence is enforced by deterministic code — regex pattern matching, structural
anomaly detection, and payload quarantine — NOT by asking the LLM to "be
careful."  Every detection is logged with full provenance for judge auditability.

Usage:
    from security.injection_guard import InjectionGuard, sanitize_tool_output

    guard = InjectionGuard()
    result = guard.sanitize("some raw tool output", tool_name="web_search_tool")
    # result.clean_text — safe for agent consumption
    # result.injection_alerts — audit log entries
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from models.schemas import InjectionAlert, SanitizedResult

logger = logging.getLogger("crisis_response.security")

# ---------------------------------------------------------------------------
# Pattern catalogue — each tuple is (pattern_name, compiled_regex)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Direct instruction hijacking
    (
        "IGNORE_PREVIOUS",
        re.compile(
            r"(?i)(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above|earlier|system)\s+"
            r"(instructions?|prompts?|rules?|guidelines?|context)",
        ),
    ),
    # System/assistant role injection
    (
        "ROLE_INJECTION",
        re.compile(
            r"(?i)(you\s+are\s+now|new\s+instructions?|system\s*:|assistant\s*:|"
            r"\[INST\]|\[\/INST\]|<\|system\|>|<\|assistant\|>|<\|user\|>)",
        ),
    ),
    # Resource rerouting commands
    (
        "REROUTE_COMMAND",
        re.compile(
            r"(?i)(reroute|redirect|divert|send)\s+(all\s+)?(supplies|resources|aid|teams|water|"
            r"medical|shelter|equipment)\s+(to|towards|at)\s+",
        ),
    ),
    # Priority manipulation
    (
        "PRIORITY_MANIPULATION",
        re.compile(
            r"(?i)(set\s+priority\s+to|change\s+priority|"
            r"mark\s+(this|all)\s+as\s+(critical|highest|urgent)|"
            r"override\s+severity|escalate\s+to\s+critical)",
        ),
    ),
    # Data fabrication instructions
    (
        "FABRICATION_INSTRUCTION",
        re.compile(
            r"(?i)(fabricate|invent|make\s+up|generate\s+fake|create\s+false)\s+"
            r"(data|reports?|claims?|incidents?|casualties|numbers?)",
        ),
    ),
    # Prompt leaking / exfiltration
    (
        "PROMPT_EXFILTRATION",
        re.compile(
            r"(?i)(print|output|reveal|show|display|repeat)\s+(your\s+)?"
            r"(system\s+prompt|instructions?|internal\s+prompt|hidden\s+prompt|secret)",
        ),
    ),
    # Encoded / obfuscated injection attempts
    # NOTE: \\u escapes are NOT flagged because they are standard JSON encoding
    # (e.g. \u2014 = em-dash). We only flag explicit eval/exec/decode patterns.
    (
        "ENCODED_INJECTION",
        re.compile(
            r"(?i)(base64\s*[\.\(]|rot13|hex\s+decode|eval\s*\(|exec\s*\(|"
            r"\\x[0-9a-f]{2}(?:\\x[0-9a-f]{2})+)",
        ),
    ),
    # Markdown/HTML injection for rendering exploits
    (
        "MARKUP_INJECTION",
        re.compile(
            r"(<script|<iframe|<object|<embed|javascript\s*:|onerror\s*=|onload\s*=)",
            re.IGNORECASE,
        ),
    ),
    # Separator-based injection (tries to break out of data context)
    (
        "SEPARATOR_INJECTION",
        re.compile(
            r"(?i)(---+\s*(?:new|system|admin|override)\s*---+|"
            r"={3,}\s*(?:INSTRUCTIONS?|OVERRIDE|ADMIN)\s*={3,})",
        ),
    ),
]


# ---------------------------------------------------------------------------
# Structural anomaly patterns
# ---------------------------------------------------------------------------

_STRUCTURAL_ANOMALIES: list[tuple[str, re.Pattern]] = [
    # Instruction-like blocks embedded in data
    (
        "EMBEDDED_INSTRUCTION_BLOCK",
        re.compile(
            r"(?i)(?:^|\n)\s*(?:INSTRUCTION|DIRECTIVE|COMMAND|ORDER)\s*:\s*.{10,}",
            re.MULTILINE,
        ),
    ),
    # Suspiciously long ALL-CAPS directives
    (
        "ALLCAPS_DIRECTIVE",
        re.compile(
            r"[A-Z\s]{30,}(?:REROUTE|REDIRECT|IGNORE|OVERRIDE|PRIORITY|URGENT|CRITICAL)",
        ),
    ),
]


class InjectionGuard:
    """
    Deterministic prompt-injection detector and sanitiser.

    Runs BEFORE any tool result reaches the agent's reasoning context.
    All detections are logged with full provenance for audit.
    """

    def __init__(
        self,
        extra_patterns: Optional[list[tuple[str, re.Pattern]]] = None,
        confidence_penalty: float = 0.5,
    ) -> None:
        self.patterns = list(_INJECTION_PATTERNS)
        self.structural_patterns = list(_STRUCTURAL_ANOMALIES)
        if extra_patterns:
            self.patterns.extend(extra_patterns)
        self.confidence_penalty = confidence_penalty
        self._alert_log: list[InjectionAlert] = []

    @property
    def alert_log(self) -> list[InjectionAlert]:
        """Full history of all injection alerts raised by this guard instance."""
        return list(self._alert_log)

    def sanitize(self, raw_text: str, tool_name: str = "unknown") -> SanitizedResult:
        """
        Scan *raw_text* for injection patterns and return a SanitizedResult.

        - Matching fragments are excised from the text and quarantined.
        - Each detection produces an InjectionAlert with full provenance.
        - The returned clean_text is safe for agent consumption.
        """
        if not raw_text:
            return SanitizedResult(clean_text="", was_modified=False)

        payload_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        alerts: list[InjectionAlert] = []
        quarantined: list[str] = []
        clean = raw_text

        # Pass 1: regex pattern scan
        for pattern_name, regex in self.patterns:
            for match in regex.finditer(clean):
                fragment = match.group(0)
                # Expand quarantine to the full line containing the match
                line_start = clean.rfind("\n", 0, match.start()) + 1
                line_end = clean.find("\n", match.end())
                if line_end == -1:
                    line_end = len(clean)
                quarantined_line = clean[line_start:line_end].strip()

                alert = InjectionAlert(
                    alert_id=str(uuid.uuid4()),
                    tool_name=tool_name,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    matched_pattern=pattern_name,
                    raw_payload_hash=payload_hash,
                    quarantined_fragment=quarantined_line,
                    severity="CRITICAL" if pattern_name in (
                        "IGNORE_PREVIOUS", "REROUTE_COMMAND", "ROLE_INJECTION",
                    ) else "HIGH",
                )
                alerts.append(alert)
                quarantined.append(quarantined_line)
                logger.warning(
                    "INJECTION DETECTED [%s] tool=%s pattern=%s fragment=%r",
                    alert.alert_id,
                    tool_name,
                    pattern_name,
                    quarantined_line[:120],
                )

        # Pass 2: structural anomaly scan
        for pattern_name, regex in self.structural_patterns:
            for match in regex.finditer(clean):
                line_start = clean.rfind("\n", 0, match.start()) + 1
                line_end = clean.find("\n", match.end())
                if line_end == -1:
                    line_end = len(clean)
                quarantined_line = clean[line_start:line_end].strip()

                alert = InjectionAlert(
                    alert_id=str(uuid.uuid4()),
                    tool_name=tool_name,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    matched_pattern=f"STRUCTURAL:{pattern_name}",
                    raw_payload_hash=payload_hash,
                    quarantined_fragment=quarantined_line,
                    severity="HIGH",
                )
                alerts.append(alert)
                quarantined.append(quarantined_line)

        # Excise all quarantined fragments from the clean text
        for fragment in quarantined:
            clean = clean.replace(fragment, "[REDACTED — INJECTION QUARANTINED]")

        # Collapse multiple consecutive redaction markers
        clean = re.sub(
            r"(\[REDACTED — INJECTION QUARANTINED\]\s*){2,}",
            "[REDACTED — INJECTION QUARANTINED]\n",
            clean,
        )

        was_modified = len(alerts) > 0
        self._alert_log.extend(alerts)

        if was_modified:
            logger.warning(
                "Injection guard quarantined %d fragment(s) from tool=%s",
                len(alerts),
                tool_name,
            )

        return SanitizedResult(
            clean_text=clean.strip(),
            was_modified=was_modified,
            injection_alerts=alerts,
            quarantined_fragments=quarantined,
        )

    def reset_log(self) -> None:
        """Clear the alert history (useful between test runs)."""
        self._alert_log.clear()


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

# Singleton guard instance for the application
_default_guard = InjectionGuard()


def sanitize_tool_output(raw_text: str, tool_name: str = "unknown") -> SanitizedResult:
    """
    Module-level convenience wrapper around the default InjectionGuard.

    Use this as the standard entry point in tool wrapper functions:

        result = sanitize_tool_output(raw_response, tool_name="web_search_tool")
        if result.was_modified:
            log_injection_alerts(result.injection_alerts)
        safe_text = result.clean_text
    """
    return _default_guard.sanitize(raw_text, tool_name)


def get_default_guard() -> InjectionGuard:
    """Return the module-level singleton InjectionGuard instance."""
    return _default_guard
