#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the HellaSwag evidence pack.

This script translates a PUBLIC, downloadable eval definition into
evalwarden's artifact format (dataset.json / environment.json /
grader.json) WITHOUT inventing anything:

- Only facts present in the public sources are encoded. Anything the
  definition does not say is left out, and the omission is documented in
  PROVENANCE.json next to the artifact.
- No traces are fabricated: there is no run.json. Checks that need run
  records simply do not fire.
- Answer-bearing material is EXCLUDED from the translated artifact even
  though it is public: the integrity question is whether the AGENT can
  see it, and the task definition keeps the answer harness-side as the
  sample target. The exclusion is documented.

It follows the conventions of builders/build_aime2025_card.py in this
repository (itself modeled on the evalwarden repo's build_real_cards.py):
same artifact schema version, same definition-sample size (12), same
note/exclusion style. It ships in this repository so the pack and its
builder land in one commit; the pack pins this file by content hash.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
- HellaSwag: Rowan/hellaswag (validation split) rev
  218ec52e09a7e7462a5400043bb9a69a41d06b76 (revision pinned in the task
  source, hellaswag.py: HELLASWAG_DATASET_REVISION). The task passes no
  dataset config name, so the dataset's default config is loaded. The
  task's solver is system_message(SYSTEM_MESSAGE) then inspect_ai's
  multiple_choice with its default SINGLE_ANSWER template; the template
  text and choice formatting are read from inspect_ai 0.3.277
  (solver/_multiple_choice.py) and encoded verbatim below. Sample ids
  reproduce the task's create_stable_id (inspect_evals
  utils/deps_utils.py: md5 of the fields joined by a null byte, 8 hex
  chars, prefixed).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
HELLASWAG_DATASET = "Rowan/hellaswag"
HELLASWAG_CONFIG = "default"
HELLASWAG_REVISION = "218ec52e09a7e7462a5400043bb9a69a41d06b76"
HELLASWAG_SPLIT = "validation"
HELLASWAG_TOTAL = 10042
HELLASWAG_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=Rowan/hellaswag"
    "&config=default&split=validation&offset=0&length=12"
)
# The task's SYSTEM_MESSAGE constant (hellaswag.py), prepended as a
# system message by the system_message solver. The constant is
# newline-wrapped in the source; its text is:
HELLASWAG_SYSTEM_MESSAGE_TEXT = "Choose the most plausible continuation for the story."
# Exact solver prompt template: MultipleChoiceTemplate.SINGLE_ANSWER
# (SINGLE_ANSWER_TEMPLATE) from inspect_ai's
# src/inspect_ai/solver/_multiple_choice.py (0.3.277), the default for
# multiple_choice() with a single correct answer. Choice lines follow
# that module's answer_options(): "A) text", letters comma-joined.
# Encoded verbatim (verified byte-for-byte against the source during
# pack authoring).
HELLASWAG_PROMPT_TEMPLATE = (
    "Answer the following multiple choice question. The entire content of "
    "your response should be of the following format: 'ANSWER: $LETTER' "
    "(without quotes) where LETTER is one of {letters}.\n"
    "\n"
    "{question}\n"
    "\n"
    "{choices}"
)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stable_id(*fields: str, prefix: str) -> str:
    # inspect_evals.utils.create_stable_id: md5 of the fields joined by
    # a null byte, first 8 hex chars, prefixed.
    combined = "\0".join(str(f) for f in fields)
    return f"{prefix}_{hashlib.md5(combined.encode()).hexdigest()[:8]}"


def _format_hellaswag_prompt(ctx: str, endings: list[str]) -> str:
    letters = ",".join(chr(ord("A") + i) for i in range(len(endings)))
    choice_lines = "\n".join(
        f"{chr(ord('A') + i)}) {c}" for i, c in enumerate(endings)
    )
    return HELLASWAG_PROMPT_TEMPLATE.format(
        letters=letters, question=ctx, choices=choice_lines
    )


