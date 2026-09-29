# How this differs

The registry is an audit log for measurement instruments. It is not another
way to rank models.

Four things people confuse it with, fairly stated.

| What | What it is good at | The registry's different job |
|------|-------------------|------------------------------|
| **Score leaderboards** (Hugging Face Open LLM Leaderboard, Papers With Code, LMSYS Chatbot Arena) | Ranking models by reported scores, in one place, over time. This is how the field tracks progress. | Leaderboards rank the runners. The registry inspects the stopwatch. It audits the tests those scores come from, so you can tell whether a score means what it claims. |
| **Benchmark standards** (MLCommons, HELM) | Defining how an eval should be built and reported so results are comparable. Standards make the field legible. | A standard says what a good eval looks like. The registry checks whether a given eval definition actually meets that bar, independently of its authors. |
| **Eval harnesses** (Inspect AI, lm-eval-harness) | Running evals reproducibly: loading data, prompting models, scoring answers. Harnesses are the lab bench. | A harness executes an eval. The registry never executes anything. It audits the definition on paper: what the agent can see, how the grader works, whether the judge is calibrated. No GPU, no API keys, no runs. |
| **One-off audit posts and papers** | Deep, expert, often the first to spot a real problem with a benchmark. This work matters. | A post is a snapshot. It cannot be re-run, it rots as the benchmark changes, and you have to trust the author's setup. Every registry card is a machine-checkable artifact: a stranger regenerates it from public inputs or it does not ship. |

The short version: leaderboards tell you who won, standards tell you how to
play fair, harnesses run the game, audit papers write the match report. The
registry checks the referee's rulebook, and it checks it again every week.
