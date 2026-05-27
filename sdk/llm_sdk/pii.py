"""Lightweight regex-based PII redaction.

Good enough for demo + dashboard previews. Production should use Presidio
or a dedicated NER model for higher recall.
"""
import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s-])?"
    r"(?:\(\d{3}\)\s?\d{3}[\s-]?\d{4}|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b)"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Visa/Mastercard/Amex/Disc — 13-19 digits with optional spaces/dashes
_CC = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact(text: str) -> str:
    if not text:
        return text
    text = _EMAIL.sub("[REDACTED-EMAIL]", text)
    text = _CC.sub(_cc_filter, text)
    text = _SSN.sub("[REDACTED-SSN]", text)
    text = _PHONE.sub("[REDACTED-PHONE]", text)
    return text


def _cc_filter(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[REDACTED-CC]"
    return match.group(0)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0
