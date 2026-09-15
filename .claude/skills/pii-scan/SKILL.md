---
name: pii-scan
description: Scan BrewOps source code and docs for personal data (names, email addresses, phone numbers, physical addresses) that shouldn't be hardcoded there, as part of keeping the codebase GDPR-friendly. Use whenever someone asks to check for PII, personal information, or GDPR compliance in the code, or asks "is there anyone's real name/email/address in this repo?" Make sure to use this skill whenever the user mentions PII, personal data, GDPR, data protection, or privacy scanning of the codebase, even if they phrase it as something else like "make sure nothing sensitive is in there."
---

Find personal data that has leaked into BrewOps source code or docs, and report it so a human can decide what to do. This skill never edits or deletes anything on its own — false positives are common (a machine literally named "Bertha", a test fixture email like `test@example.com`, a placeholder street name), so only a human should make the call to remove real PII.

**Scope**: source code and documentation only — `.py`, `.js`, `.html`, `.css`, `.md`, config files, etc. This skill deliberately does not scan `data/` (the CSV ingest files), `brewops.db`, or git history — those hold real operational data (including real names from hand-logged `manual_*.csv` entries per CLAUDE.md) and are a separate, higher-stakes concern than PII accidentally typed into source or docs. If the user wants those scanned too, ask them explicitly before doing it — a hit in `data/` or the db is a data-handling question, not a "clean up a stray comment" question.

This is a code-hygiene scan, not a legal GDPR audit — it says nothing about lawful basis, retention, or data subject rights. Mention that once, briefly, in the report; don't let "PII scan passed" read as "GDPR compliant."

## How to run it

See `steps.md` for the full procedure (regex prefilter, contextual read-through, false-positive cross-check) and the required report format. Follow it exactly — don't skip steps or improvise a different report layout.

## Version

0.2.0
