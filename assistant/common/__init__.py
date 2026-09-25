"""Small, pure, stage-agnostic helpers shared across the codebase.

Gil, 2026-09-25: *"make sort of our own library with these functions, and then
call them in the code, so we can clean it up and make it more readable."* What
belongs here is DATA and ARITHMETIC that every copy agreed on — weekday and
month tables, clock arithmetic, rate formatting. What does NOT belong here is a
RULE that decides behaviour (that lives with its stage, or in
`assistant/intent/` when two stages must share it) — two helpers that look
alike but encode different decisions stay apart. The audit that drove this is
summarised in DOCUMENTATION/TASKS.md.
"""
