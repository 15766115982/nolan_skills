---
name: azure-pr-reviewer
description: |
  Review Azure DevOps pull requests. Fetches PR details and changed files from Azure DevOps,
  performs code review focusing on quality, bugs, performance, and security, presents inline
  comments and a summary to the user for approval, and posts approved comments back to Azure
  DevOps. Use this skill whenever the user mentions reviewing an Azure DevOps PR, Azure PR,
  ADO pull request, or asks to review code in Azure DevOps. Also use when the user pastes an
  Azure DevOps PR URL and wants feedback, inline comments, or a summary review.
compatibility: |
  Requires Python 3 and the `AZURE_DEVOPS_PAT` environment variable set to a valid Azure
  DevOps Personal Access Token with Code (read and write) permissions.
---

# Azure DevOps PR Reviewer

## Purpose

Automate the review of Azure DevOps pull requests:
1. Fetch PR metadata and file changes via the Azure DevOps REST API.
2. Analyze changes for code quality, potential bugs, performance issues, and security risks.
3. Present a structured review (inline comments + summary) to the user.
4. After user approval, publish comments as inline threads on the PR.

## Prerequisites

- `AZURE_DEVOPS_PAT` environment variable must be set to a PAT with **Code (read & write)** scope.
- The user provides an Azure DevOps PR URL such as:
  - `https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}`
  - `https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}`

If the PAT is missing, ask the user to create one at `https://dev.azure.com/{org}/_usersSettings/tokens` with **Code (read & write)** scope and set it as `AZURE_DEVOPS_PAT`.

## Helper Script

This skill bundles `scripts/azdo_review.py`. Reference it as:

```bash
python ~/.claude/skills/azure-pr-reviewer/scripts/azdo_review.py <command> <args>
```

If `python` is not available, try `python3`.

Commands:
- `fetch-pr <url>` — PR metadata
- `fetch-diff <url>` — changed files with content
- `fetch-repo-context <url>` — repository-wide context from the target branch
- `fetch-existing-comments <url>` — existing comment threads (for deduplication)
- `post-comments <url> <comments.json>` — post comments, skipping duplicates

## Step 1: Fetch PR metadata

Run:

```bash
python ~/.claude/skills/azure-pr-reviewer/scripts/azdo_review.py fetch-pr "<PR_URL>"
```

Parse the JSON output. Present to the user:
- **Title**
- **Author**
- **Source → Target** branches
- **Description** (summarize if very long)
- **Iterations count** (proxy for update history)

If the command fails, report the error and stop.

## Step 2: Fetch changed files

Run:

```bash
python ~/.claude/skills/azure-pr-reviewer/scripts/azdo_review.py fetch-diff "<PR_URL>"
```

The JSON contains:
- `pullRequest`: metadata
- `changes`: array of changed files, each with:
  - `path`: file path
  - `changeType`: add, edit, delete, rename
  - `oldContent`: previous content (for edits/deletes), or `null` if unavailable/binary
  - `newContent`: new content (for adds/edits), or `null` if unavailable/binary
  - `note`: e.g. `"binary file"`

**Pre-filtered by the script**: binary files, lockfiles, and paths inside `node_modules/`, `vendor/`, `dist/`, `build/`, `.git/`, `.vscode/`, `.idea/` are excluded automatically.

### Handling large PRs

If the `changes` array contains more than **15 files**, ask the user whether to:
- Review all files anyway (warn that coverage may be shallow), or
- Focus on a subset they specify, or
- Skip test/config files and focus on source files

If individual files are very large (>500 lines), focus on the most impactful sections (new functions, modified conditionals, API surface changes) and note in the summary that large files were sampled.

## Step 3: Fetch repository context

Run:

```bash
python ~/.claude/skills/azure-pr-reviewer/scripts/azdo_review.py fetch-repo-context "<PR_URL>"
```

The JSON contains:
- `targetBranch`: the branch the PR targets (usually `refs/heads/main`)
- `repositoryFiles`: flat list of all file paths in the target branch
- `contextFiles`: key configuration files and their contents (e.g., `package.json`, `tsconfig.json`, `requirements.txt`, `README.md`, `CODEOWNERS`, `Dockerfile`, `.editorconfig`, etc.)
- `siblingContext`: for each directory touched by the PR, a list of sibling files in that directory

Use this context to perform **deeper, project-aware reviews**:

- **Coding standards**: Check `.editorconfig`, `tsconfig.json`, `pyproject.toml`, or `Makefile` to see if the PR violates project conventions (indentation, line length, import style, etc.).
- **Dependency awareness**: If `package.json` shows `lodash` is already a dependency, suggest using it instead of hand-rolling utility functions. If a new dependency is introduced, verify it matches the project's tech stack.
- **Architecture consistency**: Use `siblingContext` to understand the module structure. If the PR adds a new file, check whether it follows the naming and organization patterns of its siblings.
- **Ownership & process**: `CODEOWNERS` can tell you if sensitive areas require specific reviewers; mention if the PR touches files owned by a different team.
- **Documentation**: If the PR introduces a new public API or feature flag, check `README.md` or docs directories and suggest updates.

