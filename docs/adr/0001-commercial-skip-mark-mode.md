# Commercial Skip gains a Mark mode, decoupled from cutting

## Context

Commercial Skip was a single on/off (`comskip_enabled`) that always meant
"detect and physically cut," and it forced `transcode_enabled=true` because the
cut needs FFmpeg. Users wanted a non-destructive option: keep the full recording
but expose where the ads are.

## Decision

Commercial Skip becomes a three-way mode — **Off / Mark / Cut**:

- **Cut** is the pre-existing behaviour, unchanged. Still forces re-encode/remux.
- **Mark** runs Comskip but does not cut. It writes an EDL sidecar and (when the
  container is MKV/MP4) embeds commercial-break chapters. See [ADR-0002](0002-plex-commercial-skip-via-chapters.md).

Mark is fully decoupled from cutting: it no longer forces a container conversion.
The "comskip forces re-encode" rule narrows to **Cut only**, so Mark honours the
Post-Processing format picker, including Keep .ts (sidecar-only in that case).

Schema: keep `comskip_enabled` meaning "Comskip runs" and add a cut-vs-mark flag
defaulting to **Cut**, so existing installs are byte-for-byte unchanged.

## Considered options

- A two-switch model ("write EDL" + "cut them out") was rejected: it admits a
  meaningless "both on" state. The three-way mode makes illegal combinations
  unrepresentable.

## Consequences

- The old invariant "comskip_enabled ⇒ transcode_enabled" is no longer absolute.
  Anything relying on it must check the mode.
- A new container combination becomes reachable: Comskip running with Keep .ts.
