"""Statistics computed from the normalized match model.

Nothing here imports a parser or touches the database. Every function takes
:class:`~app.parsing.model.NormalizedMatch` (or a slice of it) and returns plain data,
so each metric is unit-testable against a handful of hand-written rows.

Metric definitions live in :mod:`app.analytics.definitions` and are served over the API,
so the documented definition and the implemented one cannot drift apart unnoticed.
"""
