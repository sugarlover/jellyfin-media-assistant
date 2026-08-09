# Known search gaps

These items are intentionally deferred rather than handled through aggressive
global normalization.

## Contextual `St.` expansion

A future matcher upgrade should consider `St.` as either `Saint` or `Street`
when catalog evidence and surrounding context support the interpretation.
Examples include artist names such as `Rebecca St. James` and titles containing
`Street`.

The current matcher does not expand `St.` because a global replacement would
create avoidable false matches. The future implementation should use
catalog-derived aliases, media context, confidence margins, and ambiguity
handling rather than treating every occurrence as equivalent.

## Ambiguous-result presentation limit

The Home Assistant search response currently returns at most five numbered
choices so it remains compatible with the established voice-selection flow.
The catalog and matcher can find more candidates; for example, `planet` may
produce twelve valid whole-token title fragments while only five are presented.

When fragment candidates have identical scores, their order currently follows
the stable catalog/index order rather than recency or popularity. Additional
valid candidates, including newer franchise entries, may therefore be outside
the first five. A future user-facing upgrade should add a safe `show more` or
pagination flow and allow the user to refine by subtitle or year. It should not
automatically prefer newer releases without an explicit user preference.
