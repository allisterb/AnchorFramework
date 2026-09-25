"""Scan a check's inputs for hidden text, adversarial prompts and markup, before anything reads them.

    anchor scan examples/aws1
    anchor scan policy.dw --json

THE INPUTS ARE THE THREAT MODEL. Anchor is run on a policy BECAUSE someone does not trust it, and
that policy's text reaches three things that would each act on it:

  a model      `auto`, `hitl` and the audit's questions hand policy text to an LLM, which follows
               instructions wherever it finds them -- including in a comment nobody else reads
  a browser    findings.html quotes rule comments and names; markup there would run
  a terminal   every verb prints policy text; an escape sequence there rewrites the screen

and, apart from all three, the policy itself can LIE: a bidi override or a look-alike letter makes
a rule display as one thing and match as another. None of that is a parse error. The parser, TLC
and Dogwood are deterministic and take it in their stride -- which is exactly why it has to be
looked for separately.

WHAT IS FLAGGED, and at what severity:

  high     reorders or hides text (bidi controls, zero-width and other invisibles, the Unicode Tag
           block, variation-selector runs), control characters and terminal escapes, a token that
           mixes scripts (`execute_trаde` with a Cyrillic `а`), a string escape that spells any of
           those while the file itself looks clean, prompt-injection phrasing, HTML/script markup,
           and an encoded blob that decodes to either
  medium   non-ASCII in an identifier, private-use characters, line/paragraph separators, a file
           that is not valid UTF-8, a remote image in markdown, an encoded blob of readable text
  info     the census of every other non-ASCII codepoint, for a person to judge -- accented names,
           typography and box drawing are normal and are not findings

Patterned on `reference/scan-codepoints.pl`, which does this for third-party material. That script
is not in the repository and needs Perl; this one ships in the image and knows the languages it
reads, so a bidi override in a string literal and one in a comment are reported as the different
things they are.

IT IS A HEURISTIC, AND SAYS SO. Phrase lists miss rephrasings and catch a comment that DISCUSSES
prompt injection. So a high finding refuses by default and `--allow-flagged-input` proceeds anyway,
on the record: the escape hatch is for a person who has read the finding, not a way round reading it.

Exit: 0 nothing above info, 1 findings, 3 nothing could be read.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote_to_bytes

HIGH, MEDIUM, INFO = "high", "medium", "info"

# What each suffix is written in, which decides where comments and strings are.
LANG = {".dw": "dw", ".cedarschema": "dw", ".dwschema": "dw",
        ".tla": "tla", ".cfg": "tla", ".md": "text", ".txt": "text"}

# The inputs a check actually reads from a policy directory -- and so the ones worth scanning.
# Its OUTPUTS (findings.md, results.json, traces/) are written from these and are not inputs.
INPUT_SUFFIXES = {".dw", ".tla", ".cfg", ".cedarschema", ".dwschema"}
INPUT_NAMES = {"intents.md", "questions.md"}


# --------------------------------------------------------------------------------- codepoints ---

def classify(cp: int) -> tuple[str, str, str] | None:
    """(kind, severity, why) for a codepoint worth reporting on its own, else None."""
    if 0x202A <= cp <= 0x202E or 0x2066 <= cp <= 0x2069 or cp == 0x061C:
        return ("bidi-control", HIGH,
                "reorders how the text DISPLAYS without changing what it IS -- the line can read "
                "as one thing to a person and parse as another")
    if (0x200B <= cp <= 0x200F or 0x2060 <= cp <= 0x2064 or cp in (0xFEFF, 0x180E, 0x034F,
            0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5) or 0xFFF9 <= cp <= 0xFFFB):
        return ("invisible", HIGH,
                "renders as nothing; inside a name it makes two names that look identical "
                "different, and runs of it can carry encoded text")
    if cp == 0x00AD:
        return ("invisible", HIGH, "a soft hyphen, which renders as nothing on one line")
    if 0xE0000 <= cp <= 0xE007F:
        return ("tag-block", HIGH,
                "an invisible copy of an ASCII character -- the known channel for instructions a "
                "model reads and a person cannot see")
    if 0xE0100 <= cp <= 0xE01EF:
        return ("variation-selector", HIGH,
                "a supplementary variation selector; these have no use in a policy and runs of "
                "them are a known way to hide data behind one visible character")
    if cp == 0x1B:
        return ("terminal-escape", HIGH,
                "ESC: printed to a terminal it starts a control sequence that can rewrite what "
                "the screen shows, set the window title, or plant a hyperlink")
    if cp == 0x00:
        return ("binary", HIGH, "a NUL byte; this is not a text file")
    if (cp < 0x20 and cp not in (0x09, 0x0A, 0x0D)) or cp == 0x7F or 0x80 <= cp <= 0x9F:
        return ("control", HIGH, "a control character, which has no business in a policy")
    if cp in (0x2028, 0x2029):
        return ("line-separator", MEDIUM,
                "an invisible line break that some parsers honour and others do not")
    if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0x10FFFD:
        return ("private-use", MEDIUM, "a private-use character, whose meaning is not defined")
    return None


def is_selector(cp: int) -> bool:
    return 0xFE00 <= cp <= 0xFE0F


def shown(s: str, limit: int = 110) -> str:
    """`s` with anything invisible or controlling spelled out, so the report cannot itself inject.

    The scanner prints the lines it flags. Printing an ESC it found would run the very attack it
    reported; so every codepoint `classify` names, and every selector, becomes `<U+XXXX>`.
    """
    out = []
    for ch in s:
        cp = ord(ch)
        if classify(cp) or is_selector(cp) or (cp < 0x20 and ch != "\t"):
            out.append(f"<U+{cp:04X}>")
        else:
            out.append(ch)
    text = "".join(out).replace("\t", " ")
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def script_of(ch: str) -> str:
    """The script a letter belongs to, as the first word of its Unicode name: LATIN, CYRILLIC..."""
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return "UNKNOWN"


# ---------------------------------------------------------------------------------- contexts ---

def contexts(text: str, lang: str) -> list[str]:
    """Label every character `code`, `comment`, `string` or `text`.

    Enough of each language to know where its comments and string literals are -- not a parser,
    and it does not need to be: a finding reports where it sits, and the severity barely depends
    on it. What it buys is the difference between a bidi override in a comment (hidden text) and
    one in a string (a rule that matches something other than what it shows).
    """
    n = len(text)
    if lang == "text":
        return ["text"] * n
    label = ["code"] * n

    lo, hi = 0, n
    if lang == "tla":
        # Text outside the module is ignored by SANY -- free prose, i.e. a comment.
        m = re.search(r"^-{4,}\s*MODULE\b", text, re.M)
        if m:
            lo = m.start()
        ends = list(re.finditer(r"^={4,}\s*$", text, re.M))
        if ends:
            hi = ends[-1].end()
        for k in list(range(0, lo)) + list(range(hi, n)):
            label[k] = "comment"

    i = lo
    while i < hi:
        two = text[i:i + 2]
        if (lang == "dw" and two == "//") or (lang == "tla" and two == "\\*"):
            j = text.find("\n", i)
            j = hi if j < 0 else j
            for k in range(i, j):
                label[k] = "comment"
            i = j
        elif (lang == "tla" and two == "(*") or (lang == "dw" and two == "/*"):
            open_, close = ("(*", "*)") if lang == "tla" else ("/*", "*/")
            depth, j = 1, i + 2
            while j < hi and depth:
                if text.startswith(open_, j) and lang == "tla":
                    depth, j = depth + 1, j + 2
                elif text.startswith(close, j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            for k in range(i, j):
                label[k] = "comment"
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < hi and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, hi)
            for k in range(i, j):
                label[k] = "string"
            i = j
        else:
            i += 1
    return label


# ----------------------------------------------------------------------------------- phrases ---

# Prompt-injection phrasing. A HEURISTIC: it misses rephrasings, and it catches text ABOUT prompt
# injection -- which is why a hit refuses by default rather than forever. Kept deliberately
# specific: phrases aimed at a model, not English that happens to contain "system" or "user".
PHRASES = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,20}\b(all\s+|any\s+|the\s+|your\s+)?"
    r"(previous|prior|above|earlier|preceding|foregoing|original|system)\b.{0,20}"
    r"\b(instructions?|directions?|rules?|prompts?|context|guidelines|constraints)\b",
    r"\byou\s+are\s+now\b",
    r"\bfrom\s+now\s+on,?\s+(you|the\s+(assistant|model|agent))\b",
    r"\bnew\s+(system\s+)?instructions?\s*:",
    r"\b(act|behave|respond)\s+as\s+(if\s+you\s+(are|were)|an?|the)\s+\w+",
    r"\bpretend\s+(to\s+be|you\s+are)\b",
    r"\bsystem\s*(prompt|message)\b|\bdeveloper\s+message\b",
    r"<\|\s*[a-z_]+\s*\|>",
    r"\[/?INST\]|<</?SYS>>",
    # Prompt-template headers. NOT `## User...` or `## Instructions`: a brief may well have those.
    r"^\s*#{2,}\s*(system|assistant|developer)\s*(:|$)|^\s*#{2,}\s*instruction\s*:",
    r"^\s*(system|assistant|developer)\s*:\s*\S",
    r"\b(do\s+not|don'?t|never)\s+(tell|inform|reveal|mention|show|disclose)\b.{0,20}\b(user|human|operator)\b",
    r"\bwithout\s+(telling|informing|notifying|alerting)\s+(the\s+)?(user|human|operator)\b",
    # Aimed at ANCHOR'S models. Deliberately not "the agent must": a policy governs an agent, and
    # "the agent must verify identity first" is how half the requirements in this domain are said.
    r"\b(the|this)\s+(ai|assistant|model|llm|reviewer|drafter|checker|anchor)\s+"
    r"(must|should|shall|needs\s+to|is\s+required\s+to)\b",
    r"\b(send|post|upload|exfiltrate|forward|email|leak)\b.{0,40}(https?://|\b[\w.+-]+@[\w-]+\.[\w.]+)",
    r"\b(call|invoke|use|run|execute)\s+the\s+[\w-]+\s+tool\b",
    r"\b(begin|end)\s+(of\s+)?(system|instructions?|prompt)\b",
    r"\b(mark|report|treat|classify)\s+(this|the)\s+(policy|rule|claim|finding)s?\s+as\s+"
    r"(safe|correct|valid|passing|compliant|clean)\b",
]
PHRASE = [re.compile(p, re.I | re.M) for p in PHRASES]

# Markup that would do something if it reached a page. `<` alone is ordinary in both languages
# (`a < b`, TLA+ `<<1, 2>>`); it has to be followed by a tag name to count.
MARKUP = [
    (re.compile(r"<\s*/?\s*(script|iframe|frame|frameset|object|embed|applet|svg|math|style|link|"
                r"meta|base|form|input|textarea|button|img|image|video|audio|source|template|"
                r"noscript|portal)\b", re.I), "an HTML tag that loads or runs something"),
    (re.compile(r"\bon[a-z]{3,}\s*=", re.I), "an HTML event-handler attribute, which runs script"),
    (re.compile(r"\b(javascript|vbscript|livescript)\s*:", re.I), "a script URL scheme"),
    (re.compile(r"\bdata\s*:\s*(text/html|image/svg\+xml|application/(x-)?(java|ecma)script)",
                re.I), "a data: URL that a browser would render as a document or run"),
    (re.compile(r"\bsrcdoc\s*=", re.I), "an iframe srcdoc attribute, which renders its value"),
    (re.compile(r"&(lt|#0*60|#x0*3c);?\s*/?\s*(script|iframe|img|svg)", re.I),
     "ENCODED markup, which becomes live wherever something decodes entities"),
]

REMOTE_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*<?\s*https?://", re.I)

# Lookalikes folded to Latin before matching phrases, so `ignоre` with a Cyrillic `о` is still
# `ignore`. Not exhaustive -- the letters that pass for Latin in most fonts.
SKELETON = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l", "ɡ": "g", "ν": "v", "ο": "o",
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z",
    "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y",
    "Χ": "X"})


def skeleton(line: str) -> str:
    """A line as its look-alike Latin: compatibility-folded, invisibles dropped, homoglyphs mapped.

    Evading a phrase list is cheap -- a zero-width space between two letters, a Cyrillic `о`, a
    fullwidth `＜` -- so the patterns are matched against what the line LOOKS like, not its bytes.
    """
    folded = unicodedata.normalize("NFKC", line)
    kept = "".join(ch for ch in folded
                   if not (classify(ord(ch)) and classify(ord(ch))[0] in ("invisible", "tag-block"))
                   and not is_selector(ord(ch)))
    return kept.translate(SKELETON)


# ---------------------------------------------------------------------------- encoded blobs ---

BLOB = [
    ("base64", re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}")),
    ("hex", re.compile(r"\b(?:[0-9a-fA-F]{2}){16,}\b")),
    ("percent-encoding", re.compile(r"(?:%[0-9a-fA-F]{2}){6,}")),
]


def decoded(kind: str, s: str) -> str | None:
    """The blob as text, if it decodes to something readable; None for bytes or garbage.

    Only READABLE decodings are worth a finding. A hash or a key is a long blob that decodes to
    noise, and flagging every one would teach people to ignore the scanner.
    """
    try:
        if kind == "hex":
            raw = bytes.fromhex(s)
        elif kind == "percent-encoding":
            raw = unquote_to_bytes(s)
        else:
            if re.fullmatch(r"[0-9a-fA-F]+", s):
                return None                      # all hex: that is the hex check's business
            t = s.replace("-", "+").replace("_", "/")
            raw = base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
        text = raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if len(text) < 12:
        return None
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in text)
    return text if printable / len(text) >= 0.9 else None


# ---------------------------------------------------------------------------------- findings ---

@dataclass
class Hit:
    path: str
    line: int
    col: int
    where: str          # code | comment | string | text
    kind: str
    severity: str
    what: str
    snippet: str


@dataclass
class Report:
    files: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    census: Counter = field(default_factory=Counter)
    unreadable: list[str] = field(default_factory=list)

    @property
    def high(self) -> list[Hit]:
        return [h for h in self.hits if h.severity == HIGH]

    @property
    def medium(self) -> list[Hit]:
        return [h for h in self.hits if h.severity == MEDIUM]

    def summary(self) -> str:
        if not self.files:
            return "no inputs scanned"
        n = len(self.files)
        if not self.high and not self.medium:
            return f"{n} input file{'s' if n != 1 else ''} scanned: clean"
        return (f"{n} input file{'s' if n != 1 else ''} scanned: {len(self.high)} high, "
                f"{len(self.medium)} medium")

    def as_dict(self) -> dict:
        return {"files": self.files, "unreadable": self.unreadable, "summary": self.summary(),
                "high": len(self.high), "medium": len(self.medium),
                "hits": [asdict(h) for h in self.hits],
                "census": {f"U+{cp:04X}": n for cp, n in self.census.most_common()}}


def scan_text(text: str, path: str, lang: str = "text") -> tuple[list[Hit], Counter]:
    """Every finding in `text`, and the census of the non-ASCII it holds that is not a finding."""
    hits: list[Hit] = []
    census: Counter = Counter()
    where = contexts(text, lang)
    lines = text.split("\n")
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    def pos(offset: int) -> tuple[int, int]:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - starts[lo] + 1

    def hit(offset: int, kind: str, severity: str, what: str) -> None:
        line, col = pos(offset)
        ctx = where[min(offset, len(where) - 1)] if where else "text"
        hits.append(Hit(path, line, col, ctx, kind, severity, what, shown(lines[line - 1])))

    # 1. Codepoints, with runs of the same kind reported once -- a run is how data is encoded.
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        c = classify(cp)
        if c and not (cp == 0xFEFF and i == 0):          # a leading BOM is ordinary
            j = i + 1
            while j < n and classify(ord(text[j])) and classify(ord(text[j]))[0] == c[0]:
                j += 1
            run = j - i
            name = unicodedata.name(text[i], f"U+{cp:04X}")
            detail = f"U+{cp:04X} {name}" + (f", {run} in a row" if run > 1 else "")
            hit(i, c[0], c[1], f"{detail}: {c[2]}")
            i = j
            continue
        if is_selector(cp):
            j = i + 1
            while j < n and is_selector(ord(text[j])):
                j += 1
            ctx = where[i] if where else "text"
            if j - i > 1 or ctx in ("code", "string"):
                hit(i, "variation-selector", HIGH,
                    f"{j - i} variation selector(s) {'in a name' if ctx != 'comment' else 'in a row'}"
                    f": one after an emoji is ordinary, a run is a known way to hide data")
            i = j
            continue
        if cp > 0x7F and cp != 0xFFFD:
            census[cp] += 1
        i += 1

    # 2. Names that are not what they look like. In code and string literals only: prose in a
    # comment is allowed to be in any language, a name that decides what a rule matches is not.
    if lang in ("dw", "tla"):
        for m in re.finditer(r"\w+", text):
            tok = m.group()
            ctx = where[m.start()]
            if ctx not in ("code", "string") or tok.isascii():
                continue
            scripts = {script_of(ch) for ch in tok if ch.isalpha()}
            if len(scripts) > 1:
                hit(m.start(), "mixed-script", HIGH,
                    f"'{shown(tok, 40)}' mixes {', '.join(sorted(scripts))} letters -- it looks "
                    f"like one name and matches another, because names are compared byte for byte")
            elif ctx == "code":
                hit(m.start(), "non-ascii-name", MEDIUM,
                    f"'{shown(tok, 40)}' is a name with non-ASCII letters, which a reader may not "
                    f"be able to tell from an ASCII one")

        # 3. Escapes inside string literals: the file is clean ASCII, the VALUE is not.
        for m in re.finditer(r"\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})"
                             r"|\\x([0-9a-fA-F]{2})", text):
            if where[m.start()] != "string":
                continue
            cp = int(next(g for g in m.groups() if g), 16)
            c = classify(cp) or (("variation-selector", HIGH, "a variation selector")
                                 if is_selector(cp) else None)
            if c:
                hit(m.start(), c[0], c[1],
                    f"{m.group()} WRITTEN AS AN ESCAPE -- the file looks clean and the string's "
                    f"value holds U+{cp:04X}: {c[2]}")

    # 4. Phrases and markup, against what each line LOOKS like -- and only where prose can be.
    #
    # NOT IN CODE. An instruction to a model is prose, and the only places prose fits in a policy
    # or a module are comments and string literals; English in code does not parse, and a name
    # like `ignore_previous_instructions` has no word breaks for a phrase to match. Code is also
    # where the grammar's own words live: `system: SystemContext` is a field of every AgentCore
    # request, not a chat role. So a match whose start sits in code is skipped, and the first
    # match that does not is the one reported -- a comment trailing code on the same line counts.
    def first_prose(rx: re.Pattern, look: str, raw: str, offset: int) -> tuple[int, str] | None:
        for m in rx.finditer(look):
            at = offset + min(m.start(), max(len(raw) - 1, 0))
            if lang == "text" or not where or where[at] != "code":
                return at, m.group()
        return None

    for k, raw in enumerate(lines):
        if not raw.strip():
            continue
        look = skeleton(raw)
        offset = starts[k]
        for rx in PHRASE:
            found = first_prose(rx, look, raw, offset)
            if found:
                hit(found[0], "prompt-injection", HIGH,
                    f"reads as an instruction to a model: '{shown(found[1], 60)}'")
                break
        for rx, what in MARKUP:
            found = first_prose(rx, look, raw, offset)
            if found:
                hit(found[0], "markup", HIGH, f"{what}: '{shown(found[1], 60)}'")
                break
        m = REMOTE_IMAGE.search(raw)
        if m:
            hit(offset + m.start(), "remote-image", MEDIUM,
                "a remote image, fetched when the markdown is rendered -- which tells its host "
                "who read it and when")

    # 5. Encoded blobs that decode to text, rescanned for what that text says.
    seen: set[int] = set()
    for kind, rx in BLOB:
        for m in rx.finditer(text):
            if m.start() in seen or (where and where[m.start()] == "code"):
                continue
            plain = decoded(kind, m.group())
            if plain is None:
                continue
            seen.add(m.start())
            look = skeleton(plain)
            payload = next((p for p in PHRASE if p.search(look)), None) or \
                next((r for r, _ in MARKUP if r.search(look)), None)
            hit(m.start(), "encoded-text", HIGH if payload else MEDIUM,
                f"a {kind} blob that decodes to readable text"
                + (" CARRYING AN INSTRUCTION OR MARKUP" if payload else "")
                + f": '{shown(plain, 70)}'")

    # One finding per kind per line. Four ESCs in one hyperlink sequence are one attack, and a
    # report that says so four times teaches its reader to skim.
    hits.sort(key=lambda h: (h.line, h.col))
    folded: dict[tuple[int, str], Hit] = {}
    extra: Counter = Counter()
    for h in hits:
        key = (h.line, h.kind)
        if key in folded:
            extra[key] += 1
        else:
            folded[key] = h
    for key, more in extra.items():
        folded[key].what += f" (and {more} more like it on this line)"
    return list(folded.values()), census


def scan_file(path: Path, report: Report, shown_as: str | None = None) -> None:
    label = shown_as or path.as_posix()
    try:
        raw = path.read_bytes()
    except OSError as e:
        report.unreadable.append(f"{label}: {e}")
        return
    report.files.append(label)
    if b"\x00" in raw:
        report.hits.append(Hit(label, 1, 1, "text", "binary", HIGH,
                               "contains NUL bytes: not a text file, and not something a policy "
                               "input should be", ""))
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        report.hits.append(Hit(label, 1, 1, "text", "not-utf8", MEDIUM,
                               f"not well-formed UTF-8 ({e.reason} at byte {e.start}); read with "
                               f"replacement characters, so what is shown may not be what is there",
                               ""))
        text = raw.decode("utf-8", errors="replace")
    hits, census = scan_text(text, label, LANG.get(path.suffix.lower(), "text"))
    report.hits.extend(hits)
    report.census.update(census)


def inputs_of(directory: Path) -> list[Path]:
    """What a check reads from a policy directory: its policies, modules, schemas and briefs."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and (p.suffix.lower() in INPUT_SUFFIXES or p.name in INPUT_NAMES))


