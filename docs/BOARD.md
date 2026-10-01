# Acceptance board

`rumbo/web/board.html` is one self-contained, read-only HTML resource. It has no
package install, external assets, telemetry, or write/approval tool. The server
returns it as `text/html;profile=mcp-app` to capable MCP hosts.

## What the board shows

The board follows goal → task → artifact → evidence → human decision. It includes:

- Original request, constraints, contract revision, and named decision owner
- Filterable task states with keyboard-operable selection
- Exact acceptance check values, keys, and manual-review prompts
- Artifact path, revision, maker, size, and SHA-256
- Deterministic receipts separated from attributed reviewer assertions
- Revision/digest-invalid historical records and superseded decisions
- Recorded decision requests, without implying that their resolution is tracked
- Demo labeling whenever the source snapshot has `demo: true`
- Explicit last-snapshot warning when a refresh fails
- Copy handoff, with a selectable text fallback if clipboard access is unavailable

The summary counts come from the engine's snapshot, not browser-side acceptance
logic. “Checks passed” is never labeled as human acceptance. A local hash chain
checks record consistency; it does not independently prove real-world correctness
or authenticate a human beyond the engine's configured principal boundary.

## Standalone local mode

A top-level page reads `GET /api/state` on the same origin and only on load or an
explicit Refresh. It omits credentials and does not include API tokens. The
server's standalone preview serves synthetic demo state; it does not expose an
unauthenticated private-project board. Real project state travels through the
MCP host's authenticated bridge.

## MCP Apps bridge

The implementation follows the stable
[MCP Apps 2026-01-26 specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx):

1. The embedded view sends `ui/initialize` with `appInfo`, empty privileges, inline
   display support, and protocol version `2026-01-26`
2. It checks the negotiated version, applies a bounded light/dark theme, and sends
   `ui/notifications/initialized`
3. The initial state comes from the host's `ui/notifications/tool-result` with
   `params.structuredContent`. It does **not** duplicate that initial tool call
4. Explicit Refresh calls `tools/call` with name `rumbo_state` and empty arguments,
   only when the host advertises `serverTools`
5. It emits deduplicated `ui/notifications/size-changed` messages, handles partial
   host context/theme updates, ping, and resource teardown

Messages must come from the parent window. After the initialize response the
view also pins its origin (including the opaque `null` origin used by some
sandboxes). Unrecognized messages are ignored. Host CSS/fonts are not injected.
The bridge has 10-second request timeouts. An unsupported negotiated version
stops initialization with an explicit message. The view accepts the standard
CallToolResult directly and tolerates a `result` wrapper for compatible hosts.

All untrusted values use `textContent`, not HTML interpretation. Artifact paths
are displayed as text, not executable or downloadable links. The restrictive
page CSP allows inline code/style and same-origin data reads, with no image/font,
object, form, or base-URL capabilities. The host's resource CSP further restricts
network access for the embedded view.

## Verification

Run the always-available Python source checks and optional Node runtime checks:

```sh
python -m unittest discover -s tests -p test_board.py -v
```

The Node tests execute the production script against a minimal DOM adapter. They
cover rendered provenance, real `Engine.snapshot()` schema compatibility, exact
criteria, bridge handshake/no duplicate initial fetch, explicit refresh, spoofed
message rejection, unsupported versions, filtering, copying, stale refresh
warnings, historical digests, superseded decisions, and recorded requests. These
are behavior checks, **not a browser layout or accessibility audit**. Node is a
test-only convenience; it is not required to run Rumbo or the board.

For real browser regression checks on a machine with Playwright and Chromium:

```sh
RUMBO_BROWSER_TESTS=1 python -m unittest discover -s tests -p test_board.py -v
```

The five optional browser tests exercise visible rendering, selection/filtering,
copying, error recovery, narrow-width overflow, hostile text, and iframe bridge
behavior using a temporary loopback fixture server. They are off by default so
The runtime does not acquire a browser dependency. The repository CI workflow installs pinned development-only Playwright/Chromium on a standard Ubuntu runner and executes scripts/run_tests.py --strict, which fails on any skipped test. It stores only synthetic board screenshots for one day. A CI run must be checked on its exact commit; inclusion of the workflow does not claim that it has run.

### Current environment limitations (2026-10-01)

Source and Node runtime checks passed. Browser visual/layout verification remains
unverified. Two attempted routes were unavailable:

- Cloud browser (CUA) opening `http://127.0.0.1:8767/` returned
  `Browser Use cannot open http://127.0.0.1:8767 in tab 18. Browser reported: net::ERR_BLOCKED_BY_CLIENT`
- Installed Chromium launched by the optional test suite failed before loading
  the board, including when tool escalation was requested:
  `FATAL:chrome/browser/process_singleton_posix.cc:297] Check failed: . socket() failed: Operation not permitted (1)`
  with `chrome_crashpad_handler: --database is required`

No approval-reviewer denial was returned. No file/data-URL alternative was used
because the loopback block could reflect a policy restriction. No rendered
browser screenshot is included or claimed. Responsive CSS and accessibility
semantics are implemented, but visual layout, keyboard flow, screen-reader
behavior, and real-host rendering still need verification in a supported browser.
