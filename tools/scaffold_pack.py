#!/usr/bin/env python3
"""Scaffold a new evidence-pack builder for an inspect_evals task.

Usage:
    python3 tools/scaffold_pack.py <task_name> [--out DIR] [--force]

Example:
    python3 tools/scaffold_pack.py gsm8k
    python3 tools/scaffold_pack.py wmdp_bio --out /tmp/scaffold_wmdp

What this does:
- Resolves the task in the pinned inspect_evals source (v0.23.0,
  commit bd59dd3b48974ad2e91219a6ceed41011e201163) by fetching the
  task's module directory listing, its main task file, and its
  eval.yaml from raw.githubusercontent.com at that commit.
- Derives everything that is mechanically derivable from those pinned
  files: the HF dataset path / config / split / revision (from the
  task's own hf_dataset call), the datasets-server rows URL, the task
  files a pack would pin, the split's row count, and the build
  function / file naming every existing builder follows.
- Checks the dataset is public via the HuggingFace API and REFUSES to
  scaffold a gated dataset: a pack whose inputs need auth is invalid
  by the registry's founding rule.
- Writes builders/build_<task>_card.py from the house template with
  the derived constants filled in and every judgment field (grader
  modeling, exclusions, the record-to-sample mapping, prompt-template
  verification, notes prose) left as a TODO constant. The generated
  builder REFUSES TO RUN while any TODO is unresolved, so a
  scaffolded pack can never pass verify_pack.py by accident.
- Prints the README row and gallery article stubs plus the checklist
  of human steps that remain.

What this does NOT do: it does not write prose, model graders, decide
exclusions, or assemble evidence-pack.json. Those are the judgment
core of a pack; the scaffold only removes the mechanical shell around
them. Stdlib only, like verify_pack.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
INSPECT_EVALS_REPO = "UKGovernmentBEIS/inspect_evals"
RAW_BASE = (
    f"https://raw.githubusercontent.com/{INSPECT_EVALS_REPO}/{INSPECT_EVALS_COMMIT}"
)
API_BASE = f"https://api.github.com/repos/{INSPECT_EVALS_REPO}"
TASK_ROOT = "src/inspect_evals"
N_SAMPLES = 12
UA = {"User-Agent": "evidence-registry-scaffold/1.0"}


def get_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str):
    return json.loads(get_bytes(url).decode("utf-8"))


def get_text(url: str) -> str:
    return get_bytes(url).decode("utf-8")


class ScaffoldError(Exception):
    pass


# --------------------------------------------------------------------------
# Task resolution in the pinned inspect_evals source
# --------------------------------------------------------------------------

def list_dir(path: str) -> list[str]:
    data = get_json(f"{API_BASE}/contents/{path}?ref={INSPECT_EVALS_COMMIT}")
    if not isinstance(data, list):
        raise ScaffoldError(f"unexpected listing for {path}: {str(data)[:200]}")
    return [entry["name"] for entry in data]


def resolve_module(task: str) -> str:
    """Find the inspect_evals module directory that defines <task>.

    Exact directory first (agentharm -> agentharm); otherwise the
    longest directory name that prefixes the task (wmdp_bio -> wmdp).
    """
    try:
        names = list_dir(f"{TASK_ROOT}/{task}")
        if names:
            return task
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    dirs = [n for n in list_dir(TASK_ROOT)]
    prefixes = sorted(
        (d for d in dirs if task.startswith(d + "_")), key=len, reverse=True
    )
    if prefixes:
        return prefixes[0]
    raise ScaffoldError(
        f"no inspect_evals module directory resolves task {task!r} "
        f"(tried exact dir and underscore prefixes)"
    )


def parse_eval_yaml(text: str) -> dict:
    """Extract the few eval.yaml fields the scaffold needs.

    Hand-parsed (stdlib only): the file's structure is regular --
    a tasks list with name/dataset_samples pairs and an
    external_assets list with huggingface sources.
    """
    tasks: dict[str, int | None] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^\s+-\s*name:\s*(\S+)\s*$", line)
        if m:
            current = m.group(1)
            tasks.setdefault(current, None)
            continue
        m = re.match(r"^\s+dataset_samples:\s*(\d+)\s*$", line)
        if m and current is not None:
            tasks[current] = int(m.group(1))
    hf_source = None
    m = re.search(
        r"type:\s*huggingface\s*\n\s*source:\s*(\S+)", text
    )
    if m:
        hf_source = m.group(1)
    title = None
    m = re.search(r"^title:\s*'([^']+)'", text, re.M)
    if m:
        title = m.group(1)
    return {"tasks": tasks, "hf_source": hf_source, "title": title}


# --------------------------------------------------------------------------
# Task source parsing (deliberately shallow: derive only what is explicit)
# --------------------------------------------------------------------------

def _balanced(text: str, start: int) -> tuple[str, int]:
    """Return (text inside parens, index after close) for the '(' at start."""
    depth = 0
    quote = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    raise ScaffoldError("unbalanced parentheses while parsing task source")


def _split_kwargs(argtext: str) -> dict[str, str]:
    """Split a call's argument text into {name: raw_value} for named args."""
    parts: list[str] = []
    depth = 0
    quote = None
    cur = ""
    for ch in argtext:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    kwargs: dict[str, str] = {}
    for part in parts:
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", part, re.S)
        if m:
            kwargs[m.group(1)] = m.group(2).strip()
    return kwargs


