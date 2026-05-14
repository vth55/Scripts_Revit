# -*- coding: utf-8 -*-
"""Excel and CSV reading helpers for IronPython/pyRevit."""
import os
import csv
import codecs
import zipfile
import xml.etree.ElementTree as ET

import clr
clr.AddReference("System")
from System import Type, Activator
from System.Runtime.InteropServices import Marshal


EXCEL_EXTENSIONS = ('.xlsx', '.xls', '.xlsm', '.xlsb')
OPENXML_EXTENSIONS = ('.xlsx', '.xlsm')
NS_MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
NS_REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
NS_PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'


def _release_com(obj):
    try:
        if obj is not None:
            Marshal.FinalReleaseComObject(obj)
    except Exception:
        pass


def _cell_to_text(value):
    if value is None:
        return u''
    try:
        return unicode(value)
    except Exception:
        try:
            return str(value)
        except Exception:
            return u''


def _col_ref_to_index(cell_ref):
    letters = []
    for ch in cell_ref or '':
        if ch.isalpha():
            letters.append(ch.upper())
        else:
            break
    if not letters:
        return 0
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def _open_xml_workbook(path):
    return zipfile.ZipFile(path, 'r')


def _xml_text(node):
    if node is None:
        return u''
    return u''.join(node.itertext()) if hasattr(node, 'itertext') else (node.text or u'')


def _load_shared_strings(zf):
    names = (
        'xl/sharedStrings.xml',
    )
    for name in names:
        if name not in zf.namelist():
            continue
        root = ET.fromstring(zf.read(name))
        values = []
        for si in root.findall(NS_MAIN + 'si'):
            values.append(_xml_text(si))
        return values
    return []


def _workbook_sheet_map(zf):
    wb_root = ET.fromstring(zf.read('xl/workbook.xml'))
    rel_root = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    rels = {}
    for rel in rel_root.findall(NS_PKG_REL + 'Relationship'):
        rel_id = rel.attrib.get('Id')
        target = rel.attrib.get('Target', '')
        if rel_id:
            if not target.startswith('xl/'):
                target = 'xl/' + target.lstrip('/')
            rels[rel_id] = target
    sheets = []
    for sheet in wb_root.find(NS_MAIN + 'sheets').findall(NS_MAIN + 'sheet'):
        name = _cell_to_text(sheet.attrib.get('name'))
        rel_id = sheet.attrib.get(NS_REL + 'id')
        target = rels.get(rel_id)
        if name and target:
            sheets.append((name, target))
    return sheets


def _read_openxml_sheet(path, sheet_name=None):
    zf = _open_xml_workbook(path)
    try:
        sheets = _workbook_sheet_map(zf)
        if not sheets:
            return []
        target = None
        if sheet_name:
            for name, rel_target in sheets:
                if name == sheet_name:
                    target = rel_target
                    break
        if target is None:
            target = sheets[0][1]
        root = ET.fromstring(zf.read(target))
        shared = _load_shared_strings(zf)
        data = root.find(NS_MAIN + 'sheetData')
        if data is None:
            return []
        rows = []
        max_cols = 0
        current_row_number = 0
        for row_node in data.findall(NS_MAIN + 'row'):
            try:
                row_number = int(row_node.attrib.get('r', '0'))
            except Exception:
                row_number = 0
            if row_number <= 0:
                row_number = current_row_number + 1
            while current_row_number + 1 < row_number:
                rows.append({})
                current_row_number += 1
            row_map = {}
            for cell in row_node.findall(NS_MAIN + 'c'):
                ref = cell.attrib.get('r', '')
                col_idx = _col_ref_to_index(ref)
                ctype = cell.attrib.get('t', '')
                value = u''
                if ctype == 'inlineStr':
                    value = _xml_text(cell.find(NS_MAIN + 'is'))
                else:
                    v = cell.find(NS_MAIN + 'v')
                    raw = _xml_text(v)
                    if ctype == 's':
                        try:
                            sidx = int(raw)
                            value = shared[sidx] if 0 <= sidx < len(shared) else u''
                        except Exception:
                            value = u''
                    elif ctype == 'b':
                        value = u'TRUE' if raw == '1' else u'FALSE'
                    else:
                        value = raw
                row_map[col_idx] = _cell_to_text(value)
                if col_idx + 1 > max_cols:
                    max_cols = col_idx + 1
            rows.append(row_map)
            current_row_number = row_number
        normalized = []
        width = max_cols or 1
        for row_map in rows:
            normalized.append([row_map.get(i, u'') for i in range(width)])
        return normalized
    finally:
        zf.close()


