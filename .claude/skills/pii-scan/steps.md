# Detailed steps

## How to run it

1. **Regex prefilter.** Run the bundled script to catch emails, phone numbers, and address-shaped text fast and deterministically:
   ```
   python3 .claude/skills/pii-scan/scripts/regex_prefilter.py
   ```
   Run it from the repo root (or pass a root path as the first argument). It only looks at files tracked by git or respecting `.gitignore`, and already excludes `data/`, `.git`, binaries, and lockfiles.

2. **Contextual read-through for names.** Regex cannot tell a person's name from any other capitalized word — that takes judgment, which is why this step exists. A name doesn't only hide in test fixtures and comments; it can just as easily be sitting in plain sight in user-facing copy (a page title, a header, placeholder text, an about/credits string) where it reads as normal branding rather than "data." Read through the actual rendered content of every file, not just the parts that look data-shaped — that means frontend markup (`<title>`, `<h1>`, visible labels) and docs prose just as much as fixtures — and look for:
   - Real-looking personal names anywhere in a file's text, including page titles/headers/branding strings (not machine names like "Bertha" or drink names — cross-check against `DRINK_TYPES` in `schema.py` and machine names in the schema/seed data if unsure whether something is a person or a device)
   - Anything that reads like a real person's email, phone, or address that regex might have missed (unusual formatting, obfuscated like `name [at] domain`, etc.)
   - Don't flag obvious placeholders (`test@example.com`, `123 Main St`, `Jane Doe`, `John Smith`) as findings — note them only if genuinely ambiguous.

3. **Cross-check regex hits for false positives.** Every regex hit needs a human-judgment pass before it goes in the report:
   - Version numbers, timestamps, or IDs that happen to match the phone-number pattern
   - Package/library version strings that match address patterns
   - Test fixtures that are intentionally fake

## Report format

Report directly in the conversation as a markdown table, most-confident findings first. If nothing is found, say so plainly rather than a long report of near-misses. Keep the report to just the table (or the plain "nothing found" line) plus the one closing line below — do not add prose summarizing what was checked, what came back clean, or why (e.g. don't explain that machine names or placeholder emails were ruled out); that reasoning stays internal to the scan.

| File:Line | Type | Snippet | Why it's likely real PII |
|---|---|---|---|

After the table, add exactly one closing line, folding together the scan-vs-audit caveat and the scope note: e.g. "Code-hygiene scan, not a legal GDPR audit; `data/`, `brewops.db`, and git history weren't scanned — say if you want those checked too." Don't restate it as separate paragraphs.

If findings exist, add a one-line recommendation per finding (e.g. "replace with a placeholder name") in the table or right after it — not an automatic fix. This repo treats `tests/` as read-only for verification purposes, so a finding inside `tests/` should be flagged to the user rather than edited.
