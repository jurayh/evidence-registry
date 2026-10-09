#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the Winogrande evidence pack.

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
- Winogrande: allenai/winogrande (config "winogrande_xl", the task's
  default dataset_name; validation split) rev
  01e74176c63542e6b0bcb004dcdea22d94fb67b5 (revision pinned in the task
  source, winogrande.py: WINOGRANDE_DATASET_REVISION). The task defines
  its own USER_PROMPT_TEMPLATE in winogrande.py (based on the OpenAI
  simple-evals multiple-choice template); it is encoded verbatim below.
  Choice lines and the letters list follow inspect_ai 0.3.277
  (solver/_multiple_choice.py: answer_options() and prompt()). Sample
  ids reproduce the task's create_stable_id (inspect_evals
  utils/deps_utils.py: md5 of the sentence, 8 hex chars, prefixed). The
  fewshot seed is DEFAULT_FEWSHOT_SEED in inspect_evals/constants.py
  (= 42) at the same commit.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
WINOGRANDE_DATASET = "allenai/winogrande"
WINOGRANDE_CONFIG = "winogrande_xl"
WINOGRANDE_REVISION = "01e74176c63542e6b0bcb004dcdea22d94fb67b5"
WINOGRANDE_SPLIT = "validation"
WINOGRANDE_TOTAL = 1267
WINOGRANDE_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=allenai/winogrande"
    "&config=winogrande_xl&split=validation&offset=0&length=12"
)
# Exact solver prompt template: USER_PROMPT_TEMPLATE from
# inspect_evals/winogrande/winogrande.py at the pinned commit. The
# source builds it by concatenating an f-string (with BLANK_TAG =
# "[BLANK]" substituted) and a plain literal that begins with a space
# and ends with a newline after {choices}; both are preserved here,
# including the trailing newline, which the formatted prompt therefore
# ends with. Encoded verbatim (verified byte-for-byte against the
# pinned source during pack authoring).
WINOGRANDE_PROMPT_TEMPLATE = (
    "Answer the following multiple choice question by choosing the best "
    "logical option to replace the [BLANK]. The entire content of your "
    "response should be of the following format: 'ANSWER: $LETTER' "
    "(without quotes) where LETTER is one of {letters}.\n"
    "\n"
    "{question}\n"
    "{choices}\n"
)
# Fixed header of the fewshot system message:
# SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE in winogrande.py, before the
# sampled examples are substituted. The examples themselves are
# excluded (see PROVENANCE).
WINOGRANDE_FEWSHOT_HEADER = (
    "The following are multiple choice questions, with answers on the "
    "best logical completion to replace [BLANK] by A or B."
)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stable_id(text: str, prefix: str) -> str:
    # inspect_evals.utils.create_stable_id: md5 of the field, 8 hex chars.
    return f"{prefix}_{hashlib.md5(text.encode()).hexdigest()[:8]}"


def _format_winogrande_prompt(sentence_with_blank: str, options: list[str]) -> str:
    letters = ",".join(chr(ord("A") + i) for i in range(len(options)))
    choice_lines = "\n".join(
        f"{chr(ord('A') + i)}) {c}" for i, c in enumerate(options)
    )
    return WINOGRANDE_PROMPT_TEMPLATE.format(
        letters=letters, question=sentence_with_blank, choices=choice_lines
    )