def build_hellaswag(work: Path) -> Path:
    """Translate the inspect_evals hellaswag task definition (default args)."""
    out = work / "hellaswag"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(HELLASWAG_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": _stable_id(r["ctx"], r["source_id"], prefix="hellaswag"),
                "prompt": _format_hellaswag_prompt(r["ctx"], r["endings"]),
                "metadata": {
                    # record_to_sample metadata in hellaswag.py.
                    "source_id": r["source_id"],
                },
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "HellaSwag via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of {HELLASWAG_TOTAL} "
                    f"items from {HELLASWAG_DATASET} (config "
                    f"'{HELLASWAG_CONFIG}', validation split, the task's "
                    f"default) rev {HELLASWAG_REVISION[:12]}. The solver "
                    "sees the formatted multiple-choice item (context "
                    "plus four candidate endings) under a one-line "
                    "system message (see environment notes). The label "
                    "is public in the dataset but EXCLUDED here: it is "
                    "the harness-side sample target that choice() "
                    "grades against, which the agent never sees. Sample "
                    "= first 12 rows in dataset order via the "
                    "datasets-server rows API; the task applies no "
                    "shuffle at default args (shuffle=False) and "
                    "multiple_choice does not shuffle choices by "
                    "default, so this matches the task's own sample "
                    "and choice order."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "environment.json").write_text(
        json.dumps(
            {
                "env": {},
                "mounts": [],
                "notes": (
                    "The solver chain is system_message then "
                    "multiple_choice over plain `generate` (no tools, "
                    "no sandbox). The system message is the task's "
                    "SYSTEM_MESSAGE constant, agent-visible by design; "
                    "its entire text is: \""
                    + HELLASWAG_SYSTEM_MESSAGE_TEXT
                    + "\" (newline-wrapped in the source). The task "
                    "definition (hellaswag.py) declares no "
                    "GenerateConfig overrides, no agent-visible "
                    "environment variables, and no mounts."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "grader.json").write_text(
        json.dumps(
            {
                "kind": "script",
                "verifier": {
                    "path": (
                        "inspect_ai.scorer.choice: parses the model's "
                        "selected letter from the completion and "
                        "compares it to the harness-side target letter"
                    ),
                    "writable_by_agent": False,
                },
                "tests": ["letter-match (target letter per item)"],
                "notes": (
                    "choice() grades the selected letter against the "
                    "sample target (the letter of the record's label "
                    "index), which lives harness-side. Scoring runs "
                    "harness-side after the agent submits; the agent "
                    "never sees the target and has no write path to "
                    "the scoring. Completions with no parseable letter "
                    "score as incorrect; there is no empty-output "
                    "credit path. No judge model is involved: "
                    "JUDGE-001..006 do not apply."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "benchmark": "HellaSwag (Zellers et al., 2019)",
                "task_definition": "inspect_evals/hellaswag @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": [
                    "hellaswag.py",
                    "eval.yaml",
                    "utils/deps_utils.py (create_stable_id)",
                ],
                "dataset": HELLASWAG_DATASET,
                "dataset_config": HELLASWAG_CONFIG,
                "dataset_split": HELLASWAG_SPLIT,
                "dataset_revision": HELLASWAG_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "MultipleChoiceTemplate.SINGLE_ANSWER from inspect_ai "
                    "0.3.277 src/inspect_ai/solver/_multiple_choice.py; "
                    "choice lines per that module's answer_options(); "
                    "system message is the SYSTEM_MESSAGE constant in "
                    "hellaswag.py at the pinned commit"
                ),
                "translation": (
                    "mechanical: prompt = SINGLE_ANSWER template over "
                    "ctx + lettered endings in dataset order; sample "
                    "ids reproduce the task's create_stable_id(ctx, "
                    "source_id, prefix='hellaswag'); source_id metadata "
                    "reproduces record_to_sample; the dataset label "
                    "becomes the harness-side sample target letter and "
                    "is excluded"
                ),
                "excluded": [
                    "label (the index of the correct ending per item): "
                    "public in the dataset but harness-side; it is the "
                    "sample target that choice() grades against"
                ],
                "no_traces": True,
                "generated_by": "builders/build_hellaswag_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"hellaswag: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/hellaswag_work")
    work.mkdir(parents=True, exist_ok=True)
    build_hellaswag(work)
