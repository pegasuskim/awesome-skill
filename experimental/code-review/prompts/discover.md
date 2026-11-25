Inspect the complete change inventory before concentrating on individual bugs.
Use the supplied full diff file and read surrounding source as needed. Account
for every changed path in coverage; mark a path not_reviewed with a reason if it
cannot be inspected. Binary/generated files may matter to runtime behavior.

Find behavioral failure hypotheses, including issues spanning multiple files.
Gather preliminary code and contract evidence and list defenses still to check.
Discovery candidates are not final findings: an uncertain but realistic,
consequential hypothesis can be retained for verification. Clearly describe its
assumptions instead of claiming it is proven. Do not stop after the first bug.

List inaccessible services, submodules, unresolved intent, or other coverage
limitations. Empty candidates is valid; it is not proof that the change is safe.
summary describes the complete change and its purpose. The assessment is
provisional: account for every candidate still awaiting verification.
