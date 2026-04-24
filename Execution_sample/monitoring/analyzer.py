from __future__ import annotations

from dataclasses import dataclass

from monitoring.config import MonitorConfig


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    alerts: list[dict]
    recommendations: list[str]
    safe_mode_suggested: bool

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "alerts": list(self.alerts),
            "recommendations": list(self.recommendations),
            "safe_mode_suggested": self.safe_mode_suggested,
        }


class MetricsAnalyzer:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config

    def analyze(self, snapshot: dict) -> AnalysisResult:
        alerts: list[dict] = []
        recommendations: list[str] = []

        tick = snapshot.get("tick_health", {})
        latency = snapshot.get("latency", {})
        api = snapshot.get("api", {})
        signal = snapshot.get("signal", {})
        resources = snapshot.get("resources", {})

        queue_size = tick.get("queue_size", {}).get("latest", 0.0)
        tick_delay = tick.get("delay_ms", {}).get("p95", 0.0)
        end_to_end_p95 = latency.get("end_to_end_ms", {}).get("p95", 0.0)
        api_failure_pct = api.get("summary", {}).get("failure_pct", 0.0)
        signal_fill_rate = signal.get("fill_rate_pct", 0.0)
        signal_total = signal.get("generated_total", 0)
        cpu_pct = resources.get("cpu_pct", 0.0)
        memory_mb = resources.get("memory_mb", 0.0)

        severity_score = 0

        if end_to_end_p95 > self.config.latency_limit_ms:
            severity_score += 2
            alerts.append(
                {
                    "code": "LATENCY_P95_HIGH",
                    "severity": "WARNING",
                    "message": f"P95 latency is {end_to_end_p95:.1f} ms",
                    "value": round(end_to_end_p95, 2),
                    "limit": self.config.latency_limit_ms,
                }
            )
            recommendations.append("Reduce load or reduce strategies if latency stays elevated.")

        if queue_size > self.config.queue_limit:
            severity_score += 3
            alerts.append(
                {
                    "code": "QUEUE_OVERLOAD",
                    "severity": "CRITICAL",
                    "message": f"Tick queue size is {queue_size:.0f}",
                    "value": int(queue_size),
                    "limit": self.config.queue_limit,
                }
            )
            recommendations.append("Queue overloaded. Reduce strategies or investigate slow stages.")

        if tick_delay > self.config.tick_delay_limit_ms:
            severity_score += 2
            alerts.append(
                {
                    "code": "TICK_DELAY_HIGH",
                    "severity": "WARNING",
                    "message": f"Tick delay P95 is {tick_delay:.1f} ms",
                    "value": round(tick_delay, 2),
                    "limit": self.config.tick_delay_limit_ms,
                }
            )
            recommendations.append("Data is arriving late. Check websocket health and queue depth.")

        if api_failure_pct > self.config.api_failure_limit_pct:
            severity_score += 3
            alerts.append(
                {
                    "code": "API_FAILURE_RATE",
                    "severity": "CRITICAL",
                    "message": f"API failure rate is {api_failure_pct:.1f}%",
                    "value": round(api_failure_pct, 2),
                    "limit": self.config.api_failure_limit_pct,
                }
            )
            recommendations.append("API unstable. Prefer shadow mode or reduce execution load.")

        if signal_total >= self.config.no_fill_signal_limit and signal_fill_rate <= 0.0:
            severity_score += 2
            alerts.append(
                {
                    "code": "NO_FILLS_DESPITE_SIGNALS",
                    "severity": "WARNING",
                    "message": f"{signal_total} signals produced without fills",
                    "value": int(signal_total),
                    "limit": self.config.no_fill_signal_limit,
                }
            )
            recommendations.append("No fills despite signals. Check execution path, broker, or symbol availability.")

        if cpu_pct > self.config.cpu_warn_pct:
            severity_score += 1
            alerts.append(
                {
                    "code": "CPU_HIGH",
                    "severity": "WARNING",
                    "message": f"CPU usage is {cpu_pct:.1f}%",
                    "value": round(cpu_pct, 2),
                    "limit": self.config.cpu_warn_pct,
                }
            )

        if memory_mb > self.config.memory_warn_mb:
            severity_score += 1
            alerts.append(
                {
                    "code": "MEMORY_HIGH",
                    "severity": "WARNING",
                    "message": f"Memory usage is {memory_mb:.1f} MB",
                    "value": round(memory_mb, 2),
                    "limit": self.config.memory_warn_mb,
                }
            )

        status = "STABLE"
        if severity_score >= 5:
            status = "UNSTABLE"
        elif severity_score >= 2:
            status = "WARNING"

        if status == "UNSTABLE" and not recommendations:
            recommendations.append("System unstable. Consider safe mode and reduce runtime load.")

        return AnalysisResult(
            status=status,
            alerts=alerts,
            recommendations=list(dict.fromkeys(recommendations)),
            safe_mode_suggested=status == "UNSTABLE",
        )
