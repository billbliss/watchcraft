"""Run only explicitly approved portal work and explicitly requested PRs."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

REPOSITORY = "billbliss/watchcraft-collections"


def command(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


def cli_args(command_name, *values, config):
    from watchcraft_author import build_parser
    return build_parser().parse_args(["queue", command_name, *values,
        "--operator-token-source", config.operator_token_source,
        "--r2-credentials-source", config.r2_credentials_source])


def publish_preview(work, config, q):
    control = q.operator_client(config.operator_token_source)
    job = control.post("/submissions/get", {"job_id": work["compilation_job_id"]})["job"]
    bundle = q.verified_json_result(job, config.r2_credentials_source)
    collection_id = bundle["manifest"]["collection_id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,199}", collection_id):
        raise ValueError("Collection ID is not a safe publication path")
    branch = "codex/portal-" + hashlib.sha256(work["execution_id"].encode()).hexdigest()[:24]
    repo_info = json.loads(command(["gh", "repo", "view", REPOSITORY, "--json", "defaultBranchRef,isPrivate"]))
    if repo_info["isPrivate"]:
        raise RuntimeError("A public collection repository is required for a loadable preview")
    base = repo_info["defaultBranchRef"]["name"]
    with tempfile.TemporaryDirectory(prefix="watchcraft-portal-") as folder:
        root = Path(folder)
        checkout = root / "repository"
        command(["git", "clone", "--filter=blob:none", "--single-branch", "--branch", base, f"https://github.com/{REPOSITORY}.git", str(checkout)])
        command(["git", "switch", "-c", branch], checkout)
        published = checkout / "collections" / collection_id / "collection.json"
        baseline = ["--published-collection", str(published)] if published.is_file() else []
        candidate = root / "candidate"
        q.run_materialize_project(cli_args("materialize-project", work["compilation_job_id"], "--output-directory", str(candidate), *baseline, config=config))
        publication_args = [*baseline] if baseline else ["--collections-root", str(checkout / "collections")]
        q.run_publish_project(cli_args("publish-project", work["compilation_job_id"], "--candidate-directory", str(candidate), *publication_args, config=config))
        command(["git", "add", "--all"], checkout)
        existing = command(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], checkout)
        if existing:
            command(["git", "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/portal-preview"], checkout)
            # Never replace a preview someone edited after it was published.
            diff = command(["git", "diff", "--cached", "refs/remotes/origin/portal-preview", "--"], checkout)
            if diff:
                raise RuntimeError("The preview branch differs from the verified collection; review it before retrying")
            commit = command(["git", "rev-parse", "refs/remotes/origin/portal-preview"], checkout)
        else:
            command(["git", "-c", "user.name=Watchcraft Authoring", "-c", "user.email=watchcraft-authoring@users.noreply.github.com", "commit", "-m", f"Add collection: {bundle['manifest']['title']}"], checkout)
            commit = command(["git", "rev-parse", "HEAD"], checkout)
            command(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", "push", "origin", f"HEAD:refs/heads/{branch}"], checkout)
        manifest_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/collections/{collection_id}/collection.json"
        # Verify the remote manifest and every bound resource before enabling Load.
        from youtube_discovery import request_text
        remote = json.loads(request_text(manifest_url))
        expected = json.loads((candidate / "collection.json").read_text())
        if remote != expected:
            raise RuntimeError("Published preview manifest does not match the verified candidate")
        from youtube_discovery import request_text
        for item in expected["items"].values():
            relative = item["analysis"]["path"]
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise RuntimeError("Unsafe preview resource path")
            actual = request_text(manifest_url.rsplit("/", 1)[0] + "/" + relative)
            if json.loads(actual) != json.loads((candidate / relative).read_text()):
                raise RuntimeError("Published preview resource does not match the verified candidate")
    return {"preview_url": manifest_url, "preview_branch": branch, "preview_commit": commit}


def submit_pull_request(work):
    branch = work["preview_branch"]
    if not re.fullmatch(r"codex/portal-[a-f0-9]{24}", branch):
        raise ValueError("Invalid preview branch")
    prs = json.loads(command(["gh", "pr", "list", "--repo", REPOSITORY, "--head", branch, "--state", "all", "--json", "url,headRefOid"]))
    if prs:
        matching = [pr for pr in prs if pr["headRefOid"] == work["preview_commit"]]
        if len(matching) != 1:
            raise RuntimeError("The existing pull request has changed; review it before retrying")
        return {"pull_request_url": matching[0]["url"]}
    head = command(["gh", "api", f"repos/{REPOSITORY}/git/ref/heads/{branch}", "--jq", ".object.sha"])
    if head != work["preview_commit"]:
        raise RuntimeError("The preview branch changed after validation")
    base = command(["gh", "repo", "view", REPOSITORY, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"])
    with tempfile.TemporaryDirectory(prefix="watchcraft-pr-") as folder:
        body = Path(folder) / "body.md"
        body.write_text(f"Adds the collection prepared from approved Watchcraft execution `{work['execution_id']}`.\n\nThe collection manifest and analysis resources were validated against the compiled artifact.\n\n[Loadable preview]({work['preview_url']})\n")
        url = command(["gh", "pr", "create", "--repo", REPOSITORY, "--base", base, "--head", branch,
            "--title", f"Add Watchcraft collection ({work['execution']['project']['project_id']})", "--body-file", str(body)])
    return {"pull_request_url": url}


def perform_phase(work, config, q):
    phase = work["phase"]
    plan = work["execution"]["plan"]["job_id"]
    if phase not in {"processing", "pull_request"} and work["execution"]["estimate"].get("planned_items") != len(work["execution"]["selection"]["item_ids"]):
        raise RuntimeError("Collection assembly needs a plan containing only the approved videos")
    if phase == "processing":
        args = cli_args("process-project", "--execution-id", work["execution_id"], "--r2-staging-credentials-source", config.r2_staging_credentials_source, config=config)
        q.run_process_project(args)
    elif phase == "terminology":
        q.run_resolve_project_terminology(cli_args("resolve-project-terminology", "--plan-job-id", plan, config=config))
    elif phase == "normalization":
        q.run_normalize_project(cli_args("normalize-project-topics", "--plan-job-id", plan, config=config))
    elif phase == "compilation":
        result = {}
        q.run_compile_project(cli_args("compile-project", "--plan-job-id", plan, config=config), completed_callback=lambda job: result.update(compilation_job_id=job))
        if not result:
            raise RuntimeError("Compilation returned no verified result")
        return result
    elif phase == "preview":
        return publish_preview(work, config, q)
    elif phase == "pull_request":
        return submit_pull_request(work)
    else:
        raise ValueError("Unsupported workflow phase")
    return {}


def run_portal_worker(config, q, *, stop=None, perform=perform_phase):
    if not 2 <= config.poll_seconds <= 30:
        raise ValueError("Poll interval must be between 2 and 30 seconds")
    stop = stop or threading.Event()
    control = q.operator_client(config.operator_token_source)
    runner = str(uuid.uuid4())
    print("Portal worker starting. Waiting for accepted plans or requested pull requests.", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        while not stop.is_set():
            work = control.post("/portal/claim", {"runner_id": runner})["workflow"]
            if work:
                args = {"execution_id": work["execution_id"], "runner_id": runner, "phase": work["phase"]}
                print(f"Portal workflow: {work['phase']}", flush=True)
                failed = False
                future = pool.submit(perform, work, config, q)
                try:
                    while True:
                        try:
                            result = future.result(timeout=20)
                            break
                        except concurrent.futures.TimeoutError:
                            if future.done():
                                raise
                            control.post("/portal/update", {**args, "event": "heartbeat"})
                    control.post("/portal/update", {**args, "event": "complete", **result})
                except Exception as error:
                    failed = True
                    print(f"Portal workflow stopped: {error}", flush=True)
                    try:
                        control.post("/portal/update", {**args, "event": "failed", "error_message": __import__("youtube_audio").sanitized_diagnostic_text(str(error))[:2000]})
                    except Exception:
                        pass
                if config.once:
                    return 1 if failed else 0
            elif config.once:
                return 0
            if stop.wait(config.poll_seconds):
                break
    return 0
