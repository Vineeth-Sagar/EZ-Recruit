"""
4_🧪_Test_Run.py
Manually trigger the GitHub Actions workflow for an immediate job search —
and actually watch it happen, instead of "check your email in 5-15 minutes".
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from utils.secrets_helper import get_secret
from utils.theme import inject_base_css

sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(page_title="Test Run — OpportunityBot", page_icon="🧪", layout="wide")

inject_base_css()

st.title("🧪 Test Run")
st.caption("Trigger an immediate job search without waiting for tomorrow's scheduled run.")

# ── Status check ─────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config.json"

cfg = {}
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

profiles_count = len(cfg.get("resume_profiles", []))
email_set      = bool(cfg.get("email", {}).get("recipient_email"))

# ── Readiness check ──────────────────────────────────────────
st.subheader("✅ Pre-flight Check")

checks = {
    "At least 1 resume profile added":  profiles_count > 0,
    "Recipient email configured":        email_set,
    "GH_PAT secret available":          bool(get_secret("GH_PAT", "")),
    "GITHUB_REPO secret set":            bool(get_secret("GITHUB_REPO", "")),
    "OPENROUTER_API_KEY secret set":         bool(get_secret("OPENROUTER_API_KEY", "")),
}

all_ready = True
for label, ok in checks.items():
    icon = "✅" if ok else "❌"
    if not ok:
        all_ready = False
    st.markdown(f"{icon} {label}")

st.markdown("---")

# ── Live progress helpers ─────────────────────────────────────
STEP_ICONS = {
    "success":   "✅",
    "failure":   "❌",
    "cancelled": "🚫",
    "skipped":   "⏭️",
}


def _render_run_progress(pat: str, repo: str, run: dict) -> str:
    """Render one snapshot of a run's job/step progress. Returns the run's
    overall status ('queued' | 'in_progress' | 'completed')."""
    from utils.github_sync import get_run_jobs, get_job_log_tail

    status = run.get("status", "queued")
    conclusion = run.get("conclusion")
    run_number = run.get("run_number", "?")

    label = f"Run #{run_number} — {status}"
    if conclusion:
        label += f" ({conclusion})"
    st.caption(label)

    jobs = get_run_jobs(pat, repo, run["id"])
    for job in jobs:
        for step in job.get("steps", []):
            step_conclusion = step.get("conclusion")
            step_status = step.get("status")
            icon = STEP_ICONS.get(step_conclusion) or ("🔄" if step_status == "in_progress" else "⏳")
            st.markdown(f"{icon} {step['name']}")

        if job.get("conclusion") == "failure":
            log_tail = get_job_log_tail(pat, repo, job["id"])
            if log_tail:
                st.error("This run failed. Last lines of the log:")
                st.code(log_tail, language="text")

    if status == "completed":
        if conclusion == "success":
            st.success("✅ Run completed successfully! Check your email for the report.")
        else:
            st.error(f"❌ Run finished with conclusion: **{conclusion}**. See the log above, or check the Actions tab for full detail.")

    return status


@st.fragment(run_every=5)
def _watch_run_fragment():
    from utils.github_sync import get_latest_run

    pat  = get_secret("GH_PAT", "")
    repo = get_secret("GITHUB_REPO", "")
    trigger_time_iso = st.session_state.get("trigger_time_iso")

    run = get_latest_run(pat, repo)
    if not run:
        st.info("Waiting for the run to register on GitHub Actions…")
        return

    # Guard against showing a stale previous run before the new one appears —
    # workflow_dispatch takes a couple seconds to show up in the runs list.
    if trigger_time_iso and run["created_at"] < trigger_time_iso:
        st.info("Waiting for the new run to start…")
        return

    status = _render_run_progress(pat, repo, run)

    if status == "completed":
        st.session_state["watch_run"] = False
        st.session_state["last_run_html_url"] = run.get("html_url", "")
        st.rerun()


# ── Trigger button ───────────────────────────────────────────
if all_ready:
    if not st.session_state.get("watch_run"):
        st.success("🟢 Everything is ready! Click below to run the bot now.")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🚀 Run Bot Now", type="primary", use_container_width=True):
                with st.spinner("Triggering GitHub Actions workflow…"):
                    from utils.github_sync import trigger_workflow
                    pat  = get_secret("GH_PAT", "")
                    repo = get_secret("GITHUB_REPO", "")
                    trigger_time_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    success = trigger_workflow(pat, repo)

                    if success:
                        st.session_state["watch_run"] = True
                        st.session_state["trigger_time_iso"] = trigger_time_iso
                        st.rerun()
                    else:
                        st.error("❌ Could not trigger workflow. Check your GH_PAT permissions (needs `workflow` scope).")

    if st.session_state.get("watch_run"):
        st.subheader("📡 Live Progress")
        repo = get_secret("GITHUB_REPO", "")
        st.caption(f"Polling every 5s — full detail always at `https://github.com/{repo}/actions`")
        _watch_run_fragment()
        if st.button("⏹️ Stop watching"):
            st.session_state["watch_run"] = False
            st.rerun()

    elif st.session_state.get("last_run_html_url"):
        st.info(f"Last watched run: {st.session_state['last_run_html_url']}")

else:
    st.warning("⚠️ Complete the pre-flight checks above before running.")
    if not profiles_count:
        st.info("👉 Go to **📄 Resume Manager** to upload your resume first.")
    if not email_set:
        st.info("👉 Go to **⚙️ Settings** to set your email address.")

# ── Check on a run without triggering a new one ──────────────
# Note: st.expander's `expanded` param is only read when it's created, at
# the top of this run — a plain `if st.button(...)` inside a closed-by-
# default expander re-collapses it on the rerun the click causes, hiding
# the very result the click just produced. Tracking "should be open" in
# session_state and rerunning once avoids that.
st.markdown("---")
if "show_run_check_results" not in st.session_state:
    st.session_state["show_run_check_results"] = False

with st.expander(
    "📡 Check the most recent run (without starting a new one)",
    expanded=st.session_state["show_run_check_results"],
):
    if st.button("🔄 Refresh latest run status"):
        st.session_state["show_run_check_results"] = True
        st.rerun()

    if st.session_state["show_run_check_results"]:
        pat  = get_secret("GH_PAT", "")
        repo = get_secret("GITHUB_REPO", "")
        if not (pat and repo):
            st.warning("GH_PAT and GITHUB_REPO secrets are required for this.")
        else:
            from utils.github_sync import get_latest_run
            run = get_latest_run(pat, repo)
            if not run:
                st.info("No runs found yet.")
            else:
                _render_run_progress(pat, repo, run)

# ── Alternative: run locally ─────────────────────────────────
st.markdown("---")
with st.expander("🖥️ Alternatively: Run locally on your machine"):
    st.markdown("""
    If you're running this app locally, you can run the bot directly in your terminal:

    ```bash
    # From the OpportunityBot project root:
    set OPENROUTER_API_KEY=your_key_here
    set GMAIL_APP_PASSWORD=your_app_password
    python job_hunter/main.py
    ```

    The Excel report will be saved to `data/reports/` and emailed to you.
    """)

# ── Schedule info ────────────────────────────────────────────
st.markdown("---")
st.subheader("⏰ Automatic Schedule")
send_time = cfg.get("email", {}).get("send_time_ist", "07:00")
st.info(f"""
The bot runs automatically every day at **{send_time} IST** via GitHub Actions.
No action needed — it runs in the background even when this app is closed.

To change the time → **⚙️ Settings** → Daily Email Time
""")
