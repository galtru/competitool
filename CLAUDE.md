# Ad Stack Competitive Analyzer — Technical Plan

## 1. Problem Statement

Our video player customers are reporting that competitors deliver **~2x eCPM** on equivalent inventory. We need to determine *why* by inspecting how competitor players configure and orchestrate their demand stacks (Prebid, Google IMA, identity, floors, ad pods), and produce a precise, actionable gap analysis against our own implementation.

**Working hypothesis:** the gap is driven by demand-stack architecture and identity richness, not player performance.

**Goal of this project:** a backend service that, given a URL, autonomously loads the page, plays its video, captures the full ad stack behavior, and produces an opinionated scorecard highlighting the specific things our competitors do that we don't.

---

## 2. Success Criteria

The tool is successful if it can:

1. Take a competitor URL and produce a structured report within ~5 minutes.
2. Correctly identify, for each target: Prebid bidders, identity providers (EIDs), Prebid↔IMA integration mode, ad pod configuration, and floor strategy.
3. Output a **delta scorecard** comparing the target against our known implementation, ranked by estimated revenue impact.
4. Be re-runnable on captured artifacts without re-crawling (analysis is separable from capture).

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Orchestrator (FastAPI)                                 │
│  POST /analyze { url, session_count, video_actions }    │
│  GET  /report/{id}                                      │
└────────────────────────┬────────────────────────────────┘
                         │
            ┌────────────▼────────────┐
            │  Job Queue (Celery/RQ)  │
            └────────────┬────────────┘
                         │
        ┌────────────────▼────────────────┐
        │  Capture Worker                 │
        │  Playwright (headful Chromium,  │
        │  stealth patches, real UA)      │
        │  Outputs: HAR, console, perf,   │
        │  JS globals, screenshots        │
        └────────────────┬────────────────┘
                         │
              [artifacts on disk/S3]
                         │
        ┌────────────────▼────────────────┐
        │  Analyzers (pure functions)     │
        │  - prebid_analyzer              │
        │  - ima_analyzer                 │
        │  - identity_analyzer            │
        │  - vast_analyzer                │
        │  - timing_analyzer              │
        │  - pod_analyzer                 │
        │  - floors_analyzer              │
        └────────────────┬────────────────┘
                         │
        ┌────────────────▼────────────────┐
        │  Report Builder                 │
        │  - Scorecard (signal)           │
        │  - Implementation delta         │
        │  - Raw artifacts (noise, linked)│
        └─────────────────────────────────┘
```

**Key architectural principle:** capture and analysis are decoupled. The capture worker dumps everything to disk; analyzers read artifacts and produce focused output. This lets us re-run analysis with improved heuristics without re-crawling, and lets us version analyzers independently.

---

## 4. Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Ecosystem for analysis, async support |
| Browser automation | Playwright (Chromium) | Better network interception than Puppeteer, built-in HAR, multi-browser support |
| Stealth | playwright-stealth / custom patches | Ad stacks fingerprint heavily; bot detection skews demand |
| API | FastAPI | Async-native, OpenAPI out of the box |
| Job queue | Celery or RQ | Background crawling, retry logic |
| Storage | Local disk for MVP → S3 later | HAR files are large, don't bloat the DB |
| Metadata DB | SQLite for MVP → Postgres later | Job state, report index |
| HAR parsing | haralyzer + custom | Standard HAR tooling |
| VAST parsing | python-vast or custom XML | VAST is XML, straightforward |

---

## 5. Capture Layer — Detailed Spec

### 5.1 Browser Configuration

- **Headful Chromium** (not headless). Headless is detectable and triggers low-quality demand.
- Stealth patches applied (`navigator.webdriver`, plugins array, WebGL vendor, etc.).
- Real user-agent strings; rotate across sessions.
- `--autoplay-policy=no-user-gesture-required` to allow video autoplay.
- Fresh user data dir per session (no cookie/storage carryover unless intentionally testing logged-in state).
- Viewport: vary across sessions (1920x1080, 1440x900, 1366x768).

### 5.2 Page Lifecycle Per Session

1. Navigate to target URL.
2. Auto-accept consent banner if present (try common CMP selectors: `#onetrust-accept-btn-handler`, `.cmp-accept`, etc.).
3. Scroll the video element into viewport.
4. Trigger `video.play()` on the first detected `<video>` element.
5. Run for **90–120 seconds minimum** to capture preroll + first mid-roll.
6. Inject probe scripts at key moments to snapshot JS globals.
7. Tear down and write artifacts.

### 5.3 Artifacts Captured Per Session

