---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

The document may be read after the code has changed. Focus on facts that stay true, such as the goal, constraints, the definition of done, decisions and rejected alternatives with their reasons, and what is done and what is left.

Record what was tried and observed as events of this session, not as claims about the current code.

Quote code only when it exists nowhere else, such as a reverted attempt or an agreed change not yet applied. Refer to locations by symbol or area, not line number, and mark them as leads to verify.

Include a "suggested skills" section in the document, naming which skills the next agent should load.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
