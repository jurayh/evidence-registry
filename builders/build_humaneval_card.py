#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the HumanEval evidence pack.

This script translates a PUBLIC, downloadable eval definition into
evalwarden's artifact format (dataset.json / environment.json /
grader.json) WITHOUT inventing anything:

- Only facts present in the public sources are encoded. Anything the
  definition does not say is left out, and the omission is documented in
  PROVENANCE.json next to the artifact.
- No traces are fabricated: there is no run.json. Checks that need run
  records simply do not fire.
- Answer-bearing and scoring material is EXCLUDED from the translated
  artifact even though it is public: the integrity question is whether
  the AGENT can see it, and the task definition keeps the canonical
  solution and the unit tests harness-side. The exclusions are
  documented.

It follows the conventions of builders/build_aime2025_card.py in this
repository (itself modeled on the evalwarden repo's build_real_cards.py):
same artifact schema version, same definition-sample size (12), same
note/exclusion style. It ships in this repository so the pack and its
builder land in one commit; the pack pins this file by content hash.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
- HumanEval: openai/openai_humaneval (test split, the dataset's sole
  config) rev 7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544 (revision pinned
  in the task source, humaneval.py: HUMANEVAL_DATASET_REVISION); the
  instruction prefix (INSTRUCTION) and the verify scorer are read from
  humaneval.py at the same commit; the prefix is encoded verbatim
  below.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
HUMANEVAL_DATASET = "openai/openai_humaneval"
HUMANEVAL_REVISION = "7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544"
HUMANEVAL_SPLIT = "test"
# The task loads the dataset with no config name (it has a single
# config); the datasets-server names that config after the dataset.
HUMANEVAL_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset="
    "openai/openai_humaneval&config=openai_humaneval&split=test"
    "&offset=0&length=12"
)
# Exact instruction prefix: INSTRUCTION from inspect_evals/humaneval/
# humaneval.py at the pinned commit. record_to_sample prepends it to the
# record's prompt field with no added separator. Encoded verbatim
# (verified byte-for-byte against the pinned source during pack
# authoring, including its leading and trailing newlines).
HUMANEVAL_INSTRUCTION = """
Read the following function signature and docstring, and fully implement
the function described. Your response should only contain the code for
this function.\n
"""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_humaneval(work: Path) -> Path:
    """Translate the inspect_evals humaneval task definition (default args)."""
    out = work / "humaneval"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(HUMANEVAL_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": r["task_id"],
                "prompt": HUMANEVAL_INSTRUCTION + r["prompt"],
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "HumanEval via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of 164 problems from "
                    f"{HUMANEVAL_DATASET} (test split) "
                    f"rev {HUMANEVAL_REVISION[:12]}. The solver sees the "
                    "task's instruction prefix plus the function "
                    "signature and docstring. The canonical solution and "
                    "the unit tests are public in the dataset but "
                    "EXCLUDED here: both are harness-side (the solution "
                    "is the sample target; the tests are the scoring "
                    "material), and the agent never sees either. Sample "
                    "= first 12 rows in dataset order via the "
                    "datasets-server rows API; the task applies no "
                    "shuffle, so this matches the task's own sample "
                    "order."
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
                    "The solver is plain `generate` (no tools). The "
                    "task declares a docker sandbox (sandbox='docker' "
                    "in humaneval.py), but it is the harness-side "
                    "verification environment the scorer executes tests "
                    "in, not agent tooling: the agent gets no sandbox "
                    "access, no environment variables, and no mounts."
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
                        "inspect_evals.humaneval.verify: extracts the "
                        "code block from the completion, concatenates "
                        "the sample prompt + submission + harness-side "
                        "test code + a check(entry_point) call, and "
                        "executes it with python in the task's docker "
                        "sandbox (30s timeout); process success = CORRECT"
                    ),
                    "writable_by_agent": False,
                },
                "tests": ["execution of harness-side unit tests (check(entry_point))"],
                "notes": (
                    "Execution grading stays harness-side: the tests "
                    "and the check invocation are fixed by the task "
                    "definition, the agent's submission enters only as "
                    "the function body under test, and the agent has "
                    "no write path to the tests, the sandbox image, or "
                    "the scoring code. The unit tests and the canonical "
                    "solution are excluded from this artifact because "
                    "the agent never sees them. An empty or "
                    "non-implementing completion fails the check call; "
                    "there is no empty-output credit path. humaneval.py "
                    "also declares NUM_EPOCHS = 5, but the Task it "
                    "builds sets no epochs, so no repeat structure "
                    "exists to encode. No judge model is involved: "
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
                "benchmark": "HumanEval (Chen et al., 2021)",
                "task_definition": "inspect_evals/humaneval @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["humaneval.py", "eval.yaml"],
                "dataset": HUMANEVAL_DATASET,
                "dataset_config": "openai_humaneval (sole config; the task passes no config name)",
                "dataset_split": HUMANEVAL_SPLIT,
                "dataset_revision": HUMANEVAL_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "INSTRUCTION from inspect_evals humaneval.py at the "
                    "pinned commit, prepended to the record's prompt "
                    "field exactly as record_to_sample does"
                ),
                "translation": (
                    "mechanical: prompt = INSTRUCTION + record prompt; "
                    "ids are the dataset task_id values; the canonical "
                    "solution (sample target) and the unit tests "
                    "(scoring material) are harness-side and excluded"
                ),
                "excluded": [
                    "canonical_solution (the reference implementation "
                    "per problem): public in the dataset but "
                    "harness-side; it is the sample target",
                    "test (the unit-test code per problem): public in "
                    "the dataset but harness-side scoring material, "
                    "executed against the submission at scoring time; "
                    "the agent never sees it",
                ],
                "no_traces": True,
                "generated_by": "builders/build_humaneval_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"humaneval: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/humaneval_work")
    work.mkdir(parents=True, exist_ok=True)
    build_humaneval(work)
