# dcdata

A deterministic scraper for CDS credit-event data. It collects three sources and joins them into flat CSV files:

1. **CDS Determinations Committees (DC) archive**: every *credit-event* question from
   <https://www.cdsdeterminationscommittees.org/credit-default-swaps-archive/>, with its full metadata.
2. **Procedural History** from each question's detail page: the dated timeline of "DC Decision",
   "Final List Published", "Auction Settlement Terms", and so on. The linked DC decisions and
   deliverable-obligation lists are downloaded as PDFs and converted to Markdown.
3. **CDS auction results** from <https://www.creditfixings.com>: reference entity, auction date,
   tier, currency and **Final Price**.

Each auction is then matched to the DC credit event that triggered it. Not every credit event has
an auction; for example, a question can be decided "No" or settled without one.

No LLMs and no browser automation are used. Everything is plain HTTP, HTML/JSON parsing and
RapidFuzz. Given the same cache, every run produces byte-identical CSV files.

---

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11. uv installs Python if it is missing.

```bash
uv sync                    # create .venv and install dependencies
uv run dcdata all          # scrape DC + auctions, download PDFs, convert to Markdown, match
```

A cold run makes about 1,400 polite requests (1 s minimum gap per host) and takes roughly
**70 minutes**. Responses are cached under `data/cache/` and PDFs under `data/documents/`, so a
re-run makes no network requests at all and finishes in about **10 seconds**. Use `--refresh`
to fetch everything again.

A quick smoke test, using the first 5 credit events and no PDFs:

```bash
uv run dcdata dc --limit 5 --no-download --data-dir data_smoke
```

## Commands

```
dcdata dc        scrape DC credit events, procedural history, PDFs (+ Markdown)
dcdata auctions  scrape creditfixings.com CDS auction results
dcdata match     match auctions to DC credit events (reads the CSVs of the two steps above)
dcdata all       dc -> auctions -> match
```

| Flag | Commands | Meaning |
|---|---|---|
| `--data-dir PATH` | all | Root for `cache/`, `documents/`, `markdown/`, `output/` (default `./data`) |
| `--refresh` | all | Ignore the HTTP cache and downloaded PDFs; fetch everything again |
| `--delay SECONDS` | all | Minimum gap between requests to the same host (default `1.0`) |
| `-v, --verbose` | all | Debug logging, including every request |
| `--limit N` | `dc`, `all` | Only the first N credit events, oldest first |
| `--no-download` | `dc`, `all` | Skip PDF downloads (and therefore Markdown) |
| `--no-markdown` | `dc`, `all` | Download PDFs but do not convert them |
| `--doc-types a,b` | `dc`, `all` | Document types to download (default `dc_decision,final_list`) |
| `--years 2023,2024` | `auctions`, `all` | Only these auction years (default: all years the API lists) |
| `--threshold N` | `match`, `all` | Fuzzy score cutoff, 0–100 (default `80`) |
| `--scorer NAME` | `match`, `all` | RapidFuzz scorer: `token_sort_ratio` (default), `ratio`, `partial_ratio`, `token_set_ratio`, `WRatio` |
| `--evaluate` | `match`, `all` | Also print a fuzzy-only accuracy grid scored against the link-based matches |

The available `--doc-types` are `dc_decision`, `final_list`, `initial_list`,
`preliminary_list`, `auction_terms`, `bidders`, `auction_info`, `statement`, `redline`,
`other_pdf` and `other_link`.

## Outputs

Everything goes under `data/` (git-ignored):

```
data/
  output/
    dc_credit_events.csv             one row per DC credit-event question
    dc_procedural_history.csv        one row per Procedural History entry
    dc_documents.csv                 one row per link in the Procedural History (+ download/markdown status)
    auctions.csv                     one row per CDS auction (LCDS excluded)
    matches.csv                      auctions.csv + the matched DC event and how it was matched
    credit_events_with_auctions.csv  DC-centric join: every event, one row per matched auction
    run_log.json                     timestamps, library versions, step summaries, request count
  documents/<dc_id>/*.pdf            downloaded PDFs (+ .meta.json with the final URL)
  markdown/<dc_id>/*.md              pymupdf4llm conversion of each PDF
  cache/                             raw HTTP responses (DC pages, archive JSON, creditfixings API)
```

