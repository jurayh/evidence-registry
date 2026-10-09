#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the MMLU-Pro evidence pack.

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
- MMLU-Pro: TIGER-Lab/MMLU-Pro (test split) rev
  527feea0afed1de15a8c115abf7be4c912123315 (revision pinned in the task
  source, mmlu_pro.py: MMLU_PRO_DATASET_REVISION). The task defines its
  own USER_PROMPT_TEMPLATE (in mmlu_pro.py, based on the lm-evaluation-
  harness MMLU-Pro prompt); it is encoded verbatim below. The task
  passes no dataset config name, so the dataset's default config is
  loaded. Choice lines and the letters list follow inspect_ai 0.3.277
  (solver/_multiple_choice.py: answer_options() and prompt()).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
MMLU_PRO_DATASET = "TIGER-Lab/MMLU-Pro"
MMLU_PRO_CONFIG = "default"
MMLU_PRO_REVISION = "527feea0afed1de15a8c115abf7be4c912123315"
MMLU_PRO_SPLIT = "test"
MMLU_PRO_TOTAL = 12032
MMLU_PRO_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab/MMLU-Pro"
    "&config=default&split=test&offset=0&length=12"
)
# Exact solver prompt template: USER_PROMPT_TEMPLATE from
# inspect_evals/mmlu_pro/mmlu_pro.py at the pinned commit (the source
# applies .strip() to the literal). The task's solver is
# multiple_choice(template=USER_PROMPT_TEMPLATE, shuffle=False).
# Encoded verbatim (verified byte-for-byte against the pinned source
# during pack authoring).
MMLU_PRO_PROMPT_TEMPLATE = """
Answer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}. Think step by step before answering.

Question:
{question}
Options:
{choices}
""".strip()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_mmlu_pro_prompt(question: str, options: list[str]) -> str:
    # Letters and choice lines per answer_options()/prompt() in
    # inspect_ai's _multiple_choice.py: uppercase letters comma-joined,
    # "A) text" lines newline-joined.
    letters = ",".join(chr(ord("A") + i) for i in range(len(options)))
    choice_lines = "\n".join(
        f"{chr(ord('A') + i)}) {c}" for i, c in enumerate(options)
    )
    return MMLU_PRO_PROMPT_TEMPLATE.format(
        letters=letters, question=question, choices=choice_lines
    )


def build_mmlu_pro(work: Path) -> Path:
    """Translate the inspect_evals mmlu_pro task definition (default args)."""
    out = work / "mmlu_pro"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(MMLU_PRO_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": r["question_id"],
                "prompt": _format_mmlu_pro_prompt(r["question"], r["options"]),
                "metadata": {
                    # record_to_sample transform in mmlu_pro.py:
                    # subject is the lowercased dataset category. The
                    # record's cot_content metadata is NOT reproduced:
                    # it is answer-bearing (see PROVENANCE excluded).
                    "subject": r["category"].lower(),
                },
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "MMLU-Pro via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of {MMLU_PRO_TOTAL} "
                    f"questions from {MMLU_PRO_DATASET} (config "
                    f"'{MMLU_PRO_CONFIG}', test split) rev "
                    f"{MMLU_PRO_REVISION[:12]}. The solver sees only the "
                    "formatted multiple-choice question (the task's own "
                    "prompt template over the question and its options, "
                    "which carry 3 to 10 choices per item). The answer "
                    "letter is public in the dataset but EXCLUDED here: "
                    "it is the harness-side sample target that choice() "
                    "grades against, which the agent never sees. Sample "
                    "= first 12 rows in dataset order via the "
                    "datasets-server rows API; the task loads the test "
                    "split with shuffle=True and no seed, so runtime "
                    "sample order varies run to run and this sample "
                    "illustrates the instrument, not a particular eval "
                    "draw. Choice order within an item is NOT shuffled "
                    "(multiple_choice is called with shuffle=False), so "
                    "the lettered options shown match the task's own "
                    "presentation."
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
                    "The solver is multiple_choice over plain `generate` "
                    "(no tools, no sandbox). fewshot defaults to 0, so "
                    "no system message is prepended at default args. "
                    "The task definition (mmlu_pro.py) declares no "
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
                    "sample target, which lives harness-side. Scoring "
                    "runs harness-side after the agent submits; the "
                    "agent never sees the target and has no write path "
                    "to the scoring. Completions with no parseable "
                    "letter score as incorrect; there is no "
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
                "benchmark": "MMLU-Pro (Wang et al., 2024)",
                "task_definition": "inspect_evals/mmlu_pro @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["mmlu_pro.py", "eval.yaml"],
                "dataset": MMLU_PRO_DATASET,
                "dataset_config": MMLU_PRO_CONFIG,
                "dataset_split": MMLU_PRO_SPLIT,
                "dataset_revision": MMLU_PRO_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "USER_PROMPT_TEMPLATE from inspect_evals "
                    "mmlu_pro.py at the pinned commit (defined in the "
                    "task file itself, based on the lm-evaluation-harness "
                    "MMLU-Pro prompt); choice lines and letters per "
                    "inspect_ai 0.3.277 solver/_multiple_choice.py "
                    "(answer_options() and prompt())"
                ),
                "translation": (
                    "mechanical: prompt = the task's USER_PROMPT_TEMPLATE "
                    "over question + lettered options in dataset order; "
                    "sample ids are the dataset question_id values "
                    "verbatim; subject metadata reproduces "
                    "record_to_sample's transform (category lowercased); "
                    "the dataset answer becomes the harness-side sample "
                    "target letter and is excluded"
                ),
                "excluded": [
                    "answer and answer_index (the correct option letter "
                    "and its index per question): public in the dataset "
                    "but harness-side; the answer is the sample target "
                    "that choice() grades against",
                    "cot_content (dataset-carried chain-of-thought text "
                    "that terminates in the answer): answer-bearing "
                    "sample metadata in record_to_sample; the agent "
                    "never sees it",
                ],
                "no_traces": True,
                "generated_by": "builders/build_mmlu_pro_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"mmlu_pro: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/mmlu_pro_work")
    work.mkdir(parents=True, exist_ok=True)
    build_mmlu_pro(work)