| Artifact | Format | Purpose |
|---|---|---|
| Network log | HAR | Full request/response data |
| Console log | JSONL | Errors, warnings, Prebid debug if available |
| Performance entries | JSON | `performance.getEntries()` snapshots |
| JS globals snapshots | JSON | `pbjs.getConfig()`, `pbjs.getBidResponses()`, `pbjs.getEvents()`, `googletag` state, IMA state |
| Video element events | JSONL | play, timeupdate, ad start/end via MutationObserver |
| Screenshots | PNG | Page load, video first frame, ad start, ad end |
| Session metadata | JSON | URL, UA, viewport, timestamp, duration |

### 5.4 Multi-Session Strategy

Run **5–10 sessions per URL** because demand varies session-to-session (bidder participation, floors, pod length). Vary:

- Viewport size
- User-agent
- Fresh storage state
- Optionally: simulate geo via proxy (separate phase)

Aggregate stats (avg bidders responding, p50 timing, etc.) over the session set.

### 5.5 Probe Script

Inject a script at `document_start` that:

- Hooks `pbjs.que.push` to capture every config call.
- Listens for Prebid events: `auctionInit`, `bidRequested`, `bidResponse`, `bidWon`, `auctionEnd`.
- Listens for IMA events on `google.ima.AdsManager` if reachable.
- Polls `window` for known identity globals (`__uid2`, `ID5`, `LiveRampATSEmail`, etc.) every 500ms for the first 30s.
- Sends all observations to a `window.__probe_log` array that's exfiltrated at session teardown.

---

## 6. Analyzers — Detailed Spec

Each analyzer is a pure function: `(artifacts: dict) -> AnalyzerResult`. Results are aggregated across sessions before scorecard rendering.

### 6.1 `prebid_analyzer`

**Detects:** Prebid presence, version, configured bidders, auction behavior.

**Inputs:** HAR, console log, JS globals snapshots, probe log.

**Outputs:**
- `version` — from `pbjs.version`
- `mode` — `client_side` | `s2s` | `hybrid` (detect s2s via known Prebid Server endpoints)
- `timeout_ms` — from `pbjs.getConfig().bidderTimeout`
- `bidders` — list of all configured adapters (from auction events or config snapshot)
- `bidders_responding` — per-session count of adapters that returned a bid
- `auction_count_per_session` — preroll only, or refresh?
- `floors_module_loaded` — boolean

### 6.2 `ima_analyzer`

**Detects:** Google IMA usage and whether Prebid is wired into it (the critical integration check).

**Inputs:** HAR (filter: `pubads.g.doubleclick.net/gampad/ads`).

**Outputs:**
- `present` — boolean
- `gam_network_id` — from `iu=` query param
- `ad_unit_path` — from `iu=`
- `cust_params_keys` — parsed from `cust_params=` query param
- **`header_bidding_integrated`** — true if `cust_params` contains `hb_pb`, `hb_bidder`, `hb_size`, `hb_uuid`. **This is the single most important signal in the entire tool.**
- `hb_pb_value` — winning Prebid bid price bucket, if present. *This is the closest we can get to seeing actual CPM from the outside.*
- `ad_pod_requested` — true if `pmad`/`pmnd`/`pmxd` params present
- `pod_max_duration_s` — from `pmxd`
- `pod_max_ads` — from `pmad`
- `targeting_params` — all key-value pairs in `cust_params`

### 6.3 `identity_analyzer`

**Detects:** identity providers loaded and propagated to bidders. This is where most of the gap likely lives.

**Inputs:** HAR (script srcs + OpenRTB request bodies), JS globals.

**Detection patterns:**
- UID2: `uid2-sdk`, `__uid2` global, `UID2` in EIDs
- ID5: `id5-sync.com`, `id5id.eids`
- LiveRamp: `launchpad-wrapper.liveramp.com`, `idl_env`, `liveramp.com` in EIDs
- SharedID: `pubcid.org`, `pubCommonId` in EIDs
- ConnectID (Yahoo): `connectid.yahoo.com`
- Criteo ID: `criteo.com/userid`
- IdentityLink: `ats.js`
- Publisher first-party hashed email: scan OpenRTB `user.ext.eids` for `pubProvidedId` or `id5-sync.com` with hashed source
- Topics API: presence of `document.browsingTopics()` calls
- Protected Audience (FLEDGE): presence of `joinAdInterestGroup` / `runAdAuction`

**Outputs:**
- `eids_observed` — list of identity sources detected
- `eid_count`
- `eids_per_bidder` — for each bidder request observed, which EIDs were sent
- `bidders_receiving_eids_pct` — coverage metric