`<dc_id>` is the detail-page slug, for example `cds/dish-dbs-corporation`, with `/` replaced by
`_` in directory names. Booleans are written as `true`/`false`, missing values as empty strings
and dates as ISO `YYYY-MM-DD`. Files are UTF-8 with `\n` line endings.

### `dc_credit_events.csv`
`dc_id` (key), `dc_url`, `reference_entity`, `committee_code`, `committee`, `category`,
`date_updated`, `submitted_date`, `status`, `outcome` (for example *Question Decided*,
*Question Dismissed*), `question`, `transaction_type`, `issue_number`, `submitted_by`,
`coverage_election`, `further_information`, `n_history_entries`, `n_target_documents`,
`detail_fetch_status` (`ok`, `ok_no_history`, `no_detail_url`, `http_<code>`, `error:<Type>`).

### `dc_procedural_history.csv`
`dc_id`, `entry_seq` (0 = **oldest** entry; the site lists newest first), `heading` (for example
*DC Decision*, *Final List Published*, *Auction Settlement Terms Published*), `entry_datetime`
(ISO, with timezone offset, as published), `entry_text`, `n_links`.

### `dc_documents.csv`
One row per hyperlink inside a history entry: `dc_id`, `entry_seq`, `link_seq`, `heading`,
`entry_datetime`, `link_text`, `url` (raw href), `url_normalized` (absolute, quoted),
`doc_type`, `is_target`, `doc_issue_number`, `doc_date`, then download fields:
`download_status` (`ok`, `http_404`, `not_pdf`, `skipped_not_target`, `error:<Type>`),
`final_url` (after redirects), `sha256`, `size_bytes`, `pdf_path`, `md_path`, `md_status`.

### `auctions.csv`
`auction_id` (key), `auction_year`, `auction_date`, `legal_name`, `short_name`, `ticker`,
`auction_type`, `tier` (for example Senior / Subordinated), `tenor`, `ccy`, `dc_region`,
`isda_link` (the DC page that creditfixings links to), `final_price`,
`initial_market_midpoint`, `auction_status`, `results_url`, `results_fetch_status`.

### `matches.csv`
All `auctions.csv` columns, followed by `dc_id`, `dc_url`, `dc_reference_entity`,
`dc_issue_number`, `dc_submitted_date`, `dc_outcome`, `match_method`, `match_score`,
`n_candidates`, `runner_up_dc_id`, `runner_up_score`, `needs_review`.

### `credit_events_with_auctions.csv`
All `dc_credit_events.csv` columns, followed by `auction_id`, `auction_date`, `legal_name`,
`ticker`, `tier`, `ccy`, `final_price`, `results_url`, `match_method`, `match_score`,
`needs_review`, `latest_decision_date` and `final_list_pdf_path`. An event with no auction
appears once, with the auction columns empty. An event with several auctions, for example
senior and subordinated tiers, appears once per auction.

## How it works

### DC archive and detail pages
The archive table is filled by a DataTables 1.9 server-side endpoint
(`POST /credit-default-swaps-archive/data/`), so the scraper calls it directly and filters
on `category = credit-event`. Each row's "More" link leads to a static detail page. Its
`ul.ProceduralHistory` list is parsed into timeline entries plus the links inside them.
Relative links are resolved against the page URL.

### Document classification and download
Each link is classified with deterministic regex rules applied to the link text, or to the file
name when the text is generic (such as "Click here" or "View attachment"). Only `dc_decision` and `final_list`
are downloaded by default. Some details matter here:

- The DC site serves PDFs with `Content-Type: text/html`, so a file counts as a PDF only when its
  body starts with `%PDF-`. Anything else, such as `.xls` or `.docx` deliverable lists, is recorded
  as `not_pdf` and not saved.
- Each PDF has a `.meta.json` sidecar that records the outcome (final URL, status, SHA-256,
  size). Re-runs reuse the outcome without re-hashing or re-requesting anything. `http_404`
  and `http_410` are remembered too. Everything else, including `not_pdf` (which might be a
  temporary HTML maintenance page), is retried on the next run. 4xx responses are recorded,
  never raised.
- Each file is converted with `pymupdf4llm.to_markdown`. Existing Markdown is reused unless
  `--refresh` is given.

