"""The bundle's reserved listing files (checklist T171, T172): index.md in the root and in every folder, log.md.

OKF uses index.md for progressive disclosure: an agent reads the root index, then a folder index, then a page.
A page missing from its folder's index is invisible to that reader, so coverage is tested.
"""

import posixpath
import re

from contextrail.knowledge.okf import load_bundle

BUNDLE = load_bundle()
_ENTRY = re.compile(r"^- \[[^\]]+\]\([^)]+\) - \S.+$")   # "- [Title](relative-url) - description"


def _folders() -> set[str]:
    return {posixpath.dirname(p.path) for p in BUNDLE.concepts() if "/" in p.path}


def test_every_folder_has_an_index_that_lists_each_of_its_pages():
    for folder in sorted(_folders()):
        index = f"{folder}/index.md"
        assert index in BUNDLE.pages, f"{folder}/ has no index.md"
        pages = {p.path for p in BUNDLE.concepts() if posixpath.dirname(p.path) == folder}
        assert BUNDLE.outgoing(index) >= pages, f"{index} does not list {sorted(pages - BUNDLE.outgoing(index))}"


def test_the_root_index_lists_every_folder_index_and_every_top_level_page():
    assert "index.md" in BUNDLE.pages
    top = {p.path for p in BUNDLE.concepts() if "/" not in p.path}
    expected = {f"{f}/index.md" for f in _folders()} | top | {"log.md"}
    assert BUNDLE.outgoing("index.md") >= expected, sorted(expected - BUNDLE.outgoing("index.md"))


def test_index_entries_are_links_with_a_description_and_every_link_resolves():
    indexes = {path: page for path, page in BUNDLE.pages.items() if posixpath.basename(path) == "index.md"}
    assert len(indexes) == len(_folders()) + 1
    for path, page in indexes.items():
        entries = [ln for ln in page.body.splitlines() if ln.startswith("- ")]
        assert entries, f"{path} lists nothing"
        for ln in entries:
            assert _ENTRY.match(ln), f"{path}: entry is not '- [Title](url) - description': {ln!r}"
        for lk in page.links:
            assert lk.resolved in BUNDLE.pages, f"{path}: link to {lk.target} does not resolve to a page"


# --- log.md (T172) ---------------------------------------------------------------------------------------------

_LOG_KINDS = ("Creation", "Update", "Deprecation", "Review")


def test_log_dates_are_iso_and_newest_first():
    dates = [s.heading for s in BUNDLE.pages["log.md"].sections if s.level == 2]
    assert dates and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates), dates
    assert dates == sorted(dates, reverse=True) and len(set(dates)) == len(dates)


def test_every_log_entry_starts_with_a_bold_kind():
    for s in (s for s in BUNDLE.pages["log.md"].sections if s.level == 2):
        entries = [ln for ln in s.text.splitlines() if ln.startswith("- ")]
        assert entries, f"{s.heading} has no entries"
        for ln in entries:
            kind = re.match(r"- \*\*(\w+)\*\* ", ln)
            assert kind and kind.group(1) in _LOG_KINDS, f"entry must start with a bold {_LOG_KINDS}: {ln!r}"


def test_every_page_has_a_creation_entry_in_the_log():
    lines = (BUNDLE.root / "log.md").read_text(encoding="utf-8").splitlines()
    log = BUNDLE.pages["log.md"]
    created = {lk.resolved for lk in log.links if lines[lk.line - 1].startswith("- **Creation** ")}
    assert {p.path for p in BUNDLE.concepts()} <= created, sorted({p.path for p in BUNDLE.concepts()} - created)
