---
name: github-engineering-workflow
description: Apply an opt-in GitHub engineering workflow covering Issue and reproducible Bug report definition, implementation traceability, atomic Conventional Commit messages, Pull Request preparation, testing, and human review. Use only when the user explicitly invokes `$github-engineering-workflow` or explicitly asks to apply this named skill; do not apply it implicitly to ordinary development tasks.
---

# GitHub Engineering Workflow

Enforce `Proposal -> Design (Issue) -> Coding (PR) -> Review -> Merge` for the current task only.

Read [references/workflow.md](references/workflow.md) completely before creating or editing an Issue, making implementation changes, committing, or preparing a PR under this skill.

## Execute the workflow

Use Chinese for all GitHub-facing text produced under this skill, including Issue titles and bodies, Markdown section headings, PR titles and descriptions, Commit messages and bodies, review comments, and release or status notes. Keep technical identifiers and required GitHub keywords such as branch names, Conventional Commit types, `Closes #N`, and `Refs #N` in their conventional English form. Repository requirements still control structure and required content. Use another language only when the user explicitly requests it for the current task.

1. Inspect repository instructions, status, remotes, current branch, existing Issue references, and available GitHub access. Preserve stricter repository rules.
2. Identify the Issue that authorizes the work. Search existing context and GitHub before proposing a duplicate.
3. If no suitable Issue exists, create one through an available GitHub integration or CLI when the user has authorized repository work. Otherwise draft the complete Issue and request the missing Issue number or access before coding. Never invent an Issue number or URL.
4. For a non-Bug Issue, confirm it contains a clear background, goal, included and excluded scope, design notes, risks, and verifiable acceptance criteria. For a Bug Issue, use the lightweight exception: require only a complete numbered reproduction process and private handling of suspected security vulnerabilities; treat every other field as optional context rather than a filing gate. Split work that cannot fit in one or a few reviewable PRs.
5. Implement only the agreed Issue scope. Keep unrelated changes and user-owned modifications untouched. Add or update tests and user-facing documentation when required.
6. Run relevant tests, checks, and builds. Report exact results and distinguish passed, failed, and not run checks.
7. Review the diff for scope, correctness, duplication, hidden risk, secrets, generated artifacts, and AI-generated code that lacks human understanding or test coverage.
8. Create atomic commits using the required format and the real Issue number. Do not commit when the Issue number is unknown.
9. Prepare or create a small PR linked to the Issue. Use `Closes #N` only when it fully resolves the Issue; otherwise use `Refs #N`. Default to a draft PR when the repository or user prefers drafts.
10. Require human review before merge. Do not bypass branch protection, required checks, approval gates, or force-push safeguards.

## Respect task boundaries

- Applying this skill does not grant permission to push, open a PR, merge, force-push, change repository settings, or contact people unless the user's request includes that action.
- Treat read-only requests as read-only. For a request to draft an Issue, PR, or Commit message, produce only that artifact.
- Do not silently install templates or repository-wide policy files. Add them only when the user asks to adopt the workflow in that repository.
- Keep this workflow active only for the task in which the user invoked the skill. Do not carry it into later tasks unless invoked again.

## Report completion

Summarize the real Issue link or number, changed scope, verification results, Commit hash/message if created, PR link/status if created, review state, and remaining risks. Clearly identify any step that could not be completed.
