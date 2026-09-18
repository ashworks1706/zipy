"""Supervised fine-tuning over the curated set.

The examples are already in the wire shape the provider received, so a conversation is the
messages plus the reply, with no translation. The run writes an adapter; what serves it is a
question for whatever [models.chat] points at, and is not decided here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from training.core.types import SftConfig, SftPlan, TrainingError, TrainingExample


def load_config(path: Path) -> SftConfig:
    """The training config. A missing key or an unknown one is an error."""
    if not path.exists():
        raise TrainingError(f"no training config at {path}")
    try:
        return SftConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise TrainingError(f"{path}: {exc}") from exc


def load_examples(path: Path) -> list[TrainingExample]:
    """The curated set. Empty or missing names the step that fills it."""
    if not path.exists():
        raise TrainingError(f"no dataset at {path}; run data export, verify, review, then curate")
    rows = [
        TrainingExample.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise TrainingError(f"{path} is empty; nothing has been accepted by a reviewer yet")
    return rows


def conversation(example: TrainingExample) -> list[dict[str, Any]]:
    """One example as the message list a chat template renders."""
    turns = list(example.messages)
    reply: dict[str, Any] = {"role": "assistant", "content": example.reply}
    if example.tool_calls:
        reply["tool_calls"] = example.tool_calls
    turns.append(reply)
    return turns


def plan(config_path: Path) -> SftPlan:
    """What a run would do, without doing it."""
    cfg = load_config(config_path)
    examples = load_examples(cfg.dataset)
    return SftPlan(
        base_model=cfg.base_model,
        dataset=cfg.dataset,
        output_dir=cfg.output_dir,
        examples=len(examples),
        with_tool_calls=sum(1 for example in examples if example.tool_calls),
        max_seq_length=cfg.max_seq_length,
        epochs=cfg.train.epochs,
    )


def train(config_path: Path) -> Path:
    """Run the fine-tune and return where the adapter landed. Needs the gpu extra and a GPU."""
    cfg = load_config(config_path)
    examples = load_examples(cfg.dataset)
    try:
        from datasets import Dataset
        from trl import SFTConfig as TrlConfig
        from trl import SFTTrainer
        from unsloth import FastLanguageModel
    except ImportError as exc:
        raise TrainingError("install the gpu extra: uv sync --extra gpu") from exc

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg.base_model,
        max_seq_length=cfg.max_seq_length,
        load_in_4bit=cfg.load_in_4bit,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg.lora.r,
        lora_alpha=cfg.lora.alpha,
        lora_dropout=cfg.lora.dropout,
        target_modules=cfg.lora.target_modules,
        random_state=cfg.train.seed,
    )
    texts = [
        tokenizer.apply_chat_template(conversation(example), tokenize=False) for example in examples
    ]
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=Dataset.from_dict({"text": texts}),
        args=TrlConfig(
            output_dir=str(cfg.output_dir),
            num_train_epochs=float(cfg.train.epochs),
            per_device_train_batch_size=cfg.train.per_device_batch_size,
            gradient_accumulation_steps=cfg.train.gradient_accumulation,
            learning_rate=cfg.train.learning_rate,
            warmup_ratio=cfg.train.warmup_ratio,
            logging_steps=cfg.train.logging_steps,
            seed=cfg.train.seed,
            report_to="tensorboard",
            dataset_text_field="text",
            max_length=cfg.max_seq_length,
        ),
    )
    trainer.train()
    adapter = cfg.output_dir / "adapter"
    model.save_pretrained(str(adapter))
    tokenizer.save_pretrained(str(adapter))
    return adapter
