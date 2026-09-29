# Evidence Registry

Versioned integrity cards for AI benchmarks. Each card binds an executable Evalwarden
audit to pinned public inputs and a one-command regeneration, so a stranger can verify it
from the bundle alone. Not a leaderboard: it rates the measurement system, not the model.

## Status: two packs, stranger-verified

The spike answered the one question it asked: **can a stranger regenerate an integrity card
from public inputs?** Yes. Both packs below regenerate byte-identically (modulo documented
timestamps) from a clean directory, verified end to end with `verify_pack.py`.
See `SPIKE_NOTES.md` for the full story, including the design decisions the spike forced
and real staleness bugs it caught in the evalwarden repo's own example cards.

## Packs

| Pack | Result | Kill criterion |
|------|--------|----------------|
| [`healthbench-via-inspect-evals`](packs/healthbench-via-inspect-evals/evidence-pack.json) | 85/100 BLOCKED, 2x JUDGE-001 | PASS: stranger regenerated the card from public inputs |
| [`swe-bench-verified-via-inspect-evals`](packs/swe-bench-verified-via-inspect-evals/evidence-pack.json) | 100/100 PASS, no findings | PASS: stranger regenerated the card from public inputs |
| [`writingbench-via-inspect-evals`](packs/writingbench-via-inspect-evals/evidence-pack.json) | 85/100 BLOCKED, 2x JUDGE-001 | Stranger-run pending |

## Layout

- `schema/evidence-pack.schema.json` — the evidence pack schema (v1).
- `verify_pack.py` — the stranger's verifier. Stdlib only.
- `packs/<card-id>/evidence-pack.json` — one pack per card.
- `CONTRIBUTING.md` — how to add a pack and the bar it must clear.
- `.github/workflows/verify.yml` — CI: schema validation plus full verification of every pack on push, PR, and weekly.
- `SPIKE_NOTES.md` — spike findings and out-of-scope notes.

## Contributing

To add a pack, read `CONTRIBUTING.md`. The short version: translate from pinned public
sources only, author the pack against the schema, and make `verify_pack.py` exit 0 on it
from a clean directory. CI re-verifies every pack on every PR.

## Verify a pack

```bash
curl -sSL https://raw.githubusercontent.com/jurayh/evidence-registry/main/verify_pack.py -o /tmp/ep_verify.py
curl -sSL https://raw.githubusercontent.com/jurayh/evidence-registry/main/packs/healthbench-via-inspect-evals/evidence-pack.json -o /tmp/ep_pack.json
python3 /tmp/ep_verify.py /tmp/ep_pack.json --work-dir /tmp/ep_work
```

Exit 0 means every check passed: all inputs public and pinned, artifact rebuilt,
harness installed at the pinned version, audit findings identical, card hash identical.
Any failure names the failing check. The pack's `kill_criterion` field records the verdict.

## The pack, briefly

A pack pins everything regeneration needs and nothing it doesn't: the harness version,
hashes of the translated artifact, each public input (URL or commit plus a content hash),
material deliberately excluded with reasons, the full audit result, explicit nulls with
reasons where runs or cost data don't exist, the expected card hash, a canonicalization
rule for timestamps, and one repro command. If any input can't be public, the pack is
invalid and the registry concept fails for that card.
