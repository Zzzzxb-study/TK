import zipfile
from xml.etree import ElementTree as ET
from django.utils.html import escape

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _paragraph_html(paragraph):
    parts = []
    for node in paragraph.iter():
        if node.tag == W + 't' and node.text:
            parts.append(escape(node.text))
        elif node.tag == W + 'tab':
            parts.append('&emsp;')
        elif node.tag == W + 'br':
            parts.append('<br>')
    return ''.join(parts).strip()


def docx_to_html(path):
    """Render safe, text-first DOCX preview HTML without exposing the source file."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    body = root.find('.//' + W + 'body')
    if body is None:
        return '<p class="preview-empty">文档没有可预览的正文。</p>'
    blocks = []
    for child in body:
        if child.tag == W + 'p':
            text = _paragraph_html(child)
            if text:
                blocks.append(f'<p>{text}</p>')
        elif child.tag == W + 'tbl':
            rows = []
            for row in child.findall('./' + W + 'tr'):
                cells = []
                for cell in row.findall('./' + W + 'tc'):
                    cell_parts = []
                    for paragraph in cell.findall('.//' + W + 'p'):
                        value = _paragraph_html(paragraph)
                        if value:
                            cell_parts.append(value)
                    cells.append('<td>' + '<br>'.join(cell_parts) + '</td>')
                if cells:
                    rows.append('<tr>' + ''.join(cells) + '</tr>')
            if rows:
                blocks.append('<table class="preview-table"><tbody>' + ''.join(rows) + '</tbody></table>')
    return ''.join(blocks) or '<p class="preview-empty">文档没有可预览的正文。</p>'