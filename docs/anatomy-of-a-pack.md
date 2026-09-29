# Anatomy of a pack

An evidence pack is one JSON file, `packs/<card-id>/evidence-pack.json`, plus
the rendered `card.html` beside it. The JSON is the machine-readable evidence.
The HTML is the human-readable card. Both are pinned to each other by hash.

## What a pack contains

- **`benchmark` and `pack_id`.** Which benchmark and which translation of it.
  Every current pack translates an inspect_evals task definition.
- **`harness`.** The exact Evalwarden version the audit ran under
  (0.6.1), with the install command. No "latest", no ranges.
- **`inputs`.** Every public input the translation consumed: the task
  definition (repo plus pinned commit), the dataset (URL plus SHA-256 of the
  exact bytes consumed), the builder script (URL plus content hash). A URL
  without a content hash is not a pin. If an input cannot be fetched without
  auth, the pack is invalid.
- **`task_manifest` and `translation`.** What the definition sample covers,
  what was translated mechanically, and what was deliberately left out with
  reasons. Answer-bearing material (gold patches, test bodies, the answer
  index) stays out of the agent-visible artifact even when it is public,
  because the integrity question is what the agent can see. The pack says so
  explicitly.
- **`audit_result`.** The full Evalwarden verdict: score, verdict, and every
  finding with severity, confidence, description, and evidence.
- **`runs` and `cost_summary`.** Definition-level cards have no run traces,
  so these are explicit nulls with reasons. `runs_coverage_note` names which
  checks stay silent without runs. Absence is stated, never hidden.
- **`expected_card` and `canonicalization`.** The SHA-256 of the card after a
  documented rule strips generation timestamps. Same card, same hash, no
  matter when you regenerate it.
- **`repro` and `kill_criterion`.** The one command that regenerates the
  card, and the recorded answer to the registry's founding question: can a
  stranger regenerate this card from public inputs?

## How to read an integrity card

Open `card.html`. The masthead shows a score out of 100 and a verdict.

- **PASS** means the checks found no integrity problem worth blocking on.
  The HealthBench meta_eval card is 95/100 PASS: the judge ships its
  physician-labeled calibration set, with one medium finding left (the
  boolean rubric has no explicit scale anchors).
- **BLOCKED** means the instrument has an integrity problem you should know
  about before citing scores from it. It does not mean the benchmark is bad.
  The HealthBench card is 85/100 BLOCKED: its model judge has no labeled
  calibration set in the definition, so its scores have no demonstrated
  relationship to human judgment.

Below the masthead, each finding carries a severity badge (high, medium),
a confidence level, a plain-language description, and the evidence that
fired it. Read the findings, not just the number. Two cards can share a
score and fail for different reasons; the HealthBench and WritingBench
cards are both 85/100 BLOCKED, and their findings describe different judge
problems.

## What "stranger-verified" means, concretely

A stranger is someone with a clean machine, the pack file, and
`verify_pack.py` (stdlib only, no dependencies). They run:

```bash
python3 verify_pack.py evidence-pack.json --work-dir /tmp/ep_work
```

The verifier fetches every input from its public URL, checks each content
hash, installs the pinned harness in a fresh virtualenv, rebuilds the
artifact from the pinned builder, re-runs the audit, regenerates the card,
strips timestamps by the documented rule, and compares the result hash to
the pack's `expected_card.sha256`. Exit 0 means every check passed. Any
failure names the failing check.

No trust in the author is required. If upstream drifted, a hash fails
loudly. If the card was hand-edited, the hash fails loudly. That is the
whole point.
