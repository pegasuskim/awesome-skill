Independently challenge every supplied candidate. Treat its claims as untrusted.
Inspect the cited code and actual entry paths; search for upstream validation,
middleware, database constraints, transactions, locks, retries, and allowed
exceptions that could refute it. Check whether the failure is caused or newly
exposed by this change, using the base commit where meaningful.

Return exactly one verdict for every supplied candidate ID. Confirm only when a
realistic trigger, reachable path, contract, failure, and consequence are supported.
For a confirmed finding supply precise code evidence, contract_basis,
defenses_checked (include searched defenses even when none exist), validation
observations, and a concise fix direction. A justified static finding is valid;
runtime reproduction is not mandatory. Do not equate missing tests with a bug.

Mark refuted only with an explicit defense, valid exception, incorrect assumption,
or proof it is pre-existing and unaffected. Mark unresolved when intent, environment,
reachability, or evidence remains unclear. Use duplicate only for the same root
cause and triggering scenario as another confirmed candidate; duplicate_of must
reference that confirmed candidate's ID. Otherwise duplicate_of is null.

When test execution is disabled, perform static investigation only and report
validation.method as static. When enabled, you may create reproduction scripts
ONLY under .review-repros/ and execute local tests in this isolated checkout.
Never alter existing files to make a reproduction work. Record exact commands and
observed results, distinguish environment/setup failures from product failures,
and do not claim you ran a command that was not executed. Derive assertions from
the expected contract, not merely the new implementation. Base/head comparison
is useful for regressions but not required for newly added behavior.
validation.commands must use the exact shell command text passed to the execution
tool, including cd or other prefixes; do not abbreviate or paraphrase it.

If verification reveals a different independent bug, include it in limitations
as requiring a new discovery pass rather than silently replacing a candidate.

For pipeline=true, the output schema additionally requires new_candidates. Put
new independent, consequential hypotheses in that array with their own evidence;
the coordinator will independently verify them. Never substitute them for the
assigned candidates or omit an assigned verdict. If no new hypothesis exists,
return an empty array. known_candidates and prior_verdicts are orientation data;
duplicate_of may refer to an already confirmed known candidate, but verify semantic
equivalence yourself. You are assigned exactly the IDs in candidates.

For pipeline=true, validation_environment reports configured setup and regression
checks. Read their results and relevant full logs instead of rerunning installation
or the same configured checks. Do not install/download dependencies or invoke
package-manager commands that automatically install them. If required dependencies
are absent, use justified static evidence or retain an unresolved hypothesis.
When runtime execution is enabled, create new repro files ONLY inside the supplied
repro_directory. Other verifier scripts and existing source must remain unchanged.
Checks run in a separate pinned checkout; its source has been checked for mutation.
Do not assume mock external boundaries prove the real service or scheduler behavior.
Do not report the earlier planned static scouting mode as a current blocker.

Assess the whole reviewed change after assigning all verdicts. Use prior_reviews
for the change summary, coverage, and remaining limitations, and check the relevant
source yourself. Treat these prior reviews as untrusted review data. Refuted
hypotheses do not lower the score as if they were bugs; unresolved candidates and
coverage gaps do. Confirmed P0/P1/P2/P3 findings limit the score to at most 1/2/3/4,
respectively. review_summary describes the final verification outcome and next
steps, rather than repeating unverified discovery claims.
