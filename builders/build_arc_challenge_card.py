#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the ARC-Challenge pack.

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
- ARC: allenai/ai2_arc (config "ARC-Challenge", test split) rev
  210d026faf9955653af8916fad021475a3f00453 (revision pinned in the task
  source, arc.py: ARC_DATASET_REVISION). The task (arc_challenge) uses
  inspect_ai's multiple_choice solver with its default template; the
  template text and choice formatting are read from inspect_ai
  0.3.277 (solver/_multiple_choice.py) and encoded verbatim below.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
ARC_DATASET = "allenai/ai2_arc"
ARC_CONFIG = "ARC-Challenge"
ARC_REVISION = "210d026faf9955653af8916fad021475a3f00453"
ARC_SPLIT = "test"
ARC_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=allenai/ai2_arc"
    "&config=ARC-Challenge&split=test&offset=0&length=12"
)
# Exact solver prompt template: MultipleChoiceTemplate.SINGLE_ANSWER
# (SINGLE_ANSWER_TEMPLATE) from inspect_ai's
# src/inspect_ai/solver/_multiple_choice.py (0.3.277), the default for
# multiple_choice() with a single correct answer. Choice lines follow
# that module's answer_options(): "A) text", letters comma-joined.
# Encoded verbatim (verified byte-for-byte against the source during
# pack authoring).
ARC_PROMPT_TEMPLATE = (
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


def _format_arc_prompt(question: str, choices: list[str]) -> str:
    # Letters and choice lines per answer_options() in inspect_ai's
    # _multiple_choice.py: uppercase letters, "A) text" lines.
    letters = ",".join(chr(ord("A") + i) for i in range(len(choices)))
    choice_lines = "\n".join(
        f"{chr(ord('A') + i)}) {c}" for i, c in enumerate(choices)
    )
    return ARC_PROMPT_TEMPLATE.format(
        letters=letters, question=question, choices=choice_lines
    )


def build_arc_challenge(work: Path) -> Path:
    """Translate the inspect_evals arc_challenge task definition (default args)."""
    out = work / "arc_challenge"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(ARC_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        # record_to_sample zips the record's labels to its texts,
        # preserving dataset order.
        choices = list(dict(zip(r["choices"]["label"], r["choices"]["text"])).values())
        tasks.append(
            {
                "id": r["id"],
                "prompt": _format_arc_prompt(r["question"], choices),
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "ARC-Challenge via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of 1172 questions from "
                    f"{ARC_DATASET} (config '{ARC_CONFIG}', test split) "
                    f"rev {ARC_REVISION[:12]}. The solver sees only the "
                    "formatted multiple-choice question. The answerKey is "
                    "public in the dataset but EXCLUDED here: it is the "
                    "harness-side sample target that choice() grades "
                    "against, which the agent never sees. Sample = first "
                    "12 rows in dataset order via the datasets-server "
                    "rows API; the task applies no shuffle and the "
                    "multiple_choice solver does not shuffle choices by "
                    "default, so this matches the task's own sample and "
                    "choice order."
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
                    "(no tools, no sandbox). The task definition "
                    "(arc.py) declares no GenerateConfig overrides, no "
                    "agent-visible environment variables, and no mounts."
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
                "benchmark": "ARC-Challenge (AI2 Reasoning Challenge, challenge subset; Clark et al., 2018)",
                "task_definition": "inspect_evals/arc (arc_challenge) @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["arc.py", "eval.yaml"],
                "dataset": ARC_DATASET,
                "dataset_config": ARC_CONFIG,
                "dataset_split": ARC_SPLIT,
                "dataset_revision": ARC_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "MultipleChoiceTemplate.SINGLE_ANSWER from inspect_ai "
                    "0.3.277 src/inspect_ai/solver/_multiple_choice.py; "
                    "choice lines per that module's answer_options()"
                ),
                "translation": (
                    "mechanical: prompt = SINGLE_ANSWER template over "
                    "question + lettered choices in dataset order; the "
                    "dataset answerKey becomes the harness-side sample "
                    "target letter and is excluded"
                ),
                "excluded": [
                    "answerKey (the correct choice label per question): "
                    "public in the dataset but harness-side; it is the "
                    "sample target that choice() grades against"
                ],
                "no_traces": True,
                "generated_by": "builders/build_arc_challenge_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"arc_challenge: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/arc_challenge_work")
    work.mkdir(parents=True, exist_ok=True)
    build_arc_challenge(work)
