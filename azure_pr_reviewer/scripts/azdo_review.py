#!/usr/bin/env python3
"""Azure DevOps PR Review Helper

Commands:
  fetch-pr <url>                   -> JSON with PR metadata
  fetch-diff <url>                 -> JSON with changed files and their contents
  fetch-repo-context <url>         -> JSON with repo-wide context (tree, config files, sibling dirs)
  fetch-existing-comments <url>    -> JSON with existing PR comment threads
  post-comments <url> <comments.json> -> Posts comments to the PR (skips duplicates)
"""
import sys
import os
import json
import re
import urllib.request
import urllib.parse
import base64


def get_auth_header():
    pat = os.environ.get("AZURE_DEVOPS_PAT")
    if not pat:
        raise RuntimeError("AZURE_DEVOPS_PAT environment variable is not set")
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def parse_pr_url(url):
    patterns = [
        r"https://dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)/pullrequest/(?P<id>\d+)",
        r"https://(?P<org>[^.]+)\.visualstudio\.com/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)/pullrequest/(?P<id>\d+)",
    ]
    for p in patterns:
        m = re.match(p, url.strip())
        if m:
            return m.groupdict()
    raise ValueError(f"Unsupported PR URL format: {url}")


def api_request(method, org, project, path, body=None, api_version="7.0"):
    url = f"https://dev.azure.com/{org}/{project}/_apis{path}?api-version={api_version}"
    headers = get_auth_header()
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err_body = json.load(e)
        except Exception:
            err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {err_body}") from e


def api_get(org, project, path, api_version="7.0"):
    return api_request("GET", org, project, path, None, api_version)


def api_post(org, project, path, body, api_version="7.0"):
    return api_request("POST", org, project, path, body, api_version)


def fetch_pr(url):
    info = parse_pr_url(url)
    org, project, repo, pr_id = info["org"], info["project"], info["repo"], info["id"]
    repo_data = api_get(org, project, f"/git/repositories/{repo}")
    repo_id = repo_data["id"]
    pr_data = api_get(org, project, f"/git/repositories/{repo_id}/pullrequests/{pr_id}")
    iterations = api_get(org, project, f"/git/repositories/{repo_id}/pullrequests/{pr_id}/iterations")
    return {
        "organization": org,
        "project": project,
        "repository": repo,
        "repositoryId": repo_id,
        "pullRequestId": int(pr_id),
        "title": pr_data.get("title"),
        "description": pr_data.get("description"),
        "sourceBranch": pr_data.get("sourceRefName", ""),
        "targetBranch": pr_data.get("targetRefName", ""),
        "author": pr_data.get("createdBy", {}).get("displayName"),
        "status": pr_data.get("status"),
        "iterations": iterations.get("value", []),
    }


def fetch_file_content(org, project, repo_id, path, version):
    # version like refs/heads/main -> main
    if version.startswith("refs/heads/"):
        version = version[len("refs/heads/"):]
    encoded_path = urllib.parse.quote(path, safe="")
    encoded_version = urllib.parse.quote(version, safe="")
    url = (
        f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/items"
        f"?path={encoded_path}&versionDescriptor.versionType=branch&versionDescriptor.version={encoded_version}"
        f"&api-version=7.0"
    )
    req = urllib.request.Request(url, headers=get_auth_header())
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            # Try to decode as text; if it looks binary, return marker
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return {"_binary": True, "_size": len(content)}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_diff(url):
    pr_info = fetch_pr(url)
    org, project, repo_id = pr_info["organization"], pr_info["project"], pr_info["repositoryId"]
    pr_id = pr_info["pullRequestId"]
    iterations = pr_info["iterations"]
    if not iterations:
        raise RuntimeError("No iterations found for this PR")
    latest = iterations[-1]
    iteration_id = latest["id"]

    changes_resp = api_get(
        org, project,
        f"/git/repositories/{repo_id}/pullrequests/{pr_id}/iterations/{iteration_id}/changes"
    )
    changes = changes_resp.get("changeEntries") or changes_resp.get("changes") or []

    SKIP_PATTERNS = [
        r"\.(png|jpg|jpeg|gif|bmp|ico|svg|woff|woff2|ttf|eot|mp3|mp4|avi|mov|zip|tar|gz|rar|7z|exe|dll|so|dylib|bin|lock)$",
        r"(^|/)(node_modules|vendor|dist|build|\.git|\.vscode|\.idea)/",
        r"package-lock\.json$",
        r"yarn\.lock$",
        r"pnpm-lock\.yaml$",
    ]
    skip_re = [re.compile(p, re.IGNORECASE) for p in SKIP_PATTERNS]

    result = []
    for change in changes:
        item = change.get("item", {})
        path = item.get("path", "")
        if any(r.search(path) for r in skip_re):
            continue

        change_type = change.get("changeType", "")
        entry = {"path": path, "changeType": change_type}

        # Fetch old content
        if change_type != "add":
            old = fetch_file_content(org, project, repo_id, path, pr_info["targetBranch"])
            if isinstance(old, dict) and old.get("_binary"):
                entry["oldContent"] = None
                entry["note"] = "binary file"
            else:
                entry["oldContent"] = old

        # Fetch new content
        if change_type != "delete":
            new = fetch_file_content(org, project, repo_id, path, pr_info["sourceBranch"])
            if isinstance(new, dict) and new.get("_binary"):
                entry["newContent"] = None
                entry["note"] = "binary file"
            else:
                entry["newContent"] = new

        result.append(entry)

    return {
        "pullRequest": pr_info,
        "changes": result,
    }


