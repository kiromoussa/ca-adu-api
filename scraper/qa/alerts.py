"""Alerting + qa_alerts persistence for the QA cross-check.

Sends a Slack message (SLACK_WEBHOOK_URL) and/or an email summary, and writes
every discrepancy into the qa_alerts table via the service role. Alerting is
best-effort: a failed Slack post never blocks the DB write.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from .crosscheck import Discrepancy

logger = logging.getLogger(__name__)


class AlertSink:
    """Fan-out for discrepancies: Supabase qa_alerts + Slack + email."""

    def __init__(self, supabase_client: Any) -> None:
        self._client = supabase_client
        self._slack_url = os.environ.get("SLACK_WEBHOOK_URL")
        self._smtp_host = os.environ.get("QA_SMTP_HOST")
        self._smtp_to = os.environ.get("QA_ALERT_EMAIL_TO")

    # ------------------------------------------------------------------
    def _slug_to_city_id(self, cities: list[dict[str, Any]]) -> dict[str, str]:
        return {c["slug"]: c["id"] for c in cities}

    def persist(self, discrepancies: list[Discrepancy], cities: list[dict[str, Any]]) -> int:
        """Insert discrepancies into qa_alerts. Returns rows written."""
        if not discrepancies:
            return 0
        slug_to_id = self._slug_to_city_id(cities)
        rows = [
            {
                "city_id": slug_to_id.get(d.slug),
                "source": d.source,
                "field": d.field,
                "scraped_value": d.scraped_value,
                "hcd_finding": d.hcd_finding,
                "severity": d.severity,
                "resolved": False,
            }
            for d in discrepancies
        ]
        self._client.table("qa_alerts").insert(rows).execute()
        logger.info("Wrote %d qa_alerts rows.", len(rows))
        return len(rows)

    # ------------------------------------------------------------------
    def _format_summary(self, discrepancies: list[Discrepancy]) -> str:
        by_sev: dict[str, int] = {}
        for d in discrepancies:
            by_sev[d.severity] = by_sev.get(d.severity, 0) + 1
        header = "CA ADU QA cross-check: " + ", ".join(f"{n} {sev}" for sev, n in sorted(by_sev.items()))
        lines = [header, ""]
        for d in discrepancies:
            field = f" [{d.field}]" if d.field else ""
            lines.append(f"- ({d.severity}) {d.slug}{field}: {d.hcd_finding}")
        return "\n".join(lines)

    def notify_slack(self, discrepancies: list[Discrepancy]) -> bool:
        if not self._slack_url or not discrepancies:
            return False
        try:
            resp = httpx.post(
                self._slack_url,
                json={"text": self._format_summary(discrepancies)},
                timeout=15.0,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Slack notify failed: %s", exc)
            return False

    def notify_email(self, discrepancies: list[Discrepancy]) -> bool:
        if not self._smtp_host or not self._smtp_to or not discrepancies:
            return False
        try:
            msg = EmailMessage()
            msg["Subject"] = f"CA ADU QA: {len(discrepancies)} discrepancy(ies)"
            msg["From"] = os.environ.get("QA_ALERT_EMAIL_FROM", "qa@ca-adu-api.local")
            msg["To"] = self._smtp_to
            msg.set_content(self._format_summary(discrepancies))
            port = int(os.environ.get("QA_SMTP_PORT", "587"))
            with smtplib.SMTP(self._smtp_host, port, timeout=20) as smtp:
                smtp.starttls()
                user = os.environ.get("QA_SMTP_USER")
                pw = os.environ.get("QA_SMTP_PASSWORD")
                if user and pw:
                    smtp.login(user, pw)
                smtp.send_message(msg)
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Email notify failed: %s", exc)
            return False

    def dispatch(self, discrepancies: list[Discrepancy], cities: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist + notify. Returns a small run report."""
        written = self.persist(discrepancies, cities)
        slacked = self.notify_slack(discrepancies)
        emailed = self.notify_email(discrepancies)
        return {
            "discrepancies": len(discrepancies),
            "qa_alerts_written": written,
            "slack_sent": slacked,
            "email_sent": emailed,
        }
