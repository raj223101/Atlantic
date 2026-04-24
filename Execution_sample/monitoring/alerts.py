from __future__ import annotations

from dataclasses import dataclass
import time

from core.logger import log


@dataclass(frozen=True)
class AlertRecord:
    code: str
    severity: str
    message: str
    value: float | int | str
    limit: float | int | str
    ts: float

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
            "limit": self.limit,
            "ts": self.ts,
        }


class AlertEngine:
    def __init__(self, cooldown_s: float = 60.0) -> None:
        self.cooldown_s = max(float(cooldown_s), 1.0)
        self._last_emitted: dict[str, float] = {}

    def emit(self, alerts: list[dict]) -> list[AlertRecord]:
        emitted: list[AlertRecord] = []
        now = time.time()
        for alert in alerts:
            code = str(alert.get("code", "UNKNOWN"))
            last_ts = self._last_emitted.get(code, 0.0)
            if now - last_ts < self.cooldown_s:
                continue
            self._last_emitted[code] = now
            record = AlertRecord(
                code=code,
                severity=str(alert.get("severity", "WARNING")),
                message=str(alert.get("message", "")),
                value=alert.get("value", 0),
                limit=alert.get("limit", 0),
                ts=now,
            )
            level = record.severity.upper()
            if level == "CRITICAL":
                log.error(
                    "[MonitorAlert] severity=%s code=%s value=%s limit=%s msg=%s",
                    record.severity,
                    record.code,
                    record.value,
                    record.limit,
                    record.message,
                )
            else:
                log.warning(
                    "[MonitorAlert] severity=%s code=%s value=%s limit=%s msg=%s",
                    record.severity,
                    record.code,
                    record.value,
                    record.limit,
                    record.message,
                )
            emitted.append(record)
        return emitted
