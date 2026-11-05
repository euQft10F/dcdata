# dcdata — Implementation Plan

Scrape CDS Determinations Committee (DC) credit events plus their Procedural History documents, and
creditfixings.com auction results. Then match auctions to DC credit events. Everything is deterministic:
no LLM calls and no browser automation.

Stack: Python 3.11, `uv`, a single package `dcdata` with CLI subcommands, CSV outputs, `pymupdf4llm`
for PDF → Markdown.

---

## 1. Research findings (verified 2026-11-05)

### 1.1 DC site — `https://www.cdsdeterminationscommittees.org`

**Archive list = JSON endpoint, no browser needed.**
- `POST /credit-default-swaps-archive/data/` (DataTables 1.9 server-side protocol, form-encoded).
- Required form fields (all of them; partial sets give wrong filtering):
  ```
  sEcho=1, iColumns=8, sColumns=, iDisplayStart=0, iDisplayLength=1000,
  iSortCol_0=0, sSortDir_0=asc, iSortingCols=1, sSearch=, bRegex=false,
  pageType=credit-default-swaps-archive,
  for i in 0..7: mDataProp_i=i, sSearch_i=<"" or "credit-event" for i=2>, bRegex_i=false,
                 bSearchable_i=true, bSortable_i=true
  ```
- The response is `{"iTotalRecords":281,"iTotalDisplayRecords":281,"aaData":[[...8 cols...], ...]}`.
  All 281 credit events come back in one request. Paginate anyway with `iDisplayStart` in case the server caps it.
- Row columns:
  | idx | meaning | example / notes |
  |---|---|---|
  | 0 | Date Updated + epoch | `"October 2, 2026' '1790966100"`: split on `"' '"` |
  | 1 | committee code(s) | `americas`, `emea-europe`, `japan`, `asia-ex-japan`, `australia-new-zealand`, `""`, or several space-separated |
  | 2 | category | `credit-event` |
  | 3 | reference entity | may have trailing whitespace |
  | 4 | Submitted epoch | **int or str**, so parse defensively |
  | 5 | status | `Closed` … |
  | 6 | outcome | `Question Decided` / `Rejected` / `Dismissed` / `Withdrawn` / `None` |
  | 7 | URL-encoded HTML block | `urllib.parse.unquote_plus()` it first |
- The HTML block (col 7) contains:
  - `h2.credit-title`: "Question: Has a Bankruptcy Credit Event occurred …"
  - `p.ceMeta_2`: Transaction Type
  - `ul.ceMeta_3 li`: Issue Number, Submitted by, Committee (display), Category, Coverage Election (optional)
  - `a.more-link[href]`: **the detail page URL** (the "More" button), e.g. `https://…/cds/dish-dbs-corporation/`
  - `div.entry-content`: "Further Information Provided by Question Submitter" (free text plus links)
- Entities often have several DC issues (Casino ×11, Hellenic Republic ×3). Each has its own URL with a `-2`, `-3` … suffix.
  The URL path (`cds/<slug>`) is the unique key → `dc_id`.

**Detail page = static HTML.**
- Procedural History lives in `li.widget_dc_history_widget ul.ProceduralHistory > li`. Each `<li>` has:
  - `<h4>` heading: `Closed`, `Ongoing`, `Final List Published`, `Initial List Published`, `Preliminary List Published`,
    `Final Auction Terms Published`, `Auction Information Published`, `List of Participating Bidders Published`,
    `Request Accepted by DC`, `Pending DC Consent`, …
  - a `<p>` holding nested `<p>` elements with free text and `<a href>` document links (zero or more)
  - `<time datetime="2026-08-10T16:30:00-04:00">`
  - The order is newest first.
- **DC Decisions often sit under `Ongoing` headings.** Classify documents by link text, never by heading.
- Link-text conventions: "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26",
  "Americas DC - DISH DBS Corporation - Final List of Deliverable Obligations", "Redline of …", "… Meeting Statement …",
  "List of Participating Bidders …", "… Auction Settlement Terms …", 2009-era generic "View Attachment".

**Documents.**
- Modern links look like `https://…/documents/YYYY/MM/<name>.pdf/` (trailing slash). The server answers `200` with
  `Content-Type: text/html` **but the body is the PDF** (`%PDF-1.5`). Detect PDFs by magic bytes, never by content-type.
- Legacy links: `http://www.isda.org/dc/docs/*.pdf` redirect (301) to `https://www.isda.org/a/<id>/<name>.pdf`,
  which works (real `application/pdf`).