def _read_csv(path):
    encodings = ('utf-8-sig', 'cp1252', 'latin-1')
    last_err = None
    for enc in encodings:
        try:
            with codecs.open(path, 'r', enc) as fp:
                sample = fp.read(4096)
                fp.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=';,|\t,')
                except Exception:
                    dialect = csv.excel
                    dialect.delimiter = ';' if sample.count(';') >= sample.count(',') else ','
                rows = []
                for row in csv.reader(fp, dialect):
                    rows.append([_cell_to_text(c) for c in row])
                return rows
        except Exception as err:
            last_err = err
    if last_err:
        raise last_err
    return []


def _open_excel(path):
    app = None
    workbooks = None
    workbook = None
    try:
        try:
            clr.AddReference("Microsoft.Office.Interop.Excel")
            from Microsoft.Office.Interop import Excel
            app = Excel.ApplicationClass()
        except Exception:
            excel_type = Type.GetTypeFromProgID("Excel.Application")
            if excel_type is None:
                raise Exception("Microsoft Excel nao esta disponivel.")
            app = Activator.CreateInstance(excel_type)
        app.Visible = False
        app.DisplayAlerts = False
        workbooks = app.Workbooks
        workbook = workbooks.Open(path, False, True)
        return app, workbooks, workbook
    except Exception:
        _release_com(workbook)
        _release_com(workbooks)
        _release_com(app)
        raise


def list_sheets(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXCEL_EXTENSIONS:
        return []
    if ext in OPENXML_EXTENSIONS:
        try:
            zf = _open_xml_workbook(path)
            try:
                return [name for name, _ in _workbook_sheet_map(zf)]
            finally:
                zf.close()
        except Exception:
            pass
    app = workbooks = workbook = None
    sheets = None
    names = []
    try:
        app, workbooks, workbook = _open_excel(path)
        sheets = workbook.Worksheets
        count = sheets.Count
        for i in range(1, count + 1):
            sheet = None
            try:
                sheet = sheets.Item[i]
                names.append(_cell_to_text(sheet.Name))
            finally:
                _release_com(sheet)
        return names
    finally:
        try:
            if workbook is not None:
                workbook.Close(False)
        except Exception:
            pass
        _release_com(sheets)
        _release_com(workbook)
        _release_com(workbooks)
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        _release_com(app)


def _read_excel_sheet(path, sheet_name=None):
    app = workbooks = workbook = worksheet = used_range = values = None
    try:
        app, workbooks, workbook = _open_excel(path)
        if sheet_name:
            worksheet = workbook.Worksheets[sheet_name]
        else:
            worksheet = workbook.Worksheets.Item[1]
        used_range = worksheet.UsedRange
        rows = []
        row_count = int(used_range.Rows.Count or 0)
        col_count = int(used_range.Columns.Count or 0)
        if row_count <= 0 or col_count <= 0:
            return rows

        try:
            values = used_range.Value2
        except Exception:
            values = None

        if values is None:
            for r in range(1, row_count + 1):
                row = []
                for c in range(1, col_count + 1):
                    try:
                        row.append(_cell_to_text(used_range.Cells.Item(r, c).Value2))
                    except Exception:
                        row.append(u'')
                rows.append(row)
            return rows

        try:
            row_count = values.GetLength(0)
            col_count = values.GetLength(1)
            for r in range(1, row_count + 1):
                row = []
                for c in range(1, col_count + 1):
                    row.append(_cell_to_text(values[r, c]))
                rows.append(row)
            return rows
        except Exception:
            try:
                for r in range(1, row_count + 1):
                    row = []
                    for c in range(1, col_count + 1):
                        try:
                            row.append(_cell_to_text(used_range.Cells.Item(r, c).Value2))
                        except Exception:
                            row.append(u'')
                    rows.append(row)
                return rows
            except Exception:
                return [[_cell_to_text(values)]]
    finally:
        try:
            if workbook is not None:
                workbook.Close(False)
        except Exception:
            pass
        _release_com(values)
        _release_com(used_range)
        _release_com(worksheet)
        _release_com(workbook)
        _release_com(workbooks)
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        _release_com(app)


def read_file(path, sheet_name=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in OPENXML_EXTENSIONS:
        try:
            return _read_openxml_sheet(path, sheet_name)
        except Exception:
            pass
    if ext in EXCEL_EXTENSIONS:
        return _read_excel_sheet(path, sheet_name)
    return _read_csv(path)
