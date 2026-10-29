"""Shared minimal Markdown-to-HTML renderer for Foundry display bundles.

Covers exactly what the frozen skill sources use — headings, lists, emphasis,
inline code, links, blockquotes, rules, paragraphs. Input is escaped first, so
the output carries no live HTML from the source document.
"""
import html
import re


def _inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])', r'<em>\1</em>', text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<a href="\2" rel="noopener">\1</a>', text)
    return text


def to_html(markdown_text, heading_offset=0):
    out, paragraph, list_tag = [], [], None

    def close_paragraph():
        if paragraph:
            out.append('<p>' + ' '.join(paragraph) + '</p>')
            paragraph.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f'</{list_tag}>')
            list_tag = None

    def open_list(tag):
        nonlocal list_tag
        if list_tag != tag:
            close_list()
            out.append(f'<{tag}>')
            list_tag = tag

    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        heading = re.match(r'(#{1,4})\s+(.*)', stripped)
        bullet = re.match(r'[-*]\s+(.*)', stripped)
        ordered = re.match(r'\d+[.)]\s+(.*)', stripped)
        if not stripped:
            close_paragraph()
            close_list()
        elif heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1)) + heading_offset
            out.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
        elif re.fullmatch(r'(-{3,}|\*{3,})', stripped):
            close_paragraph()
            close_list()
            out.append('<hr>')
        elif bullet:
            close_paragraph()
            open_list('ul')
            out.append(f'<li>{_inline(bullet.group(1))}</li>')
        elif ordered:
            close_paragraph()
            open_list('ol')
            out.append(f'<li>{_inline(ordered.group(1))}</li>')
        elif stripped.startswith('>'):
            close_paragraph()
            close_list()
            out.append(f'<blockquote>{_inline(stripped.lstrip("> "))}</blockquote>')
        else:
            if list_tag and raw.startswith(('  ', '\t')) and out and out[-1].endswith('</li>'):
                out[-1] = out[-1][:-len('</li>')] + ' ' + _inline(stripped) + '</li>'
            else:
                close_list()
                paragraph.append(_inline(stripped))
    close_paragraph()
    close_list()
    return '\n'.join(out)
