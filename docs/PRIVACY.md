# Privacy, security and data handling

## What a demo contains

A CS2 demo is a recording of a real match. It contains **identifiable information**:
player display names, 64-bit Steam IDs, the server name and address, chat messages where
the recording kept them, and every player's position throughout the match. Uploading a
demo to this application means putting that data on the machine running it.

The application never transmits demo contents anywhere. Analysis is entirely local.

## Where data is stored

Everything lives under one configurable directory (`CS2A_DATA_DIR`, default `./data`):

| Path | Contents |
|---|---|
| `data/demos/` | Uploaded `.dem` files, named by generated UUID |
| `data/tmp/` | In-flight uploads, deleted on completion or failure |
| `data/app.db` | Derived analytics |
| `data/awpy/` | Cached map radar images |
| `data/fixtures/` | Test demos, downloaded explicitly |

The whole directory is gitignored. **Demos, the database and downloaded fixtures are never
committed**, and the uploads directory is never served as static files — the production
mode serves only `frontend/dist`.

## Deletion

`DELETE /api/matches/{id}` removes the match row, every derived row (players, rounds,
round-players, events) via `ON DELETE CASCADE`, **and the stored `.dem` file**. A match
that is mid-parse is cancelled first. There is no soft delete and no retention of the
original file.

Set `CS2A_KEEP_DEMO_FILES=false` to discard the `.dem` after a successful parse, keeping
only the derived analytics. The trade-off is that the match cannot then be re-ingested
after a schema change.

## Threat model

**This is a single-user local tool.** It binds to `127.0.0.1`, has **no authentication and
no authorization**, and every endpoint is open to anyone who can reach the port. That is a
deliberate, appropriate choice for a local analysis tool — and it means:

> **Do not expose this to a network without first adding authentication, authorization and
> transport security.** Everything below is defence in depth within the local threat model,
> not a substitute for those.

## Handling untrusted input

Demos are treated as untrusted binary input, because they are.

- **Never executed.** Parsed as data only.
- **Validated by content**, not by filename: the leading bytes must be the CS2 demo
  signature. A CS:GO demo, a compressed demo and a renamed JPEG are each rejected with a
  message saying which.
- **Size-capped while streaming** (`CS2A_MAX_DEMO_BYTES`, default 400 MiB), with the
  partial file deleted the moment the cap is exceeded. A disk budget
  (`CS2A_MAX_TOTAL_BYTES`) and a free-space check refuse uploads there is no room for.
- **Stored under generated UUIDs.** The client-supplied filename is kept for display only
  and never used to construct a path, so traversal is structurally impossible rather than
  filtered. A test uploads `../../../../etc/passwd` as the filename and asserts the stored
  path is unaffected.
- **Parsed in a separate process** with an address-space limit, so a malformed demo that
  crashes or exhausts memory inside the native parser takes down only the worker, and an
  out-of-memory becomes a clean failure rather than an invitation to the kernel's OOM
  killer.

## URL import and SSRF

The realistic risk is not a remote attacker but the operator pasting a hostile link — one
crafted to make the server fetch something only the server can reach. The guards are
proportionate to that:

1. **https only** unless `CS2A_ALLOW_HTTP_IMPORT` is set; no embedded credentials; ports
   80 and 443 only; the host is IDNA-encoded so a Unicode homograph cannot resolve
   somewhere other than what was validated.
2. **Every resolved address must be globally routable, fail-closed.** If *any* address a
   host resolves to is private, the request is refused — checking only the first would let
   a host with one public and one private record through. IPv4-mapped IPv6
   (`::ffff:127.0.0.1`) is unwrapped first, the NAT64 prefix is rejected, and multicast,
   reserved, loopback, link-local and unspecified addresses are excluded explicitly
   (Python's `is_global` returns `True` for multicast).
3. **No implicit redirects.** At most five hops, each fully re-validated; https→http
   downgrades refused.
4. **The connection is pinned to the validated IP** with the hostname preserved for TLS, so
   a DNS record that changes between validation and connection cannot redirect it. If the
   transport cannot support pinning, the code degrades to validate-then-connect and logs
   that the narrow race remains.
5. **`trust_env=False`** — the detail most implementations miss. Without it, `HTTP_PROXY`
   in the environment would route the request through a proxy and bypass every address
   check above.
6. **Budgets**: connect, read and overall deadlines, plus the same streaming size cap as a
   direct upload.

### Residual risks, documented rather than hidden

- A public host the operator chooses to fetch *is* fetched. Error messages therefore never
  echo response bodies or headers, so the endpoint cannot be used as a readable proxy.
- Internal services on globally-routable addresses are indistinguishable from the internet
  and are not blocked.
- If address pinning is unavailable on the installed transport, a narrow DNS-rebinding
  window exists between validation and connection.

Neither of the first two is fixable without an egress allowlist, which is disproportionate
for a single-user local tool. Set `CS2A_ALLOW_URL_IMPORT=false` to disable the feature
entirely.

> `CS2A_ALLOW_PRIVATE_IMPORT` disables the address check. It exists for isolated testing
> and should never be enabled otherwise.

## Logging

Server logs record match IDs, map names, sizes, timings and error classes. They do **not**
record demo contents. User-facing error messages never include filesystem paths or
tracebacks; those stay in the log. A test asserts that a failed parse surfaces neither.
