"""Outbound delivery for Smart Alerts.

In-app alerts are always stored in the configured database. Optional Telegram delivery uses
server-side credentials supplied through environment variables. No token is
ever written to the repository, the database, the browser or the logs.

Delivery runs on a background daemon thread with a bounded queue, so a slow or
unreachable Bot API can never stall a scan or a page render. If delivery is
switched on without credentials, the result is reported as unavailable — MNZ
never pretends a message was sent.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from database.database import Database

TELEGRAM_TOKEN_ENV = "MNZ_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ENV = "MNZ_TELEGRAM_CHAT_ID"

_QUEUE: "queue.Queue[dict]" = queue.Queue(maxsize=50)
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False

# Delivery outcome and counters, shown in Settings so a silent failure is
# visible. Process-local: it resets when the Streamlit server restarts.
_STATE_LOCK = threading.Lock()
_STATE: dict = {"last": None, "sent": 0, "failed": 0}

_LOG = logging.getLogger(__name__)


def _record(ok: bool, alert_id, error: str = "", user_id: int | None = None) -> None:
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _STATE_LOCK:
        _STATE["last"] = {
            "ok": bool(ok), "alert_id": alert_id, "error": error or "", "at": stamp,
        }
        _STATE["sent" if ok else "failed"] += 1
    if user_id is None:
        return
    try:
        Database().add_delivery_attempt({
            "user_id": user_id, "alert_id": alert_id, "ok": bool(ok),
            "error": error or "", "created_at": stamp,
        })
    except Exception:  # persistence must never break delivery
        _LOG.exception("Could not store delivery attempt")


def delivery_report() -> dict:
    """Current delivery state for Settings: last outcome, counts, queue depth."""
    with _STATE_LOCK:
        last = dict(_STATE["last"]) if _STATE["last"] else None
        sent, failed = _STATE["sent"], _STATE["failed"]
    return {"last": last, "sent": sent, "failed": failed, "pending": _QUEUE.qsize()}


def telegram_config() -> tuple[str, str] | None:
    """Return (token, chat_id) when both are configured, else ``None``."""
    token = (os.environ.get(TELEGRAM_TOKEN_ENV) or "").strip()
    chat = (os.environ.get(TELEGRAM_CHAT_ENV) or "").strip()
    if not token or not chat:
        return None
    return token, chat


def delivery_status() -> dict:
    """Describe delivery availability for Settings (never leaks the token)."""
    configured = telegram_config() is not None
    return {
        "telegram_configured": configured,
        "provider": "Telegram Bot API" if configured else "Not configured",
        "required_env": [TELEGRAM_TOKEN_ENV, TELEGRAM_CHAT_ENV],
    }


def _redact(text: str, token: str) -> str:
    return text.replace(token, "<redacted>") if token else text


def send_telegram(text: str, *, timeout: float = 8.0) -> dict:
    """Send one message synchronously. Returns a result dict; never raises."""
    cfg = telegram_config()
    if cfg is None:
        return {"ok": False, "error": "Telegram credentials are not configured."}
    token, chat_id = cfg
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        return {"ok": bool(body.get("ok")), "error": "" if body.get("ok") else str(body)[:200]}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "error": _redact(f"HTTP {exc.code}: {detail}", token)}
    except Exception as exc:  # network, DNS, timeout
        return {"ok": False, "error": _redact(str(exc) or exc.__class__.__name__, token)}


def _send_alert(alert: dict) -> None:
    text = (
        f"MNZ BOT · {alert.get('title', 'Smart Alert')}\n"
        f"{alert.get('message', '')}\n"
        "DEMO ONLY — simulated levels, not financial advice."
    )
    try:
        result = send_telegram(text)
    except Exception as exc:  # transport code should not raise, but never lose the failure
        token = telegram_config()[0] if telegram_config() else ""
        error = _redact(str(exc) or exc.__class__.__name__, token)
        _record(False, alert.get("id"), error, alert.get("user_id"))
        _LOG.warning("Telegram delivery failed for alert %s: %s", alert.get("id"), error)
        return
    _record(bool(result.get("ok")), alert.get("id"), result.get("error", ""), alert.get("user_id"))
    if not result.get("ok"):
        _LOG.warning(
            "Telegram delivery failed for alert %s: %s",
            alert.get("id"), result.get("error", "unknown error"),
        )


def _worker() -> None:
    """Drain the queue, sending one message at a time. Never raises."""
    while True:
        alert = _QUEUE.get()
        try:
            _send_alert(alert)
        except Exception:  # a delivery problem must not kill the worker
            _LOG.exception("Unexpected Telegram delivery error")
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    with _WORKER_LOCK:
        if not _WORKER_STARTED:
            threading.Thread(target=_worker, name="mnz-alert-delivery", daemon=True).start()
            _WORKER_STARTED = True


def deliver(alert: dict, prefs: dict) -> dict | None:
    """Queue a stored alert for delivery, if enabled.

    Returns immediately: the HTTP call happens on the background worker, so a
    slow or unreachable Telegram API cannot stall a scan. Returns ``None`` when
    delivery is switched off. The in-app alert has already been saved by the
    caller, so a delivery failure never loses it.
    """
    if not prefs.get("telegram"):
        return None
    if telegram_config() is None:
        error = (
            "Telegram delivery is enabled in settings, but the server has no "
            f"{TELEGRAM_TOKEN_ENV} / {TELEGRAM_CHAT_ENV}. The in-app alert was saved."
        )
        _record(False, alert.get("id"), error, alert.get("user_id"))
        return {"ok": False, "skipped": True, "alert_id": alert.get("id"), "error": error}
    _ensure_worker()
    try:
        _QUEUE.put_nowait(alert)
    except queue.Full:
        _LOG.warning("Alert delivery queue is full; alert %s stayed in-app only.", alert.get("id"))
        error = "Alert delivery queue is full; the in-app alert was saved."
        _record(False, alert.get("id"), error, alert.get("user_id"))
        return {"ok": False, "queued": False, "alert_id": alert.get("id"), "error": error}
    return {"ok": True, "queued": True, "alert_id": alert.get("id")}


def send_test_message(user_id: int | None = None, timeout: float = 6.0) -> dict:
    """Queue a manual test message and wait briefly for its outcome.

    Used by the Settings button so the user gets a definite answer instead of
    only a queue acknowledgement. The send itself still happens on the worker.
    """
    if telegram_config() is None:
        error = (
            "Telegram is not configured on this server: set "
            f"{TELEGRAM_TOKEN_ENV} and {TELEGRAM_CHAT_ENV} as app secrets. "
            "Nothing was sent."
        )
        _record(False, "test", error, user_id)
        return {"ok": False, "queued": False, "alert_id": "test", "error": error}
    queued = deliver(
        {
            "id": "test",
            "user_id": user_id,
            "title": "MNZ BOT test message",
            "message": (
                "Manual delivery test from Settings. If you can read this, Smart Alert "
                "delivery is working. No market signal is attached."
            ),
        },
        {"telegram": True},
    )
    if not queued or not queued.get("queued"):
        return queued or {"ok": False, "queued": False, "error": "Test message was not queued."}

    deadline = time.monotonic() + timeout
    while _QUEUE.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)
    report = delivery_report()
    last = report["last"]
    if last and last.get("alert_id") == "test":
        return last
    return {
        "ok": False,
        "queued": True,
        "alert_id": "test",
        "error": "Still queued — the Telegram API is taking longer than expected. "
                 "Check Delivery status again in a moment.",
    }
