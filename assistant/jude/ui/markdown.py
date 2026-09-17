"""Markdown → the HTML subset Qt's rich text understands.

Jude answers in markdown — headings, bold, bullet lists, the odd code span —
and the web UI renders it, so a Mac window that prints the asterisks is
noticeably worse at reading the same answer. There is no markdown library in
this project's environment and adding one for six constructs would be a new
dependency on a machine that deliberately has few, so this is a small renderer
for exactly what Jude emits.

Two things it is careful about:

- **It escapes before it formats.** A source quoted inside an answer can
  contain `<` or `&`, and Qt would otherwise eat it as markup.
- **It tolerates half-written input.** It runs on a partial answer every ~70ms
  while tokens arrive, so an unclosed `**` must render as text rather than
  swallow the rest of the paragraph; the next repaint fixes it by itself.
"""

from __future__ import annotations

import re

_CODE_SLOT = "\x00c{}\x00"       # a byte the model cannot emit, so never a collision

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_SECTION = re.compile(r"^\*\*([^*]+)\*\*:?$")          # **Title** alone on a line
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC = re.compile(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])")
# A citation as Jude writes them: [Shabbat 3:1], [Genesis 1:1a]. Deliberately
# narrow — a bracketed aside in prose is not a source and must stay plain.
_CITE = re.compile(r"\[([^\]\n]+[\s:][\d:ab]+)\]")

_HEADING_PX = {1: 16.5, 2: 15.0, 3: 14.0, 4: 13.5, 5: 13.0, 6: 13.0}


def escape(text: str) -> str:
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(text: str, theme) -> str:
    codes: list[str] = []

    def stash(match: "re.Match") -> str:
        codes.append(match.group(1))
        return _CODE_SLOT.format(len(codes) - 1)

    # Code first and links second: whatever is inside a code span is literal,
    # and a URL is full of characters the emphasis rules would otherwise chew.
    out = _CODE_SPAN.sub(stash, escape(text))
    out = _LINK.sub(
        lambda m: f"<a href='{m.group(2)}' style='color:{theme.accent};'>{m.group(1)}</a>",
        out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    out = _CITE.sub(
        lambda m: f"<span style='color:{theme.accent};'>[{m.group(1)}]</span>", out)
    for index, code in enumerate(codes):
        out = out.replace(
            _CODE_SLOT.format(index),
            # Single quotes around the style: MONO_FONT itself contains double
            # quotes ("SF Mono"), which would close the attribute early and
            # spill raw CSS into the rendered answer.
            f"<code style='font-family:{theme.mono}; color:{theme.text};'>{code}</code>")
    return out


def render(text: str, theme) -> str:
    """One answer as Qt rich text. Called once per repaint, never per token."""
    lines = str(text or "").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_tag: "str | None" = None
    fence: "list[str] | None" = None

    def close_paragraph() -> None:
        if paragraph:
            out.append("<p style='margin:4px 0;'>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def open_list(tag: str) -> None:
        nonlocal list_tag
        if list_tag != tag:
            close_list()
            out.append(f"<{tag} style='margin:2px 0 2px 14px;'>")
            list_tag = tag

    for line in lines:
        if line.strip().startswith("```"):
            if fence is None:
                close_paragraph()
                close_list()
                fence = []
            else:
                body = escape("\n".join(fence))
                out.append(
                    f"<pre style='font-family:{theme.mono}; background:{theme.surface};"
                    f" color:{theme.text};'>{body}</pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue

        if not line.strip():
            close_paragraph()
            close_list()
            continue

        heading = _HEADING.match(line)
        section = _SECTION.match(line.strip())
        if heading or section:
            close_paragraph()
            close_list()
            level = len(heading.group(1)) if heading else 2
            body = _inline(heading.group(2) if heading else section.group(1), theme)
            out.append(
                f"<div style='margin:9px 0 2px; font-weight:700;"
                f" font-size:{_HEADING_PX[level]}px; color:{theme.accent};'>{body}</div>")
            continue

        bullet = _BULLET.match(line)
        if bullet:
            close_paragraph()
            open_list("ul")
            out.append(f"<li>{_inline(bullet.group(1), theme)}</li>")
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            close_paragraph()
            open_list("ol")
            out.append(f"<li>{_inline(numbered.group(2), theme)}</li>")
            continue

        close_list()
        paragraph.append(_inline(line, theme))

    if fence is not None:                 # a code block still being streamed
        paragraph.extend(escape(l) for l in fence)
    close_paragraph()
    close_list()
    return "".join(out)
