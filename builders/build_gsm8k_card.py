#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the GSM8K evidence pack.

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
- GSM8K: openai/gsm8k (config "main", test split) rev
  cc7b047b6e5bb11b4f1af84efc572db110a51b3c (revision pinned in the task
  source, gsm8k.py: GSM8K_DATASET_REVISION); the solver prompt template
  (MATH_PROMPT_TEMPLATE) is read from gsm8k.py at the same commit and
  encoded verbatim below.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
GSM8K_DATASET = "openai/gsm8k"
GSM8K_REVISION = "cc7b047b6e5bb11b4f1af84efc572db110a51b3c"
GSM8K_SPLIT = "test"
GSM8K_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=openai/gsm8k"
    "&config=main&split=test&offset=0&length=12"
)
# Exact solver prompt template: MATH_PROMPT_TEMPLATE from
# inspect_evals/gsm8k/gsm8k.py at the pinned commit (after the source's
# .strip()). The task's solver is prompt_template(MATH_PROMPT_TEMPLATE)
# over the raw question text, then generate(). Encoded verbatim
# (verified byte-for-byte against the pinned source during pack
# authoring).
GSM8K_PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.

Reasoning:
""".strip()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stable_id(text: str, prefix: str) -> str:
    # inspect_evals.utils.create_stable_id: md5 of the field, 8 hex chars.
    return f"{prefix}_{hashlib.md5(text.encode()).hexdigest()[:8]}"


def build_gsm8k(work: Path) -> Path:
    """Translate the inspect_evals gsm8k task definition (default args)."""
    out = work / "gsm8k"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(GSM8K_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": _stable_id(r["question"], "gsm8k"),
                "prompt": GSM8K_PROMPT_TEMPLATE.replace("{prompt}", r["question"]),
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "GSM8K via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of 1319 problems from "
                    f"{GSM8K_DATASET} (config 'main', test split) "
                    f"rev {GSM8K_REVISION[:12]}. The solver sees the "
                    "question text wrapped in the task's prompt template, "
                    "plus a fewshot system message (see environment "
                    "notes). The final answer is public in the dataset "
                    "(the tail of the 'answer' field, after '####') but "
                    "EXCLUDED here: it is the harness-side sample target "
                    "that the match scorer grades against, which the "
                    "agent never sees. The worked reasoning in the same "
                    "field is likewise harness-side sample metadata for "
                    "test items. Sample = first 12 rows in dataset order "
                    "via the datasets-server rows API; the task applies "
                    "no shuffle to the test split, so this matches the "
                    "task's own sample order."
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
                    "The solver is prompt_template over plain `generate` "
                    "(no tools, no sandbox). With default args the task "
                    "prepends a system message holding 10 fewshot worked "
                    "examples drawn from the TRAIN split (shuffle with "
                    "seed 42, DEFAULT_FEWSHOT_SEED in inspect_evals "
                    "constants): agent-visible by design, train-split "
                    "material containing no test targets. The task "
                    "definition (gsm8k.py) declares no GenerateConfig "
                    "overrides, no agent-visible environment variables, "
                    "and no mounts."
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
                        "inspect_ai.scorer.match (numeric=True): takes "
                        "the value on the final 'ANSWER:' line of the "
                        "completion and numeric-matches it against the "
                        "harness-side target"
                    ),
                    "writable_by_agent": False,
                },
                "tests": ["numeric answer match (ANSWER: line)"],
                "notes": (
                    "match(numeric=True) grades the extracted ANSWER: "
                    "value against the sample target, which lives "
                    "harness-side. Scoring runs harness-side after the "
                    "agent submits; the agent never sees the target and "
                    "has no write path to the scoring. A completion with "
                    "no ANSWER: value scores as incorrect; there is no "
                    "empty-output credit path. No judge model is "
                    "involved: JUDGE-001..006 do not apply."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "benchmark": "GSM8K (Cobbe et al., 2021)",
                "task_definition": "inspect_evals/gsm8k @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["gsm8k.py", "eval.yaml"],
                "dataset": GSM8K_DATASET,
                "dataset_config": "main",
                "dataset_split": GSM8K_SPLIT,
                "dataset_revision": GSM8K_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "MATH_PROMPT_TEMPLATE from inspect_evals gsm8k.py at "
                    "the pinned commit (the task's solver is "
                    "prompt_template(MATH_PROMPT_TEMPLATE) + generate())"
                ),
                "translation": (
                    "mechanical: prompt = MATH_PROMPT_TEMPLATE over the "
                    "raw question text; sample ids reproduce the task's "
                    "create_stable_id(question, prefix='gsm8k'); the "
                    "dataset answer becomes the harness-side sample "
                    "target and is excluded"
                ),
                "excluded": [
                    "answer tail (the final numeric answer after '####' "
                    "in each record's 'answer' field): public in the "
                    "dataset but harness-side; it is the sample target "
                    "the match scorer grades against",
                    "worked reasoning (the rest of the 'answer' field): "
                    "harness-side sample metadata for test items; the "
                    "agent never sees it",
                    "fewshot system message content (10 worked examples "
                    "sampled from the train split with seed 42): "
                    "agent-visible by design and train-split material "
                    "with no test targets, but reproducing it would "
                    "require replicating the task's seeded train-split "
                    "sampling inside this builder; its existence, size, "
                    "and seed are documented in the environment notes",
                ],
                "no_traces": True,
                "generated_by": "builders/build_gsm8k_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"gsm8k: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/gsm8k_work")
    work.mkdir(parents=True, exist_ok=True)
    build_gsm8k(work)
