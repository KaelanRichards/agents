---
name: plain-writing
description: Write and rewrite plain, concise, active prose without losing facts or technical precision. Use for documentation, READMEs, messages, reports, PR descriptions, commit messages, landing-page copy, existing-text rewrites, and requests to remove AI writing patterns, jargon, stale phrases, passive voice, or inflated language.
---

# Plain Writing

Apply Orwell's six rules to prose. Preserve facts, numbers, names, quotations, code, identifiers, and
technical distinctions.

## Rules

1. Avoid familiar metaphors, similes, and figures of speech.
2. Prefer a short word when it keeps the same meaning.
3. Cut every word that carries no fact, relation, tone, or necessary qualification.
4. Prefer active voice when it makes the actor and action clear.
5. Replace foreign phrases, scientific words, and jargon only when everyday English is equally precise.
6. Break any rule before making the prose unclear, ugly, misleading, or technically wrong.

Never apply these rules mechanically to code, commands, API names, field names, quoted material, or
necessary domain terms.

## Rewrite existing prose

1. List each stale phrase, long word with its shorter replacement, removable word or clause, and
   passive construction.
2. Rewrite the text.
3. Check that every fact, number, name, quotation, and technical distinction remains unchanged.
4. Read once for meaning and once for excess.

Show the violation list when the user requests an audit or rewrite report. For direct file edits, use
the list as an internal pass unless the user asks to see it.

Example:

Before: "Comprehensive error handling has been implemented across all API endpoints to ensure robust
and reliable performance."

After: "We added error handling to every API endpoint."

## PRs and commits

State what changed and why. Avoid achievement language and empty claims such as "comprehensive,"
"robust," "reliable," "successfully," and "perfect." A reviewer should understand the change in one
read.

## Landing pages

Write one concrete claim per line. Prefer short words and active voice. Apply the swap test to every
line: if a competitor could paste it unchanged onto its page, rewrite or delete it.

## Progress reports

Start with three plain sentences: what changed, what failed, and what comes next. Add detail only when
it changes the next action. Do not use emoji checkmarks, "Successfully," "Perfect," or a wall of
bullets.