def scan(paths: list[Path], texts: dict[str, str] | None = None, *,
         relative_to: Path | None = None, everything: bool = False) -> Report:
    """Scan files, directories (their inputs, or every text file with `everything`), and strings.

    `texts` is for input that never touched disk -- an `--intent` typed on the command line is
    handed to a model exactly as a file would be, so it is scanned exactly as one.
    """
    report = Report()
    seen: set[Path] = set()                  # a directory and its intents.md, named separately
    for p in paths:
        if p is None:
            continue
        if p.is_dir():
            files = (sorted(q for q in p.rglob("*") if q.is_file()) if everything
                     else inputs_of(p))
        else:
            files = [p] if p.exists() else []
        for f in files:
            if f.resolve() in seen:
                continue
            seen.add(f.resolve())
            label = f.as_posix()
            if relative_to is not None:
                try:
                    label = f.resolve().relative_to(relative_to.resolve()).as_posix()
                except ValueError:
                    pass
            scan_file(f, report, label)
    for name, text in (texts or {}).items():
        if text:
            report.files.append(name)
            hits, census = scan_text(text, name, "text")
            report.hits.extend(hits)
            report.census.update(census)
    return report


# ------------------------------------------------------------------------------------ output ---

def render(report: Report, *, census: bool = True) -> str:
    out = [f"anchor scan: {report.summary()}"]
    for u in report.unreadable:
        out.append(f"  could not read {u}")
    for path in dict.fromkeys(h.path for h in report.hits):
        out.append(f"\n  {path}")
        for h in (x for x in report.hits if x.path == path):
            out.append(f"    {h.severity.upper():<6} line {h.line}, col {h.col}, in {h.where}: "
                       f"{h.kind}")
            out.append(f"           {h.what}")
            if h.snippet:
                out.append(f"           | {h.snippet}")
    if census and report.census:
        common = ", ".join(f"U+{cp:04X} {shown(chr(cp))} x{n}"
                           for cp, n in report.census.most_common(12))
        out.append(f"\n  other non-ASCII, not findings (for a person to judge): {common}")
    return "\n".join(out)


