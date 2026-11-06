import pytest

from dcdata.config import TARGET_DOC_TYPES
from dcdata.dc.classify import annotate_link, classify_link, extract_doc_date, extract_issue_number

DC = "https://www.cdsdeterminationscommittees.org/documents"

# Real (link_text, href, expected doc_type) taken from <ul class="ProceduralHistory"> in
# tests/fixtures/dc_detail_*.html.
REAL_LINKS = [
    # credit-suisse-group-ag
    (
        "DC Decision",
        f"{DC}/2023/05/emea-dc-credit-suisse-group-ag-dc-decision-17-may-2023.pdf/",
        "dc_decision",
    ),
    # dish-dbs-corporation
    (
        "Americas DC Meeting Statement - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26",
        f"{DC}/2026/08/dish-dbs-corporation-meeting-statement-re-removal-from-final-list.pdf/",
        "statement",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26",
        f"{DC}/2026/08/dish-dbs-corporation-decision-08-10-26.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC - DISH DBS Corporation - Final List of Deliverable Obligations",
        f"{DC}/2026/08/dish-dbs-corporation-final-list-updated.pdf/",
        "final_list",
    ),
    (
        "Redline of updated Final List of Deliverable Obligations against previously published Final List",
        f"{DC}/2026/08/dish-dbs-corporation-redline-of-final-list-2.pdf/",
        "redline",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/04/26",
        f"{DC}/2026/08/dish-dbs-corporation-decision-08-04-2026.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC - DISH DBS Corporation - Final List of Deliverable Obligations",
        f"{DC}/2026/07/dish-dbs-corporation-updated-final-list.pdf/",
        "final_list",
    ),
    (
        "Redline of updated Final List of Deliverable Obligations against originally published Final List",
        f"{DC}/2026/07/dish-dbs-corporation-redline-of-final-list.pdf/",
        "redline",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 07/30/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-07-30-26.pdf/",
        "dc_decision",
    ),
    (
        "List of Participating Bidders - Americas DC - Issue Number 2026063001 (DISH DBS Corporation)",
        f"{DC}/2026/07/dish-dbs-corporation-list-of-participating-bidders.pdf/",
        "bidders",
    ),
    (
        "Americas DC - DISH DBS Corporation - Final List of Deliverable Obligations",
        f"{DC}/2026/07/dish-dbs-corporation-final-list.pdf/",
        "final_list",
    ),
    (
        "2026 DISH DBS Corporation Credit Derivatives Auction Settlement Terms - July 22, 2026",
        f"{DC}/2026/07/dish-dbs-corporation-auction-settlement-terms.pdf/",
        "auction_terms",
    ),
    (
        "Redline of Auction Settlement Terms against Liberty Interactive LLC",
        f"{DC}/2026/07/dish-dbs-corporation-redline-of-asts-v-liberty-interactive-llc.pdf/",
        "redline",
    ),
    (
        "Americas DC Decision - Issue Number 2026041701 (DISH DBS Corporation) - 07/22/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-07-22-26.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC - DISH DBS Corporation - Initial List of Deliverable Obligations",
        f"{DC}/2026/07/dish-dbs-corporation-initial-list.pdf/",
        "initial_list",
    ),
    (
        "Submission of Potential Deliverable Obligations and Challenges",
        f"{DC}/2026/04/submission-of-potential-deliverable-obligations.pdf/",
        "other_pdf",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 07/16/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-07-16-26.pdf/",
        "dc_decision",
    ),
    (
        # Contains "Auction Settlement Terms" but is the checklist, not the terms.
        "Required Information for Auction Settlement Terms - Issue Number 2026063001 (DISH DBS Corporation) - 07/14/26",
        f"{DC}/2026/07/dish-dbs-corporation-auction-checklist.pdf/",
        "auction_info",
    ),
    (
        "Americas DC Decision - Auction Timetable - Issue Number 2026063001 (DISH DBS Corporation) - 07/14/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-7-14-26.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC Meeting Statement - Issue Number 2026063001 (DISH DBS Corporation) - 07/10/26",
        f"{DC}/2026/07/dish-dbs-corporation-meeting-statement-07-10-26.pdf/",
        "statement",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 07/10/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-07-10-26.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC - DISH DBS Corporation - Preliminary List of Deliverable Obligations",
        f"{DC}/2026/07/dish-dbs-corporation-preliminary-list.pdf/",
        "preliminary_list",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 07/09/26",
        f"{DC}/2026/07/dish-dbs-corporation-decision-07-09-26.pdf/",
        "dc_decision",
    ),
    (
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 07/02/26",
        f"{DC}/2026/07/dish-dbs-decision-07-02-26.pdf/",
        "dc_decision",
    ),
    # general-growth-properties-inc (2009, generic text, raw spaces in href)
    (
        "View Attachment",
        "http://www.cdsdeterminationscommittees.org/docs/20090416 200904163 DC resolutions.pdf",
        "dc_decision",
    ),
    # the-hellenic-republic-2 (legacy isda.org)
    (
        "EMEA Determinations Committee Decision 01032012",
        "http://www.isda.org/dc/docs/EMEA_Determinations_Committee_Decision_01032012Q2.pdf",
        "dc_decision",
    ),
    ("EMEA DC Statement 01032012", "http://www.isda.org/dc/docs/EMEA_DC_Statement_01032012.pdf", "statement"),
]

