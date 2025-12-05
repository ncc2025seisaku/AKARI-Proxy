#!/usr/bin/env python3
"""Disaster-mode scenario runner for AKARI-UDPv2.

This script bundles multiple harsh-network scenarios derived from the
disaster checklist and runs them via udp_load_runner.run_load_test.
Each scenario summary is appended to a JSONL history file so runs
remain auditable and comparable.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from udp_load_runner import build_parser as build_base_parser
from udp_load_runner import run_load_test
from datetime import datetime
from collections import defaultdict


@dataclass(frozen=True)
class Scenario:
    key: str
    description: str
    overrides: dict[str, object]


SCENARIOS: list[Scenario] = [
    Scenario(
        key="baseline_demo",
        description="Baseline sanity: local demo server, no loss/jitter.",
        overrides={"demo_server": True, "requests": 80, "concurrency": 8, "timeout": 3.0},
    ),
    Scenario(
        key="delay_loss_extreme",
        description="3s delay + 20% loss + 300ms jitter (disaster worst-case).",
        overrides={
            "timeout": 10.0,
            "loss_rate": 0.2,
            "jitter": 0.3,
            "requests": 200,
            "concurrency": 16,
            "max_nack_rounds": 6,
            "heartbeat_interval": 0.8,
            "heartbeat_backoff": 1.3,
            "max_retries": 3,
            "initial_retry_delay": 0.6,
            "retry_jitter": 0.05,
        },
    ),
    Scenario(
        key="jitter_spike",
        description="Jitter 350ms spike: reorder/timeout/backoff stability check.",
        overrides={"timeout": 5.0, "jitter": 0.35, "requests": 200, "concurrency": 16},
    ),
    Scenario(
        key="loss_heavy",
        description="25% loss: retry backoff and stability check.",
        overrides={
            "timeout": 8.0,
            "loss_rate": 0.25,
            "requests": 220,
            "concurrency": 20,
            "max_nack_rounds": 6,
            "heartbeat_interval": 0.6,
            "heartbeat_backoff": 1.25,
            "max_retries": 3,
            "initial_retry_delay": 0.5,
            "retry_jitter": 0.05,
        },
    ),
    Scenario(
        key="burst_traffic",
        description="High concurrency burst: PPS and throughput durability.",
        overrides={
            "requests": 800,
            "concurrency": 48,
            "timeout": 6.5,
            "loss_rate": 0.05,
            "max_nack_rounds": 5,
            "heartbeat_interval": 0.6,
            "heartbeat_backoff": 1.2,
            "max_retries": 1,
            "initial_retry_delay": 0.4,
            "retry_jitter": 0.05,
        },
    ),
    Scenario(
        key="multistream_sustained",
        description="Mid-load sustained run: watch for leaks and drift.",
        overrides={"requests": 400, "concurrency": 32, "timeout": 4.5, "jitter": 0.08, "delay": 0.01},
    ),
    Scenario(
        key="flap_drop",
        description="Intermittent drop: 20% loss + small delay to verify recovery.",
        overrides={
            "requests": 150,
            "concurrency": 12,
            "timeout": 7.5,
            "loss_rate": 0.2,
            "delay": 0.02,
            "max_nack_rounds": 6,
            "heartbeat_interval": 0.6,
            "heartbeat_backoff": 1.2,
            "max_retries": 2,
            "initial_retry_delay": 0.4,
            "retry_jitter": 0.05,
        },
    ),
    Scenario(
        key="flap_harsh",
        description="Harsh flap: 1.3s interval blackouts (0.25s) + light loss; focus on recovery.",
        overrides={
            "requests": 200,
            "concurrency": 16,
            "timeout": 7.5,
            "loss_rate": 0.05,
            "flap_interval": 1.3,
            "flap_duration": 0.25,
            "heartbeat_interval": 0.3,
            "max_retries": 10,
            "initial_retry_delay": 0.06,
            "heartbeat_backoff": 1.1,
            "retry_jitter": 0.05,
            "max_nack_rounds": 8,
        },
    ),
    Scenario(
        key="flap_recovery_tuned",
        description="Gentler flap: shorter blackout with heartbeat/retry emphasis.",
        overrides={
            "requests": 200,
            "concurrency": 16,
            "timeout": 7.5,
            "loss_rate": 0.05,
            "flap_interval": 1.3,
            "flap_duration": 0.12,
            "heartbeat_interval": 0.3,
            "heartbeat_backoff": 1.2,
            "max_retries": 10,
            "initial_retry_delay": 0.05,
            "max_nack_rounds": 6,
        },
    ),
    Scenario(
        key="mtu_variation_like",
        description="MTU variation approximation: smaller buffer + mild loss/jitter.",
        overrides={
            "requests": 240,
            "concurrency": 24,
            "timeout": 6.5,
            "buffer_size": 1400,
            "loss_rate": 0.05,
            "jitter": 0.05,
            "max_nack_rounds": 5,
            "heartbeat_interval": 0.5,
            "heartbeat_backoff": 1.2,
            "max_retries": 1,
            "initial_retry_delay": 0.3,
            "retry_jitter": 0.05,
        },
    ),
    Scenario(
        key="gz_large_body",
        description="10MB body via demo server to stress compression/streaming.",
        overrides={
            "requests": 6,
            "concurrency": 2,
            "timeout": 40.0,
            "demo_body_size": 10_000_000,
            "delay": 0.01,
            "max_nack_rounds": 8,
            "heartbeat_interval": 1.0,
            "heartbeat_backoff": 1.5,
            "max_retries": 5,
            "initial_retry_delay": 1.0,
            "retry_jitter": 0.1,
        },
    ),
    Scenario(
        key="sw_fetch_3000_like",
        description="3000-fetch like load with mild loss/jitter.",
        overrides={
            "requests": 3000,
            "concurrency": 120,
            "timeout": 6.5,
            "loss_rate": 0.02,
            "jitter": 0.02,
            "max_nack_rounds": 4,
            "heartbeat_interval": 0.5,
            "heartbeat_backoff": 1.2,
            "max_retries": 2,
            "initial_retry_delay": 0.3,
            "retry_jitter": 0.05,
        },
    ),
]

SCENARIO_MAP = {scenario.key: scenario for scenario in SCENARIOS}


def append_jsonl(path: Path, obj: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(obj, ensure_ascii=False) + "\n")


def build_suite_parser() -> argparse.ArgumentParser:
    parser = build_base_parser()
    parser.description = "AKARI-UDPv2 disaster checklist scenario runner"
    parser.set_defaults(requests=200, concurrency=16, timeout=3.0)
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Scenario key to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="How many times to run the scenario list")
    parser.add_argument("--suite-log", default="logs/disaster_suite_history.jsonl", help="Append-only JSONL for scenario summaries")
    parser.add_argument("--suite-summary", default="logs/disaster_suite_summary.json", help="Aggregated summary JSON (overwritten each run)")
    parser.add_argument("--event-log", default="logs/disaster_suite_events.jsonl", help="Append request-level events to this JSONL")
    parser.add_argument("--no-event-log", action="store_true", help="Disable per-request event logging")
    parser.add_argument(
        "--report",
        default="logs/disaster_report.md",
        help="Write a human-friendly Markdown report after the run (set empty to skip)",
    )
    return parser


def select_scenarios(names: Iterable[str] | None) -> list[Scenario]:
    if not names:
        return SCENARIOS
    missing = [name for name in names if name not in SCENARIO_MAP]
    if missing:
        raise SystemExit(f"Unknown scenario(s): {', '.join(missing)}. Known: {', '.join(SCENARIO_MAP)}")
    return [SCENARIO_MAP[name] for name in names]


def build_run_args(args: argparse.Namespace, scenario: Scenario, event_log: Path | None) -> argparse.Namespace:
    run_args = deepcopy(args)
    for key, value in scenario.overrides.items():
        setattr(run_args, key, value)
    run_args.log_file = str(event_log) if event_log else None
    run_args.summary_file = None
    run_args.log_context = {"scenario": scenario.key}
    run_args.scenario_key = scenario.key
    # ユーザーが --demo-server / --no-demo-server を明示した場合はシナリオのデフォルトより優先
    if args.demo_server is not None:
        run_args.demo_server = args.demo_server
    return run_args


def _latest_records_by_scenario(history_path: Path) -> dict[str, dict[str, object]]:
    """Pick the latest record per scenario from history JSONL."""
    latest: dict[str, dict[str, object]] = {}
    if not history_path.exists():
        return latest
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = obj.get("scenario")
        if not key:
            continue
        ts = obj.get("timestamp", 0)
        if key not in latest or ts > latest[key].get("timestamp", 0):
            latest[key] = obj
    return latest


def _format_ms(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds * 1000:.1f} ms"


def _status_emoji(success: int, timeout: int, error: int, requests: int) -> str:
    if error > 0:
        return "❌"
    if timeout > 0:
        return "⚠️"
    if success == requests:
        return "✅"
    return "⚠️"


def build_markdown_report(*, history_path: Path, run_started_at: float, run_finished_at: float) -> str:
    latest = _latest_records_by_scenario(history_path)
    if not latest:
        return "# Disaster Suite レポート\n\n履歴がありません。"

    scenarios = list(latest.keys())
    scenarios.sort()

    started = datetime.fromtimestamp(run_started_at).isoformat()
    finished = datetime.fromtimestamp(run_finished_at).isoformat()

    lines: list[str] = []
    lines.append(f"# Disaster Suite レポート（最新実行）\n")
    lines.append(f"- 実行開始: {started}")
    lines.append(f"- 実行終了: {finished}")
    sample = next(iter(latest.values()))
    runtime = sample.get("runtime", {})
    lines.append(f"- 接続先: {runtime.get('host', '?')}:{runtime.get('port', '?')} / protocol v{runtime.get('protocol_version', '?')}")
    lines.append(f"- 実行シナリオ数: {len(scenarios)}")
    lines.append("")

    lines.append("## シナリオ別サマリ\n")
    lines.append("| 状態 | シナリオ | 成功/総数 | 成功率 | タイムアウト | エラー | p95遅延 | RPS | 実行時間 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    worst_p95 = ("", 0.0)
    most_timeout = ("", 0)

    for key in scenarios:
        rec = latest[key]
        summary = rec.get("summary", {})
        runtime = rec.get("runtime", {})
        req = int(runtime.get("requests", summary.get("success", 0)))
        success = int(summary.get("success", 0))
        timeout = int(summary.get("timeout", 0))
        error = int(summary.get("error", 0))
        p95 = float(summary.get("latency_p95_sec", 0.0) or 0.0)
        rps = float(summary.get("rps", 0.0) or 0.0)
        elapsed = float(summary.get("elapsed_sec", 0.0) or 0.0)

        success_rate = (success / req * 100) if req else 0.0
        emoji = _status_emoji(success, timeout, error, req)
        lines.append(
            f"| {emoji} | {key} | {success}/{req} | {success_rate:.1f}% | {timeout} | {error} | {_format_ms(p95)} | {rps:.1f} | {elapsed:.3f}s |"
        )

        if p95 > worst_p95[1]:
            worst_p95 = (key, p95)
        if timeout > most_timeout[1]:
            most_timeout = (key, timeout)

    lines.append("")
    lines.append("## ハイライト")
    lines.append(f"- p95 が最も遅いシナリオ: **{worst_p95[0]}** ({worst_p95[1]*1000:.1f} ms)")
    lines.append(f"- タイムアウトが最も多いシナリオ: **{most_timeout[0]}** ({most_timeout[1]} 件)")
    lines.append("")

    lines.append("## 見方")
    lines.append("- ✅: 成功率100% かつエラーなし")
    lines.append("- ⚠️: タイムアウトあり (エラー0)")
    lines.append("- ❌: エラーあり")
    lines.append("- p95遅延: 95%点の応答時間（ミリ秒）")
    lines.append("- RPS: Requests per second（1秒あたり平均完了数）")
    lines.append("")
    return "\n".join(lines)


def extract_runtime(run_args: argparse.Namespace) -> dict[str, object]:
    return {
        "host": run_args.host,
        "port": run_args.port,
        "protocol_version": run_args.protocol_version,
        "requests": run_args.requests,
        "concurrency": run_args.concurrency,
        "timeout": run_args.timeout,
        "loss_rate": run_args.loss_rate,
        "jitter": run_args.jitter,
        "delay": run_args.delay,
        "max_nack_rounds": run_args.max_nack_rounds,
        "flap_interval": run_args.flap_interval,
        "flap_duration": run_args.flap_duration,
        "buffer_size": run_args.buffer_size,
        "heartbeat_interval": run_args.heartbeat_interval,
        "heartbeat_backoff": run_args.heartbeat_backoff,
        "max_retries": run_args.max_retries,
        "initial_retry_delay": run_args.initial_retry_delay,
        "demo_server": run_args.demo_server,
        "urls": run_args.urls,
        "url_file": run_args.url_file,
        "demo_body_size": run_args.demo_body_size,
        "demo_body_file": run_args.demo_body_file,
    }


def main(argv: list[str] | None = None) -> None:
    parser = build_suite_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(name)s: %(message)s")
    event_log_path = None if args.no_event_log else Path(args.event_log)
    history_path = Path(args.suite_log)
    suite_summary_path = Path(args.suite_summary) if args.suite_summary else None

    selected = select_scenarios(args.scenarios)
    all_records: list[dict[str, object]] = []
    started_at = time.time()

    for iteration in range(args.repeat):
        for scenario in selected:
            run_args = build_run_args(args, scenario, event_log_path)
            logging.info("Running scenario=%s iteration=%s", scenario.key, iteration + 1)
            summary = run_load_test(run_args)
            record = {
                "timestamp": time.time(),
                "iteration": iteration + 1,
                "scenario": scenario.key,
                "description": scenario.description,
                "runtime": extract_runtime(run_args),
                "summary": summary,
            }
            append_jsonl(history_path, record)
            all_records.append(record)
            logging.info(
                "Done scenario=%s success=%s timeout=%s error=%s",
                scenario.key,
                summary.get("success"),
                summary.get("timeout"),
                summary.get("error"),
            )

    finished_at = time.time()
    if suite_summary_path:
        suite_summary_path.parent.mkdir(parents=True, exist_ok=True)
        suite_summary_path.write_text(
            json.dumps(
                {"started_at": started_at, "finished_at": finished_at, "records": all_records},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_md = build_markdown_report(
            history_path=Path(args.suite_log),
            run_started_at=started_at,
            run_finished_at=finished_at,
        )
        report_path.write_text(report_md, encoding="utf-8")


if __name__ == "__main__":
    main()
