# Evidence Registry spike: can a stranger regenerate an integrity card?

**Question:** can a stranger regenerate an Evalwarden integrity card from public inputs alone?

**Answer: yes.** 2026-09-29, HealthBench card (`healthbench-via-inspect-evals`, 85/100 BLOCKED).
A clean-directory run of `verify_pack.py` against the pack passed 10/10 checks:
pinned task-definition commit resolves, dataset sample hash matches, builder script
byte-identical, task manifest matches, harness 0.6.1 installed fresh, audit findings
identical (BLOCKED, 2x JUDGE-001), canonical card HTML hash identical.

## What the spike built

- `schema/evidence-pack.schema.json` — the minimal portable bundle (v1): card id,
  harness pin, task manifest hash, input pins, exclusions with reasons, embedded audit
  result, runs (empty here, with an explicit coverage note), cost (explicit null with a
  reason, since no runs exist), expected card hash, canonicalization rule, one repro command.
- `verify_pack.py` — the stranger's script. Stdlib only. Fetches the pinned public inputs,
  rebuilds the artifact with the pinned upstream builder, installs the pinned harness,
  re-runs the audit, and compares hashes. Exit 0 means the kill criterion passes.
- `packs/healthbench-via-inspect-evals/evidence-pack.json` — the first real pack.

## Design decisions the spike forced

1. **Canonicalization is part of the schema.** The card embeds two generation timestamps
   (footer and the methodology-table "Generated" row). Byte-equality needs a documented
   rule: strip both, keep the harness version string (a version mismatch must fail, not be
   normalized away). The rule lives in the pack, and the verifier implements it.
2. **Absence is explicit.** No runs exist for definition-level cards, so `runs` is `[]`
   with a coverage note naming exactly which checks stay silent, and `cost_summary` is
   `null` with reason `no_run_records`. Silent omission would make "regenerable" unverifiable.
3. **Canonical serialization must be specified once.** The spike caught a real bug this way:
   the pack author hashed the dataset sample with default JSON separators while the verifier
   used compact separators. Same bytes, different hashes, spurious FAIL. The schema now
   fixes one canonical form (sorted keys, compact separators, UTF-8) for all content hashes.
4. **The task-definition pin is human-auditable, not machine-derived.** The builder encodes
   judge defaults as constants read by a human from the pinned commit; the machine-verifiable
   link is the builder script's content hash. The pack says so honestly instead of claiming
   a derivation it cannot perform.
5. **Drift detection is the point.** The HealthBench blob URL carries no content pin upstream,
   so the pack pins the hash of the exact bytes consumed. Any blob change fails loudly.
   (The blob was stable through this spike; the mechanism is tested by construction.)

## Bonus finding: the registry already caught something

The committed example card `healthbench-via-inspect-evals.html` in the evalwarden repo is
**stale relative to its own committed artifact**. The rebrand commit (`6a26828`) changed
`schema_version` in `dataset.json` (`evalint-artifact-v1` -> `evalwarden-artifact-v1`) without
rebuilding the card, so the card's evidence row shows the old dataset digest (`10672842737c…`)
while the artifact hashes to `ab66cf91…`. A regenerated card from this pack carries the
correct digest. This is exactly the drift the registry exists to catch.

## Out of scope for the spike

No site, no contribution workflow, no multi-card index. Those are the first shippable slice;
this spike only proves the schema and the regeneration loop.
