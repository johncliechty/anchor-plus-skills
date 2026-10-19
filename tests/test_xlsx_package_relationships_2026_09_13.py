"""Synthetic workbook regressions; contains no personal campaign material."""
import io
import zipfile
from xml.sax.saxutils import escape, quoteattr
import pytest
import office_preview as op

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def workbook(entries):
    """entries: (label, target, member, text, external)."""
    out = io.BytesIO()
    sheets, rels = [], []
    with zipfile.ZipFile(out, 'w') as archive:
        for n, (name, target, member, text, external) in enumerate(entries, 1):
            sheets.append(f'<sheet name={quoteattr(name)} sheetId="{n}" r:id="rId{n}"/>')
            if target is not None:
                mode = ' TargetMode="External"' if external else ''
                rels.append(f'<Relationship Id="rId{n}" Target={quoteattr(target)}{mode}/>')
            if member:
                xml = (f'<worksheet xmlns="{S}"><sheetData><row r="1"><c r="A1" t="inlineStr">'
                       f'<is><t>{escape(text)}</t></is></c></row></sheetData></worksheet>')
                archive.writestr(member, xml)
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{"".join(sheets)}</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{REL}">{"".join(rels)}</Relationships>')
    return out.getvalue()


def test_eight_package_root_sheets_render_without_loss():
    data = workbook([(f'Sheet {n}', f'/xl/worksheets/sheet{n}.xml', f'xl/worksheets/sheet{n}.xml', f'Cell {n}', False) for n in range(1, 9)])
    sheets = op.xlsx_sheets(data)
    assert [s['name'] for s in sheets] == [f'Sheet {n}' for n in range(1, 9)]
    assert [s['rows'] for s in sheets] == [[[f'Cell {n}']] for n in range(1, 9)]
    page = op.render_preview(data, 'Example.xlsx', '/download')
    assert page.count("<section class='sheet'>") == 8
    assert '(no sheets found)' not in page
    assert 'href="/download"' in page


@pytest.mark.parametrize('target,member', [
    ('worksheets/sheet1.xml', 'xl/worksheets/sheet1.xml'),
    ('/xl/worksheets/sheet1.xml', 'xl/worksheets/sheet1.xml'),
    ('worksheets/../worksheets/./sheet1.xml', 'xl/worksheets/sheet1.xml'),
    ('../shared.xml', 'shared.xml'),
    ('worksheets/sheet%201.xml', 'xl/worksheets/sheet%201.xml'),
    ('xl/worksheets/sheet1.xml', 'xl/worksheets/sheet1.xml'),
])
def test_supported_internal_targets(target, member):
    data = workbook([('One', target, member, 'preserved', False)])
    assert op.xlsx_sheets(data)[0]['rows'] == [['preserved']]


@pytest.mark.parametrize('target,external', [
    (None, False), ('worksheets/missing.xml', False), ('../../outside.xml', False),
    ('https://example.invalid/worksheet.xml', False), ('worksheets/one.xml', True),
])
def test_unreadable_sheet_is_visible_and_good_neighbor_survives(target, external):
    data = workbook([('<unreadable>', target, None, '', external),
                     ('Good', '/xl/worksheets/good.xml', 'xl/worksheets/good.xml', '<script>visible</script>', False)])
    sheets = op.xlsx_sheets(data)
    assert len(sheets) == 2 and sheets[0]['error']
    assert sheets[1]['rows'] == [['<script>visible</script>']]
    page = op.render_preview(data, 'Example.xlsx', '/download')
    assert 'This worksheet could not be read.' in page
    assert '&lt;unreadable&gt;' in page and '&lt;script&gt;visible&lt;/script&gt;' in page
    assert '<script>visible</script>' not in page
