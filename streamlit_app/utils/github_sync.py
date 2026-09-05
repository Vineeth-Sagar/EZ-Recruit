"""
github_sync.py
Saves config.json and resume PDFs to the GitHub repo via PyGitHub API.
This lets the Streamlit app (hosted on Streamlit Cloud) write to the repo
that GitHub Actions reads from — making the whole loop free and automatic.
"""
import base64
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_repo(pat: str, repo_full_name: str):
    """Return a PyGitHub Repo object."""
    try:
        from github import Github
    except ImportError:
        raise ImportError("PyGitHub not installed. Run: pip install PyGithub")
    g = Github(pat)
    return g.get_repo(repo_full_name)


def push_config(config_dict: dict, pat: str, repo_full_name: str, branch: str = "main") -> bool:
    """Write config.json to the GitHub repo."""
    try:
        repo = _get_repo(pat, repo_full_name)
        content = json.dumps(config_dict, indent=2, ensure_ascii=False)
        encoded = content.encode("utf-8")

        try:
            existing = repo.get_contents("config.json", ref=branch)
            repo.update_file(
                path="config.json",
                message="⚙️ Update config via OpportunityBot App",
                content=encoded,
                sha=existing.sha,
                branch=branch,
            )
        except Exception:
            # File doesn't exist yet — create it
            repo.create_file(
                path="config.json",
                message="⚙️ Initial config via OpportunityBot App",
                content=encoded,
                branch=branch,
            )

        logger.info("[GH Sync] config.json pushed successfully")
        return True

    except Exception as e:
        logger.error(f"[GH Sync] Failed to push config: {e}")
        return False


def push_resume(pdf_bytes: bytes, filename: str, pat: str, repo_full_name: str, branch: str = "main") -> bool:
    """Upload a resume PDF to resumes/ folder in the repo."""
    try:
        repo = _get_repo(pat, repo_full_name)
        path = f"resumes/{filename}"

        try:
            existing = repo.get_contents(path, ref=branch)
            repo.update_file(
                path=path,
                message=f"📄 Update resume: {filename}",
                content=pdf_bytes,
                sha=existing.sha,
                branch=branch,
            )
        except Exception:
            repo.create_file(
                path=path,
                message=f"📄 Upload resume: {filename}",
                content=pdf_bytes,
                branch=branch,
            )

        logger.info(f"[GH Sync] Resume '{filename}' pushed successfully")
        return True

    except Exception as e:
        logger.error(f"[GH Sync] Failed to push resume '{filename}': {e}")
        return False


def delete_resume(filename: str, pat: str, repo_full_name: str, branch: str = "main") -> bool:
    """Delete a resume PDF from the repo."""
    try:
        repo = _get_repo(pat, repo_full_name)
        path = f"resumes/{filename}"
        existing = repo.get_contents(path, ref=branch)
        repo.delete_file(
            path=path,
            message=f"🗑️ Delete resume: {filename}",
            sha=existing.sha,
            branch=branch,
        )
        return True
    except Exception as e:
        logger.error(f"[GH Sync] Failed to delete '{filename}': {e}")
        return False


def list_reports(pat: str, repo_full_name: str, branch: str = "main") -> list:
    """List all Excel report files in data/reports/."""
    try:
        repo = _get_repo(pat, repo_full_name)
        try:
            contents = repo.get_contents("data/reports", ref=branch)
            reports = [
                {
                    "name": c.name,
                    "download_url": c.download_url,
                    "size": c.size,
                    "sha": c.sha,
                }
                for c in contents
                if c.name.endswith(".xlsx")
            ]
            return sorted(reports, key=lambda x: x["name"], reverse=True)
        except Exception:
            return []
    except Exception as e:
        logger.error(f"[GH Sync] Failed to list reports: {e}")
        return []


def trigger_workflow(pat: str, repo_full_name: str, workflow_file: str = "daily_job_hunt.yml", branch: str = "main") -> bool:
    """Manually trigger the GitHub Actions workflow (Test Run feature)."""
    try:
        repo = _get_repo(pat, repo_full_name)
        workflow = repo.get_workflow(workflow_file)
        result = workflow.create_dispatch(ref=branch)
        logger.info("[GH Sync] Workflow triggered successfully")
        return True
    except Exception as e:
        logger.error(f"[GH Sync] Failed to trigger workflow: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# Live run tracking (Test Run page "watch it happen" feature)
#
# These use raw REST calls with the PAT as a bearer token rather than
# PyGithub, specifically so we can reach the jobs/logs endpoints — and
# because it's *your own* PAT (repo-scoped), these succeed where an
# unauthenticated call to the same endpoints gets a 403 requiring admin
# rights.
# ─────────────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"


def _api_headers(pat: str) -> dict:
    return {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}


def get_latest_run(pat: str, repo_full_name: str, workflow_file: str = "daily_job_hunt.yml") -> Optional[dict]:
    """Return the most recent run of this workflow (any status), or None."""
    import requests
    url = f"{GITHUB_API}/repos/{repo_full_name}/actions/workflows/{workflow_file}/runs"
    try:
        resp = requests.get(url, headers=_api_headers(pat), params={"per_page": 1}, timeout=15)
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
        return runs[0] if runs else None
    except Exception as e:
        logger.error(f"[GH Sync] Failed to fetch latest run: {e}")
        return None


def get_run_jobs(pat: str, repo_full_name: str, run_id: int) -> list:
    """Return the jobs (with their steps) for a specific workflow run."""
    import requests
    url = f"{GITHUB_API}/repos/{repo_full_name}/actions/runs/{run_id}/jobs"
    try:
        resp = requests.get(url, headers=_api_headers(pat), timeout=15)
        resp.raise_for_status()
        return resp.json().get("jobs", [])
    except Exception as e:
        logger.error(f"[GH Sync] Failed to fetch run jobs: {e}")
        return []


def get_job_log_tail(pat: str, repo_full_name: str, job_id: int, max_lines: int = 60) -> str:
    """Return the last `max_lines` lines of a job's raw log. Requires a PAT
    with admin rights on the repo — which your own repo-scoped PAT has."""
    import requests
    url = f"{GITHUB_API}/repos/{repo_full_name}/actions/jobs/{job_id}/logs"
    try:
        resp = requests.get(url, headers=_api_headers(pat), timeout=15)
        if resp.status_code != 200:
            return ""
        lines = resp.text.splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception as e:
        logger.error(f"[GH Sync] Failed to fetch job log: {e}")
        return ""
