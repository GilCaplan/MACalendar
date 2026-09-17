"""The widgets of the Mac Jude app.

Split by what is on the screen rather than by kind — `window` assembles,
`sidebar` and `composer` are the chrome, `transcript` owns the conversation,
`sources` and `trace` own the two things an answer carries with it, and
`client`/`stream` are the only modules here that speak HTTP.

Nothing in this package imports `assistant.engine` or opens a store. Jude is a
separate brain reached over `/jude/*`, and this window is a client of that API
in exactly the way the iPhone is: same routes, same bodies, same NDJSON.
"""
