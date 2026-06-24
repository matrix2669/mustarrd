# Plex commercial skip via embedded chapters, not DB injection

## Context

In Mark mode we want Plex users to benefit from commercial detection. But Plex
offers automatic commercial skip **only for recordings its own DVR made**; for a
file Mustarrd drops into a normal library, Plex ignores sidecar `.edl` and has no
supported auto-skip. The only way to make Plex clients auto-skip an external file
is to write "commercial" markers directly into Plex's private SQLite database.

## Decision

Mark mode embeds commercial-break **chapter markers** into the MKV/MP4 (derived
from the same Comskip segments as the EDL). Plex shows these chapters, giving
one-click / chapter-nav skipping. The EDL sidecar continues to serve generic
players (Kodi, Jellyfin, Emby, MythTV) that auto-skip from it.

## Considered options

- **Plex DB marker injection** (true auto-skip) was rejected. It requires
  Mustarrd to run on the same host as the Plex server with read/write access to
  `com.plexapp.plugins.library.db`, is unsupported by Plex, and breaks on Plex
  schema changes. Mustarrd integrates with Plex over the API only and must not
  depend on co-location or Plex internals.

## Consequences

- Plex gets **manual** chapter skip, not automatic skip. This is an accepted
  limitation, surfaced in the UI.
- Chapters need a container, so Mark + Keep .ts yields the sidecar with no Plex
  benefit; the UI warns about this.
