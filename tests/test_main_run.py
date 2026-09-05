"""
Integration-style tests for job_hunter/main.py's run() orchestration.

Every external effect (scraping, the LLM, email, disk I/O) is monkeypatched
out — these tests are about the *control flow* of run(): given a scenario,
does it alert, send a report, or do neither, and does it call the right
thing exactly once?

test_run_alerts_instead_of_silently_exiting_when_ai_totally_fails is a
regression test for a real bug: when every job's AI scoring fell back to
keyword-only matching (because the OpenRouter model id was invalid), the
run used to just exit with no report AND no error alert. This pins that
behavior down so it can't quietly regress.
"""
from job_hunter import main as main_module
from job_hunter.ai_engine import AI_UNAVAILABLE_MARKER


class DummyConfig:
    resume_profiles = ["dummy-profile"]  # only needs to be truthy here
    enabled_sources = {"linkedin": True}
    locations = ["Bengaluru"]
    min_match_percent = 50
    watchlist_companies = []
    sender_email = "sender@example.com"
    recipient_email = "recipient@example.com"
    user_name = "Test User"


def _patch_common(monkeypatch, *, scraped_jobs, batch_match):
    """Wire up the parts of run() that aren't the thing under test."""
    monkeypatch.setattr(main_module, "ensure_dirs", lambda: None)
    monkeypatch.setattr(main_module, "clear_old_entries", lambda days=60: None)
    monkeypatch.setattr(main_module, "load_config", lambda: DummyConfig())
    monkeypatch.setattr(main_module, "get_openrouter_api_key", lambda: "fake-key")
    monkeypatch.setattr(main_module, "get_gmail_app_password", lambda: "fake-pwd")
    monkeypatch.setattr(main_module, "get_serpapi_key", lambda: "")
    monkeypatch.setattr(main_module, "gather_all_roles", lambda config: ["SDE Intern"])
    monkeypatch.setattr(
        main_module, "load_resume_profiles",
        lambda config, key: [("id1", "SDE", {"technical_skills": []})],
    )
    monkeypatch.setattr(main_module, "run_scrapers", lambda config, roles, serpapi_key: list(scraped_jobs))
    monkeypatch.setattr(main_module, "filter_new_jobs", lambda jobs: jobs)
    monkeypatch.setattr(main_module, "batch_match_jobs_against_all_profiles", batch_match)
    monkeypatch.setattr(main_module, "mark_jobs_seen", lambda jobs: None)
    monkeypatch.setattr(main_module, "build_excel", lambda **kw: None)
    monkeypatch.setattr(main_module, "generate_resume_tips", lambda *a, **kw: [])


def test_run_alerts_instead_of_silently_exiting_when_ai_totally_fails(monkeypatch):
    alerts = []
    reports = []

    def fake_batch_match(new_jobs, profiles, key):
        for job in new_jobs:
            job["match_percentage"] = 0
            job["why_good_fit"] = AI_UNAVAILABLE_MARKER

    _patch_common(
        monkeypatch,
        scraped_jobs=[{"company": "Acme", "title": "SDE Intern", "source": "LinkedIn", "description": ""}],
        batch_match=fake_batch_match,
    )
    monkeypatch.setattr(main_module, "send_error_alert", lambda *a, **kw: alerts.append(a))
    monkeypatch.setattr(main_module, "send_report_email", lambda *a, **kw: reports.append(a))

    main_module.run()

    assert len(alerts) == 1, "a total AI failure must trigger exactly one error alert"
    assert not reports, "no report should be sent when every score is a meaningless fallback 0%"
    assert "AI matching failed" in alerts[0][3]


def test_run_sends_report_when_ai_matching_succeeds(monkeypatch):
    alerts = []
    reports = []

    def fake_batch_match(new_jobs, profiles, key):
        for job in new_jobs:
            job["match_percentage"] = 90
            job["why_good_fit"] = "Strong overlap with required skills."
            job["missing_skills"] = []

    _patch_common(
        monkeypatch,
        scraped_jobs=[{"company": "Acme", "title": "SDE Intern", "source": "LinkedIn", "description": ""}],
        batch_match=fake_batch_match,
    )
    monkeypatch.setattr(main_module, "send_error_alert", lambda *a, **kw: alerts.append(a))
    monkeypatch.setattr(main_module, "send_report_email", lambda *a, **kw: reports.append(a))

    main_module.run()

    assert len(reports) == 1, "a genuine match should still produce a report"
    assert not alerts, "no error alert should fire on a normal successful run"


def test_run_returns_quietly_when_no_jobs_pass_threshold_but_ai_worked(monkeypatch):
    """Distinguish 'AI works, nothing scored well today' (fine, no alert)
    from 'AI is broken' (needs an alert) — same empty-report outcome,
    different cause."""
    alerts = []
    reports = []

    def fake_batch_match(new_jobs, profiles, key):
        for job in new_jobs:
            job["match_percentage"] = 10  # genuinely scored, just low
            job["why_good_fit"] = "Missing most required skills."
            job["missing_skills"] = ["Kubernetes"]

    _patch_common(
        monkeypatch,
        scraped_jobs=[{"company": "Acme", "title": "SDE Intern", "source": "LinkedIn", "description": ""}],
        batch_match=fake_batch_match,
    )
    monkeypatch.setattr(main_module, "send_error_alert", lambda *a, **kw: alerts.append(a))
    monkeypatch.setattr(main_module, "send_report_email", lambda *a, **kw: reports.append(a))

    main_module.run()

    assert not alerts
    assert not reports
