"""CSV column contracts (PLAN.md section 4). All writers use these lists verbatim."""

DC_EVENTS_COLUMNS = [
    "dc_id",
    "dc_url",
    "reference_entity",
    "committee_code",
    "committee",
    "category",
    "date_updated",
    "submitted_date",
    "status",
    "outcome",
    "question",
    "transaction_type",
    "issue_number",
    "submitted_by",
    "coverage_election",
    "further_information",
    "n_history_entries",
    "n_target_documents",
    "detail_fetch_status",
]

DC_HISTORY_COLUMNS = [
    "dc_id",
    "entry_seq",
    "heading",
    "entry_datetime",
    "entry_text",
    "n_links",
]

DC_LINK_COLUMNS = [
    "dc_id",
    "entry_seq",
    "link_seq",
    "heading",
    "entry_datetime",
    "link_text",
    "url",
    "url_normalized",
    "doc_type",
    "is_target",
    "doc_issue_number",
    "doc_date",
]

DC_DOWNLOAD_COLUMNS = [
    "download_status",
    "final_url",
    "sha256",
    "size_bytes",
    "pdf_path",
    "md_path",
    "md_status",
]

DC_DOCUMENTS_COLUMNS = DC_LINK_COLUMNS + DC_DOWNLOAD_COLUMNS

AUCTIONS_COLUMNS = [
    "auction_id",
    "auction_year",
    "auction_date",
    "legal_name",
    "short_name",
    "ticker",
    "auction_type",
    "tier",
    "tenor",
    "ccy",
    "dc_region",
    "isda_link",
    "final_price",
    "initial_market_midpoint",
    "auction_status",
    "results_url",
    "results_fetch_status",
]

MATCH_EXTRA_COLUMNS = [
    "dc_id",
    "dc_url",
    "dc_reference_entity",
    "dc_issue_number",
    "dc_submitted_date",
    "dc_outcome",
    "match_method",
    "match_score",
    "n_candidates",
    "runner_up_dc_id",
    "runner_up_score",
    "needs_review",
]

MATCHES_COLUMNS = AUCTIONS_COLUMNS + MATCH_EXTRA_COLUMNS

JOINED_COLUMNS = DC_EVENTS_COLUMNS + [
    "auction_id",
    "auction_date",
    "legal_name",
    "ticker",
    "tier",
    "ccy",
    "final_price",
    "results_url",
    "match_method",
    "match_score",
    "needs_review",
    "latest_decision_date",
    "final_list_pdf_path",
]

MATCH_METHODS = ("exact_link", "normalized_link", "document_link", "fuzzy", "unmatched")
