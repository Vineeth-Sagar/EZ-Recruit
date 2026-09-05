"""
selftest.py
A minimal, cheap sanity check against the REAL OpenRouter API.

This exists because the unit tests in tests/ mock the API out entirely —
they verify our own logic, but they can't catch an invalid model slug, an
expired key, or an OpenRouter outage. Those only show up by actually
calling the API. Run on a schedule (see
.github/workflows/openrouter_selftest.yml) so that class of failure is
caught within a day, instead of silently degrading every report to
keyword-only matching for weeks before anyone notices (which is exactly
what happened with the "openrouter/free" bug this guards against).
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OpportunityBot.selftest")


def main() -> int:
    from job_hunter.ai_engine import OPENROUTER_MODEL, _get_client
    from job_hunter.config_loader import get_openrouter_api_key, get_gmail_app_password, load_config

    content = ""
    try:
        client = _get_client(get_openrouter_api_key())
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
            temperature=0.0,
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"OpenRouter call raised an exception: {e}")

    if content:
        logger.info(f"✅ Self-test passed (model={OPENROUTER_MODEL!r}). Response: {content!r}")
        return 0

    logger.error(f"❌ Self-test FAILED for model={OPENROUTER_MODEL!r} — got an empty response.")
    try:
        config = load_config()
        send_error_alert_if_configured(config, get_gmail_app_password(), OPENROUTER_MODEL)
    except Exception as e:
        logger.error(f"Could not send self-test failure alert: {e}")
    return 1


def send_error_alert_if_configured(config, gmail_pwd: str, model: str) -> None:
    from job_hunter.emailer import send_error_alert
    send_error_alert(
        config.sender_email, gmail_pwd, config.recipient_email,
        f"Weekly OpenRouter self-test failed for model '{model}'. "
        "AI matching in the daily job hunt is likely broken right now — "
        "check that OPENROUTER_API_KEY is valid and OPENROUTER_MODEL is a "
        "real OpenRouter model id (format: vendor/model:free)."
    )


if __name__ == "__main__":
    sys.exit(main())
