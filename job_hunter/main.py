"""
main.py
OpportunityBot — Daily Job Hunter Orchestrator
Runs every morning via GitHub Actions cron.
"""
import logging
import sys
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from collections import Counter

# ── Setup logging ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("OpportunityBot")

# ── Path setup ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from job_hunter.config_loader import load_config, get_openrouter_api_key, get_gmail_app_password, get_serpapi_key, ensure_dirs, save_resume_cache
from job_hunter.deduplicator import filter_new_jobs, mark_jobs_seen, clear_old_entries
from job_hunter.ai_engine import (
    parse_resume, batch_match_jobs_against_all_profiles,
    generate_resume_tips, extract_text_from_pdf, compute_resume_hash, AI_UNAVAILABLE_MARKER,
)
from job_hunter.excel_builder import build_excel
from job_hunter.emailer import send_report_email, send_error_alert


def gather_all_roles(config) -> list:
    """Collect all unique target roles across all resume profiles."""
    roles = set()
    for profile in config.resume_profiles:
        roles.update(profile.target_roles)
    # Fallback generic roles if none configured
    if not roles:
        roles = {"Software Engineer", "SDE", "Intern", "Graduate Engineer"}
    return list(roles)


def _build_scraper_tasks(sources: dict, roles: list, locations: list, serpapi_key: str):
    """Build a (name, zero-arg callable) task per enabled source. The import
    happens inside each callable (not at module load time) so one source's
    missing/broken dependency can't prevent the others from running."""
    tasks = []

    if any(sources.get(s) for s in ["linkedin", "indeed", "glassdoor"]):
        def _run_jobspy():
            from job_hunter.scrapers.jobspy_scraper import scrape_jobspy
            return scrape_jobspy(roles, locations, sources)
        tasks.append(("JobSpy", _run_jobspy))

    if sources.get("naukri"):
        def _run_naukri():
            from job_hunter.scrapers.naukri_scraper import scrape_naukri
            return scrape_naukri(roles, locations)
        tasks.append(("Naukri", _run_naukri))

    if sources.get("wellfound"):
        def _run_wellfound():
            from job_hunter.scrapers.wellfound_scraper import scrape_wellfound
            return scrape_wellfound(roles)
        tasks.append(("Wellfound", _run_wellfound))

    if sources.get("internshala"):
        def _run_internshala():
            from job_hunter.scrapers.internshala_scraper import scrape_internshala
            return scrape_internshala(roles, locations)
        tasks.append(("Internshala", _run_internshala))

    if sources.get("unstop"):
        def _run_unstop():
            from job_hunter.scrapers.unstop_scraper import scrape_unstop
            return scrape_unstop(roles)
        tasks.append(("Unstop", _run_unstop))

    if sources.get("cutshort"):
        def _run_cutshort():
            from job_hunter.scrapers.unstop_scraper import scrape_cutshort
            return scrape_cutshort(roles)
        tasks.append(("Cutshort", _run_cutshort))

    if sources.get("yc_jobs"):
        def _run_yc():
            from job_hunter.scrapers.yc_scraper import scrape_yc_jobs
            return scrape_yc_jobs(roles, locations)
        tasks.append(("YC Jobs", _run_yc))

    if sources.get("hackernews"):
        def _run_hn():
            from job_hunter.scrapers.hn_scraper import scrape_hn_hiring
            return scrape_hn_hiring(roles, locations)
        tasks.append(("HackerNews", _run_hn))

    if sources.get("serpapi"):
        def _run_serpapi():
            from job_hunter.scrapers.serpapi_scraper import scrape_serpapi
            return scrape_serpapi(roles, locations, serpapi_key)
        tasks.append(("SerpAPI", _run_serpapi))

    return tasks


