# Redesign Help

Lessons from the Settings page redesign (June 2026) that transfer to redesigning
other sections of Mustarrd. Read this before starting a similar pass on Browse,
Downloads, Scheduled, etc.

## Reusable building blocks (already built — don't reinvent)

All in `frontend/src/components/settings/`, but most are not settings-specific:

- **`NumberStepper`** — horizontal `[−] value [+]` with unit label, clamping,
  46px touch sizing under 820px. Use it anywhere a `NumberInput` feels fiddly.
- **`SettingsPrimitives.jsx`** — `SectionHeader` (18/700 title + dimmed desc),
  `SubGroup` (uppercase subhead + dashed rule via `Divider labelPosition="left"`),
  `SettingRow` (label left / control right, description below, 1px rules between
  consecutive rows via `.row + .row` in module CSS), `LabelWithTooltip`
  (info-circle icon + Mantine Tooltip with `events={{ hover, focus, touch }}`),
  `StepperField` (label-above-stepper for grid layouts).
- **`SaveBar`** — floating "N unsaved changes" bar. Pair it with the dirty-count
  pattern below.
- **`SettingsSearch` + `sections.js`** — the registry/search pattern (items with
  `{ label, section, kw }`) generalizes to any client-side jump-to-thing search.

## Design-handoff bundles

- The bundle README is the source of truth for IA/behavior; the prototype's
  `*-components.css` is the authoritative reference for exact sizes/colors,
  including mobile rules. The JSX files are references, not code to ship.
- Prototype hex values are chosen to match Mantine dark defaults — translate to
  Mantine CSS variables, don't hardcode: `--mantine-color-default` (card),
  `--mantine-color-default-border`, `--mantine-color-default-hover`,
  `--mantine-color-dimmed`, `--mantine-color-text`, `--mantine-color-body`,
  and mustard = `--mantine-color-yellow-7` (#f59f00, the theme primary).
  Hardcoding breaks the light theme (Appearance section is a real toggle).
- Ignore any tweaks-panel / review-tooling files in a bundle.

## Mantine / CSS gotchas

- **Inline `styles={{ input: { fontSize } }}` beats CSS media queries.** If a
  size must change at a breakpoint (e.g. mobile 16px to prevent iOS zoom), use
  `classNames={{ input: classes.foo }}` + a CSS module, never the `styles` prop.
- CSS modules hash every class: descendant selectors like `.msg .n` silently
  fail unless the inner class is also from the module (or `:global`). One
  exported class per element is safest.
- A keyframe animating `transform` fights a base `transform` used for
  positioning (e.g. `translateX(-50%)` centering). Put positioning on an outer
  element and the entrance animation on an inner one.
- Scheme-specific styles: `:global([data-mantine-color-scheme='light']) .foo`.
- `SegmentedControl` supports per-item `disabled` in `data`, and labels can be
  JSX (icon + text). Items render as `role="radio"` — handy in tests.
- Mantine `NavLink` is fine for rails; override via
  `styles={{ root, label, section }}`.
- Responsive card grids: `repeat(auto-fill, minmax(min(330px, 100%), 1fr))` —
  the `min()` prevents overflow on narrow phones without a media query.

## Breakpoint inconsistency (watch out)

- The app shell (`App.jsx`) collapses the navbar at **48em (768px)**; the
  settings redesign uses **820px** per the design. Global `styles.css` forces
  16px inputs only ≤768px. If a redesigned page uses 820px, it must handle its
  own 768–820px input sizing (see `.page .mantine-Input-input` rule in
  `Settings.module.css`).
- jsdom tests get `matchMedia → matches: false`, i.e. always desktop layout.

## State patterns worth copying

- **Dirty tracking / partial saves**: keep an `editedFields` Set updated on
  every change; `changedFields = edited ∩ (value differs from server snapshot)`;
  save sends only those fields. `settingsApi.update` (and the backend generally)
  accepts partial payloads and returns the full updated record — use the
  response to resync the local snapshot (`setQueryData` + replace form state)
  instead of waiting for a refetch. Unedited fields should resync from the
  server so changes made elsewhere (other sections, other tabs) aren't clobbered.
- **Cross-links between sections** must go through the same `selectSection`
  helper that sets the URL param (and `mobileView` on mobile) — not router
  `<Link>` — or the mobile drill-down state desyncs.
- The unsaved-changes blocker uses `UNSAFE_NavigationContext` + `navigator.block`,
  which exists because `main.jsx` uses `unstable_HistoryRouter` with history v5.
  `MemoryRouter` (tests) has no `.block`; the hook guards for that — keep the
  guard if you copy it.

## Backend facts that affect UI decisions

- **Verify backend capabilities before disabling UI combos.** The handoff README
  claimed remux+comskip was MKV-only; reading `post_processor.py` showed
  stream-copy commercial removal works for MP4 too, so no combo needed
  disabling. The old 8-option dropdown's limitations were UI-only.
- Settings coercion lives in `backend/api/settings.py` (e.g. `comskip_enabled`
  forces `transcode_enabled=true`). The PUT response reflects coerced values —
  another reason to resync from the response.
- Useful live-status endpoints: `/api/downloads/disk-space` (free GB),
  `/api/settings/folders/status` (writability probes),
  `/api/settings/tools` (ffmpeg/comskip/hw-accel), `/api/epg/status`
  (now includes `interval_hours`). Prefer surfacing these inline (badges next
  to the relevant field) over status strips — that was an explicit design call.
- If the design shows data with no API (e.g. guide coverage counts), drop it or
  add a tiny backend field (like `interval_hours`) — don't fake it in the UI.

## Testing notes (Vitest + RTL)

- `src/test/setup.js` stubs `matchMedia` and `ResizeObserver`; `window.scrollTo`
  is NOT stubbed — stub it in any test of a component that calls it.
- Mock `../api` wholesale with `vi.mock`; page tests need
  QueryClientProvider + MantineProvider + MemoryRouter (see
  `src/pages/Settings.test.jsx` for a working harness + fixture).
- TanStack Query v5 calls `mutationFn(variables, context)` — assert
  `mock.calls[0][0]`, not `toHaveBeenCalledWith(variables)`.
- An `<Anchor>` inside alert text splits the text nodes: `getByText(/full
  sentence/)` breaks. Match the fragments separately.
- Keep `disabled` props on controls even when also using an
  `opacity/pointer-events` "dimmed" wrapper — accessibility and existing tests
  rely on real disabled state.

## Verification workflow on this machine

- Run servers as background tasks with the command in the foreground of the
  task (`exec python main.py` / `exec npm run dev`). Appending `&` inside the
  command kills the child when the shell exits — vite "starts" then dies,
  and a half-dead instance can squat the port (vite then silently picks 4179).
- Backend: `cd backend && source venv/bin/activate && python main.py` (4177);
  frontend `npm run dev` (4178, proxies /api).
- If the Chrome extension isn't connected, you can still catch
  compile/transform errors by curling each changed module through the dev
  server: `curl http://localhost:4178/src/pages/Foo.jsx` → non-200 = broken.
  `npx vite build` is the stricter offline check.
- No ESLint config in the repo — the build and tests are the only gates.

## Process conventions

- Small commits per section/component; the page shell is unavoidably one big
  commit — split out child components, backend tweaks, and tests.
- User-facing changes need a `CHANGELOG.md` entry, newest at top, in the
  "What you would notice" / "What changed" format.
- PRs with UI changes expect screenshots under `.github/pr-screenshots/`.
- Renamed labels/sections will break tests — grep tests for the old strings
  (`Comskip`, `Guide`, etc.) as part of the rename.