- Legacy links: `http://www.cdsdeterminationscommittees.org/docs/<name with spaces>.pdf` contain raw spaces
  (percent-encode them) and are sometimes **404**. Record the status; don't fail the run.
- The same PDF URL can appear on several pages (e.g. "Submission of Potential Deliverable Obligations"), so download each URL once.
- `/robots.txt` is 404 (no rules). Still be polite: rate-limit and identify with a generic UA.

### 1.2 creditfixings.com: an Angular SPA backed by a public JSON API

- API base: `https://api.creditfixings.com/api` (taken from the bundle `main-*.js`: `apiUrl`).
- The **"I Agree" disclaimer is client-side only** (it sets an `agreed` cookie). The API doesn't check it, so no Selenium/Playwright is needed.
- Endpoints:
  - `GET /auctions/years` → `[2026, 2025, …, 2010]`
  - `GET /auctions/year/{y}` → list of auctions:
    `{auctionID, auctionDate (ISO), auctionYear, auctionType ("CDS"|"LCDS"), legalName, shortName, ticker, tier, tenor, CCY, dcRegion, isdaLink, state, …}`
  - `GET /auction-results/{ticker}` → `{auctions:[…], auctionDetailsMap:{"<auctionID>": {stateParams:{…}, note, bids, offers, …}}, resultsNote}`
  - `GET /auction-details/{auctionID}` → the same detail object for one auction (fallback)
- **Final Price** is in `auctionDetailsMap[id].stateParams["Final Price"]` (string, e.g. `"26.625"`). This is the "Final Price" shown at
  the top of the Auction Results page. `stateParams` also has `Initial Market Midpoint`, `Auction Status`, `Relevant Currency`, `Dealer Count`, `Net Open Interest`, ….
  The year-list `stateParams` is `null`, so you must call the results endpoint.
- UI results link: `https://www.creditfixings.com/#/auction-results/{ticker}`.
- Totals: 155 auctions in 2010–2026, of which **19 LCDS (excluded per decision)** → **136 CDS auctions**.
  One credit event can have several auctions (tiers such as `Senior`/`Subordinated`, `Bucket 1..6`), so the output has one row per auction.
- **Every auction has `isdaLink`**, a direct link to the DC detail page. That makes it an exact join key.

### 1.3 Matching benchmark (done in research)

- Exact `isdaLink` == DC `More` URL (normalised): **133 / 136** CDS auctions.
- The 3 non-exact:
  - CODERE: malformed `…/lcds/cds/codere-finance-luxembourg-sa/`. Fixed by URL normalisation (keep path from the last `/cds/`).
  - DISH DBS (2026-08-04) and Liberty Interactive (2026-05-13): `isdaLink` points at a **PDF** on the DC site. Match it via the
    documents table: the PDF URL appears in that DC page's Procedural History.
- Fuzzy-only, measured against the 133 known pairs (correct / wrong / none):

  | scorer | threshold | result |
  |---|---|---|
  | `partial_ratio`, no date logic | 85 | 93 correct (≈70%) |
  | `partial_ratio` + date window + "Decided" tie-break | 85 | 118 / 12 / 3 |
  | `token_sort_ratio` (normalised) + same tie-breaks | 80 | 120 / 8 / 5 |
  | `ratio` + same tie-breaks | 80 | 121 / 8 / 4 |

  Below 80 adds only wrong matches. The remaining errors come from **several DC issues of the same entity close in time**,
  which no name scorer can separate. **Conclusion:** use the deterministic link joins first. Fuzzy is a labelled fallback only.

---

## 2. Decisions (confirmed with the user)

| topic | decision |
|---|---|
| Documents to download | **Decisions + lists only.** All timeline entries and links go into the CSV. Only PDFs of type `dc_decision`, `final_list`, `initial_list`, `preliminary_list`, `auction_terms` are downloaded and converted. Redlines, meeting statements, bidder lists and other links are recorded but not downloaded. `--doc-types` CLI flag overrides this. |
| LCDS | **Excluded entirely** (`auctionType == "LCDS"` dropped at scrape time). |
| PDF → Markdown | **pymupdf4llm** (AGPL-3.0; fine for internal use). |
| Output | **CSV only** (+ PDF and Markdown folders). |
| Structure | **One package, CLI subcommands**: `dcdata dc`, `dcdata auctions`, `dcdata match`, `dcdata all`. |
| Browser | None. Plain HTTP (httpx). |
| Fuzzy | RapidFuzz `token_sort_ratio` on normalised names, threshold **80** (CLI-configurable), plus date window and tie-breaks. Fallback only. |