def run_scrapers(config, roles: list, serpapi_key: str = "", timeout_per_source: int = 300) -> list:
    """Run all enabled scrapers concurrently and merge results.

    These used to run strictly one after another, so one slow source
    delayed every source behind it — worst case, risking the 45-minute
    GitHub Actions job timeout. Running them in a thread pool bounds total
    wall time to roughly the slowest single source instead of the sum of
    all of them. Each source still gets a soft per-source timeout so one
    stuck call doesn't dominate the run; the GitHub Actions job timeout
    remains the hard backstop if a source ignores its own internal timeout.
    """
    sources = config.enabled_sources
    locations = config.locations
    tasks = _build_scraper_tasks(sources, roles, locations, serpapi_key)

    if not tasks:
        logger.warning("[Main] No sources enabled.")
        return []

    all_jobs = []
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="scraper") as executor:
        future_to_name = {executor.submit(fn): name for name, fn in tasks}
        for future, name in future_to_name.items():
            try:
                jobs = future.result(timeout=timeout_per_source)
                all_jobs.extend(jobs)
                logger.info(f"[Main] {name}: {len(jobs)} jobs")
            except FutureTimeoutError:
                logger.warning(f"[Main] {name} exceeded {timeout_per_source}s — skipping its results for this run.")
            except Exception as e:
                logger.warning(f"[Main] {name} failed: {e}")

    logger.info(f"[Main] Total scraped: {len(all_jobs)} jobs")
    return all_jobs


def load_resume_profiles(config, openrouter_key: str):
    """Load and parse all resume profiles.

    Skips the (LLM-backed) parse entirely when the PDF's content hash
    matches what's cached in config.json from a previous run — resumes
    rarely change day to day, so re-parsing every run was pure wasted
    OpenRouter free-tier quota for an identical result.
    """
    parsed_profiles = []
    for profile_cfg in config.resume_profiles:
        pdf_path = profile_cfg.pdf_path
        if not pdf_path.exists():
            logger.warning(f"[Main] Resume not found: {pdf_path}")
            continue

        current_hash = compute_resume_hash(pdf_path)

        if profile_cfg.extracted_full and profile_cfg.resume_hash == current_hash:
            logger.info(f"[Main] Resume unchanged, using cached parse: {profile_cfg.name}")
            parsed_profiles.append((profile_cfg.id, profile_cfg.name, dict(profile_cfg.extracted_full)))
            continue

        logger.info(f"[Main] Parsing resume: {profile_cfg.name}")
        parsed = parse_resume(pdf_path, openrouter_key)
        if not parsed.get("error"):
            parsed_profiles.append((profile_cfg.id, profile_cfg.name, parsed))
            try:
                save_resume_cache(profile_cfg.id, current_hash, parsed)
            except Exception as e:
                logger.warning(f"[Main] Could not save resume cache for {profile_cfg.name}: {e}")
        else:
            logger.warning(f"[Main] Could not parse resume for {profile_cfg.name}")

    return parsed_profiles


