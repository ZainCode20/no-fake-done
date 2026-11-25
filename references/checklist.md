# Semantic Slop Checklist

Regex catches stubs, secrets, and skipped tests. Before declaring a task
complete, verify these 4 architectural failure modes manually:

## 1. "Adding Instead of Replacing"
- Did you leave obsolete or broken logic in place and wrap it in a fallback
  branch or compatibility shim?
- **Fix:** Replace the broken path cleanly and delete dead code unless
  backward compatibility was explicitly requested.

## 2. The "80% Complete" Trap
- Are error paths, empty/null inputs, and boundary conditions handled, or only
  the happy path?
- Is every newly created helper or endpoint actually wired into its caller?

## 3. Scope Creep & Unrequested Refactors
- Run `git diff --stat`: did you edit unrelated files, rename existing public
  symbols, or reformat untouched code?
- **Fix:** Revert unrelated diffs so the review stays focused on the request.

## 4. Real Test Integrity
- Do new or modified tests actually fail if the bug is reintroduced?
- Were tests executed **after** your very last edit, with real output observed?