---

## 3. Project layout

```
dcdata/
├─ pyproject.toml            # uv project, requires-python ">=3.11,<3.12", script entry dcdata = "dcdata.cli:main"
├─ .python-version           # 3.11
├─ .gitignore                # .venv/, data/, __pycache__/, .pytest_cache/, .ruff_cache/
├─ README.md
├─ PLAN.md
├─ src/dcdata/
│  ├─ __init__.py
│  ├─ cli.py                 # argparse: dc | auctions | match | all  (+ shared flags)
│  ├─ config.py              # URLs, paths, UA, rate limits, thresholds, target doc types
│  ├─ http.py                # Fetcher: httpx client, rate-limit, retries, on-disk cache
│  ├─ csvio.py               # write_csv(rows, path, columns) / read_csv → list[dict]; deterministic
│  ├─ urls.py                # normalize_dc_url(), quote_href(), dc_id_from_url()
│  ├─ dc/
│  │  ├─ __init__.py
│  │  ├─ archive.py          # fetch_archive() + parse_archive_rows() → list[CreditEvent]
│  │  ├─ detail.py           # parse_procedural_history(html) → list[HistoryEntry], list[DocLink]
│  │  ├─ classify.py         # classify_link(text, url) → doc_type
│  │  ├─ documents.py        # download_documents(), PDF sniffing, dedupe, sha256
│  │  └─ pipeline.py         # run_dc(): orchestrates archive → details → docs → markdown → CSVs
│  ├─ pdfmd.py               # pdf_to_markdown(pdf_path, md_path) using pymupdf4llm
│  ├─ auctions/
│  │  ├─ __init__.py
│  │  ├─ api.py              # thin API client (years, by_year, results_by_ticker, details_by_id)
│  │  └─ pipeline.py         # run_auctions() → auctions.csv
│  └─ match/
│     ├─ __init__.py
│     ├─ normalize.py        # normalize_name()
│     ├─ matcher.py          # match_auctions(auctions, events, documents) → list[Match]
│     ├─ evaluate.py         # fuzzy-only accuracy vs exact-link ground truth
│     └─ pipeline.py         # run_match() → matches.csv, credit_events_with_auctions.csv
├─ tests/
│  ├─ fixtures/              # captured real responses (see §6)
│  ├─ test_archive.py  test_detail.py  test_classify.py  test_documents.py
│  ├─ test_auctions.py test_normalize.py test_matcher.py test_urls.py
└─ data/                     # git-ignored, created at runtime
   ├─ cache/                 # raw HTTP cache: dc/archive.json, dc/pages/<slug>.html, cf/*.json
   ├─ documents/<dc_slug>/<file>.pdf
   ├─ markdown/<dc_slug>/<file>.md
   └─ output/*.csv
```

**Dependencies:** `httpx`, `beautifulsoup4`, `lxml`, `tenacity`, `rapidfuzz`, `pymupdf4llm`.
**Dev:** `pytest`, `respx` (httpx mocking), `ruff`.
No pandas: stdlib `csv` is enough and keeps output byte-stable.

---

## 4. Data contracts (CSV schemas). Agents MUST adhere to these exactly.

General rules: UTF-8 (no BOM), `\n` line endings, header row, `csv.QUOTE_MINIMAL`, empty string for null,
booleans as `true`/`false`, dates ISO `YYYY-MM-DD`, datetimes ISO 8601 with offset as on the page.
**Rows sorted deterministically** (sort keys given per file). No run timestamps inside CSVs; those go in `data/output/run_log.json`.

### 4.1 `dc_credit_events.csv`: one row per DC credit-event question. Sort: `submitted_date, dc_id`.
| column | source |
|---|---|
| `dc_id` | URL path without slashes at the ends, e.g. `cds/dish-dbs-corporation` |
| `dc_url` | normalised More URL (https, trailing `/`) |
| `reference_entity` | col 3, stripped |
| `committee_code` | col 1 raw |
| `committee` | `ceMeta_3` "Committee:" text |
| `category` | col 2 |
| `date_updated` | col 0 epoch → UTC date (cross-check with the text date) |
| `submitted_date` | col 4 epoch → UTC date (empty if missing) |
| `status` | col 5 |
| `outcome` | col 6 |
| `question` | `h2.credit-title` text with the "Question:" prefix removed |
| `transaction_type` | `p.ceMeta_2 strong` |
| `issue_number` | `ceMeta_3` "Issue Number:" |
| `submitted_by` | `ceMeta_3` "Submitted by:" |
| `coverage_election` | `ceMeta_3` "Coverage Election:" (optional) |
| `further_information` | `div.entry-content` text, whitespace-collapsed, without the leading label |
| `n_history_entries` | count from the detail page |
| `n_target_documents` | count of links with a target doc_type |
| `detail_fetch_status` | `ok` / `http_<code>` / `error` |

