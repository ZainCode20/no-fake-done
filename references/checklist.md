# Semantic Slop Checklist

Regex checks catch stubs and skipped tests, but **architectural slop**
requires a quick human-style check before you declare victory.

## 1. "Adding Instead of Replacing"
- Did you leave old broken code in place and wrap it in a compatibility layer
  or fallback branch?
- If the old behavior is obsolete, remove it cleanly rather than stacking
  workarounds.

## 2. The "80% Complete" Trap
- Are all error paths, edge cases, and empty/null inputs handled, or only the
  happy path?
- Do newly added functions actually get called from the real entry point?

## 3. Scope Creep & Unrequested Refactors
- Check `git diff --stat`: did you touch unrelated files, rename existing
  symbols, or reformat code you didn't need to change?
- Revert any accidental formatting or unrelated edits.

## 4. Test Integrity
- Do new or updated tests verify **real behavior** (not mocked tautologies)?
- Did you run the full relevant test suite **after** your final edit?
