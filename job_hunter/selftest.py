"""
selftest.py
A minimal, cheap sanity check against the REAL OpenRouter API.

This exists because the unit tests in tests/ mock the API out entirely —
they verify our own logic, but they can't catch an invalid model slug, an
expired key, or a provider outage. Those only show up by actually calling
the API. Run on a schedule (see .github/workflows/openrouter_selftest.yml)
so that class of failure is caught within a day, instead of silently
degrading every report to keyword-only matching for weeks before anyone
notices (which is exactly what happened with the "openrouter/free" bug
this guards against).

Tests the primary AND fallback model separately (rather than just calling
the combined _generate() helper) so the alert can distinguish "primary is
down but the fallback is already covering it — daily bot is fine" from
"both are down — daily bot is actually broken right now". The first one
is exactly what happened on 2026-09-07 when nemotron-3-super started
404ing at the provider level; testing only the combined result would have
reported success and hidden that the primary needed attention.
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OpportunityBot.selftest")


def _try_model(client, model: str) -> tuple[bool, str]:
    """Return (ok, detail) for one real, cheap call to `model`."""
    if not model:
        return False, "no model configured"
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
            temperature=0.0,
        )
        content = (response.choices[0].message.content or "").strip()
        return (True, content) if content else (False, "empty response")
    except Exception as e:
        return False, str(e)


def main() -> int:
    from job_hunter.ai_engine import OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODEL, _get_client
    from job_hunter.config_loader import get_openrouter_api_key, get_gmail_app_password, load_config

    client = _get_client(get_openrouter_api_key())

    primary_ok, primary_detail = _try_model(client, OPENROUTER_MODEL)
    if primary_ok:
        logger.info(f"✅ Primary model OK (model={OPENROUTER_MODEL!r}). Response: {primary_detail!r}")
        return 0

    logger.error(f"❌ Primary model FAILED (model={OPENROUTER_MODEL!r}): {primary_detail}")

    fallback_ok, fallback_detail = _try_model(client, OPENROUTER_FALLBACK_MODEL)

    try:
        config = load_config()
        gmail_pwd = get_gmail_app_password()
        _send_alert(config, gmail_pwd, OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODEL, primary_detail, fallback_ok, fallback_detail)
    except Exception as e:
        logger.error(f"Could not send self-test failure alert: {e}")

    if fallback_ok:
        logger.warning(f"⚠️ Fallback model OK (model={OPENROUTER_FALLBACK_MODEL!r}) — the daily bot is still working via _generate()'s automatic fallback, but the primary needs attention.")
        return 0  # daily runs aren't actually broken; don't fail CI red for a covered issue

    logger.error(f"❌ Fallback model ALSO FAILED (model={OPENROUTER_FALLBACK_MODEL!r}): {fallback_detail}. The daily bot has no working model right now.")
    return 1


def _send_alert(config, gmail_pwd: str, primary: str, fallback: str, primary_detail: str, fallback_ok: bool, fallback_detail: str) -> None:
    from job_hunter.emailer import send_error_alert

    if fallback_ok:
        message = (
            f"Weekly self-test: primary AI model '{primary}' failed ({primary_detail}), "
            f"but the fallback model '{fallback}' is working, and _generate() already "
            "falls back to it automatically — today's daily job hunt should be unaffected. "
            f"Worth updating OPENROUTER_MODEL away from '{primary}' when convenient, since "
            "it's currently dead weight (one extra failed call + wait per request)."
        )
    else:
        message = (
            f"Weekly self-test: BOTH the primary model '{primary}' ({primary_detail}) and "
            f"the fallback model '{fallback}' ({fallback_detail}) failed. AI matching in the "
            "daily job hunt is likely broken right now — check OPENROUTER_API_KEY, and that "
            "OPENROUTER_MODEL/OPENROUTER_FALLBACK_MODEL are still valid, live OpenRouter "
            "model ids (format: vendor/model:free)."
        )

    send_error_alert(config.sender_email, gmail_pwd, config.recipient_email, message)


if __name__ == "__main__":
    sys.exit(main())
