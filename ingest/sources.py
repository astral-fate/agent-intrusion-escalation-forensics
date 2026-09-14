"""Source registry, fetcher and byte-level cache for the Track 2 forensic corpus.

Everything downstream reads through this module, so it is the only place that touches the
network. Three rules are enforced here rather than trusted to callers:

1. **A browser User-Agent is mandatory.** Five of the six primary sources return HTTP 403 to a
   default Python UA, and an earlier pass in this project recorded that 403 as "the data is
   unavailable" and marked two datasets DEAD. They were not. The single header below is the
   entire difference, so it is a named constant with this note attached to it.
2. **Raw bytes are cached and hashed.** A claim in the paper has to be traceable to the exact
   bytes it was computed from. The cache is content-addressed by SHA-256 recorded in
   `cache/manifest.json`, so a source silently changing under us is detectable rather than
   invisible.
3. **Source class is declared, not inferred.** PRIMARY (the actor or victim), INDEPENDENT
   (METR/Redwood-class third party), SECONDARY (press). The paper's citation discipline needs
   this attached to the data, not remembered.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
MANIFEST = CACHE / "manifest.json"

#: Without this, huggingface.co, openai.com and metr.org all return HTTP 403. See rule 1 above.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TIMEOUT = 120


@dataclass(frozen=True)
class Source:
    """One retrievable primary artifact."""

    key: str
    url: str
    kind: str          # html | pdf | markdown
    source_class: str  # PRIMARY | INDEPENDENT | SECONDARY
    author: str
    title: str

    @property
    def path(self) -> Path:
        return CACHE / f"{self.key}.{self.kind if self.kind != 'markdown' else 'md'}"


SOURCES: dict[str, Source] = {
    s.key: s for s in [
        Source(
            key="hf_replay_space",
            url=("https://huggingface-anatomy-of-frontier-lab-model-intrusion"
                 ".static.hf.space/index.html"),
            kind="html", source_class="PRIMARY", author="Hugging Face",
            title="Anatomy of a Frontier Lab Model Intrusion (interactive replay)",
        ),
        Source(
            key="hf_blog_timeline",
            url=("https://raw.githubusercontent.com/huggingface/blog/main/"
                 "agent-intrusion-technical-timeline.md"),
            kind="markdown", source_class="PRIMARY", author="Hugging Face",
            title=("Anatomy of a Frontier Lab Agent Intrusion: A Technical Timeline of the "
                   "July 2026 Incident"),
        ),
        Source(
            key="hf_disclosure",
            url="https://huggingface.co/blog/security-incident-july-2026",
            kind="html", source_class="PRIMARY", author="Hugging Face",
            title="Security incident disclosure — July 2026",
        ),
        Source(
            key="metr_report",
            url="https://metr.org/hugging-face-incident-report-aug-2026.pdf",
            kind="pdf", source_class="INDEPENDENT", author="METR and Redwood Research",
            title=("Brief independent investigation of agents' behavior, reasoning and "
                   "collaboration in the OpenAI / Hugging Face hacking incident"),
        ),
        Source(
            key="openai_road_ahead",
            url="https://openai.com/index/hugging-face-incident-and-the-road-ahead/",
            kind="html", source_class="PRIMARY", author="OpenAI",
            title="The Hugging Face incident and the road ahead",
        ),
        Source(
            key="openai_disclosure",
            url="https://openai.com/index/hugging-face-model-evaluation-security-incident/",
            kind="html", source_class="PRIMARY", author="OpenAI",
            title="Hugging Face model evaluation security incident",
        ),
        # Added in revision. The perpetrator-side escalation interval is only in this
        # document: the 26 Aug blog announces the report but carries no UTC appendix, and
        # its own timeline widget misdates the Artifactory rebuild by 1--2 days relative to
        # this PDF. Everything the paper says about OpenAI's alert-to-response gap is
        # anchored here rather than in press reporting.
        Source(
            key="openai_tech_report",
            url=("https://cdn.openai.com/pdf/67869394-cb91-4c12-888c-5cbd85c7814c/"
                 "OpenAI-Hugging-Face%20Incident-Technical-Report.pdf"),
            kind="pdf", source_class="PRIMARY", author="OpenAI",
            title="OpenAI - Hugging Face Incident Technical Report",
        ),
    ]
}


def _manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(m: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")


def fetch(key: str, refresh: bool = False) -> bytes:
    """Return the raw bytes of one source, from cache unless `refresh`.

    On every fetch the SHA-256 is recorded. If a re-fetch produces a different digest from the
    one already on record, that is reported loudly: the paper's numbers were computed from the
    old bytes, and a silent upstream edit is exactly the failure this manifest exists to catch.
    """
    src = SOURCES[key]
    man = _manifest()

    if src.path.exists() and not refresh:
        return src.path.read_bytes()

    req = urllib.request.Request(src.url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
        status = r.status

    digest = hashlib.sha256(data).hexdigest()
    prior = man.get(key, {}).get("sha256")
    if prior and prior != digest:
        print(f"  !! {key}: upstream bytes CHANGED since {man[key]['fetched']}")
        print(f"     was {prior}\n     now {digest}")
        print("     Any number already computed from this source must be recomputed.")

    CACHE.mkdir(parents=True, exist_ok=True)
    src.path.write_bytes(data)
    man[key] = {
        "url": src.url, "sha256": digest, "bytes": len(data), "http_status": status,
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_class": src.source_class, "author": src.author, "title": src.title,
    }
    _save_manifest(man)
    return data


def text(key: str, refresh: bool = False) -> str:
    """UTF-8 text of a non-PDF source."""
    if SOURCES[key].kind == "pdf":
        raise ValueError(f"{key} is a PDF -- use ingest.metr, which records page numbers")
    return fetch(key, refresh).decode("utf-8", errors="replace")


def fetch_all(refresh: bool = False) -> dict[str, int]:
    sizes = {}
    for key in SOURCES:
        try:
            sizes[key] = len(fetch(key, refresh))
            print(f"  {key:22} {sizes[key]:>9,} bytes  [{SOURCES[key].source_class}]")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            # Reported, never swallowed: a missing source must not look like an empty one.
            print(f"  {key:22} FAILED -- {e}")
            sizes[key] = 0
    return sizes


if __name__ == "__main__":
    print("Fetching Track 2 primary sources (browser UA; cached + hashed)\n")
    got = fetch_all()
    print(f"\n{sum(1 for v in got.values() if v)}/{len(got)} sources cached")
    print(f"manifest: {MANIFEST}")
