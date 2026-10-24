"""Background processing: a supervised subprocess per demo.

The lifecycle is ``uploaded -> queued -> processing -> completed | failed | cancelled``,
with the current stage persisted so a poll can report real progress. There is no
percentage: the parser exposes no progress signal, so a number would be invented.
"""