### 4.2 `dc_procedural_history.csv`: one row per timeline `<li>`. Sort: `dc_id, entry_seq`.
| column | notes |
|---|---|
| `dc_id` | FK |
| `entry_seq` | 0 = **oldest**. Assign by reversing page order (the page is newest first), so the sort is stable even when timestamps tie |
| `heading` | `<h4>` text |
| `entry_datetime` | `<time datetime>` attribute |
| `entry_text` | plain text of the body, paragraphs joined with `\n`, whitespace-collapsed per paragraph |
| `n_links` | number of `<a href>` in the body |

### 4.3 `dc_documents.csv`: one row per link in Procedural History. Sort: `dc_id, entry_seq, link_seq`.
| column | notes |
|---|---|
| `dc_id`, `entry_seq` | FK to history |
| `link_seq` | 0-based order of the link within the entry |
| `heading`, `entry_datetime` | denormalised from the entry, for convenience |
| `link_text` | anchor text, whitespace-collapsed |
| `url` | href exactly as on the page |
| `url_normalized` | spaces percent-encoded, http→https for the DC domain, used for download/dedupe |
| `doc_type` | from `classify_link` (§5.B) |
| `is_target` | `doc_type in TARGET_DOC_TYPES` |
| `doc_issue_number` | regex `Issue Number\s+(\d{10})` on the link text, else empty |
| `doc_date` | date parsed from the link text (`MM/DD/YY`, `MM/DD/YYYY`, `Month D, YYYY`, `DDMMYYYY` in filenames), else empty |
| `download_status` | `ok` / `skipped_not_target` / `not_pdf` / `http_<code>` / `error:<ExcType>` / `not_attempted` |
| `final_url` | URL after redirects |
| `sha256`, `size_bytes` | of the PDF bytes |
| `pdf_path` | path relative to the project root, POSIX separators, e.g. `data/documents/cds_dish-dbs-corporation/dish-dbs-corporation-final-list.pdf` |
| `md_path` | likewise under `data/markdown/…/*.md` |
| `md_status` | `ok` / `error:<ExcType>` / `empty_text` (scanned PDF with no text layer) / blank if no PDF |

### 4.4 `auctions.csv`: one row per CDS auction. Sort: `auction_date, auction_id`.
| column | source |
|---|---|
| `auction_id` | `auctionID` |
| `auction_year` | `auctionYear` |
| `auction_date` | `auctionDate[:10]` |
| `legal_name` | `legalName`, stripped (**full entity name**) |
| `short_name` | `shortName`, stripped |
| `ticker`, `auction_type`, `tier`, `tenor`, `ccy`, `dc_region` | as named |
| `isda_link` | raw |
| `final_price` | `stateParams["Final Price"]`, string kept exactly as the API gives it |
| `initial_market_midpoint` | `stateParams["Initial Market Midpoint"]` |
| `auction_status` | `stateParams["Auction Status"]` |
| `results_url` | `https://www.creditfixings.com/#/auction-results/{ticker}` |
| `results_fetch_status` | `ok` / `missing_final_price` / `http_<code>` |

### 4.5 `matches.csv`: one row per auction. Sort: `auction_date, auction_id`.
All `auctions.csv` columns, then:
`dc_id, dc_url, dc_reference_entity, dc_issue_number, dc_submitted_date, dc_outcome, match_method, match_score, n_candidates, runner_up_dc_id, runner_up_score, needs_review`
- `match_method` ∈ `exact_link` | `normalized_link` | `document_link` | `fuzzy` | `unmatched`
- `match_score`: 100 for link methods, the fuzzy score otherwise
- `needs_review = true` when method is `fuzzy` AND (runner-up within 3 points with the same outcome rank, OR `n_candidates > 1`)