### Auctions
creditfixings.com is an Angular app backed by a public JSON API (`api.creditfixings.com/api`).
The scraper reads `/auctions/years`, then `/auctions/year/{y}`, then `/auction-results/{ticker}`
for each auction's Final Price. LCDS (loan-only CDS) auctions are dropped. Some tickers carry a
leading space in the API (for example `" MONTE"`), and these are kept verbatim because they are
distinct keys.

### Matching
Each auction is assigned to at most one DC event. The first stage that succeeds wins:

| Method | Rule |
|---|---|
| `exact_link` | The auction's `isda_link` is the DC detail page, after scheme, case and trailing-slash normalisation |
| `normalized_link` | Same, after repairing malformed paths such as `/lcds/cds/<slug>` |
| `document_link` | `isda_link` points to a PDF that appears in some event's Procedural History |
| `fuzzy` | Entity-name similarity ≥ threshold, and the auction falls between 7 days before and 365 days after the DC question was submitted. Candidates are ranked by (*Question Decided*, rounded score, −date gap, `dc_id`), so the result is deterministic |
| `unmatched` | Nothing qualified |

Names are normalised before fuzzy scoring: lower-cased and accent-stripped, with punctuation and
legal suffixes removed (Inc, S.A., plc, AG, N.V., GmbH, …). A `fuzzy` match is flagged
`needs_review = true` whenever more than one candidate qualified. A `document_link` match is
flagged when the same document appears under several events. The runner-up's id and score
are written next to it.

**Current result:** all 136 auctions match through a link-based method (133 `exact_link`,
1 `normalized_link`, 2 `document_link`), so the fuzzy stage is currently a safety net for
future data. `--evaluate` measures how well it would do alone. Every scorer reaches about 90 %
correct at any threshold between 70 and 95, so the threshold matters little. The errors come
from repeat defaulters such as *Hellenic Republic* or *Caesars* that have several plausible
events in the date window:

```
scorer            threshold  correct  wrong  none
token_sort_ratio  80         120      8      5      <- default
ratio             80         121      8      4
WRatio            90         122      8      3
```

## Determinism

- Stable sort keys for every CSV (for example `(submitted_date, dc_id)` and
  `(dc_id, entry_seq, link_seq)`), the stdlib `csv` writer, fixed column lists (`schemas.py`),
  LF line endings and atomic writes.
- Fuzzy ties are broken by `dc_id`; no set or dict iteration order leaks into the output.
- `run_log.json` is the only output that changes between identical runs, because it holds
  timestamps and the request count.
- The upstream sites can change, of course. Delete `data/cache` or pass `--refresh` to pick up
  new events and auctions.

## Known limitations

- **Dead legacy links.** About 280 document links from 2009–2012 point to `/docs/...` paths that
  now return 404. They are recorded as `http_404` in `dc_documents.csv`. Links that redirect to
  isda.org work.
- **Non-PDF lists.** A few final lists are `.xls` or `.docx`. They are recorded as `not_pdf` and
  not downloaded.
- **Scanned PDFs.** pymupdf4llm extracts the text layer only and does no OCR, so an image-only
  PDF produces sparse Markdown.
- **Link-text heuristics.** Document types come from regex rules. Unusual wording falls into
  `other_pdf` and is not downloaded by default. Pass `--doc-types` to widen the selection.
- **Licensing.** pymupdf4llm and PyMuPDF are AGPL-3.0 licensed. Take this into account before
  redistributing the tool.

## Development

```bash
uv run pytest              # offline test suite using fixtures in tests/fixtures/
uv run ruff check .        # lint
uv run ruff format .       # format
```

Layout:

```
src/dcdata/
  cli.py            argparse entry point, run_log.json
  config.py         URLs, defaults, Settings
  http.py           Fetcher: per-host throttle, tenacity retries, disk cache
  csvio.py          deterministic CSV read/write
  urls.py           URL quoting / normalisation shared by scraper and matcher
  schemas.py        CSV column contracts
  pdfmd.py          PDF -> Markdown
  dc/               archive.py, detail.py, classify.py, documents.py, pipeline.py
  auctions/         api.py, pipeline.py
  match/            normalize.py, matcher.py, evaluate.py, pipeline.py
```

The original design notes, including the site research and the work-package split, are in
[`PLAN.md`](PLAN.md).
