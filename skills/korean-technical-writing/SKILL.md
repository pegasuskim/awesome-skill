---
name: korean-technical-writing
description: "Technical-writing standard for Korean text. Covers Diátaxis document modes, plain Korean sentences without translationese, one name per term, and Korean AI tells. Use for /korean-technical-writing or when writing or reviewing Korean docs, READMEs, RFCs, PR descriptions, or commit messages."
---

# Korean technical writing

The goal is Korean that a tired engineer understands on the first read. Apply every section below to Korean prose. Leave code, identifiers, commands, and quoted English untouched.

Three rules sit above the sections.

- Cut every word that does no work. Delete "~라는 점에 유의해야 합니다" and keep the fact it wraps. Write "~하려면", not "~하기 위해서는".
- Use the short, everyday word. Write "쓰다", not "활용하다". Write "돕다", not "용이하게 하다". A Sino-Korean word has to buy its length with precision, such as "인증" or "캐시", which have no shorter exact word.
- When a rule makes a sentence worse, fix the sentence another way or leave it alone. A sentence that follows every rule and still reads like a translation has failed.

The codebase is the word list. Write the real symbol, file, flag, or command name, not a description of it.

Don't invent jargon. Use the words a Korean developer says out loud, such as "옮기다", "지우다", "줄어들기만 하는 한도". A named pattern is fine when the doc says what it means the first time.

## Vary the rhythm

A doc can follow every rule and still read machine-written, with every sentence the same length and nothing specific in it.

- Mix sentence lengths on purpose. A short sentence lands a point. A longer one carries a fact with its condition or consequence.
- Have a view where the mode allows it. In an explanation, say what you make of a trade-off instead of listing pros and cons.
- Be specific. Write "열 이름을 바꾸면 빌드가 실패합니다", not "스키마 변경은 문제를 일으킬 수 있습니다".

## Pick the mode first (Diátaxis)

One document, one mode. Ask whether the content serves doing or understanding, and whether it serves learning or work.

- Doing and learning make a **tutorial**.
- Doing and work make a **how-to**.
- Understanding and work make a **reference**.
- Understanding and learning make an **explanation**.

**Tutorial.** Open with what the reader will build. Make every step produce a visible result, and show what the reader should see, such as the output or the log line. Cut explanation to one clause and a link.

**How-to.** Solve a problem the reader has. Assume competence and skip teaching. Allow forks, such as "x가 필요하면 y를 하세요". Title the guide by the task, such as "레이더 보정하기", not "레이더 보정".

**Reference.** Describe and only describe. State facts, options, limits, and errors without hedging. Mirror the structure of the thing described.

**Explanation.** Cover one bounded topic and anchor it on a real why question. Give design decisions, history, constraints, and alternatives. Opinion is allowed here and nowhere else.

Don't mix modes. Split and link instead.

## Hold one register

Use 합니다체 for statements and "~하세요" for instructions, or use 해요체 throughout. Don't switch inside a document, because a register change reads as a change of speaker.

Keep list items and table cells in one form per list. Use full sentences or noun phrases, not both.

Don't address the reader as "당신" or "여러분". Korean drops the subject, so write the instruction directly, such as "`install.sh`를 실행하세요".

Write instructions as plain commands. Write "~하세요", not "~해 주시기 바랍니다". Never write "간단히", "쉽게", or "빠르게" in a procedure. If it were simple, the reader would not be here.

For commit messages and PR titles, follow the language and form the repo already uses.

## Name the actor and drop translationese

Write the subject when dropping it allows two readings. Write "컴파일러가 쿼리를 검증합니다", not "쿼리를 검증합니다" when the reader cannot tell who validates.

Avoid passive forms copied from English, such as "~되어지다" and "~에 의해 ~되다". Write "로더가 파일을 파싱합니다", not "파일은 로더에 의해 파싱됩니다". A "~되다" verb is fine when the actor is unknown or beside the point.

Drop light-verb padding. Write "배포합니다", not "배포를 진행합니다" or "배포 작업을 수행합니다".

Use a plain particle where a phrase copied from English sits. Write "환경 변수로 설정합니다", not "환경 변수를 통해 설정합니다". Treat "~에 대해", "~에 있어서", and "~로 인해" the same way.

Don't stack "의". Write "서버 설정을 바꾸면", not "서버의 설정의 변경 시".

Don't turn the main verb into a noun. Write "캐시를 지우세요", not "캐시를 지우는 것이 필요합니다".