# Further cases: generic texts with informative filenames, traps, and non-PDF links.
EXTRA_LINKS = [
    ("Click here", f"{DC}/2026/07/acme-corp-final-list.pdf/", "final_list"),
    ("here", "http://www.isda.org/dc/docs/Acme_Initial_List_of_Deliverable_Obligations.pdf", "initial_list"),
    ("PDF", f"{DC}/2026/07/acme%20preliminary%20list.pdf/", "preliminary_list"),
    ("", f"{DC}/2026/07/acme-list-of-participating-bidders.pdf/", "bidders"),
    ("View Attachment", "http://www.isda.org/dc/docs/Acme_Auction_Terms.pdf", "auction_terms"),
    ("Download", f"{DC}/2026/07/acme-notice.pdf/", "other_pdf"),
    ("View Attachment", "https://www.example.com/press-release", "other_link"),
    ("Press release", "https://www.example.com/press-release.html", "other_link"),
    # Trap: a meeting statement that mentions a decision is still a statement.
    ("Americas DC Meeting Statement regarding the DC Decision of 07/10/26", f"{DC}/x.pdf/", "statement"),
    # Bare "Determinations Committee" must not make something a decision.
    ("Determinations Committee Rules", f"{DC}/rules.pdf/", "other_pdf"),
    ("DC Resolution", f"{DC}/r.pdf/", "dc_decision"),
    ("Credit Event Determination", f"{DC}/d.pdf/", "dc_decision"),
]


@pytest.mark.parametrize(("text", "url", "expected"), REAL_LINKS + EXTRA_LINKS)
def test_classify_link(text, url, expected):
    assert classify_link(text, url) == expected


def test_enough_real_cases():
    assert len(REAL_LINKS) >= 25


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26", "2026063001"),
        ("List of Participating Bidders - Issue Number: 2026041701", "2026041701"),
        ("issue number 2026041701", "2026041701"),
        ("Issue Number 12345", ""),
        ("Issue Number 202606300199", ""),
        ("DC Decision", ""),
        ("", ""),
    ],
)
def test_extract_issue_number(text, expected):
    assert extract_issue_number(text) == expected


@pytest.mark.parametrize(
    ("text", "url", "expected"),
    [
        (
            "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26",
            "",
            "2026-08-10",
        ),
        ("Decision - 7/14/2026", "", "2026-07-14"),
        ("Auction Settlement Terms - July 22, 2026", "", "2026-07-22"),
        ("Auction Settlement Terms - Sept. 3 2015", "", "2015-09-03"),
        ("Decision 17 May 2023", "", "2023-05-17"),
        ("Decision 1st March 2012", "", "2012-03-01"),
        # Text wins over the filename.
        ("Decision - 08/04/26", f"{DC}/2026/08/x-decision-20200101.pdf/", "2026-08-04"),
        # Invalid date in text falls through to the filename.
        ("Decision - 13/45/26", f"{DC}/2026/08/x-2026-08-01.pdf/", "2026-08-01"),
        (
            "DC Decision",
            f"{DC}/2023/05/emea-dc-credit-suisse-group-ag-dc-decision-17-may-2023.pdf/",
            "2023-05-17",
        ),
        (
            "View Attachment",
            "http://www.cdsdeterminationscommittees.org/docs/20090416 200904163 DC resolutions.pdf",
            "2009-04-16",
        ),
        ("View Attachment", "http://www.isda.org/dc/docs/EMEA_DC_Statement_01032012.pdf", "2012-03-01"),
        ("EMEA Determinations Committee Decision 01032012", "", "2012-03-01"),
        ("x", "https://e.org/docs/report-2019-02-28.pdf", "2019-02-28"),
        # Ambiguous dashed numeric filename dates are not parsed.
        ("Final List", f"{DC}/2026/07/x-decision-07-10-26.pdf/", ""),
        # 10-digit issue numbers are not dates.
        ("Issue Number 2026063001", "", ""),
        ("Final List of Deliverable Obligations", f"{DC}/2026/07/dish-dbs-corporation-final-list.pdf/", ""),
        ("", "", ""),
    ],
)
def test_extract_doc_date(text, url, expected):
    assert extract_doc_date(text, url) == expected


def test_annotate_link():
    link = {
        "dc_id": "cds/dish-dbs-corporation",
        "link_text": "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26",
        "url": f"{DC}/2026/08/dish-dbs-corporation-decision-08-10-26.pdf/",
        "url_normalized": f"{DC}/2026/08/dish-dbs-corporation-decision-08-10-26.pdf/",
    }
    out = annotate_link(link, TARGET_DOC_TYPES)
    assert out is not link and "doc_type" not in link
    assert out["doc_type"] == "dc_decision"
    assert out["is_target"] is True
    assert out["doc_issue_number"] == "2026063001"
    assert out["doc_date"] == "2026-08-10"
    assert out["dc_id"] == "cds/dish-dbs-corporation"

    stmt = annotate_link({**link, "link_text": "EMEA DC Statement 01032012"}, TARGET_DOC_TYPES)
    assert stmt["doc_type"] == "statement" and stmt["is_target"] is False
    assert stmt["doc_issue_number"] == ""


def test_two_digit_years():
    assert extract_doc_date("DC Decision 03/09/13", "") == "2013-03-09"
    assert extract_doc_date("DC Decision 12/31/98", "") == "1998-12-31"
