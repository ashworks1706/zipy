"""Prometheus metrics for the whole process, served at /metrics.

Every metric lives in a registry passed in by wiring, so two engines in one process, or two
tests, never share counts. Labels are plugin and role names, never org ids: per-org numbers live
in Postgres, not in a metrics system every operator can read.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

SECONDS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)


class Metrics:
    """Every metric the engine records."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.messages = Counter(
            "zipy_messages",
            "Messages that reached the gateway.",
            ["platform", "outcome"],
            registry=r,
        )
        self.request_seconds = Histogram(
            "zipy_request_seconds",
            "Time from message to reply.",
            ["platform"],
            buckets=SECONDS,
            registry=r,
        )
        self.model_calls = Counter(
            "zipy_model_calls", "Model calls.", ["role", "outcome"], registry=r
        )
        self.model_seconds = Histogram(
            "zipy_model_call_seconds", "Model call latency.", ["role"], buckets=SECONDS, registry=r
        )
        self.tokens = Counter("zipy_tokens", "Model tokens.", ["role", "kind"], registry=r)
        self.cost_cents = Counter("zipy_cost_cents", "Model spend in cents.", ["role"], registry=r)
        self.tool_calls = Counter(
            "zipy_tool_calls", "Tool executions.", ["tool", "action", "outcome"], registry=r
        )
        self.tool_seconds = Histogram(
            "zipy_tool_seconds", "Tool execution latency.", ["tool"], buckets=SECONDS, registry=r
        )
        self.confirmations = Counter(
            "zipy_confirmations", "Confirmation prompts by how they ended.", ["answer"], registry=r
        )
        self.recalls = Counter("zipy_recalls", "Semantic recall searches.", ["outcome"], registry=r)
        self.jobs = Counter("zipy_jobs", "Background jobs.", ["kind", "outcome"], registry=r)

    def exposition(self) -> tuple[bytes, str]:
        """The registry in Prometheus text format, and its content type."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

    def snapshot(self) -> dict[str, float]:
        """Every sample as name{label=value,...} to value, for the console's metrics pane."""
        samples: dict[str, float] = {}
        for family in self.registry.collect():
            for sample in family.samples:
                if sample.name.endswith("_created"):
                    continue
                labels = ",".join(f"{k}={v}" for k, v in sorted(sample.labels.items()))
                key = f"{sample.name}{{{labels}}}" if labels else sample.name
                samples[key] = float(sample.value)
        return samples