def _string_value(raw: str, constants: dict[str, str]):
    """Resolve a raw kwarg value to a string literal or a known constant."""
    raw = raw.strip()
    m = re.match(r'^"([^"]*)"$', raw) or re.match(r"^'([^']*)'$", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        return constants.get(raw)
    return None


def parse_task_source(src: str) -> dict:
    constants: dict[str, str] = {}
    for m in re.finditer(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([^"]*)"', src, re.M):
        constants[m.group(1)] = m.group(2)

    revisions: dict[str, str] = {}
    for m in re.finditer(
        r'^([A-Z][A-Z0-9_]*REVISION)\s*=\s*"([0-9a-f]{40})"', src, re.M
    ):
        revisions[m.group(1)] = m.group(2)

    hf_calls: list[dict] = []
    for m in re.finditer(r"hf_dataset\s*\(", src):
        argtext, _ = _balanced(src, m.end() - 1)
        kwargs = _split_kwargs(argtext)
        call = {"raw_kwargs": kwargs}
        for key in ("path", "name", "data_dir", "split", "revision", "limit"):
            if key in kwargs:
                call[key] = _string_value(kwargs[key], constants)
                call[key + "_raw"] = kwargs[key]
        hf_calls.append(call)

    task_fns: list[str] = []
    for m in re.finditer(r"@task\s*\ndef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", src):
        task_fns.append(m.group(1))

    rts = None
    m = re.search(r"^def record_to_sample\(.*?(?=^\S|\Z)", src, re.M | re.S)
    if m:
        rts = m.group(0).rstrip()

    scorer_imports: list[str] = []
    m = re.search(r"from inspect_ai\.scorer import ([^\n]+)", src)
    if m:
        scorer_imports = [s.strip() for s in m.group(1).split(",")]

    return {
        "constants": constants,
        "revisions": revisions,
        "hf_calls": hf_calls,
        "task_fns": task_fns,
        "record_to_sample_src": rts,
        "scorer_imports": scorer_imports,
    }


def function_span(src: str, name: str) -> str | None:
    m = re.search(rf"^def {re.escape(name)}\(.*?(?=^\S|\Z)", src, re.M | re.S)
    return m.group(0) if m else None


def choose_dataset_call(parsed: dict, src: str, task: str, evidence: list[str]):
    """Pick the hf_dataset call that loads the task's own dataset.

    Auxiliary calls (fewshot: a limit= kwarg or a train split) are set
    aside. If exactly one candidate remains it is derived. A config
    passed as a bare parameter is resolved through the literal the
    task function passes to its helper (the wmdp create_task pattern).
    Anything else returns None and becomes a TODO with evidence.
    """
    candidates = []
    for call in parsed["hf_calls"]:
        if "limit_raw" in call or call.get("split") == "train":
            evidence.append(
                "auxiliary hf_dataset call set aside "
                f"(split={call.get('split')!r}, limit={call.get('limit_raw')!r})"
            )
            continue
        candidates.append(call)
    if len(candidates) != 1:
        evidence.append(
            f"{len(candidates)} candidate hf_dataset calls for the task "
            "dataset; cannot choose mechanically"
        )
        return None
    call = dict(candidates[0])
    config = call.get("name") or call.get("data_dir")
    if config is None and ("name_raw" in call or "data_dir_raw" in call):
        raw = call.get("name_raw") or call.get("data_dir_raw")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw or ""):
            # Parameterized config: find which enclosing function holds
            # the call and what literal the task function passes it.
            for fn_match in re.finditer(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", src, re.M):
                span = function_span(src, fn_match.group(1))
                if span and "hf_dataset(" in span and raw in span:
                    task_span = function_span(src, task) or ""
                    lit = re.search(
                        rf"{re.escape(fn_match.group(1))}\(\s*\"([^\"]+)\"", task_span
                    )
                    if lit:
                        config = lit.group(1)
                        evidence.append(
                            f"config resolved through {fn_match.group(1)}"
                            f"({raw!r}) called by {task} with {config!r}"
                        )
                    break
    call["config"] = config
    return call


# --------------------------------------------------------------------------
# HuggingFace checks
# --------------------------------------------------------------------------

def hf_dataset_info(path: str) -> dict:
    try:
        return get_json(f"https://huggingface.co/api/datasets/{path}")
    except urllib.error.HTTPError as exc:
        raise ScaffoldError(
            f"HuggingFace API cannot see dataset {path!r} (HTTP {exc.code}); "
            "cannot confirm it is public"
        )


def hf_splits(path: str) -> list[dict]:
    data = get_json(f"https://datasets-server.huggingface.co/splits?dataset={path}")
    return data.get("splits", [])


def hf_total_rows(path: str, config: str, split: str) -> int | None:
    url = (
        "https://datasets-server.huggingface.co/rows?dataset="
        f"{path}&config={config}&split={split}&offset=0&length=1"
    )
    try:
        data = get_json(url)
        return data.get("num_rows_total")
    except Exception:
        return None


# --------------------------------------------------------------------------
# Builder template
# --------------------------------------------------------------------------

BUILDER_TEMPLATE = '''#!/usr/bin/env python3
"""Build the evalwarden audit artifact for the %%DISPLAY%% evidence pack.

SCAFFOLDED by tools/scaffold_pack.py from the pinned inspect_evals
task definition. The constants above the TODO block were derived
mechanically from the pinned sources; everything in the TODO block is
a judgment call a human must resolve before this builder can run.

This script translates a PUBLIC, downloadable eval definition into
evalwarden's artifact format (dataset.json / environment.json /
grader.json) WITHOUT inventing anything:

- Only facts present in the public sources are encoded. Anything the
  definition does not say is left out, and the omission is documented
  in PROVENANCE.json next to the artifact.
- No traces are fabricated: there is no run.json. Checks that need run
  records simply do not fire.
- Answer-bearing material is EXCLUDED from the translated artifact even
  though it is public: the integrity question is whether the AGENT can
  see it, and the task definition keeps the answer harness-side as the
  sample target. The exclusion is documented.

It follows the conventions of builders/build_aime2025_card.py in this
repository: same artifact schema version, same definition-sample size
(12), same note/exclusion style. It ships in this repository so the
pack and its builder land in one commit; the pack pins this file by
content hash.

Pinned sources (all public, no auth):
- inspect_evals @ bd59dd3b48974ad2e91219a6ceed41011e201163 (tag v0.23.0)
  (https://github.com/UKGovernmentBEIS/inspect_evals)
%%PINNED_SOURCES%%
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "evalwarden-artifact-v1"
N_SAMPLES = 12

INSPECT_EVALS_COMMIT = "bd59dd3b48974ad2e91219a6ceed41011e201163"
%%DERIVED_CONSTANTS%%
# ======================================================================
# SCAFFOLD TODOs -- judgment calls the scaffold could not derive from
# the pinned sources. Resolve every item, then remove its name from
# TODO_UNRESOLVED. build_%%TASK%%() refuses to run while
# TODO_UNRESOLVED is non-empty, so a scaffolded pack can never pass
# verify_pack.py by accident.
# ======================================================================
TODO_UNRESOLVED = [
%%TODO_LIST%%
]

# Display name for the artifact's eval_id, e.g. "GSM8K via
# inspect_evals". A naming judgment, not a derivation.
TODO_EVAL_ID = None

# PROVENANCE "benchmark" citation line, e.g.
# "GSM8K (Cobbe et al., 2021)".
TODO_BENCHMARK = None

# The exact solver prompt template, copied verbatim from the pinned
# task source (or, for solver-provided templates like inspect_ai's
# multiple_choice, from the pinned inspect_ai source), with its source
# noted. Verify byte-for-byte before pasting. None if the task's
# solver presents the record's input field unmodified.
TODO_PROMPT_TEMPLATE = None

# Where TODO_PROMPT_TEMPLATE comes from, for PROVENANCE, e.g.
# "MATH_PROMPT_TEMPLATE from inspect_evals gsm8k.py at the pinned
# commit (the task's solver is prompt_template(TEMPLATE) + generate())".
TODO_PROMPT_TEMPLATE_SOURCE = None

# dataset.json "notes": what the sample is, what the solver sees,
# what is excluded and why, and the sample-order framing (does the
# task shuffle? does the sample match the task's own order?).
TODO_DATASET_NOTES = None

# environment.json "notes": the solver chain, tools/sandbox, any
# system message or fewshot content (existence, size, seed), any
# GenerateConfig overrides, agent-visible environment variables.
TODO_ENVIRONMENT_NOTES = None

# The environment's "env" mapping itself. {} for the common case (no
# agent-visible environment variables in the definition). Any entry
# here is agent-visible state: check it against ENV-001's meaning.
TODO_ENV = {}

# The full grader.json dict (kind, verifier, judge block if any,
# tests, notes). Model the grader by its most integrity-relevant
# component, per the MATH pack's precedent, and scope any judge
# findings to that component in the notes.
TODO_GRADER = None

# PROVENANCE entries.
TODO_PROVENANCE_TRANSLATION = None
TODO_PROVENANCE_EXCLUDED = None  # list of strings, one per exclusion

# Task files actually read while resolving these TODOs. Prefilled
# with the files the scaffold fetched; extend it with every further
# file you open (scorer modules, prompt modules, utils).
TODO_TASK_FILES_READ = %%TASK_FILES_READ%%


def _check_todos() -> None:
    if TODO_UNRESOLVED:
        raise SystemExit(
            "SCAFFOLD TODOs unresolved: "
            + ", ".join(TODO_UNRESOLVED)
            + ". Resolve each TODO constant in this file, remove its "
            "name from TODO_UNRESOLVED, and re-run."
        )


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "evalwarden-card-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _stable_id(*fields: object, prefix: str) -> str:
    # inspect_evals.utils.create_stable_id: md5 of the fields joined
    # by null bytes, 8 hex chars.
    combined = "\\0".join(str(f) for f in fields)
    return f"{prefix}_{hashlib.md5(combined.encode()).hexdigest()[:8]}"


def _record_to_task(row: dict) -> dict:
    """Translate one dataset record into an artifact task.

    TODO: implement against the task's record_to_sample (quoted in
    the comment block above this function in the scaffolded file, if
    the scaffold found one). Produce {"id": ..., "prompt": ...,
    "metadata": {...}} where prompt is exactly what the solver
    presents to the agent. The sample target (answer, answer key,
    worked solution) is harness-side: never put it in the prompt or
    metadata; list it in TODO_PROVENANCE_EXCLUDED instead.
    """
    raise NotImplementedError(
        "TODO: implement _record_to_task from the task's record_to_sample"
    )


def build_%%TASK%%(work: Path) -> Path:
    """Translate the inspect_evals %%TASK%% task definition (default args)."""
    _check_todos()
    out = work / "%%TASK%%"
    out.mkdir(parents=True, exist_ok=True)

    data = _get_json(%%PREFIX%%_ROWS_URL)
    rows = [r["row"] for r in data["rows"]]
    assert len(rows) == N_SAMPLES, f"expected {N_SAMPLES} rows, got {len(rows)}"

    tasks = [_record_to_task(r) for r in rows]

    (out / "dataset.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eval_id": TODO_EVAL_ID,
                "tasks": tasks,
                "notes": TODO_DATASET_NOTES,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "environment.json").write_text(
        json.dumps(
            {
                "env": TODO_ENV,
                "mounts": [],
                "notes": TODO_ENVIRONMENT_NOTES,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out / "grader.json").write_text(
        json.dumps(TODO_GRADER, indent=2),
        encoding="utf-8",
    )

    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "benchmark": TODO_BENCHMARK,
                "task_definition": "inspect_evals/%%MODULE%% @ " + INSPECT_EVALS_COMMIT,
                "task_files_read": TODO_TASK_FILES_READ,
%%PROVENANCE_DERIVED%%
                "prompt_template_source": TODO_PROMPT_TEMPLATE_SOURCE,
                "sample": (
                    f"first {N_SAMPLES} rows via HuggingFace datasets-server "
                    "(offset 0, length 12)"
                ),
                "translation": TODO_PROVENANCE_TRANSLATION,
                "excluded": TODO_PROVENANCE_EXCLUDED,
                "no_traces": True,
                "generated_by": "builders/build_%%TASK%%_card.py (evidence-registry)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"%%TASK%%: {len(tasks)} tasks -> {out}")
    return out


if __name__ == "__main__":
    import sys

    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/%%TASK%%_work")
    work.mkdir(parents=True, exist_ok=True)
    build_%%TASK%%(work)
'''


def render_builder(task: str, module: str, derived: dict, evidence: list[str]) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]", "_", task).upper()
    const_lines = []
    if derived.get("dataset"):
        const_lines.append(f'{prefix}_DATASET = "{derived["dataset"]}"')
    if derived.get("config"):
        const_lines.append(f'{prefix}_CONFIG = "{derived["config"]}"')
    if derived.get("revision"):
        const_lines.append(f'{prefix}_REVISION = "{derived["revision"]}"')
    if derived.get("split"):
        const_lines.append(f'{prefix}_SPLIT = "{derived["split"]}"')
    if derived.get("rows_url"):
        const_lines.append(f"{prefix}_ROWS_URL = (\n    \"{derived['rows_url']}\"\n)")
    if derived.get("total_rows") is not None:
        const_lines.append(
            f"# Rows in the derived split (datasets-server, at scaffold time): "
            f"{derived['total_rows']}"
        )
    derived_block = "\n".join(const_lines) if const_lines else (
        "# TODO: no dataset constants could be derived (see scaffold report)."
    )

    todo_names = [
        "TODO_EVAL_ID",
        "TODO_BENCHMARK",
        "TODO_PROMPT_TEMPLATE",
        "TODO_PROMPT_TEMPLATE_SOURCE",
        "TODO_DATASET_NOTES",
        "TODO_ENVIRONMENT_NOTES",
        "TODO_GRADER",
        "TODO_PROVENANCE_TRANSLATION",
        "TODO_PROVENANCE_EXCLUDED",
        "TODO_TASK_FILES_READ",
        "_record_to_task",
    ]
    todo_list = "\n".join(f'    "{name}",' for name in todo_names)

    pinned_sources = ""
    if derived.get("dataset"):
        pinned_sources = (
            f"- {task}: {derived['dataset']} (config "
            f"\"{derived.get('config')}\", {derived.get('split')} split) rev "
            f"{derived.get('revision')}"
        )
    else:
        pinned_sources = "- (dataset not derived; see the scaffold report)"

    prov_lines = []
    if derived.get("dataset"):
        prov_lines.append(
            f'                "dataset": {prefix}_DATASET,'
        )
    if derived.get("config"):
        prov_lines.append(
            f'                "dataset_config": "{derived["config"]}",'
        )
    if derived.get("split"):
        prov_lines.append(
            f'                "dataset_split": {prefix}_SPLIT,'
        )
    if derived.get("revision"):
        prov_lines.append(
            f'                "dataset_revision": {prefix}_REVISION,'
        )
    prov_block = "\n".join(prov_lines)

    task_files = derived.get("task_files_read") or [f"{module}.py", "eval.yaml"]
    task_files_repr = json.dumps(task_files)

    text = BUILDER_TEMPLATE
    replacements = {
        "%%DISPLAY%%": task,
        "%%TASK%%": task,
        "%%MODULE%%": module,
        "%%PREFIX%%": prefix,
        "%%PINNED_SOURCES%%": pinned_sources,
        "%%DERIVED_CONSTANTS%%": derived_block,
        "%%TODO_LIST%%": todo_list,
        "%%TASK_FILES_READ%%": task_files_repr,
        "%%PROVENANCE_DERIVED%%": prov_block,
    }
    for token, value in replacements.items():
        text = text.replace(token, value)

    # Quote the task's record_to_sample above _record_to_task as a
    # comment: factual source material for the human implementer.
    rts = derived.get("record_to_sample_src")
    if rts:
        quoted = "\n".join(
            "# " + line if line.strip() else "#" for line in rts.splitlines()
        )
        anchor = "def _record_to_task(row: dict) -> dict:"
        text = text.replace(
            anchor,
            "# record_to_sample from the pinned task source, quoted for\n"
            "# the implementer (verify against the pinned commit):\n"
            + quoted
            + "\n\n\n"
            + anchor,
        )
    return text


def render_stubs(task: str, module: str, derived: dict) -> str:
    pack_id = task.replace("_", "-") + "-via-inspect-evals"
    display = derived.get("eval_yaml_title") or task
    return f"""README row (fill in score/verdict/lesson after the audit runs):

| [`{pack_id}`](packs/{pack_id}/evidence-pack.json) | ![<SCORE>/100 <VERDICT>](https://img.shields.io/badge/<SCORE>%2F100-<VERDICT>-<brightgreen|red>) <LESSON: one line, the audit's own finding in plain words> | [card](packs/{pack_id}/card.html) | PASS |

Gallery article for index.html (same placeholders):

  <article class="pack" data-name="{task.replace('_', ' ')}">
    <div class="pack-head">
      <h2>{display}</h2>
      <span class="pill <pass|blocked>"><SCORE>/100 <VERDICT></span>
    </div>
    <p class="lesson"><LESSON: one line></p>
    <p class="links">
      <a href="packs/{pack_id}/card.html">Rendered card</a>
      <a href="packs/{pack_id}/evidence-pack.json">Evidence pack (JSON)</a>
    </p>
  </article>
"""


CHECKLIST = """Human steps remaining:
  1. Open the generated builder and resolve every TODO constant
     (grader modeling, exclusions, prompt template verified
     byte-for-byte against the pinned source, record-to-sample
     mapping in _record_to_task, notes prose). Remove each resolved
     name from TODO_UNRESOLVED.
  2. Run the builder; eyeball the artifact (dataset.json prompts are
     exactly what the agent sees; no target material anywhere).
  3. Assemble packs/<pack-id>/evidence-pack.json against
     schema/evidence-pack.schema.json: builder content hash, task
     manifest hash, dataset sample hash, audit result (pinned
     evalwarden), canonical card hash, coverage note, repro block.
  4. Validate the pack against the schema; copy the regenerated card
     to packs/<pack-id>/card.html.
  5. Run verify_pack.py on the pack from a clean directory until it
     exits 0 (9/9). Disclose any author-run transport substitution
     in the pack's verifier_note.
  6. Paste the README row and gallery article stubs (above) with the
     real score, verdict, and lesson.
  7. Commit builder + pack together, then the docs update."""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("task", help="inspect_evals task name, e.g. gsm8k, wmdp_bio")
    ap.add_argument("--out", default=None,
                    help="Directory for the generated builder (default: builders/)")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite an existing builder file")
    args = ap.parse_args()
    task = args.task

    evidence: list[str] = []
    derived: dict = {}

    module = resolve_module(task)
    files = list_dir(f"{TASK_ROOT}/{module}")
    evidence.append(f"module directory: {TASK_ROOT}/{module} ({len(files)} files)")

    main_file = f"{module}.py" if f"{module}.py" in files else None
    if main_file is None:
        py_files = [f for f in files if f.endswith(".py")]
        raise ScaffoldError(
            f"no {module}.py in {TASK_ROOT}/{module}; candidates: {py_files}. "
            "Resolve the main task file manually."
        )
    src = get_text(f"{RAW_BASE}/{TASK_ROOT}/{module}/{main_file}")
    parsed = parse_task_source(src)
    if task not in parsed["task_fns"]:
        # The task may live in a sibling file of the module.
        found = False
        for f in files:
            if f.endswith(".py") and f != main_file:
                other = get_text(f"{RAW_BASE}/{TASK_ROOT}/{module}/{f}")
                p2 = parse_task_source(other)
                if task in p2["task_fns"]:
                    main_file, src, parsed = f, other, p2
                    found = True
                    evidence.append(f"task {task} is defined in {f}, not {module}.py")
                    break
        if not found:
            raise ScaffoldError(
                f"task {task!r} not defined in {TASK_ROOT}/{module} "
                f"(found tasks: {parsed['task_fns']})"
            )
    evidence.append(f"main task file: {main_file}; tasks in module: {parsed['task_fns']}")

    eval_yaml = {}
    if "eval.yaml" in files:
        eval_yaml = parse_eval_yaml(
            get_text(f"{RAW_BASE}/{TASK_ROOT}/{module}/eval.yaml")
        )
        derived["eval_yaml_title"] = eval_yaml.get("title")
        if task in eval_yaml.get("tasks", {}):
            evidence.append(
                f"eval.yaml: task {task} registered, "
                f"dataset_samples={eval_yaml['tasks'][task]}"
            )

    call = choose_dataset_call(parsed, src, task, evidence)
    dataset_path = None
    if call is not None:
        dataset_path = call.get("path")
        derived["dataset"] = dataset_path
        derived["config"] = call.get("config")
        derived["split"] = call.get("split")
        rev = call.get("revision")
        if rev is None and parsed["revisions"]:
            # The hf_dataset call referenced the revision constant by
            # a name we resolved already; if not, a single revision
            # constant in the file is the only candidate.
            if len(parsed["revisions"]) == 1:
                rev = next(iter(parsed["revisions"].values()))
        derived["revision"] = rev
        evidence.append(
            f"dataset call derived: path={dataset_path} config={derived['config']} "
            f"split={derived['split']} revision={rev}"
        )
    else:
        evidence.append(
            "no derivable hf_dataset call in the main task file; the "
            "dataset must be resolved by hand (check sibling modules "
            "for load_dataset / snapshot_download indirection)"
        )
        for name, value in parsed["revisions"].items():
            evidence.append(f"revision constant in main file: {name} = {value}")
        if eval_yaml.get("hf_source"):
            dataset_path = eval_yaml["hf_source"]
            evidence.append(
                f"eval.yaml external_assets names HF source: {dataset_path} "
                "(candidate only, not derived from the task's loader)"
            )

    if dataset_path:
        info = hf_dataset_info(dataset_path)
        gated = info.get("gated", False)
        evidence.append(f"HF dataset {dataset_path}: gated={gated!r}")
        if gated not in (False, None):
            print(f"REFUSED: dataset {dataset_path} is gated ({gated!r}).")
            print("A pack whose inputs need auth is invalid; see CONTRIBUTING.md.")
            return 2
        if call is not None and derived.get("config") and derived.get("split"):
            splits = hf_splits(dataset_path)
            pairs = {(s["config"], s["split"]) for s in splits}
            if (derived["config"], derived["split"]) not in pairs:
                evidence.append(
                    f"WARNING: datasets-server has no "
                    f"({derived['config']}, {derived['split']}) split for "
                    f"{dataset_path}; available: {sorted(pairs)}"
                )
            else:
                derived["total_rows"] = hf_total_rows(
                    dataset_path, derived["config"], derived["split"]
                )
                derived["rows_url"] = (
                    "https://datasets-server.huggingface.co/rows?dataset="
                    f"{dataset_path}&config={derived['config']}"
                    f"&split={derived['split']}&offset=0&length={N_SAMPLES}"
                )
    derived["record_to_sample_src"] = parsed.get("record_to_sample_src")
    derived["task_files_read"] = [main_file, "eval.yaml"]
    if parsed["scorer_imports"]:
        evidence.append(
            "scorer imports in task file (grader TODO evidence): "
            + ", ".join(parsed["scorer_imports"])
        )
    if parsed["record_to_sample_src"]:
        evidence.append("record_to_sample found in task file; quoted in the builder")
    else:
        evidence.append("no record_to_sample in the main task file")

    builder_text = render_builder(task, module, derived, evidence)
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "builders"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"build_{task}_card.py"
    if out_path.exists() and not args.force:
        print(f"REFUSED: {out_path} exists (pass --force to overwrite)")
        return 2
    out_path.write_text(builder_text, encoding="utf-8")

    print(f"scaffolded builder: {out_path}")
    print()
    print("Derivation report:")
    for line in evidence:
        print(f"  - {line}")
    print()
    print(render_stubs(task, module, derived))
    print(CHECKLIST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