def gate(report: Report, *, allow: bool, who: str) -> int | None:
    """Print the scan, and refuse -- return 2, no verdict -- if a high finding would reach `who`.

    None means carry on. Called BEFORE anything is shown to a model, so a refusal costs nothing.
    """
    if not report.high:
        if report.medium:
            print(render(report, census=False) + "\n", file=sys.stderr)
        return None
    print(render(report, census=False), file=sys.stderr)
    if allow:
        print(f"\n--allow-flagged-input: showing these inputs to {who} anyway. The report will "
              f"say so.\n", file=sys.stderr)
        return None
    print(f"\nRefusing to show these inputs to {who}: {len(report.high)} high-severity finding(s) "
          f"above. Read them first; if they are benign -- a comment that discusses prompt "
          f"injection, say -- run again with --allow-flagged-input.", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(prog=os.environ.get("ANCHOR_VERB") or None,
                                 description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path,
                    help="policy files, or directories -- whose inputs are scanned")
    ap.add_argument("--all", action="store_true",
                    help="for a directory, every text file under it rather than just the inputs "
                         "a check reads -- for vetting third-party material")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    args = ap.parse_args()

    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    report = scan(args.paths, everything=args.all)
    print(json.dumps(report.as_dict(), indent=2) if args.json else render(report))
    if not report.files:
        return 3
    return 1 if (report.high or report.medium) else 0


if __name__ == "__main__":
    raise SystemExit(main())