def normalize_comment(text):
    """Normalize comment text for deduplication comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def fetch_existing_comments(url):
    """Fetch existing comment threads on the PR."""
    pr_info = fetch_pr(url)
    org, project, repo_id = pr_info["organization"], pr_info["project"], pr_info["repositoryId"]
    pr_id = pr_info["pullRequestId"]

    threads_resp = api_get(org, project, f"/git/repositories/{repo_id}/pullrequests/{pr_id}/threads")
    threads = threads_resp.get("value", [])

    existing = []
    for thread in threads:
        thread_id = thread.get("id")
        thread_context = thread.get("threadContext", {})
        file_path = thread_context.get("filePath", "")
        right_start = thread_context.get("rightFileStart", {})
        line = right_start.get("line", 0)

        for comment in thread.get("comments", []):
            content = comment.get("content", "")
            if content:
                existing.append({
                    "threadId": thread_id,
                    "filePath": file_path,
                    "line": line,
                    "content": content,
                    "normalized": normalize_comment(content),
                })

    return {
        "organization": org,
        "project": project,
        "repository": pr_info["repository"],
        "pullRequestId": pr_id,
        "count": len(existing),
        "comments": existing,
    }


def fetch_repo_tree(org, project, repo_id, branch="main"):
    """Fetch the file tree for a given branch."""
    if branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/"):]
    encoded_branch = urllib.parse.quote(branch, safe="")
    url = (
        f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/items"
        f"?recursionLevel=Full&versionDescriptor.versionType=branch&versionDescriptor.version={encoded_branch}"
        f"&api-version=7.0"
    )
    req = urllib.request.Request(url, headers=get_auth_header())
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    return data.get("value", [])


KEY_CONTEXT_FILES = [
    "README.md", "readme.md", "Readme.md",
    "package.json",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "tsconfig.json", "jsconfig.json",
    ".editorconfig",
    "CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS",
    "CONTRIBUTING.md", "contributing.md",
    ".gitignore",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile", "justfile",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "Cargo.toml",
    "go.mod", "go.sum",
    "CMakeLists.txt",
    "pubspec.yaml",
    "Gemfile",
    "composer.json",
]


def fetch_repo_context(url):
    """Fetch repository-wide context from the target branch (usually main)."""
    pr_info = fetch_pr(url)
    org, project, repo_id = pr_info["organization"], pr_info["project"], pr_info["repositoryId"]
    target_branch = pr_info.get("targetBranch", "refs/heads/main")

    # Fetch file tree
    tree = fetch_repo_tree(org, project, repo_id, target_branch)

    # Build a set of existing paths for quick lookup
    path_set = set()
    for item in tree:
        path = item.get("path", "")
        if path:
            path_set.add(path.lstrip("/"))

    # Fetch key context files
    context_files = []
    for key_file in KEY_CONTEXT_FILES:
        if key_file in path_set:
            content = fetch_file_content(org, project, repo_id, key_file, target_branch)
            if isinstance(content, str):
                context_files.append({"path": key_file, "content": content})
            # else: binary or unavailable, skip

    # Also gather sibling context for changed files:
    # For each changed file, list other files in the same directory to understand module structure
    changes = fetch_diff(url)
    sibling_dirs = {}
    for change in changes.get("changes", []):
        path = change.get("path", "")
        if "/" in path:
            dir_path = path.rsplit("/", 1)[0]
        else:
            dir_path = ""
        if dir_path not in sibling_dirs:
            sibling_dirs[dir_path] = []
        # Collect all files in this directory from tree
        for item in tree:
            item_path = item.get("path", "").lstrip("/")
            if item_path.startswith(dir_path + "/") or (not dir_path and "/" not in item_path):
                # Ensure it's directly in this directory, not a subdirectory
                relative = item_path[len(dir_path) + 1:] if dir_path else item_path
                if "/" not in relative and relative:
                    sibling_dirs[dir_path].append(relative)

    # Clean up: remove duplicate entries and empty lists
    sibling_context = {}
    for d, files in sibling_dirs.items():
        unique = sorted(set(files))
        if unique:
            sibling_context[d] = unique

    return {
        "pullRequest": pr_info,
        "targetBranch": target_branch,
        "repositoryFiles": [item.get("path", "").lstrip("/") for item in tree if item.get("gitObjectType") == "blob"],
        "contextFiles": context_files,
        "siblingContext": sibling_context,
    }


def post_comments(url, comments_path):
    pr_info = fetch_pr(url)
    org, project, repo_id = pr_info["organization"], pr_info["project"], pr_info["repositoryId"]
    pr_id = pr_info["pullRequestId"]

    with open(comments_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Fetch existing comments for deduplication
    existing_resp = fetch_existing_comments(url)
    existing_set = set()
    for ec in existing_resp["comments"]:
        key = f"{ec['filePath']}:{ec['line']}:{ec['normalized']}"
        existing_set.add(key)

    results = []
    for comment in data.get("comments", []):
        file_path = comment.get("filePath", "")
        line = comment.get("line", 1)
        content = comment["content"]
        normalized = normalize_comment(content)
        key = f"{file_path}:{line}:{normalized}"

        if key in existing_set:
            results.append({"status": "skipped", "reason": "duplicate", "content_preview": content[:100]})
            continue

        thread_body = {
            "comments": [
                {
                    "parentCommentId": 0,
                    "content": content,
                    "commentType": 1,
                }
            ],
            "status": 1,
        }
        if file_path:
            thread_body["threadContext"] = {
                "filePath": file_path,
                "rightFileStart": {"line": line, "offset": 1},
                "rightFileEnd": {"line": line, "offset": 1},
            }
        resp = api_post(
            org, project,
            f"/git/repositories/{repo_id}/pullrequests/{pr_id}/threads",
            thread_body,
        )
        results.append({"threadId": resp.get("id"), "status": "posted"})
        existing_set.add(key)  # prevent duplicate within same batch

    posted = sum(1 for r in results if r["status"] == "posted")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    return {"posted": posted, "skipped": skipped, "results": results}


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: azdo_review.py fetch-pr <url> | fetch-diff <url> | fetch-repo-context <url> | fetch-existing-comments <url> | post-comments <url> <comments.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "fetch-pr":
            print(json.dumps(fetch_pr(sys.argv[2]), indent=2))
        elif cmd == "fetch-diff":
            print(json.dumps(fetch_diff(sys.argv[2]), indent=2))
        elif cmd == "fetch-repo-context":
            print(json.dumps(fetch_repo_context(sys.argv[2]), indent=2))
        elif cmd == "fetch-existing-comments":
            print(json.dumps(fetch_existing_comments(sys.argv[2]), indent=2))
        elif cmd == "post-comments":
            print(json.dumps(post_comments(sys.argv[2], sys.argv[3]), indent=2))
        else:
            raise ValueError(f"Unknown command: {cmd}")
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
