#!/usr/bin/env python3
"""Regex prefilter for pii-scan: finds candidate emails, phone numbers, and
street/postal addresses in tracked, non-data source files.

This is a fast, deterministic first pass. It has no idea what a person's
NAME looks like (regex can't tell "Bertha" the espresso machine from a
person), so name detection is left entirely to the Claude review step that
reads these files in context. Treat every hit below as a candidate to
double check, not a confirmed finding -- and treat a clean run as "regex
found nothing," not "this file has no PII."
"""
import re
import subprocess
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone numbers need real judgment to tell apart from other digit-groups
# (timestamps, CSS rgb() triples, version strings all "look like" phone
# patterns). To keep the false-positive rate sane, require either a leading
# '+' country code or a parenthesized area code -- loose space/dot/dash
# separated digit groups on their own are too common in non-phone contexts
# in this codebase (ISO timestamps, CSS colors) to be worth flagging.
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.-]?(?:\(\d{2,4}\)[\s.-]?)?|\(\d{2,4}\)[\s.-]?)"
    r"\d{2,4}[\s.-]\d{2,4}(?:[\s.-]\d{2,4})?(?!\d)"
)

# Spans that look like ISO datetimes or CSS rgb()/rgba() triples get
# excluded from phone/address matching entirely, since those are the two
# patterns in this codebase that otherwise swamp phone detection with noise.
ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")
RGB_RE = re.compile(r"rgba?\([^)]*\)")

STREET_WORDS = (
    r"Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|"
    r"Boulevard|Blvd\.?|Way|Court|Ct\.?|Square|Sq\.?|Plads|Vej|Gade"
)
ADDRESS_RE = re.compile(
    rf"\b\d{{1,5}}\s+\w+(?:\s\w+)?\s+(?:{STREET_WORDS})\b"
    rf"|\b(?:{STREET_WORDS})\s+\d{{1,5}}\b",
    re.IGNORECASE,
)
POSTAL_RE = re.compile(r"\b\d{4,5}\s+[A-ZÆØÅ][a-zæøåA-ZÆØÅ]+\b")

# Directories/extensions that are data, not source/docs -- excluded per the
# scan scope this skill was built for (source code + docs, not raw data
# files, the db, or git history).
EXCLUDE_DIR_PARTS = {"data", ".git", "node_modules", "__pycache__", ".venv"}
EXCLUDE_SUFFIXES = {".db", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock"}

PATTERNS = [
    ("email", EMAIL_RE),
    ("phone", PHONE_RE),
    ("address", ADDRESS_RE),
    ("postal_code", POSTAL_RE),
]


def tracked_and_untracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for line in out.splitlines():
        p = Path(line)
        if any(part in EXCLUDE_DIR_PARTS for part in p.parts):
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        files.append(root / p)
    return files


def scan(root: Path):
    findings = []
    for path in tracked_and_untracked_files(root):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            exclude_spans = [
                m.span() for m in ISO_DATETIME_RE.finditer(line)
            ] + [m.span() for m in RGB_RE.finditer(line)]

            def in_excluded(span):
                s, e = span
                return any(s >= xs and e <= xe for xs, xe in exclude_spans)

            for label, pattern in PATTERNS:
                for m in pattern.finditer(line):
                    if label in ("phone", "address") and in_excluded(m.span()):
                        continue
                    findings.append(
                        {
                            "file": str(path.relative_to(root)),
                            "line": lineno,
                            "type": label,
                            "match": m.group(0),
                            "context": line.strip()[:200],
                        }
                    )
    return findings


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    findings = scan(root)
    if not findings:
        print("No regex-detectable candidates (emails/phones/addresses/postal codes) found.")
        return
    for f in findings:
        print(f"{f['file']}:{f['line']}\t{f['type']}\t{f['match']!r}\t{f['context']}")


if __name__ == "__main__":
    main()