### 6.4 `vast_analyzer`

**Detects:** ad creative structure and quality signals.

**Inputs:** HAR (filter for VAST XML responses by content-type and content sniffing).

**Outputs:**
- `wrapper_depth` — count of `<VASTAdTagURI>` redirects
- `final_advertiser_domain`
- `creative_duration_s`
- `skippable` — boolean
- `vpaid` — boolean (VPAID is slower and being deprecated)
- `tracker_count` — number of tracking pixels in the chain

### 6.5 `timing_analyzer`

**Detects:** orchestration timing — when ad requests fire relative to page load and to each other.

**Inputs:** HAR, performance entries.

**Outputs:**
- `page_load_to_first_ad_request_ms`
- `first_ad_request_to_response_ms`
- `ad_response_to_ad_start_ms`
- `prebid_auction_duration_ms`
- `parallel_or_waterfall` — heuristic: if Prebid bidder requests and IMA request fire within 100ms of each other, parallel; if IMA fires after Prebid auction ends, header-bidding-then-IMA (which is correct); if IMA fires only after no Prebid bid, waterfall.

### 6.6 `pod_analyzer`

**Detects:** ad pod and break configuration.

**Inputs:** HAR (VAST responses with multiple `<Ad>` elements), IMA params.

**Outputs:**
- `pod_used` — boolean
- `max_ads_per_pod`
- `max_pod_duration_s`
- `breaks_per_session_observed` — preroll, midroll counts
- `midroll_cadence_s` — if multiple midrolls, average gap
- `ssai_detected` — boolean (look for known SSAI vendors in video manifest URL: Google DAI, AWS MediaTailor, Yospace, Broadpeak)

### 6.7 `floors_analyzer`

**Detects:** floor pricing strategy.

**Inputs:** HAR (Prebid floors fetch endpoint), `pbjs.getConfig().floors` snapshot if available.

**Outputs:**
- `floors_module_active` — boolean
- `floors_dynamic` — true if fetched from a floors endpoint at runtime
- `floor_schema` — fields used (mediaType, size, domain)
- `sample_floor_values`

---

## 7. The Scorecard — Output Spec

The report's primary deliverable is an opinionated, comparative scorecard. Raw artifacts are linked but not inlined.

### 7.1 Top-Level Structure

```json
{
  "target": "https://competitor-publisher.com/article/xyz",
  "captured_at": "2026-05-27T10:00:00Z",
  "session_count": 8,
  "summary": {
    "estimated_yield_gap_drivers": [
      {"factor": "prebid_to_ima_integration", "their_score": 10, "your_score": 0, "weight": "very_high"},
      {"factor": "identity_richness", "their_score": 9, "your_score": 2, "weight": "high"},
      {"factor": "bidder_count", "their_score": 8, "your_score": 5, "weight": "high"},
      {"factor": "floor_strategy", "their_score": 7, "your_score": 3, "weight": "medium"}
    ]
  },
  "demand_stack": { /* prebid + ima details */ },
  "identity": { /* eid details */ },
  "orchestration": { /* timing + parallel/waterfall */ },
  "pod_strategy": { /* pod + midroll + ssai */ },
  "floors": { /* floors strategy */ },
  "your_implementation_delta": {
    "missing_bidders": ["criteo", "ttd", "smartadserver"],
    "missing_identity": ["uid2", "id5", "liveramp", "sharedid"],
    "header_bidding_to_ima": "NOT_INTEGRATED — likely largest single gap",
    "prioritized_actions": [
      "1. Wire Prebid → IMA via cust_params (hb_pb, hb_bidder, hb_size, hb_uuid). Estimated 30–60% eCPM lift.",
      "2. Add UID2 + ID5 + SharedID modules to Prebid. Estimated 15–30% lift.",
      "3. Add missing bidders most common across competitors.",
      "4. Enable Prebid floors module with dynamic floors."
    ]
  },
  "raw_artifacts": {
    "har_paths": ["s3://.../session_001.har", "..."],
    "console_paths": ["..."],
    "screenshots": ["..."]
  }
}
```

### 7.2 Reading Priority

A user should be able to read **only `summary.estimated_yield_gap_drivers` + `your_implementation_delta.prioritized_actions`** and know what to build next. Everything else is supporting evidence.

### 7.3 "Your Implementation" Config

Our own implementation is provided as a static YAML config (`our_stack.yaml`) — we know what we ship. The delta engine diffs the target's observed stack against this config.

