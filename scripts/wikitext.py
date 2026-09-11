#!/usr/bin/env python3
"""Just enough wikitext parsing to pull an infobox and a plot summary out of a page.

This is deliberately not a general MediaWiki parser. It does three things:
extract the named infobox and its parameters, flatten inline markup to readable
text, and find the section that holds the plot. Everything else in the page is
left alone.

The one thing that cannot be done with a regular expression is splitting an
infobox on `|`, because parameter values routinely contain nested templates,
wikilinks and `<ref>` blocks that carry their own pipes:

    |cover artist=*[[Tom Jung]]<br/>{{C|Original cover}}
    |producer=*[[Gary Kurtz]]<ref name="Year by Year">''[[Star Wars Year...]]''</ref>

So the split tracks `{{ }}`, `[[ ]]` and `<ref> </ref>` depth and only breaks on
a pipe at depth zero. That is the whole reason this file exists.
"""

from __future__ import annotations

import html
import re

# ---------------------------------------------------------------- infoboxes


def find_infobox(text: str, names: set[str]) -> tuple[str, dict[str, str]] | None:
    """Return (template_name, params) for the first infobox in `names`, if any.

    `names` is matched case-insensitively against the template name, which on
    Wookieepedia is written `{{Book`, `{{VideoGame`, `{{Movie` and so on --
    conventionally capitalised, but not reliably so.
    """
    for match in re.finditer(r"\{\{\s*([A-Za-z0-9 _'\-]+?)\s*(\||\})", text):
        name = match.group(1).strip().lower().replace(" ", "")
        if name not in names:
            continue
        body = _balanced(text, match.start())
        if body is None:
            continue
        return name, _params(body)
    return None


def _balanced(text: str, start: int) -> str | None:
    """The full `{{...}}` beginning at `start`, honouring nesting. None if unclosed."""
    depth, i, n = 0, start, len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start + 2 : i - 2]
            continue
        i += 1
    return None


def _params(body: str) -> dict[str, str]:
    """Split an infobox body into named parameters, ignoring pipes inside nesting."""
    out: dict[str, str] = {}
    for chunk in _split_pipes(body)[1:]:  # [0] is the template name
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip().lower()
        if key:
            out[key] = value.strip()
    return out


def _split_pipes(body: str) -> list[str]:
    parts, buf = [], []
    tdepth = ldepth = 0
    refs = 0
    i, n = 0, len(body)
    while i < n:
        two = body[i : i + 2]
        if two == "{{":
            tdepth += 1
            buf.append(two)
            i += 2
            continue
        if two == "}}":
            tdepth -= 1
            buf.append(two)
            i += 2
            continue
        if two == "[[":
            ldepth += 1
            buf.append(two)
            i += 2
            continue
        if two == "]]":
            ldepth -= 1
            buf.append(two)
            i += 2
            continue
        if body.startswith("<ref", i) and not body.startswith("</ref", i):
            # A self-closing <ref name="x" /> opens nothing.
            end = body.find(">", i)
            if end != -1 and body[end - 1] != "/":
                refs += 1
            buf.append(body[i : end + 1] if end != -1 else body[i:])
            i = (end + 1) if end != -1 else n
            continue
        if body.startswith("</ref>", i):
            refs = max(0, refs - 1)
            buf.append("</ref>")
            i += 6
            continue
        if body[i] == "|" and tdepth == 0 and ldepth == 0 and refs == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(body[i])
        i += 1
    parts.append("".join(buf))
    return parts


# ------------------------------------------------------------ flattening

_REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# <br> separates list items and, in titles, words. Dropping it outright welds
# them together ("Darth Bane:Path of Destruction"), so it becomes a space first.
_BR = re.compile(r"<\s*br\s*/?\s*>", re.I)
_HTML = re.compile(r"<[^>]+>")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
# Innermost-first: [^\[\]] refuses to cross another bracket, so a nested link
# is resolved before the one wrapping it. Applied repeatedly by flatten().
_LINK_PIPED = re.compile(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]")
_LINK = re.compile(r"\[\[([^\[\]|]*)\]\]")
# File:/Image: embeds carry layout junk ("thumb|left|180px|") and a caption
# that often contains its own link. The whole embed goes, caption and all --
# it is a picture, not prose.
# No "^": match() already anchors at the offset it is given, and a literal
# "^" there would only match at a line start, silently never firing.
_EMBED_PREFIX = re.compile(r"\s*(?:File|Image)\s*:", re.I)
_ORPHAN_BRACKET = re.compile(r"\[\[|\]\]")
_BOLD_ITALIC = re.compile(r"'{2,5}")
_WS = re.compile(r"[ \t]*\n[ \t]*")