def build_winogrande(work: Path) -> Path:
    """Translate the inspect_evals winogrande task definition (default args)."""
    out = work / "winogrande"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(WINOGRANDE_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = []
    for r in rows:
        # record_to_sample in winogrande.py: the blank marker replaces
        # "_" in the sentence; the two options keep dataset order
        # ("Order is IMP" in the source).
        question = "Sentence: " + r["sentence"].replace("_", "[BLANK]")
        tasks.append(
            {
                "id": _stable_id(r["sentence"], "winogrande"),
                "prompt": _format_winogrande_prompt(
                    question, [r["option1"], r["option2"]]
                ),
                "metadata": {},
            }
        )

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": "Winogrande via inspect_evals",
                "tasks": tasks,
                "notes": (
                    f"Definition sample: {N_SAMPLES} of {WINOGRANDE_TOTAL} "
                    f"items from {WINOGRANDE_DATASET} (config "
                    f"'{WINOGRANDE_CONFIG}', the task's default "
                    f"dataset_name; validation split) rev "
                    f"{WINOGRANDE_REVISION[:12]}. The solver sees the "
                    "formatted item (the sentence with its blank marked "
                    "[BLANK], plus the two candidate completions) under "
                    "a fewshot system message (see environment notes). "
                    "The answer is public in the dataset but EXCLUDED "
                    "here: it is the harness-side sample target that "
                    "choice() grades against, which the agent never "
                    "sees. Sample = first 12 rows in dataset order via "
                    "the datasets-server rows API; the task applies no "
                    "shuffle to the validation split at default args "
                    "(shuffle=False) and multiple_choice is called with "
                    "shuffle=False, so this matches the task's own "
                    "sample and choice order."
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
                    "The solver chain is system_message (fewshot) then "
                    "multiple_choice over plain `generate` (no tools, "
                    "no sandbox). With default args (fewshot=5) the "
                    "task prepends a system message: the fixed header "
                    "\""
                    + WINOGRANDE_FEWSHOT_HEADER
                    + "\" followed by 5 worked examples drawn from the "
                    "TRAIN split of the same config (shuffle with seed "
                    "42, DEFAULT_FEWSHOT_SEED in inspect_evals "
                    "constants): agent-visible by design, train-split "
                    "material containing no validation targets; the "
                    "example content is excluded from this artifact "
                    "(see PROVENANCE). The task definition "
                    "(winogrande.py) declares GenerateConfig"
                    "(max_tokens=64), no agent-visible environment "
                    "variables, and no mounts."
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
                    "sample target (the task maps the record's answer "
                    "\"1\"/\"2\" to letters A/B harness-side). Scoring "
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
                "benchmark": "Winogrande (Sakaguchi et al., 2019), winogrande_xl subset",
                "task_definition": "inspect_evals/winogrande @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": [
                    "winogrande.py",
                    "eval.yaml",
                    "constants.py (DEFAULT_FEWSHOT_SEED = 42)",
                    "utils/deps_utils.py (create_stable_id)",
                ],
                "dataset": WINOGRANDE_DATASET,
                "dataset_config": WINOGRANDE_CONFIG,
                "dataset_split": WINOGRANDE_SPLIT,
                "dataset_revision": WINOGRANDE_REVISION,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "prompt_template_source": (
                    "USER_PROMPT_TEMPLATE from inspect_evals "
                    "winogrande.py at the pinned commit (defined in the "
                    "task file itself); choice lines and letters per "
                    "inspect_ai 0.3.277 solver/_multiple_choice.py "
                    "(answer_options() and prompt())"
                ),
                "translation": (
                    "mechanical: prompt = the task's USER_PROMPT_TEMPLATE "
                    "over 'Sentence: ' + sentence with '_' replaced by "
                    "[BLANK], plus the two lettered options in dataset "
                    "order (record_to_sample's transform); sample ids "
                    "reproduce the task's create_stable_id(sentence, "
                    "prefix='winogrande'); the dataset answer becomes "
                    "the harness-side sample target letter and is "
                    "excluded"
                ),
                "excluded": [
                    "answer (\"1\" or \"2\", the correct option per "
                    "item): public in the dataset but harness-side; "
                    "mapped to the target letter that choice() grades "
                    "against",
                    "fewshot system message content (5 worked examples "
                    "sampled from the train split with seed 42): "
                    "agent-visible by design and train-split material "
                    "with no validation targets, but reproducing it "
                    "would require replicating the task's seeded "
                    "train-split sampling inside this builder; its "
                    "existence, size, seed, and fixed header text are "
                    "documented in the environment notes",
                ],
                "no_traces": True,
                "generated_by": "builders/build_winogrande_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"winogrande: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/winogrande_work")
    work.mkdir(parents=True, exist_ok=True)
    build_winogrande(work)
