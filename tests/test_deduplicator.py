"""
Unit tests for job_hunter/deduplicator.py.

Every test runs against a throwaway SQLite file (via the `_isolated_db`
fixture) instead of the real data/seen_jobs.db, so running the suite never
touches your actual dedup state.
"""
import pytest

from job_hunter import deduplicator


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(deduplicator, "DB_PATH", tmp_path / "seen_jobs_test.db")


def test_job_hash_is_case_and_whitespace_insensitive():
    job1 = {"company": "Acme Corp", "title": "SDE Intern", "source": "LinkedIn"}
    job2 = {"company": " acme corp ", "title": " sde intern ", "source": "linkedin"}
    assert deduplicator._job_hash(job1) == deduplicator._job_hash(job2)


def test_job_hash_differs_for_different_jobs():
    job1 = {"company": "Acme", "title": "SDE", "source": "LinkedIn"}
    job2 = {"company": "Acme", "title": "PM", "source": "LinkedIn"}
    assert deduplicator._job_hash(job1) != deduplicator._job_hash(job2)


def test_filter_new_jobs_then_mark_seen_roundtrip():
    jobs = [
        {"company": "Acme", "title": "SDE", "source": "LinkedIn"},
        {"company": "Globex", "title": "PM", "source": "Indeed"},
    ]

    assert deduplicator.filter_new_jobs(jobs) == jobs

    deduplicator.mark_jobs_seen(jobs)

    # Same jobs again -> nothing new.
    assert deduplicator.filter_new_jobs(jobs) == []

    # A genuinely new job still comes through.
    fresh = [{"company": "Initech", "title": "QA", "source": "Naukri"}]
    assert deduplicator.filter_new_jobs(jobs + fresh) == fresh


def test_get_seen_count_reflects_marked_jobs():
    assert deduplicator.get_seen_count() == 0
    deduplicator.mark_jobs_seen([{"company": "Acme", "title": "SDE", "source": "LinkedIn"}])
    assert deduplicator.get_seen_count() == 1


def test_clear_old_entries_does_not_remove_todays_entries():
    deduplicator.mark_jobs_seen([{"company": "Acme", "title": "SDE", "source": "LinkedIn"}])
    deduplicator.clear_old_entries(days=60)
    assert deduplicator.get_seen_count() == 1
