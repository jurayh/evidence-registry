#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the IFEval evidence pack.

This script translates a PUBLIC, downloadable eval definition into
evalwarden's artifact format (dataset.json / environment.json /
grader.json) WITHOUT inventing anything:

- Only facts present in the public sources are encoded. Anything the
  definition does not say is left out, and the omission is documented in
  PROVENANCE.json next to the artifact.
- No traces are fabricated: there is no run.json. Checks that need run
  records simply do not fire.
- Scoring material is EXCLUDED from the translated artifact: the
  structured instruction list and per-instruction kwargs are the
  scorer's harness-side inputs in the task's record_to_sample (the
  agent sees the instructions only as prose inside the prompt). The
  exclusion is documented.

It follows the conventions of builders/build_aime2025_card.py in this
repository (itself modeled on the evalwarden repo's build_real_cards.py):
same artifact schema version, same definition-sample size (12), same
note/exclusion style. It ships in this repository so the pack and its
builder land in one commit; the pack pins this file by content hash.

One property of this benchmark is specific to this pack and is stated
plainly in the grader notes and in PROVENANCE.json
("scorer_dependency"): the task's scorer delegates ALL checking to the
external instruction_following_eval package, which the task requires
at runtime and does NOT version-pin. The pinned task definition
establishes the delegation, the data the scorer is fed, and the
strict/loose protocol; the checking code itself lives outside the
pinned inputs.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
- IFEval: google/IFEval (train split, the dataset's only split) rev
  966cd89545d6b6acfd7638bc708b98261ca58e84 (revision pinned in the task
  source, ifeval.py: IFEVAL_DATASET_REVISION). The task passes no
  dataset config name, so the dataset's default config is loaded. The
  solver is plain generate(): there is no prompt template.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
IFEVAL_DATASET = "google/IFEval"
IFEVAL_CONFIG = "default"
IFEVAL_REVISION = "966cd89545d6b6acfd7638bc708b98261ca58e84"
IFEVAL_SPLIT = "train"
IFEVAL_TOTAL = 541
IFEVAL_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=google/IFEval"
    "&config=default&split=train&offset=0&length=12"
)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_ifeval(work: Path) -> Path:
    """Translate the inspect_evals ifeval task definition (default args)."""
    out = work / "ifeval"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(IFEVAL_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        tasks.append(
            {
                "id": r["key"],
                "prompt": r["prompt"],
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "IFEval via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of {IFEVAL_TOTAL} "
                    f"prompts from {IFEVAL_DATASET} (config "
                    f"'{IFEVAL_CONFIG}', train split, the dataset's "
                    f"only split) rev {IFEVAL_REVISION[:12]}. The "
                    "solver sees only the raw prompt text: plain "
                    "generate, no prompt template, no system message. "
                    "Each record also carries a structured instruction "
                    "list and per-instruction kwargs; in the task's "
                    "record_to_sample those become harness-side sample "
                    "metadata that the scorer checks the completion "
                    "against, so they are EXCLUDED here (the agent "
                    "sees the instructions only as prose inside the "
                    "prompt). Sample = first 12 rows in dataset order "
                    "via the datasets-server rows API; the task "
                    "applies no shuffle, so this matches the task's "
                    "own sample order."
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
                    "The solver is plain `generate` (no prompt "
                    "template, no tools, no sandbox). The task "
                    "definition (ifeval.py) declares no GenerateConfig "
                    "overrides, no agent-visible environment variables, "
                    "and no mounts. The scorer's external runtime "
                    "dependency is harness-side machinery the agent "
                    "cannot see or touch; it is documented in the "
                    "grader notes, not here."
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
                        "inspect_evals.ifeval.instruction_following: "
                        "builds an InputExample from the sample's "
                        "harness-side instruction_id_list and kwargs "
                        "and calls test_instruction_following (strict "
                        "and loose passes) from the external "
                        "instruction_following_eval package"
                    ),
                    "writable_by_agent": False,
                },
                "tests": [
                    "per-instruction constraint checks (strict)",
                    "per-instruction constraint checks (loose)",
                ],
                "notes": (
                    "The checks are deterministic constraint programs "
                    "(word and paragraph counts, required formats, "
                    "keyword presence or absence, case and punctuation "
                    "rules, and similar verifiable instructions), run "
                    "in strict and loose variants; there is no model "
                    "judge: JUDGE-001..006 do not apply. Scoring runs "
                    "harness-side after the agent submits; the agent "
                    "has no write path to the scoring. Caveat, stated "
                    "plainly: the checking code does not live in the "
                    "pinned task definition or in inspect_ai. "
                    "ifeval.py requires the external "
                    "instruction_following_eval package at runtime "
                    "(require_optional_dependency) and does NOT pin "
                    "its version, so the exact checks a run applies "
                    "depend on whatever version of that package is "
                    "installed, which the task definition does not "
                    "record. The scorer also calls "
                    "ensure_nltk_resource() at setup, downloading "
                    "NLTK data at runtime: a second input outside the "
                    "definition. This card's verdict covers the "
                    "definition as pinned, not any particular "
                    "installed version of the external package."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "benchmark": "IFEval (Zhou et al., 2023)",
                "task_definition": "inspect_evals/ifeval @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": ["ifeval.py", "eval.yaml"],
                "dataset": IFEVAL_DATASET,
                "dataset_config": IFEVAL_CONFIG,
                "dataset_split": IFEVAL_SPLIT,
                "dataset_revision": IFEVAL_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "none: the task's solver is plain generate() over "
                    "the raw record prompt"
                ),
                "translation": (
                    "mechanical: prompt = the record's prompt verbatim; "
                    "sample ids are the dataset keys verbatim; the "
                    "record's instruction_id_list and kwargs become "
                    "harness-side sample metadata in record_to_sample "
                    "and are excluded"
                ),
                "scorer_dependency": (
                    "The task's scorer (instruction_following in "
                    "ifeval.py) delegates all checking to the external "
                    "instruction_following_eval package "
                    "(test_instruction_following, strict and loose), "
                    "required at runtime via require_optional_dependency "
                    "and NOT version-pinned by the task definition; the "
                    "scorer also fetches NLTK resources at setup "
                    "(ensure_nltk_resource). This pack encodes only "
                    "what the pinned definition establishes (dataset, "
                    "solver, the delegation, the strict/loose "
                    "protocol); the package's checking code is outside "
                    "the pinned inputs and outside this card's verdict."
                ),
                "excluded": [
                    "instruction_id_list and kwargs (the structured "
                    "list of verifiable instruction ids per prompt and "
                    "their parameters): harness-side scorer inputs in "
                    "record_to_sample; the agent sees the instructions "
                    "only as prose inside the prompt"
                ],
                "no_traces": True,
                "generated_by": "builders/build_ifeval_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"ifeval: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/ifeval_work")
    work.mkdir(parents=True, exist_ok=True)
    build_ifeval(work)
