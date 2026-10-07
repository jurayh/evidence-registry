#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the MATH evidence pack.

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

One modeling decision is specific to this pack and is documented in
PROVENANCE.json ("grader_modeling"): the task ships THREE scorers, one
of which (expression_equivalance) is model-graded by default. The
evalwarden grader record is singular, so the artifact models the
grader by that model-graded component (kind "judge") and describes the
two deterministic scorers in the verifier path and notes.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
- MATH: DigitalLearningGmbH/MATH-lighteval (config "default", test
  split) rev 0530c78699ea5e8eb5530600900e1f328b48acad (revision pinned
  in the task source, math.py: MATH_DATASET_REVISION); the solver
  prompt template (USER_PROMPT_TEMPLATE) and the three scorers are read
  from inspect_evals/math/math.py and inspect_evals/math/utils.py at
  the same commit; the template is encoded verbatim below.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
MATH_DATASET = "DigitalLearningGmbH/MATH-lighteval"
MATH_REVISION = "0530c78699ea5e8eb5530600900e1f328b48acad"
MATH_SPLIT = "test"
MATH_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset="
    "DigitalLearningGmbH/MATH-lighteval&config=default&split=test"
    "&offset=0&length=12"
)
# Exact solver prompt template: USER_PROMPT_TEMPLATE from
# inspect_evals/math/math.py at the pinned commit. The task's solver is
# prompt_template(USER_PROMPT_TEMPLATE) over the raw problem text, then
# generate() (fewshot defaults to 0). Encoded verbatim (verified
# byte-for-byte against the pinned source during pack authoring).
MATH_PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stable_id(text: str, prefix: str) -> str:
    # inspect_evals.utils.create_stable_id: md5 of the field, 8 hex chars.
    return f"{prefix}_{hashlib.md5(text.encode()).hexdigest()[:8]}"


def build_math(work: Path) -> Path:
    """Translate the inspect_evals math task definition (default args)."""
    out = work / "math"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(MATH_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": _stable_id(r["problem"], "math"),
                "prompt": MATH_PROMPT_TEMPLATE.replace("{prompt}", r["problem"]),
                "metadata": {
                    # record_to_sample transforms in math/utils.py.
                    "level": r["level"].lower().lstrip("level "),
                    "subject": r["type"].lower(),
                },
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "MATH via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of 5000 problems from "
                    f"{MATH_DATASET} (config 'default', test split) "
                    f"rev {MATH_REVISION[:12]}. The solver sees only the "
                    "problem text wrapped in the task's prompt template. "
                    "The worked solution is public in the dataset but "
                    "EXCLUDED here: the sample target (the final "
                    "\\boxed expression in the solution) is derived from "
                    "it harness-side, and the agent never sees either. "
                    "Sample = first 12 rows in dataset order via the "
                    "datasets-server rows API; the task loads the test "
                    "split with shuffle=True and no seed, so runtime "
                    "sample order varies run to run and this sample "
                    "illustrates the instrument, not a particular eval "
                    "draw."
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
                    "(no tools, no sandbox); fewshot defaults to 0. The "
                    "task definition (math.py) declares "
                    "GenerateConfig(temperature=0.5), no agent-visible "
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
                "kind": "judge",
                "verifier": {
                    "path": (
                        "inspect_evals.math.math ships three scorers over "
                        "the extracted final ANSWER: expression_exact_match "
                        "(deterministic string equivalence after "
                        "normalization) and expression_exact_match_sympy "
                        "(sympy equivalence), both compared against the "
                        "harness-side target, plus the model-graded "
                        "expression_equivalance recorded in the judge block"
                    ),
                    "writable_by_agent": False,
                },
                "judge": {
                    # Default of expression_equivalance(model=grader_model)
                    # with grader_model unset: score_helper calls
                    # get_model(None), the model under evaluation.
                    "model": (
                        "the model under evaluation (expression_equivalance "
                        "resolves get_model() with grader_model unset by "
                        "default; -T grader_model can pin a different one)"
                    ),
                    "protocol": "pointwise",
                    "temperature": 0.5,
                    "repeats": 1,
                    "rubric_criteria": [
                        "expression equivalence: judge whether the "
                        "extracted final answer and the target expression "
                        "are equivalent, answering only Yes or No "
                        "(EQUIVALANCE_TEMPLATE in inspect_evals/math/utils.py)"
                    ],
                    # No scale_anchors: the judgment is a binary yes/no,
                    # not an anchored scalar scale.
                    "scale_anchors": {},
                },
                "tests": [
                    "expression equivalence judgment (model, yes/no)",
                    "exact string equivalence (deterministic)",
                    "sympy equivalence (deterministic)",
                ],
                "notes": (
                    "Hybrid grader, modeled by its model-graded "
                    "component: evalwarden's grader record is singular, "
                    "so kind is 'judge' because one of the task's three "
                    "scorers (expression_equivalance, listed first in "
                    "math.py) delegates the verdict to a model. The "
                    "JUDGE-001 findings attach to that scorer only; the "
                    "other two scorers are deterministic comparisons "
                    "against the harness-side target and need no "
                    "calibration. The definition ships no labeled "
                    "calibration set and no scale anchors for the "
                    "equivalence judgment, and the judgment is sampled "
                    "once at the task's GenerateConfig temperature 0.5. "
                    "All scoring runs harness-side after the agent "
                    "submits; the agent never sees the target and has "
                    "no write path to the scoring. A completion with no "
                    "extractable ANSWER: scores as incorrect under all "
                    "three scorers; there is no empty-output credit "
                    "path."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "benchmark": "MATH (Hendrycks et al., 2021)",
                "task_definition": "inspect_evals/math @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["math.py", "utils.py", "eval.yaml"],
                "dataset": MATH_DATASET,
                "dataset_config": "default",
                "dataset_split": MATH_SPLIT,
                "dataset_revision": MATH_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "USER_PROMPT_TEMPLATE from inspect_evals math.py at "
                    "the pinned commit (the task's solver is "
                    "prompt_template(USER_PROMPT_TEMPLATE) + generate())"
                ),
                "translation": (
                    "mechanical: prompt = USER_PROMPT_TEMPLATE over the "
                    "raw problem text; sample ids reproduce the task's "
                    "create_stable_id(problem, prefix='math'); level and "
                    "subject metadata reproduce record_to_sample's "
                    "transforms; the worked solution becomes the source "
                    "of the harness-side sample target and is excluded"
                ),
                "grader_modeling": (
                    "The task ships three scorers; one "
                    "(expression_equivalance) is model-graded by default "
                    "(the model under evaluation judges equivalence when "
                    "grader_model is unset). evalwarden's grader record "
                    "is singular, so the artifact models the grader by "
                    "that component (kind 'judge', judge block) and "
                    "documents the two deterministic scorers in the "
                    "verifier path, tests list, and grader notes. The "
                    "JUDGE-001 findings therefore attach to the "
                    "equivalence scorer only."
                ),
                "excluded": [
                    "solution (the worked solution per problem, "
                    "including its final \\boxed answer): public in the "
                    "dataset but harness-side; the sample target is "
                    "derived from it and the agent never sees it"
                ],
                "no_traces": True,
                "generated_by": "builders/build_math_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"math: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/math_work")
    work.mkdir(parents=True, exist_ok=True)
    build_math(work)
