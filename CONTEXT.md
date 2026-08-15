# Mustarrd

An IPTV catchup DVR. It browses past EPG programs on Xtream Codes servers and
downloads catchup/timeshift streams, with optional commercial detection and
re-encoding before the finished file lands in the completed folder.

## Language

### Commercial Skip

**Commercial Skip**:
The feature (and Settings section) that runs Comskip over a recording to find
advertising. It has three modes: Off, Mark, and Cut.
_Avoid_: Comskip (that's the tool, not the feature), ad-detection

**Mark** (mode):
Comskip detects commercials and Mustarrd, without cutting the video, writes an
EDL sidecar (for generic players) and embeds commercial-break chapter markers in
the container (for Plex). The original content stays intact. Chapters require an
MKV/MP4 container; on Keep .ts, Mark produces the sidecar only.
_Avoid_: soft cut, EDL mode, sidecar mode

**Commercial chapter**:
A chapter marker embedded in the finished MKV/MP4 at a commercial boundary, so a
Plex client can jump the break by chapter. Mustarrd's stand-in for Plex
commercial skip, which Plex does not offer for non-DVR library files.
_Avoid_: marker (overloaded by Plex's own DB markers), ad break

**Cut** (mode):
Comskip detects commercials and FFmpeg physically removes them, producing an
altered, shorter video file. The pre-existing behaviour.
_Avoid_: remove, hard cut, strip

**EDL sidecar**:
The `.edl` (Edit Decision List) file Comskip emits, named to match the finished
video and placed alongside it, listing commercial segments so players can skip
them. Produced only in Mark mode.
_Avoid_: cutlist, skip file, chapters

### Preview

**Preview**:
Watching a provider stream in the browser before or instead of downloading it,
to answer "is this the right thing?". Applies to live channels, catchup
programs, and VOD. Time-limited and concurrency-limited by design: it is not a
TV client.
_Avoid_: playback (that's watching a finished recording), streaming, watch

**Direct preview** (mode):
A preview where the browser receives the provider's original broadcast stream
and decodes it itself. Cheap for the server, but only works when the browser
can handle both the container and the codecs.
_Avoid_: raw preview, passthrough, TS preview

**Converted preview** (mode):
A preview where the backend re-packages the provider stream into a format the
browser can decode before sending it. Used when a Direct preview is impossible
or has failed. Costs the server real work, so it is entered by fallback rather
than by default.
_Avoid_: transcoded preview (it usually only converts the audio), compatibility
mode (that's the user-facing wording, not the concept), server-side preview