def _drop_embeds(text: str) -> str:
    """Remove [[File:...]] and [[Image:...]] wholly, honouring nested brackets.

    A regex cannot do this: the caption may itself contain [[...]], and a
    non-greedy match stops at the inner "]]", leaving the outer one stranded in
    the output as literal "]]". That is exactly how markup ends up in a plot
    summary.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("[[", i) and _EMBED_PREFIX.match(text, i + 2):
            depth, j = 0, i
            while j < n - 1:
                if text[j : j + 2] == "[[":
                    depth += 1
                    j += 2
                elif text[j : j + 2] == "]]":
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            if depth == 0:
                i = j  # the whole embed is dropped
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def flatten(text: str) -> str:
    """Markup to readable plain text. Lossy on purpose."""
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    text = _BR.sub(" ", text)
    # Templates nest; three passes clears all but pathological cases, and what
    # survives is dropped by the HTML sweep below.
    for _ in range(3):
        text = _TEMPLATE.sub("", text)
    text = _drop_embeds(text)
    # Links nest -- an image caption routinely holds one. Each pass resolves
    # the innermost layer, so a few passes clear any realistic depth.
    for _ in range(4):
        before = text
        text = _LINK_PIPED.sub(r"\1", text)
        text = _LINK.sub(r"\1", text)
        if text == before:
            break
    # Wookieepedia and Memory Beta both contain genuinely malformed links --
    # a doubled "]]", an unclosed "[[" -- which no amount of correct parsing
    # will resolve, because the source itself is wrong. Once every well-formed
    # link is gone, anything left is broken markup, not content.
    text = _ORPHAN_BRACKET.sub("", text)
    text = _BOLD_ITALIC.sub("", text)
    text = _HTML.sub("", text)
    # &ndash; and friends survive every step above and read as literal noise.
    text = html.unescape(text)
    text = _WS.sub("\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def links(value: str) -> list[str]:
    """Every wikilink target in an infobox value, in order, de-duplicated.

    Infobox people fields are written as `*[[A]]<br/>*[[B]]` or with trailing
    `{{C|comment}}` qualifiers, so taking the links is far more reliable than
    trying to split the field on its punctuation.
    """
    # Two kinds of non-person link hide in a people field, and both have to go
    # before the links are read:
    #   <ref>...</ref>        cites the reference work the credit came from
    #   {{C|''[[Some Book]]'' cover}}  qualifies WHICH edition this credit is for
    # Either one puts a book in a list of authors. Refs first, then templates,
    # repeatedly, because {{C|...}} nests.
    value = _REF.sub("", value)
    for _ in range(3):
        value = _TEMPLATE.sub("", value)
    out, seen = [], set()
    for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", value):
        target = m.group(1).strip()
        # Wookieepedia disambiguates with a trailing "(novel)" etc.; the person
        # fields never need that, and File:/Category: are not people.
        if ":" in target.split("|")[0][:12]:
            continue
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


# --------------------------------------------------------------- sections


def section(text: str, titles: set[str]) -> str | None:
    """The body of the first `== Heading ==` whose name is in `titles`."""
    pattern = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.M)
    marks = list(pattern.finditer(text))
    for i, m in enumerate(marks):
        if m.group(2).strip().lower() not in titles:
            continue
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = flatten(text[start:end])
        return body or None
    return None


def lead(text: str) -> str:
    """The text before the first heading, with the infobox removed."""
    first = re.search(r"^={2,4}\s*.+?\s*={2,4}\s*$", text, re.M)
    head = text[: first.start()] if first else text
    # Drop every top-level template (the infobox and the maintenance banners).
    out, depth, buf = [], 0, []
    i, n = 0, len(head)
    while i < n:
        two = head[i : i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth = max(0, depth - 1)
            i += 2
            continue
        if depth == 0:
            buf.append(head[i])
        i += 1
    out = "".join(buf)
    return flatten(out)


YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def year_of(value: str) -> int | None:
    """First plausible publication year in a release-date field."""
    m = YEAR.search(flatten(value))
    return int(m.group(1)) if m else None