### 4.6 `credit_events_with_auctions.csv`: DC-centric left join. Sort: `submitted_date, dc_id, auction_date, auction_id`.
One row per (DC event × matched auction). DC events with no auction appear once, with empty auction columns.
Columns: all of `dc_credit_events.csv` + `auction_id, auction_date, legal_name, ticker, tier, ccy, final_price, results_url, match_method, match_score, needs_review`
+ convenience columns `latest_decision_date` (max `doc_date` / `entry_datetime` of `dc_decision` docs) and `final_list_pdf_path` (most recent `final_list` doc).

---

## 5. Component specs (one per parallel work package)

### Phase 0: Scaffolding (main agent, sequential, ~30 min). **Blocks everything else.**
1. `git init`, `uv init --package --python 3.11 --name dcdata`. Pin `.python-version` to 3.11 and `requires-python = ">=3.11,<3.12"`.
2. `uv add httpx beautifulsoup4 lxml tenacity rapidfuzz pymupdf4llm` and `uv add --dev pytest respx ruff`.
3. Write `config.py`, `http.py`, `csvio.py`, `urls.py`, the `cli.py` skeleton (subcommands wired to `run_*` stubs that raise `NotImplementedError`), empty module files and `.gitignore`.
4. Capture test fixtures into `tests/fixtures/` (§6).
5. Ruff config (line length 110), pytest config (`testpaths = ["tests"]`).
6. Initial commit.

**`config.py`** (constants, all overridable via CLI):
```python
DC_BASE = "https://www.cdsdeterminationscommittees.org"
DC_ARCHIVE_DATA_URL = f"{DC_BASE}/credit-default-swaps-archive/data/"
CF_API = "https://api.creditfixings.com/api"
CF_RESULTS_UI = "https://www.creditfixings.com/#/auction-results/{ticker}"
USER_AGENT = "dcdata-research-scraper/0.1"
REQUEST_DELAY_S = 1.0          # min gap between requests per host
MAX_RETRIES = 4                # on 429/5xx/timeouts, exponential backoff 2..30s
TIMEOUT_S = 60
TARGET_DOC_TYPES = {"dc_decision","final_list","initial_list","preliminary_list","auction_terms"}
FUZZY_SCORER = "token_sort_ratio"; FUZZY_THRESHOLD = 80
DATE_WINDOW_DAYS = (-7, 365)   # auction_date - dc_submitted_date must fall in this range
DATA_DIR = Path("data")        # cache/, documents/, markdown/, output/
```