Limitations: Do not fetch every file in the repository. Rely on `contextFiles` and `siblingContext` for structural understanding. If you need a specific existing file's content to compare against the PR changes, fetch it selectively with the `fetch-diff` data or by reasoning about the `repositoryFiles` list.

## Step 4: Generate the review

For every changed file that has textual content, analyze the changes.

- For **edit** changes, compare `oldContent` and `newContent` to identify the exact modifications. Focus your review on the modified lines and their immediate context.
- For **add** changes, review the entire `newContent`.
- For **delete** changes, review `oldContent` to flag any removal of safety checks or useful logic.

Focus areas:

### Code Quality & Readability
- Unclear or misleading variable/function/class names
- Functions or classes that are too long or do too many things
- Missing comments for non-obvious business logic or complex algorithms
- Duplicated code that could be abstracted
- Inconsistent naming, formatting, or patterns within the diff

### Potential Bugs & Logic Errors
- Missing null/undefined checks or guard clauses
- Off-by-one errors, incorrect loop boundaries
- Missing error handling for I/O, network, or parsing operations
- Race conditions, state mutations, or concurrency issues
- Incorrect assumptions about input data shape or types

### Performance
- Inefficient nested loops or repeated expensive operations
- Unbounded data loading without pagination
- N+1 query patterns
- Unnecessary object allocations in hot paths

### Security
- Injection vulnerabilities (SQL, command, XSS)
- Hardcoded secrets, API keys, or credentials
- Missing authorization checks
- Unsafe file path construction or deserialization
- Logging of sensitive user data

### Writing inline comments

For each issue, produce an inline comment object with:
- `filePath`: exact path from the `changes` entry
- `line`: line number in the **new file** (`newContent`) where the issue occurs
- `content`: a concise, actionable comment in **English**

Guidelines for comment quality:
- Be specific. Quote the relevant code snippet when helpful.
- Explain **why** it's a problem, not just **what** is wrong.
- Suggest a concrete fix or pattern to use.
- Keep tone constructive and professional. Avoid shaming language.
- Each distinct issue should be its own comment thread. Do not merge multiple unrelated issues into one comment.

If a change is clearly an auto-generated file (e.g., protobuf output, migration file), limit review to structural checks rather than style.

### Writing the summary

Produce a summary (2-4 paragraphs) covering:
1. **Overall assessment**: PR size, clarity of purpose, alignment with description
2. **Key themes**: The most common or important issues found across files
3. **Positive highlights**: Notable good practices (tests, clear naming, refactoring)
4. **Recommendations**: High-level suggestions (e.g., add integration tests, update docs)

## Step 5: Present for approval

Display the review in a clean format:

```markdown
## Review for: <PR Title>
Link: <PR_URL>

### Summary
<summary here>

### Inline Comments
| File | Line | Comment |
|------|------|---------|
| src/auth.py | 42 | Consider adding a null check for `user` before dereferencing. |
| ... | ... | ... |

### Files Skipped
- `package-lock.json` (lockfile)
- `assets/logo.png` (binary)

---

**Do you want to post these comments to Azure DevOps?**
- Reply **yes** / **approve** / **post** to publish.
- Reply **no** / **skip** / **edit** to discard or modify.
```

If the user asks for edits, apply them and re-present. Do not post without explicit approval.

## Step 6: Post comments to Azure DevOps

Once approved, create a temporary JSON file:

```json
{
  "comments": [
    {
      "filePath": "/src/auth.py",
      "line": 42,
      "content": "Consider adding a null check for `user` before dereferencing."
    },
    {
      "content": "Great work adding unit tests for the edge cases!"
    }
  ]
}
```

- Comments with `filePath` become inline threads.
- Comments without `filePath` become PR-level summary threads.

Save it to a temp path (e.g., `/tmp/azdo_comments_<timestamp>.json`) and run:

```bash
python ~/.claude/skills/azure-pr-reviewer/scripts/azdo_review.py post-comments "<PR_URL>" /tmp/azdo_comments_<timestamp>.json
```

### Duplicate detection

The script automatically fetches existing comments before posting and skips any comment that matches **file path + line + normalized content** of an already-posted comment. This prevents duplicate reviews if the skill is run multiple times on the same PR.

Report the result:
- If all posted successfully: "All N comments posted."
- If some were skipped as duplicates: "M new comments posted, N duplicates skipped."
- If some failed: list which comments failed and why.

## Error Handling

| Scenario | Action |
|----------|--------|
| `AZURE_DEVOPS_PAT` missing | Ask user to set it and retry |
| PR URL format unrecognized | Explain expected formats |
| API 404 | Verify PR exists and PAT has access |
| API 401/403 | PAT may lack scope; suggest regenerating with Code (read & write) |
| Binary file skipped | Note in "Files Skipped" section |
| Partial post failure | Report successes and failures separately |
| Duplicate comment | The script skips it automatically; report how many were skipped |

## Notes

- Review comments are always written in **English**, even if the user's request is in another language. UI text and explanations to the user should match the user's language.
- The script only fetches content for the latest iteration. If the PR has been updated while reviewing, re-run from Step 1.
- Avoid reviewing minified, generated, or third-party code. The script pre-filters many of these, but verify the `changes` list before analyzing.
