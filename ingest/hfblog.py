"""Parse Hugging Face's technical-timeline post into sections, commands and citable quotes.

    python ingest/hfblog.py

Writes `data/hfblog_sections.csv`, `data/hfblog_commands.csv` and `data/hfblog_quotes.json`.

Source note
-----------
Fetched from `raw.githubusercontent.com/huggingface/blog`, not from `huggingface.co/blog`. The
rendered page is 574 kB of site chrome around the same text; the repository serves the 38 kB
Markdown the post is generated from, which parses deterministically and carries the author list
in front matter. Same publisher, same content, far less to go wrong.

This is the victim's own account, so everything here is PRIMARY -- and it is also the account of
an organisation describing its own detection failure, which is exactly the material Track 2's
escalation argument rests on.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sources import ROOT, text

DATA = ROOT / "data"

#: Passages the escalation argument depends on. Each is located by a short, distinctive anchor
#: and the surrounding sentence is captured verbatim, so the paper quotes retrieved text rather
#: than remembered text. A missing anchor is reported, never silently skipped.
#: Anchors in the TECHNICAL TIMELINE post.
QUOTE_ANCHORS = {
    "detection_criticality": "criticality",
    "defenders_dilemma_timeline": "refused a large part",
    "asymmetry": "asymmetry",
}

#: Anchors in the DISCLOSURE post, which is a different document by the same publisher.
#:
#: The distinction cost a round trip and is worth recording. The project's incident record
#: carries the "behind commercial APIs" passage attributed to HF "Anatomy" -- the technical
#: timeline -- flagged `Verbatim (retrieved truncated -- must be re-fetched before quoting)`.
#: Re-fetching showed the sentence is **absent from the technical timeline** and present in the
#: **disclosure**. An intermediate pass here concluded it appeared in no source at all; that was
#: wrong, and it was wrong because `grep` classified the HTML as binary and printed nothing
#: rather than reporting a match. A test comparing decoded text caught it.
#:
#: So: the quotation is genuine and citable, the inherited attribution points at the wrong HF
#: post, and both posts contain a section on "the asymmetry problem" -- which is very likely how
#: the two were conflated in the first place.
#: "The asymmetry problem" was tried as a second anchor here and removed: stripping tags from
#: the rendered page leaves navigation and inline script text, and that phrase matched chrome
#: before it matched prose. An anchor has to be distinctive against the *whole* decoded
#: document, not just against the part a reader looks at.
DISCLOSURE_ANCHORS = {
    "defenders_dilemma": "behind commercial APIs",
}


def front_matter(md: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    if not m:
        return {}
    out: dict[str, list[str] | str] = {}
    authors: list[str] = []
    for line in m.group(1).split("\n"):
        if line.strip().startswith("- user:"):
            authors.append(line.split(":", 1)[1].strip())
        elif ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    if authors:
        out["authors"] = authors
    return out


def sections(md: str) -> list[dict]:
    """Headings with their level, title and body length.

    Fenced code is blanked first: several captured commands contain a leading `#` comment, and
    counting those as headings invents sections that are not in the document.
    """
    masked = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), md, flags=re.S)
    out = []
    lines = masked.split("\n")
    marks = [(i, len(m.group(1)), m.group(2).strip())
             for i, l in enumerate(lines)
             if (m := re.match(r"^(#{1,6})\s+(.*)$", l))]
    for idx, (i, lvl, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        out.append({"line": i + 1, "level": lvl, "title": title, "body_chars": len(body)})
    return out


def code_blocks(md: str) -> list[dict]:
    """Fenced blocks, tagged with the nearest preceding heading."""
    heads = sections(md)
    out = []
    for m in re.finditer(r"```([A-Za-z0-9_+-]*)\n(.*?)```", md, re.S):
        line = md[:m.start()].count("\n") + 1
        prior = [h for h in heads if h["line"] <= line]
        out.append({
            "line": line,
            "lang": m.group(1) or "text",
            "section": prior[-1]["title"] if prior else "",
            "lines": m.group(2).count("\n"),
            "code": m.group(2).strip(),
        })
    return out


#: Sentences captured after the one containing the anchor. The claim usually lives in the
#: follow-on: "…we first used frontier models behind commercial APIs." is not evidence of
#: anything until the next sentence says it did not work and why.
TRAILING_SENTENCES = 2


def _extract(flat: str, anchors: dict[str, str], where: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, anchor in anchors.items():
        i = flat.find(anchor)
        if i < 0:
            print(f"  !! anchor '{anchor}' ({name}) NOT FOUND in {where} -- re-locate it "
                  "before quoting")
            continue
        start = max(0, flat.rfind(". ", 0, i) + 2)
        end = flat.find(". ", i)
        end = len(flat) if end < 0 else end + 1
        for _ in range(TRAILING_SENTENCES):
            nxt = flat.find(". ", end)
            if nxt < 0:
                break
            end = nxt + 1
        out[name] = {"anchor": anchor, "source": where, "text": flat[start:end].strip()}
    return out


def quotes(md: str) -> dict[str, dict]:
    """Verbatim sentences from the technical-timeline Markdown."""
    body = re.sub(r"```.*?```", " ", md, flags=re.S)
    return _extract(re.sub(r"\s+", " ", body), QUOTE_ANCHORS, "hf_blog_timeline")


def disclosure_quotes(html: str) -> dict[str, dict]:
    """Verbatim sentences from the disclosure post.

    Tags are stripped before matching. Searching raw HTML would miss any passage a tag happens
    to split, and would also make a match position meaningless for locating a sentence.
    """
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    return _extract(flat, DISCLOSURE_ANCHORS, "hf_disclosure")


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    md = text("hf_blog_timeline")

    fm = front_matter(md)
    secs = sections(md)
    blocks = code_blocks(md)
    qs = quotes(md)
    qs.update(disclosure_quotes(text("hf_disclosure")))

    assert secs, "no headings parsed -- the Markdown structure changed"
    assert blocks, "no code blocks parsed -- the captured commands are the point of this source"

    with (DATA / "hfblog_sections.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["line", "level", "title", "body_chars"])
        w.writeheader()
        w.writerows(secs)
    with (DATA / "hfblog_commands.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["line", "lang", "section", "lines", "code"])
        w.writeheader()
        w.writerows(blocks)
    (DATA / "hfblog_quotes.json").write_text(
        json.dumps({"front_matter": fm, "quotes": qs}, indent=2), encoding="utf-8")

    print(f"authors      {', '.join(fm.get('authors', [])) or '(none parsed)'}")
    print(f"sections     {len(secs)}")
    print(f"code blocks  {len(blocks)}  ({sum(b['lines'] for b in blocks)} lines of captured "
          "commands)")
    n_anchors = len(QUOTE_ANCHORS) + len(DISCLOSURE_ANCHORS)
    print(f"quotes       {len(qs)}/{n_anchors} anchors located "
          "(technical timeline + disclosure)")
    for name, q in qs.items():
        print(f"\n  [{name}]\n    {q['text'][:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