**`http.py`: `Fetcher`** (sync httpx; the request volume is small, so concurrency isn't needed and sync keeps it deterministic):
- `get(url, *, cache_key=None, refresh=False) -> Response-like(status, final_url, content, headers)` and `post_form(url, data, cache_key, refresh)`.
- Per-host rate limit (`REQUEST_DELAY_S`), `follow_redirects=True`, tenacity retry on `httpx.TransportError` and status in {429, 500, 502, 503, 504}.
- Cache: when `cache_key` is given, store the body at `data/cache/<cache_key>` plus a `.meta.json` (status, final_url, content-type). Serve from the cache unless `refresh`.
  Binary documents are *not* cached here; `documents.py` manages its own files.
- Never raises on 4xx. It returns the status so callers record it.

**`urls.py`:**
- `quote_href(href)`: percent-encode spaces and unsafe chars in the path/query, leaving `%xx` intact (`urllib.parse.quote(…, safe=":/?#[]@!$&'()*+,;=%")`).
- `normalize_dc_url(url)`: lowercase scheme and host; `http→https`; keep `www.`; if the path contains `/cds/` take from the **last** `/cds/` (fixes `/lcds/cds/…`); ensure a trailing `/`; drop query/fragment.
- `dc_id_from_url(url)`: normalised path with slashes stripped at the ends (`cds/foo-2`).
- `slug_dir(dc_id)`: `dc_id.replace("/", "_")` for filesystem folders.

---

### Work package A: DC archive and detail parsing (`dc/archive.py`, `dc/detail.py`, `dc/pipeline.py` part 1)
**Inputs:** fixtures `dc_archive_ce.json`, `dc_detail_*.html`. **Outputs:** functions and tests. No network in tests.
1. `fetch_archive(fetcher, category="credit-event", refresh=False) -> list[list]`: build the exact form (§1.1), page with `iDisplayLength=500` until all `iTotalDisplayRecords` rows are collected, cache key `dc/archive_<category>_<start>.json`. Assert the `category` column on every row; log a warning and drop any mismatches.
2. `parse_archive_row(row) -> dict` producing the §4.1 columns (excluding the detail-derived ones). BeautifulSoup + lxml on `unquote_plus(row[7])`. Parse `ceMeta_3` items by their `<em>` label text (`"Issue Number:"`, …), not by position (Coverage Election is optional).
3. Epoch → date: `datetime.fromtimestamp(int(x), tz=timezone.utc).date().isoformat()`. Handle int/str/empty.
4. `parse_procedural_history(html) -> list[dict]` (entries, §4.2) and links (`dict` per §4.3, without download columns):
   - Locate `ul.ProceduralHistory`. If missing, return `[]` and let the caller mark `detail_fetch_status=ok_no_history`.
   - Iterate **direct child** `li` only (nested lists inside the body exist on some pages).
   - Body text: inner `<p>` children, `get_text(" ", strip=True)` each, joined with `\n`. Treat `&nbsp;` as a space.
   - Links: every `a[href]` in the body. Skip `mailto:` and fragment-only links.
   - `entry_seq`: reverse page order.
5. `pipeline.run_dc` step 1–2: for each event, `fetcher.get(dc_url, cache_key=f"dc/pages/{slug}.html")`, parse, collect rows.
6. Tests: 281-row parse from fixture; DISH detail → 15+ entries, first (oldest) heading, `Final List Published` entries carry 3 links;
   GGP legacy page → link with spaces and text "View Attachment"; Hellenic page → isda.org links; a page without history → `[]`.

### Work package B: Link classification, downloading, PDF → Markdown (`dc/classify.py`, `dc/documents.py`, `pdfmd.py`)
**Inputs:** link dicts per §4.3. **Outputs:** download/markdown columns filled in, files on disk.
1. `classify_link(text, url) -> str`. Lowercase the text; if the text is generic (`view attachment`, `click here`, `here`, `pdf`, empty), classify on the **URL filename** instead
   (unquote, replace `-_` with spaces). The ordered rules, first match wins:
   | order | pattern (regex, case-insensitive) | doc_type |
   |---|---|---|
   | 1 | `\bredline\b` | `redline` |
   | 2 | `\bdecision\b\|\bresolutions?\b\|\bdetermination\b(?!s committee\b)` | `dc_decision` |
   | 3 | `final list` | `final_list` |
   | 4 | `initial list` | `initial_list` |
   | 5 | `preliminary list` | `preliminary_list` |
   | 6 | `auction settlement terms\|auction terms` | `auction_terms` |
   | 7 | `participating bidders` | `bidders` |
   | 8 | `statement` | `statement` |
   | 9 | `auction (checklist\|information)\|required information` | `auction_info` |
   | 10 | `\.pdf` in URL | `other_pdf` |
   | 11 | otherwise | `other_link` |
   Note: "EMEA Determinations Committee Decision …" must classify as `dc_decision`; the lookahead in rule 2 only stops the bare
   "Determinations Committee" phrase from matching by itself, while `\bdecision\b` still catches it. Unit-test ≥ 25 real link texts taken from fixtures (table-driven).
2. `download_documents(fetcher, links, target_types, refresh=False)`:
   - Process only `is_target` links; set the others to `skipped_not_target`.
   - **Deduplicate by `url_normalized`.** The first occurrence downloads; later ones reuse the result (same `pdf_path`).
   - Destination: `data/documents/<slug_dir(dc_id)>/<safe_basename>.pdf`. `safe_basename` = last non-empty URL path segment, unquoted,
     with `.pdf` stripped, `[^A-Za-z0-9._-]` → `_`, truncated to 120 chars. On a filename collision with a different URL, append `__<sha1(url)[:8]>`.
   - Skip the download if the file exists and `refresh` is false (recompute sha256 from disk). **Write atomically** (`.part` file, then rename).
   - Validate: `content[:5] == b"%PDF-"`, otherwise `not_pdf` and nothing is saved. A 404 or other code → `http_<code>`.
3. `pdfmd.pdf_to_markdown(pdf_path, md_path) -> status`: `pymupdf4llm.to_markdown(str(pdf_path))`; write UTF-8; status `empty_text` if the stripped output is shorter than 20 chars;
   catch exceptions → `error:<Type>`. Skip if `md_path` exists and is newer than the PDF. Pin the `pymupdf4llm` version in the lockfile for reproducibility.
4. Tests: classification table; `respx`-mocked download returning PDF bytes with a `text/html` content-type → `ok`; an HTML body → `not_pdf`; 404 → `http_404`;
   duplicate URL downloaded once; tiny generated PDF (create with `pymupdf` in the test) → markdown contains the expected text.

### Work package C: Auctions (`auctions/api.py`, `auctions/pipeline.py`)
1. `CreditFixingsAPI(fetcher)` with `years()`, `by_year(y)`, `results_by_ticker(t)`, `details_by_id(id)`. Cache keys `cf/years.json`, `cf/year_<y>.json`, `cf/results_<ticker>.json`, `cf/details_<id>.json`.
   Send `Origin: https://www.creditfixings.com` and `Accept: application/json`.
2. `run_auctions(years=None, refresh=False)`:
   - `years()` (optionally intersected with `--years`); `by_year(y)` for each; **drop `auctionType == "LCDS"`** (log the count, expected 19).
   - Deduplicate auctions by `auctionID`.
   - For each distinct ticker, call `results_by_ticker` once; read `auctionDetailsMap[str(id)].stateParams`. If the id is missing or `stateParams` is null → `details_by_id(id)`;
     still missing → `results_fetch_status=missing_final_price`.
   - Write `auctions.csv` (§4.4).
3. Tests (fixtures `cf_years.json`, `cf_year_2026.json`, `cf_year_2012.json`, `cf_results_NFEFIN.json`, `cf_results_NRAMC.json`): NFEFIN final price `26.625`;
   NRAMC two buckets → 104.25 and 99.125 mapped to auction ids 9032 and 9036; LCDS filtered out (FCGIA from the 2012 fixture absent); fallback path exercised via respx.

### Work package D: Matching (`match/normalize.py`, `match/matcher.py`, `match/evaluate.py`, `match/pipeline.py`)
**Inputs:** the three CSVs (`auctions.csv`, `dc_credit_events.csv`, `dc_documents.csv`). Uses only `csvio` and `urls`, so it can be built in parallel against fixtures.
1. `normalize_name(s)`: NFKD → ASCII, lowercase, drop parenthesised text, remove the legal-suffix list
   (`the, plc, public limited company, limited, ltd, llc, inc, incorporated, corp, corporation, co, company, sa, s a, sas, sab de cv, ag, nv, bv, spa, asa, ab, oyj, gmbh, lp, holdings?, group, sociedad anonima, formerly known as …`),
   non-alphanumerics → space, collapse spaces. Keep `&` → ` and `.
2. `match_auctions(auctions, events, documents, cfg) -> list[dict]`, evaluated per auction in order:
   1. **exact_link**: `normalize_dc_url(isda_link) == dc_url` and the link already looks canonical (normalisation changed nothing except the trailing slash or scheme).
   2. **normalized_link**: as above but normalisation repaired the path (e.g. `/lcds/cds/` → `/cds/`).
   3. **document_link**: `quote_href(isda_link)` (normalised with http→https, trailing slash insensitive) equals some `dc_documents.url_normalized` → that row's `dc_id`.
      If several dc_ids reference the same document, choose with the fuzzy rule below restricted to those candidates.
   4. **fuzzy**: candidates = events where `max(scorer(n(legal_name), n(entity)), scorer(n(short_name), n(entity))) >= threshold` and
      `DATE_WINDOW_DAYS[0] <= (auction_date - submitted_date).days <= DATE_WINDOW_DAYS[1]`.
      Rank by the tuple `(outcome == "Question Decided", round(score), -abs(gap_days), dc_id)` descending. `dc_id` is the final tie-break so the result is deterministic.
      Record `n_candidates`, runner-up id and score, and `needs_review`.
   5. **unmatched**.
3. `evaluate.py` (`dcdata match --evaluate`): rerun **only** step 4 on auctions whose method is `exact_link`, and print a correct / wrong / none table
   for scorers {`ratio`, `token_sort_ratio`, `token_set_ratio`, `partial_ratio`, `WRatio`} × thresholds {95, 90, 85, 80, 75, 70}. This documents why the defaults were chosen and catches regressions.
4. `pipeline.run_match()` writes `matches.csv` and `credit_events_with_auctions.csv` (§4.5, §4.6).
5. Tests: synthetic tables covering each method; the CODERE-style URL → `normalized_link`; a PDF-style `isda_link` → `document_link`;
   two same-name DC events → the date window picks the right one; output sort order is stable.

### Phase 2: Integration (main agent, after A–D merge)
1. Fill in `dc/pipeline.run_dc`: archive → details → classify → download → markdown → write the 3 DC CSVs. Show progress with simple logging (`logging`, INFO: one line per entity).
2. `cli.py` flags:
   - shared: `--data-dir`, `--refresh` (ignore the cache), `--delay`, `-v`
   - `dc`: `--limit N` (first N events, for smoke tests), `--no-download`, `--no-markdown`, `--doc-types a,b,c`
   - `auctions`: `--years 2020,2021`
   - `match`: `--threshold`, `--scorer`, `--evaluate`
   - `all`: runs dc → auctions → match
3. `run_log.json`: start/end time, counts per status, versions. This is the only non-deterministic artefact.
4. Smoke test: `uv run dcdata dc --limit 5`, then a full run.
5. README: install (`uv sync`), usage, outputs, determinism notes, AGPL note for pymupdf4llm.
6. Commit.

---

## 6. Test fixtures (captured in Phase 0 from live responses)

`tests/fixtures/`:
- `dc_archive_ce.json`: full 281-row credit-event response
- `dc_detail_dish-dbs-corporation.html`: modern, many entries, Decisions under "Ongoing"
- `dc_detail_general-growth-properties-inc.html`: 2009, spaces in href, "View Attachment"
- `dc_detail_the-hellenic-republic-2.html`: isda.org legacy links
- `dc_detail_credit-suisse-group-ag.html`: short modern history
- `cf_years.json`, `cf_year_2026.json`, `cf_year_2012.json` (contains LCDS + buckets)
- `cf_results_NFEFIN.json`, `cf_results_NRAMC.json`

---

## 7. Parallel execution plan

```
Phase 0  (main agent)          scaffold + shared modules + fixtures + commit
            │
            ├── Agent A  DC archive/detail parsing        (dc/archive.py, dc/detail.py)
            ├── Agent B  classify + download + PDF→MD      (dc/classify.py, dc/documents.py, pdfmd.py)
            ├── Agent C  auctions API scraper              (auctions/*)
            └── Agent D  matching + evaluation             (match/*)
            │
Phase 2  (main agent)          wire pipelines + CLI, full live run, verify acceptance, README, commit
```
- Each agent runs in an **isolated git worktree**, touches **only its own files** plus its own tests, and must not edit the shared modules
  (if a shared change is needed, it reports it instead of making it).
- Each agent's definition of done: `uv run pytest tests/test_<its area>*.py` passes and `uv run ruff check` is clean. No live network in unit tests.
- Agents A and B may each make **≤ 10 live requests** for spot-checks. Agent C may hit the API live (≈ 150 small JSON calls is fine).
- The main agent merges the worktrees in the order A, B, C, D (no file overlap, so no conflicts are expected).

---

## 8. Acceptance criteria (verified on the full live run)

| check | expected |
|---|---|
| `dc_credit_events.csv` rows | 281 (as of 2026-11-05; grows over time) |
| events with `detail_fetch_status=ok` | 281 |
| `auctions.csv` rows | 136 (no LCDS); every row has a `final_price` |
| `matches.csv` methods | `exact_link` 133, `normalized_link` 1 (CODERE), `document_link` 2 (DISH, Liberty), `fuzzy` 0, `unmatched` 0 |
| target PDFs | every `is_target` row is `ok` or a recorded `http_404` / `not_pdf`; all `ok` files start with `%PDF-` |
| markdown | one `.md` per `ok` PDF; `md_status` recorded |
| determinism | a second run (from cache) produces byte-identical CSVs (`git diff --no-index` / sha256 compare) |
| `--evaluate` | `token_sort_ratio`@80 gives ≈120/8/5 on the exact-link set, matching the research |

## 9. Risks and mitigations
- **DC site changes its DataTables params or HTML.** Fixture tests pin the current structure; the pipeline logs counts and warns when 0 entries are parsed.
- **The creditfixings API changes or adds auth.** Isolated in `auctions/api.py`. As a fallback, a Playwright path could click "I Agree" and read the rendered page, but that's out of scope unless needed.
- **Scanned legacy PDFs with no text layer.** `md_status=empty_text`. OCR is out of scope (it would add a non-trivial dependency).
- **Rate limiting.** 1 s per-host delay and retry with backoff. The full run is ≈ 281 pages + ≈ 1–2k PDFs + ≈ 150 JSON calls, so roughly 30–60 min on the first run and minutes from the cache afterwards.
- **Fuzzy false positives** on future data: `needs_review` flag plus runner-up columns. Link-based methods always take precedence.
