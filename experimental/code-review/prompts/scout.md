Review every path assigned in changes. all_changes contains the complete inventory:
use it to notice interactions, but report coverage ONLY for assigned paths.
The runner assigns each changed path to one scout. A grouping hint is neither a
complete graph nor a restriction on reading callers, dependencies or consumers.

Start with the supplied context_pack and full diff, then investigate the original
source and pinned base. Excerpts are truncated conveniences, not proof of coverage.
Follow references outside the group within this checkout. Search for failure
conditions and defenses, including unchanged code and contracts. Do not stop at
the first candidate. Retain realistic consequential uncertainties for verification.

Return preliminary candidates with triggers, contracts, source evidence and
defenses still to check. This worker's assessment is provisional and scoped to
the assignment; the coordinator will assess the entire change after verification.
summary must explain the assignment and its relationship to the complete change.
Mark inaccessible assigned paths not_reviewed. Record actual blocking limitations,
not the planned static-only scouting mode or hypothetical absence of future work.
Do not install dependencies or execute tests here: a separate configured check
worker and independent candidate verifiers handle runtime validation.