Use Korean word order for counts and possession. Write "파일 세 개", not "세 개의 파일". Write "이 함수는 인자 세 개를 받습니다", not "이 함수는 세 개의 인자를 가집니다".

Write "~할 수 있습니다" only for a real option. When the outcome is certain, state it, such as "CI가 실패합니다".

## Load one thought per sentence

Give one instruction per sentence and one thought per sentence elsewhere.

Split long sentences. Korean puts the verb last, so a long sentence keeps the reader waiting for its meaning. Look hard at an instruction past about 60 characters and at other sentences past about 80. These are signals to check, not hard limits.

Don't chain clauses with "~고", "~며", "~하여", or "~는데" when each clause is its own thought. End the sentence and start a new one.

Keep modifying clauses short. Two nested clauses before one noun make the reader parse backward. Rewrite "사용자가 입력한 값을 검증하는 함수가 반환한 오류" as two sentences.

Put the condition or warning before the step it guards, such as "문서를 지우려면 **삭제**를 누르세요."

Put the common case first and exceptions after.

## Leave no sentence open to two readings

Watch the scope of negation. "모든 테스트가 통과하지 않았습니다" can mean none passed or some failed. Write "일부 테스트가 실패했습니다" or "모든 테스트가 실패했습니다".

Put "만" right after the word it limits, such as "`--write`는 예산을 낮출 때만 실행하세요."

Make every "이", "그", "이것", and "해당" point at one obvious thing. Repeat the noun when in doubt. Don't use "해당" as a generic pointer. Write "`budget.json`", not "해당 파일".

Break long noun strings. Write "프로토를 임포트하는 파일 수를 예산과 비교하는 스크립트", not "프로토 임포트 예산 검사 스크립트".

Rewrite "A와 B의 C" when it can group two ways. Write "서버 설정과 클라이언트 설정", not "서버와 클라이언트의 설정".

Use periods. Replace semicolons and em dashes with new sentences. Don't use slashes. Write "A나 B, 또는 둘 다", not "A/B".

Make text in parentheses a full unit or its own sentence.

Skip idioms, 사자성어, and metaphors.

Call each thing by one name everywhere. Don't reword an unchanged sentence between edits.

## Write English terms one way

Keep code identifiers, commands, flags, and file paths in English and in code font.

For a concept term, pick one form per document and keep it. Prefer the form the team says aloud, such as "커밋", "브랜치", and "저장소". Don't alternate "저장소", "레포", and "repository" for one thing.

Give the English once at the first use of a term the reader may not know, such as "멱등성(idempotency)".

Choose the particle by how the English word is read aloud, such as "API를", "`main`을", and "commit을". Don't put a space between the word and its particle.

## Remove Korean AI tells

Delete openers and closers that carry no fact, such as "~에 대해 알아보겠습니다", "살펴보겠습니다", "결론적으로", "정리하자면", and "도움이 되었길 바랍니다".

Delete importance padding, such as "~하는 것이 중요합니다", "핵심은 ~입니다", and "주목할 점은". State the point itself.

Replace vague praise with the fact or the number, such as "다양한", "효율적인", "원활한", "강력한", "유연한", and "체계적인". Write "`cache.get()`은 디스크를 읽지 않고 메모리에서 값을 반환합니다", not "강력한 캐시 기능을 제공합니다". If a sentence could appear unchanged in another project's docs, it says nothing about this one.

Drop "단순히 A가 아니라 B" framing. State B.

Don't force ideas into groups of three. Use the natural number.

Don't hedge what you checked. Write "~입니다", not "~인 것으로 보입니다" or "~할 수도 있을 것 같습니다".

Don't write lists whose bold label restates the line, such as "**성능:** 성능이 개선되었습니다". Don't decorate headings or bullets with emoji.

## PRs and commits

Every section except the mode section applies to PR descriptions and commit messages. A PR body is a briefing a reviewer reads in under a minute. Link logs and metric tables instead of pasting them.

## Worked example

Before:

> 프로토 임포트 래칫 예산 스크립트 파라미터의 설정은 budget.json을 통해 수행됩니다. --write 옵션을 사용하여 실행하는 것은 커밋된 예산을 현재 카운트에 맞게 업데이트하는 것으로, 이를 낮추는 경우에만 진행되어야 한다는 점을 기억하는 것이 중요합니다. 초과 시 CI가 실패합니다.

After:

> `budget.mjs`는 `budget.json`에서 커밋된 예산을 읽고, 프로토를 임포트하는 파일 수를 셉니다. 파일 수가 예산보다 많으면 CI가 실패합니다. `budget.mjs --write`는 예산을 낮출 때만 실행하세요.