```yaml
# our_stack.yaml
prebid:
  version: "8.20.0"
  bidders: ["appnexus", "rubicon", "openx", "pubmatic", "ix"]
  timeout_ms: 1500
  floors_module: false
ima:
  present: true
  header_bidding_integrated: false  # ← known gap
identity:
  eids: ["sharedid"]
pod:
  max_ads: 1  # ← known gap, no pods
  midroll: false
```

---

## 8. Phased Build Plan

### Phase 1 — MVP (Week 1–2)

**Goal:** prove the capture+analysis loop on one URL.

- [ ] FastAPI skeleton with `POST /analyze` and `GET /report/{id}`
- [ ] Playwright capture worker (single session, single URL, local disk)
- [ ] HAR + console + screenshots + JS globals snapshot
- [ ] CMP auto-accept (top 5 CMPs by market share: OneTrust, Quantcast, Sourcepoint, Didomi, TrustArc)
- [ ] Auto video play with viewport scroll
- [ ] `prebid_analyzer` — version, bidders, timeout, mode
- [ ] `ima_analyzer` — presence, hb_keys check, gam network
- [ ] `identity_analyzer` — UID2, ID5, LiveRamp, SharedID detection
- [ ] Scorecard renderer with hardcoded `our_stack.yaml`
- [ ] **Exit criteria:** run against 3 known competitor URLs, produce a report that names the top 3 gaps correctly.

### Phase 2 — Robustness (Week 3)

- [ ] Job queue (Celery/RQ) for async execution
- [ ] Multi-session per URL (5–10), aggregate stats
- [ ] Stealth hardening — pass common bot detection tests
- [ ] Vary viewport/UA across sessions
- [ ] `vast_analyzer` — wrapper depth, skippable, VPAID
- [ ] `timing_analyzer` — full timing breakdown, parallel vs waterfall heuristic
- [ ] SQLite metadata store for job/report index

### Phase 3 — Depth (Week 4–5)

- [ ] `pod_analyzer` — pods, midrolls, SSAI detection
- [ ] `floors_analyzer`
- [ ] Cross-target comparison view (analyze 10 competitors, find common patterns)
- [ ] HTML report rendering on top of the JSON
- [ ] S3 artifact storage
- [ ] Postgres metadata DB

### Phase 4 — Scale & Polish

- [ ] Residential proxy support for geo variation (US, EU, APAC)
- [ ] Logged-in / paywall handling
- [ ] Scheduled re-runs (track competitor changes over time)
- [ ] Slack/email alerting when a competitor stack changes meaningfully

---

## 9. Known Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Bot detection skews demand | Reports underestimate competitor CPM, falsely make them look weaker | Stealth patches, headful, residential proxies, validate by spot-checking known-good site |
| Prebid wrapped/obfuscated | Can't read `pbjs.*` globals | Fall back to network parsing of OpenRTB requests |
| GDPR consent gating | Empty data from EU IPs | Auto-accept CMP, use US IPs for primary runs |
| SSAI hides ad calls | Can't see auction at all | Detect SSAI explicitly and flag — that itself is the finding |
| Competitor changes stack | Reports go stale | Phase 4: scheduled re-runs |
| Single session lies | Misleading conclusions | Phase 2: enforce N≥5 sessions before scoring |
| ToS/legal | Crawling concerns | Public pages only, rate-limit politely, honest UA, no auth bypass |

---

## 10. Repository Layout

```
ad-analyzer/
├── README.md
├── pyproject.toml
├── our_stack.yaml             # config: our known implementation
├── api/
│   ├── main.py                # FastAPI app
│   ├── routes.py
│   └── models.py              # Pydantic models
├── capture/
│   ├── worker.py              # Playwright orchestration
│   ├── stealth.py             # browser hardening
│   ├── cmp.py                 # consent banner handlers
│   ├── probe.js               # injected page-side script
│   └── lifecycle.py           # session lifecycle
├── analyzers/
│   ├── base.py                # AnalyzerResult dataclass
│   ├── prebid.py
│   ├── ima.py
│   ├── identity.py
│   ├── vast.py
│   ├── timing.py
│   ├── pod.py
│   └── floors.py
├── report/
│   ├── scorecard.py           # scoring logic
│   ├── delta.py               # diff vs our_stack.yaml
│   └── renderer.py            # JSON + HTML output
├── storage/
│   ├── artifacts.py           # local disk / S3 abstraction
│   └── db.py                  # SQLite/Postgres
└── tests/
    ├── fixtures/              # canned HARs from real sites
    ├── test_prebid.py
    ├── test_ima.py
    └── ...
```
