Perform a second discovery pass over the complete change. Existing candidates
are supplied so you can avoid repeating them. Look for distinct failure
scenarios that the first pass may have missed, especially interactions across
files, valid inputs rejected, concurrent/repeated operations, partial failures,
and compatibility with existing callers or data. Revisit paths previously marked
not_reviewed. Search supporting code instead of relying on the earlier summary.
Account for every changed path in coverage. Return only new candidates.
summary still describes the complete change, not just this pass's new findings.
The assessment must account for existing_candidates as well as new candidates
and limitations in prior_reviews; earlier statements are claims to investigate.
