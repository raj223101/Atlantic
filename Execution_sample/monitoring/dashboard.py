from __future__ import annotations


def _line(label: str, value: str) -> str:
    return f"{label:<18} {value}"


def render_dashboard(snapshot: dict, analysis: dict) -> str:
    tick = snapshot.get("tick_health", {})
    latency = snapshot.get("latency", {})
    api = snapshot.get("api", {})
    signal = snapshot.get("signal", {})
    system = snapshot.get("system", {})
    resources = snapshot.get("resources", {})

    lines = [
        "SYSTEM HEALTH DASHBOARD",
        "",
        _line("Tick Rate:", f"{tick.get('tick_rate_per_sec', 0.0):.1f} ticks/sec"),
        _line("Tick Delay:", f"{tick.get('delay_ms', {}).get('avg', 0.0):.1f} ms avg"),
        _line("Queue Size:", f"{tick.get('queue_size', {}).get('latest', 0.0):.0f}"),
        _line("Queue Wait:", f"{tick.get('queue_wait_ms', {}).get('avg', 0.0):.1f} ms avg"),
        _line("Avg Latency:", f"{latency.get('end_to_end_ms', {}).get('avg', 0.0):.1f} ms"),
        _line("P95 Latency:", f"{latency.get('end_to_end_ms', {}).get('p95', 0.0):.1f} ms"),
        _line("P99 Latency:", f"{latency.get('end_to_end_ms', {}).get('p99', 0.0):.1f} ms"),
        _line("API Success:", f"{api.get('summary', {}).get('success_pct', 0.0):.1f}%"),
        _line("Signal Fill Rate:", f"{signal.get('fill_rate_pct', 0.0):.1f}%"),
        _line("CPU Usage:", f"{resources.get('cpu_pct', 0.0):.1f}%"),
        _line("Memory:", f"{resources.get('memory_mb', 0.0):.1f} MB"),
        "",
        f"STATUS: {analysis.get('status', 'STABLE')}",
    ]

    recommendations = analysis.get("recommendations", [])
    if recommendations:
        lines.append("")
        lines.append("Recommendations:")
        lines.extend(f"- {item}" for item in recommendations[:4])

    alerts = analysis.get("alerts", [])
    if alerts:
        lines.append("")
        lines.append("Active Alerts:")
        lines.extend(
            f"- {item.get('severity', 'INFO')}: {item.get('message', '')}"
            for item in alerts[:5]
        )

    system_mode = system.get("mode")
    if system_mode:
        lines.append("")
        lines.append(_line("Mode:", system_mode))

    return "\n".join(lines)
