Independently investigate the complete change while other scouts work concurrently.
Focus on contracts and scenarios spanning groups: entry points to consumers,
authorization boundaries, existing data, retries, repeated/concurrent operations,
partial failures, rollback and externally visible compatibility. Do not assume
other workers will examine an interaction. Search the original source and pinned
base; directory and lexical import grouping can miss aliases and dynamic behavior.

Use context_pack and the full diff to orient yourself. Account for every path in
changes in coverage. A full inventory or source excerpt alone is not a completed
review. In deep mode, deliberately challenge plausible happy-path assumptions and
investigate negative and adversarial scenarios across the entire change.

Return every supported preliminary candidate, including realistic unresolved
hypotheses, with its contract, trigger and defenses to check. summary describes
the entire change; assessment is provisional pending independent verification.
Record actual blocking limitations. Static-only scouting is planned; tests and
environment preparation are handled separately, so do not list the planned mode
itself as an unresolved limitation. Never install dependencies or execute tests.
