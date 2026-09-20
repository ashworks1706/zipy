"""The types datasets, curation and post-training share.

A TrainingExample is one model call: every message that went into it and the reply that came out.
The wire shape is the one the engine already sends to the provider, so an example needs no
translation to be trained on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: What a reviewer can say about one example.
Verdict = Literal["keep", "drop", "fix"]

VERDICTS: tuple[Verdict, ...] = ("keep", "drop", "fix")

#: What a reviewer can answer: a verdict, or leaving the example alone.
Answer = Verdict | Literal["skip", "quit"]


class TrainingExample(BaseModel):
    """One model call, as the engine made it."""

    #: The request the call belongs to, plus its position in that request.
    id: str
    #: The messages sent, in the wire shape the provider received.
    messages: list[dict[str, Any]] = Field(default_factory=list)
    #: What came back.
    reply: str = ""
    #: The tool calls the reply asked for, in the wire shape.
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    org_id: str = ""
    platform: str = ""
    at: datetime | None = None


class Decision(BaseModel):
    """One judgment about one example."""

    id: str
    verdict: Verdict
    reason: str = ""
    #: The reply as it should have been. Set only when the verdict is fix.
    reply: str | None = None
    #: The example as it was judged. A mismatch means the decision no longer describes it.
    fingerprint: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    by: str = ""


class LoraConfig(BaseModel):
    """The adapter."""

    model_config = ConfigDict(extra="forbid")

    r: int
    alpha: int
    dropout: float
    target_modules: list[str]


class TrainConfig(BaseModel):
    """The run."""

    model_config = ConfigDict(extra="forbid")

    epochs: int
    per_device_batch_size: int
    gradient_accumulation: int
    learning_rate: float
    warmup_ratio: float
    logging_steps: int
    seed: int


class SftConfig(BaseModel):
    """configs/train/sft.yaml. An unknown or missing key fails."""

    model_config = ConfigDict(extra="forbid")

    base_model: str
    dataset: Path
    output_dir: Path
    max_seq_length: int
    load_in_4bit: bool
    lora: LoraConfig
    train: TrainConfig


class SftPlan(BaseModel):
    """What a training run would do, printed before it does it."""

    base_model: str
    dataset: Path
    output_dir: Path
    examples: int
    with_tool_calls: int
    max_seq_length: int
    epochs: int


class TrainingError(Exception):
    """A dataset or a training run could not be read, built or started."""
