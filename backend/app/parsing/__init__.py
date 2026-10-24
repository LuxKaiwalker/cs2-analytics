"""Demo parsing: the boundary between a third-party parser and the rest of the app.

``model`` defines the normalized, parser-independent representation. ``awpy_parser``
is the only module in the application that imports ``awpy`` (besides ``maps.data``,
which uses awpy purely as a map-asset CDN client).
"""
