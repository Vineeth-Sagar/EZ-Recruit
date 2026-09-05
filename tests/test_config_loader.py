"""
Unit tests for job_hunter/config_loader.py, including the resume-parse
cache added to make load_resume_profiles() skip unchanged PDFs.
"""
import json

import pytest

from job_hunter import config_loader

SAMPLE_CONFIG = {
    "profile": {"name": "Test User", "branch": "CSE", "graduation_year": 2027, "college": ""},
    "email": {"sender_email": "a@example.com", "recipient_email": "b@example.com", "send_time_ist": "07:00"},
    "preferences": {
        "locations": ["Bengaluru"], "job_types": ["Internship"],
        "min_salary_lpa": 0, "min_match_percent": 50, "batch_year": 2027,
    },
    "watchlist_companies": ["Google"],
    "enabled_sources": {"linkedin": True},
    "resume_profiles": [
        {
            "id": "abc123",
            "name": "SDE",
            "filename": "resume.pdf",
            "target_roles": ["SDE Intern"],
            "extracted_skills": [],
            "last_updated": "2026-01-01",
        }
    ],
}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    return path


def test_load_config_parses_basic_fields(config_path):
    cfg = config_loader.load_config()
    assert cfg.user_name == "Test User"
    assert cfg.sender_email == "a@example.com"
    assert cfg.recipient_email == "b@example.com"
    assert cfg.watchlist_companies == ["Google"]
    assert len(cfg.resume_profiles) == 1


def test_resume_profile_cache_fields_default_empty(config_path):
    cfg = config_loader.load_config()
    profile = cfg.resume_profiles[0]
    assert profile.resume_hash == ""
    assert profile.extracted_full == {}


def test_load_config_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "does_not_exist.json")
    with pytest.raises(FileNotFoundError):
        config_loader.load_config()


def test_save_resume_cache_round_trips_and_strips_raw_text(config_path):
    config_loader.save_resume_cache(
        "abc123", "deadbeef",
        {"technical_skills": ["Python"], "_raw_text": "should never be persisted"},
    )

    cfg = config_loader.load_config()
    profile = cfg.resume_profiles[0]
    assert profile.resume_hash == "deadbeef"
    assert profile.extracted_full == {"technical_skills": ["Python"]}
    assert "_raw_text" not in profile.extracted_full


def test_save_resume_cache_unknown_id_is_a_noop(config_path):
    before = config_path.read_text(encoding="utf-8")
    config_loader.save_resume_cache("no-such-profile", "hash", {"a": 1})
    after = config_path.read_text(encoding="utf-8")
    assert before == after
