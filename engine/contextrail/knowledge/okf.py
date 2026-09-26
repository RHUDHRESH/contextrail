"""OKF v0.1 loader (checklist T176): frontmatter parser, sections, links and the link graph.

A bundle is a directory of Markdown files with YAML frontmatter; only `type` is required, and unknown keys are kept,
never rejected (OKF v0.1). `index.md` and `log.md` are reserved listing files and need no frontmatter. `raw/`
(immutable source copies) and `drafts/` (machine-written updates awaiting a person) are not curated knowledge and
are never loaded. Conventions are in knowledge/SCHEMA.md.

The loader is lenient where the policy loader is strict: a broken page is recorded in `Bundle.problems` (and
reported by the lint, T179) instead of stopping the engine, because knowledge is evidence, not the rules.
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from contextrail.settings import get_settings

RESERVED = frozenset({"index.md", "log.md"})
NOT_CURATED = frozenset({"raw", "drafts"})
_REPO_ROOT = Path(__file__).resolve().parents[3]

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def knowledge_dir() -> Path:
    """The bundle root: $KNOWLEDGE_DIR, else Settings.knowledge_dir, else <repo>/knowledge."""
    return Path((os.environ.get("KNOWLEDGE_DIR") or get_settings().knowledge_dir) or _REPO_ROOT / "knowledge")


class Frontmatter(BaseModel):
    """OKF fields plus ContextRail's extensions (SCHEMA.md). Unknown keys land in `model_extra`, untouched."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str | None = None
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = []
    last_verified: date | None = None
    owner: str | None = None
    rules: list[str] = []
    claims: dict[str, str] = {}

    @field_validator("claims", mode="before")
    @classmethod
    def _claim_values_are_text(cls, v: object) -> object:
        # YAML turns `180` into an int and `4h` into a str; a claim is compared as text either way.
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return v


def slugify(heading: str) -> str:
    s = re.sub(r"\s+", "-", heading.strip().lower())
    return re.sub(r"[^\w\-§]", "", s)


@dataclass(frozen=True)
class Section:
    heading: str
    level: int      # 1-6; 0 for text before the first heading
    slug: str
    text: str       # what sits directly under the heading, up to the next heading of any level
    line: int       # 1-based line of the heading in the file


@dataclass(frozen=True)
class Link:
    text: str
    target: str             # as written
    resolved: str | None    # bundle-relative POSIX path it points to (anchor dropped); None for URLs with a scheme
    line: int


@dataclass(frozen=True)
class Problem:
    path: str
    message: str


@dataclass(frozen=True)
class Page:
    path: str                       # bundle-relative POSIX path, e.g. "policies/contractor-onboarding.md"
    meta: Frontmatter | None        # None when a reserved file has no frontmatter or the frontmatter is invalid
    body: str
    sections: tuple[Section, ...]
    links: tuple[Link, ...]
    reserved: bool

    def section(self, clause: str) -> Section | None:
        """The section whose heading is `clause`, or starts with it followed by a space ("§4" -> "§4 Production")."""
        for s in self.sections:
            if s.heading == clause or s.heading.startswith(clause + " "):
                return s
        return None

    @property
    def title(self) -> str:
        if self.meta and self.meta.title:
            return self.meta.title
        first = next((s.heading for s in self.sections if s.level == 1), None)
        return first or self.path


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None, text
    end = re.search(r"^(---|\.\.\.)\s*$", text[4:], flags=re.MULTILINE)
    if end is None:
        return None, text
    return text[4:4 + end.start()], text[4 + end.end():].lstrip("\n")


def _sections_and_links(path: str, body: str, offset: int) -> tuple[tuple[Section, ...], tuple[Link, ...]]:
    sections: list[Section] = []
    links: list[Link] = []
    seen: dict[str, int] = {}
    current: tuple[str, int, int] | None = None
    buf: list[str] = []
    in_fence = False
    here = posixpath.dirname(path)

    def close() -> None:
        text = "\n".join(buf).strip()
        if current is None and not text:
            return
        heading, level, line = current or ("", 0, offset + 1)
        slug = slugify(heading)
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        sections.append(Section(heading, level, slug, text, line))

    for n, line in enumerate(body.split("\n"), start=offset + 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            close()
            current, buf = (m.group(2).strip(), len(m.group(1)), n), []
            continue
        buf.append(line)
        if in_fence:
            continue
        for lm in _LINK.finditer(_INLINE_CODE.sub(" ", line)):
            target = lm.group(2)
            if target.startswith("#"):
                continue  # an anchor within this page
            resolved = None
            if not _SCHEME.match(target):
                bare = unquote(target.split("#", 1)[0].split("?", 1)[0])
                resolved = posixpath.normpath(posixpath.join(here, bare)) if bare else path
            links.append(Link(lm.group(1), target, resolved, n))
    close()
    return tuple(sections), tuple(links)


def parse_page(path: str, text: str) -> tuple[Page, list[Problem]]:
    """Parse one file. Always returns a Page (so its links still count); problems say what is wrong with it."""
    reserved = posixpath.basename(path) in RESERVED
    raw, body = _split_frontmatter(text)
    problems: list[Problem] = []
    meta: Frontmatter | None = None
    if raw is None:
        if not reserved:
            problems.append(Problem(path, "missing YAML frontmatter (every non-reserved page needs one, OKF v0.1)"))
    else:
        try:
            data = yaml.safe_load(raw) or {}
            if isinstance(data, dict):
                meta = Frontmatter.model_validate(data)
            else:
                problems.append(Problem(path, f"invalid frontmatter: expected a mapping, got {type(data).__name__}"))
        except yaml.YAMLError as e:
            problems.append(Problem(path, f"invalid frontmatter: {e}"))
        except ValidationError as e:
            detail = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            problems.append(Problem(path, f"invalid frontmatter: {detail}"))
        if meta is not None and not reserved and not (meta.type or "").strip():
            problems.append(Problem(path, "frontmatter must have a non-empty 'type' (OKF v0.1)"))
            meta = None
    offset = text.replace("\r\n", "\n").count("\n") - body.count("\n")
    sections, links = _sections_and_links(path, body, offset)
    return Page(path, meta, body, sections, links, reserved), problems


@dataclass
class Bundle:
    root: Path
    pages: dict[str, Page]
    problems: list[Problem] = field(default_factory=list)
    _backlinks: dict[str, set[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for src in self.pages:
            for dst in self.outgoing(src):
                self._backlinks.setdefault(dst, set()).add(src)

    def concepts(self) -> list[Page]:
        """Curated concept pages: not reserved, with valid frontmatter."""
        return [p for p in self.pages.values() if not p.reserved and p.meta is not None]

    def outgoing(self, path: str) -> set[str]:
        """Pages this file links to (links to itself and to files that are not loaded pages are left out)."""
        page = self.pages[path]
        return {lk.resolved for lk in page.links if lk.resolved in self.pages and lk.resolved != path}

    def backlinks(self, path: str) -> set[str]:
        return set(self._backlinks.get(path, set()))


def load_bundle(root: Path | str | None = None) -> Bundle:
    root = Path(root) if root is not None else knowledge_dir()
    pages: dict[str, Page] = {}
    problems: list[Problem] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if rel.split("/", 1)[0] in NOT_CURATED or any(part.startswith(".") for part in rel.split("/")):
            continue
        page, found = parse_page(rel, f.read_text(encoding="utf-8"))
        pages[rel] = page
        problems += found
    return Bundle(root=root, pages=pages, problems=problems)
