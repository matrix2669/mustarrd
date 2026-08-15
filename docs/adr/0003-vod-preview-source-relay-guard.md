# VOD preview source relay is guarded by token plus peer address, not by its own listener

## Context

A VOD preview must seek: nobody decides whether a two-hour film is the right one
from its first thirty seconds. Seeking means FFmpeg has to issue byte-range
requests against the source itself, and it cannot be handed the provider URL to
do that with — the URL embeds the account username and password, and anything in
FFmpeg's argv is readable by every user on the host via `ps`.

So the provider URL stays in-process behind an opaque token, and FFmpeg is
pointed at a relay endpoint on `http://127.0.0.1:<port>/api/vod/preview/source/
<token>`. The question is what stops anyone other than our own FFmpeg from
calling that endpoint.

Today the relay is a route on the main FastAPI app, guarded by three things: an
unguessable 256-bit token, a short TTL with revocation when the preview session
closes, and a check that the caller's peer address is loopback.

The peer-address check is worth less than it looks. Where a reverse proxy shares
this process's network namespace — the same container, or a proxy on the same
host forwarding to 127.0.0.1 — every request arrives from 127.0.0.1 and the
check stops distinguishing anything. In that topology the token is the only
guard.

## Decision

Keep the relay on the main app, guarded by token + peer address, and additionally
refuse any request carrying proxy headers (`X-Forwarded-For`, `X-Forwarded-Host`,
`X-Real-IP`, `Forwarded`). FFmpeg sends none of them; a proxy forwarding a
request almost always adds them.

## Considered options

- **A separate loopback-only listener for the relay** — bind a second HTTP
  server to `127.0.0.1:0` and serve the relay route there alone. This is
  strictly stronger: "only local callers" becomes a property the kernel enforces
  through the bind address, rather than application logic inspecting a peer
  address it cannot trust. A proxy fronting the app on its public port cannot
  reach the relay at all, because the relay is not on that port. Rejected *for
  now* on cost, not on merit: it adds a second server lifecycle (startup,
  ephemeral port allocation, shutdown, desktop and Docker modes) for a residual
  risk the token already bounds. This is the option to take if the relay ever
  carries something worth more than one title.
- **A Unix domain socket** — would give the same kernel-enforced guarantee with
  filesystem permissions. Rejected: FFmpeg's HTTP client cannot read HTTP over a
  Unix socket.

## Consequences

- Behind a namespace-sharing reverse proxy, the effective guard is the token
  plus the proxy-header check.
- The token itself is in FFmpeg's argv, so a local user on the host can read it
  from `ps` and fetch the bytes. This is inherent to the design and accepted:
  the token is worth one title for at most fifteen minutes, whereas the
  credentials it replaced are worth the whole account indefinitely. Shrinking
  that prize is the entire point of the relay.
