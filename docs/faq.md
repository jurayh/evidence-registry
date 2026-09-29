# FAQ

**Do you run the benchmarks?**
No. The registry audits eval definitions, never executes them. There are no
model calls, no GPUs, no API keys. The question is what the instrument looks
like on paper: what the agent can see, how the grader works, whether the
judge is calibrated.

**Why are there no run traces?**
Because no runs happened. These are definition-level cards. Checks that need
run records stay silent, and each pack says so in `runs_coverage_note`
instead of hiding the gap. COST-001 notes the missing cost data for the same
reason. If a benchmark ships interesting run data in the future, a pack can
encode it.

**What does BLOCKED mean?**
The instrument has an integrity problem a user should know about before
citing scores from it. It is not a verdict that the benchmark is bad. A
BLOCKED card names the problem precisely so the benchmark's authors can fix
it and the card can be re-issued.

**What does the score mean?**
A 0-100 summary of the findings, weighted by severity. Read the findings,
not just the number. Two cards can share a score for different reasons.

**Can I add a pack?**
Yes. Read [CONTRIBUTING.md](../CONTRIBUTING.md). The bar is one sentence: a
stranger must be able to regenerate your card from public inputs, or it does
not merge.

**Who is this for?**
People who cite benchmark scores and want the instrument checked before they
quote the number. People who build evals and want a machine-checkable verdict
on their design. Anyone who thinks measurement integrity should be
reproducible, not vibes.

**How is this different from a leaderboard / a standard / a harness / an audit paper?**
[How it differs](how-it-differs.md).

**What exactly is inside a pack, and how do I read a card?**
[Anatomy of a pack](anatomy-of-a-pack.md).