def run():
    """Main orchestration function."""
    start_time = datetime.now()
    today = start_time.strftime("%Y-%m-%d")
    today_display = start_time.strftime("%B %d, %Y")

    logger.info("=" * 60)
    logger.info("🤖 OpportunityBot starting…")
    logger.info(f"📅 Date: {today_display}")
    logger.info("=" * 60)

    # ── Load config & secrets ────────────────────────────────
    ensure_dirs()
    clear_old_entries(days=60)  # Keep DB lean

    try:
        config = load_config()
    except FileNotFoundError as e:
        logger.error(f"Config not found: {e}")
        sys.exit(1)

    try:
        openrouter_key = get_openrouter_api_key()
        gmail_pwd  = get_gmail_app_password()
        serpapi_key = get_serpapi_key()
    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)

    if not config.resume_profiles:
        logger.error("No resume profiles configured. Please set up in the web app first.")
        sys.exit(1)

    # ── Load resume profiles ─────────────────────────────────
    resume_profiles_data = load_resume_profiles(config, openrouter_key)
    if not resume_profiles_data:
        logger.error("No valid resumes found. Check files in resumes/ folder.")
        sys.exit(1)

    # ── Scrape ───────────────────────────────────────────────
    all_roles = gather_all_roles(config)
    logger.info(f"[Main] Target roles: {all_roles}")
    all_jobs = run_scrapers(config, all_roles, serpapi_key)

    if not all_jobs:
        logger.warning("[Main] No jobs found from any source.")
        send_error_alert(
            config.sender_email, gmail_pwd, config.recipient_email,
            "No jobs were found from any source today. Scraper may need maintenance."
        )
        return

    # ── Deduplicate ──────────────────────────────────────────
    new_jobs = filter_new_jobs(all_jobs)
    logger.info(f"[Main] After dedup: {len(new_jobs)} new jobs (of {len(all_jobs)} scraped)")

    if not new_jobs:
        logger.info("[Main] No new jobs today — all already seen. Skipping email.")
        return

    # ── AI Matching ──────────────────────────────────────────
    logger.info(f"[Main] Running AI batch matching for {len(new_jobs)} jobs…")
    
    batch_call_raised = False
    try:
        batch_match_jobs_against_all_profiles(new_jobs, resume_profiles_data, openrouter_key)
    except Exception as e:
        logger.error(f"[Main] Batch matching failed: {e}")
        batch_call_raised = True

    # ── AI outage detection ──────────────────────────────────
    # If every job fell back to keyword scoring (or the batch call blew up
    # entirely), the AI backend is broken — bad/rotated API key, invalid
    # model id, OpenRouter down, etc. Fallback scoring skews toward 0% (it
    # only has whatever the resume parse also managed to extract), so this
    # would otherwise silently look like "no good matches today" and the
    # run exits with no email and no error alert at all.
    ai_completely_failed = batch_call_raised or (
        bool(new_jobs) and
        all(job.get("why_good_fit") == AI_UNAVAILABLE_MARKER for job in new_jobs)
    )
    if ai_completely_failed:
        logger.error("[Main] AI matching failed for every job this run — falling back to an alert instead of a (likely wrong) report.")
        send_error_alert(
            config.sender_email, gmail_pwd, config.recipient_email,
            "AI matching failed for all jobs today, so no report was generated. "
            "This usually means OPENROUTER_API_KEY is missing/expired, the configured "
            "OPENROUTER_MODEL is invalid, or OpenRouter is having an outage. "
            "Check the GitHub Actions logs for the actual API error."
        )
        return

    matched_jobs = []
    all_missing_skills = []

    for job in new_jobs:
        if job.get("match_percentage", 0) >= config.min_match_percent:
            matched_jobs.append(job)
            all_missing_skills.extend(job.get("missing_skills", []))

    logger.info(f"[Main] {len(matched_jobs)} jobs passed {config.min_match_percent}% threshold")

    # ── Watchlist override ───────────────────────────────────
    # Always include watchlist companies regardless of match %
    watchlist_lower = [w.lower() for w in config.watchlist_companies]
    for job in new_jobs:
        if job.get("company", "").lower() in watchlist_lower and job not in matched_jobs:
            job.setdefault("match_percentage", 0)
            job.setdefault("urgency", "LOW")
            matched_jobs.append(job)

    if not matched_jobs:
        logger.info("[Main] No jobs passed the match threshold today.")
        return

    # ── Resume tips ──────────────────────────────────────────
    tips = []
    if all_missing_skills and resume_profiles_data:
        _, _, first_resume = resume_profiles_data[0]
        tips = generate_resume_tips(all_missing_skills, first_resume, openrouter_key)

    # ── Build Excel ──────────────────────────────────────────
    report_path = PROJECT_ROOT / "data" / "reports" / f"jobs_{today}.xlsx"
    try:
        build_excel(
            jobs=matched_jobs,
            watchlist=config.watchlist_companies,
            profile_name=config.user_name or "Student",
            tips=tips,
            output_path=report_path,
        )
    except Exception as e:
        logger.error(f"[Main] Excel build failed: {e}")
        raise

    # ── Send Email ───────────────────────────────────────────
    try:
        send_report_email(
            sender_email=config.sender_email,
            app_password=gmail_pwd,
            recipient_email=config.recipient_email,
            excel_path=report_path,
            jobs=matched_jobs,
            report_date=today_display,
        )
    except Exception as e:
        logger.error(f"[Main] Email failed: {e}")
        raise

    # ── Mark jobs as seen ────────────────────────────────────
    mark_jobs_seen(matched_jobs)

    elapsed = (datetime.now() - start_time).seconds
    logger.info("=" * 60)
    logger.info(f"✅ Done! {len(matched_jobs)} jobs sent. Took {elapsed}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        # Attempt error email
        try:
            cfg = load_config()
            pwd = get_gmail_app_password()
            send_error_alert(cfg.sender_email, pwd, cfg.recipient_email, str(e))
        except Exception:
            pass
        sys.exit(1)
