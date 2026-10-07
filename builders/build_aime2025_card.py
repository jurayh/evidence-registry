#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the AIME 2025 evidence pack.

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

It follows the conventions of the evalwarden repo's build_real_cards.py
(the builder the earlier packs pin): same artifact schema version, same
definition-sample size (12), same note/exclusion style. It ships in this
repository so the pack and its builder land in one commit; the pack pins
this file by content hash.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
- AIME 2025: math-ai/aime25 (config "default", test split) rev
  563bb8404243c5f09de6ec262f2db674fe5bce9b (revision pinned in the task
  source, aime2025.py: AIME2025_DATASET_REVISION); the solver prompt
  template (USER_PROMPT_TEMPLATE) and the scorer are read from
  inspect_evals/utils/aime_common.py at the same commit and encoded
  verbatim below.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
AIME2025_DATASET = "math-ai/aime25"
AIME2025_REVISION = "563bb8404243c5f09de6ec262f2db674fe5bce9b"
AIME2025_SPLIT = "test"
AIME2025_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=math-ai/aime25"
    "&config=default&split=test&offset=0&length=12"
)
# Exact solver prompt template: USER_PROMPT_TEMPLATE from
# inspect_evals/utils/aime_common.py at the pinned commit. The task's
# solver is prompt_template(USER_PROMPT_TEMPLATE) over the raw problem
# text, then generate(). Encoded verbatim (verified byte-for-byte
# against the pinned source during pack authoring).
AIME2025_PROMPT_TEMPLATE = """
Solve the following math problem step by step.
The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_aime2025(work: Path) -> Path:
    """Translate the inspect_evals aime2025 task definition (default args)."""
    out = work / "aime2025"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(AIME2025_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": r["id"],
                "prompt": AIME2025_PROMPT_TEMPLATE.replace("{prompt}", r["problem"]),
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "AIME 2025 via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of 30 problems from "
                    f"{AIME2025_DATASET} (config 'default', test split) "
                    f"rev {AIME2025_REVISION[:12]}. The solver sees only "
                    "the problem text wrapped in the task's prompt "
                    "template. The answer is public in the dataset but "
                    "EXCLUDED here: it is the harness-side sample target "
                    "that the aime scorer matches against, which the "
                    "agent never sees. Sample = first 12 rows in dataset "
                    "order via the datasets-server rows API; the task "
                    "applies no dataset-level shuffle, so this matches "
                    "the task's own sample order."
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
                    "(no tools, no sandbox). The task definition "
                    "(aime2025.py) declares no GenerateConfig overrides, "
                    "no agent-visible environment variables, and no "
                    "mounts."
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
                        "inspect_evals.utils.aime_common.aime_scorer: takes "
                        "the last substantive line of the completion, "
                        "strips any \\boxed wrapper, and numeric-matches "
                        "it against the harness-side target answer"
                    ),
                    "writable_by_agent": False,
                },
                "tests": ["numeric answer match (final line)"],
                "notes": (
                    "The aime scorer grades the extracted final-line "
                    "answer against the sample target, which lives "
                    "harness-side. Scoring runs harness-side after the "
                    "agent submits; the agent never sees the target and "
                    "has no write path to the scoring. An empty "
                    "completion scores as incorrect; there is no "
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
                "benchmark": "AIME 2025 (American Invitational Mathematics Examination, 2025)",
                "task_definition": "inspect_evals/aime2025 @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["aime2025.py", "eval.yaml", "utils/aime_common.py"],
                "dataset": AIME2025_DATASET,
                "dataset_config": "default",
                "dataset_split": AIME2025_SPLIT,
                "dataset_revision": AIME2025_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "USER_PROMPT_TEMPLATE from inspect_evals "
                    "utils/aime_common.py at the pinned commit (the "
                    "task's solver is prompt_template(USER_PROMPT_TEMPLATE) "
                    "+ generate())"
                ),
                "translation": (
                    "mechanical: prompt = USER_PROMPT_TEMPLATE over the "
                    "raw problem text; the dataset answer becomes the "
                    "harness-side sample target and is excluded"
                ),
                "excluded": [
                    "answer (the integer answer per problem): public in "
                    "the dataset but harness-side; it is the sample "
                    "target that the aime scorer matches against"
                ],
                "no_traces": True,
                "generated_by": "builders/build_aime2025_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"aime2025: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/aime2025_work")
    work.mkdir(parents=True, exist_ok=True)
    build_aime2025(work)
