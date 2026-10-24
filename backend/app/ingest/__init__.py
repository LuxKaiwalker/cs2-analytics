"""Accepting demo files: validation, safe storage, and guarded URL import.

Uploaded demos are untrusted input. They are never executed, are stored under generated
names outside any served directory, and are size-capped while streaming rather than
after the fact.
"""
