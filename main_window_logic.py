# -*- coding: utf-8 -*-
"""Central WPF workflow for MTQ Filter Manager."""
import clr, os, json

clr.AddReference("RevitAPI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

import System
from System.Collections.Generic import List
from System.Windows import MessageBox, MessageBoxButton, MessageBoxResult, Point, Rect, Visibility
from System.Windows.Media import (
    Brushes, SolidColorBrush, DrawingBrush, GeometryDrawing, GeometryGroup,
    LineGeometry, Pen, TileMode, VisualTreeHelper
)
from System.Windows.Media import Color as WpfColor
from System.Windows.Input import Key
from Autodesk.Revit.DB import (
    BuiltInParameter, Category, ElementId, ElementParameterFilter,
    FilteredElementCollector, FillPatternElement, LabelUtils,
    OverrideGraphicSettings, ParameterFilterElement, ParameterFilterRuleFactory,
    ParameterFilterUtilities
)
from pyrevit import revit, forms

import revit_query, filters_core, colors_core
import palette_helpers as ph
reload(ph)

try:
    import excel_io
except ImportError:
    excel_io = None
else:
    reload(excel_io)

try:
    import scheme_helpers
except ImportError:
    scheme_helpers = None
else:
    reload(scheme_helpers)


CAT_PH = u"pesquisar..."
VAL_PH = u"pesquisar..."
PATTERN_SOLID = u'<Solid fill>'
PATTERN_NONE = u'None'
APPLY_NONE = u'Nao aplicar'
APPLY_ACTIVE_VIEW = u'Vista ativa'
APPLY_ACTIVE_TEMPLATE = u'Template da vista ativa'


def _view_has_filter(view, filter_id):
    try:
        return filter_id in list(view.GetFilters())
    except Exception:
        return False


def _apply_filter_override(view, filter_id, override):
    try:
        if not _view_has_filter(view, filter_id):
            view.AddFilter(filter_id)
    except Exception as add_err:
        if not _view_has_filter(view, filter_id):
            return False, str(add_err)
    try:
        view.SetFilterOverrides(filter_id, override)
        return True, ''
    except Exception as set_err:
        return False, str(set_err)


def _get_filter_enabled(view, filter_id):
    try:
        return bool(view.GetIsFilterEnabled(filter_id))
    except Exception:
        return True


def _set_filter_enabled(view, filter_id, enabled):
    try:
        view.SetIsFilterEnabled(filter_id, bool(enabled))
        return True, ''
    except Exception as err:
        return False, str(err)


def _get_filter_visibility(view, filter_id):
    try:
        return bool(view.GetFilterVisibility(filter_id))
    except Exception:
        return True


def _set_filter_visibility(view, filter_id, visible):
    try:
        view.SetFilterVisibility(filter_id, bool(visible))
        return True, ''
    except Exception as err:
        return False, str(err)


def _color_mode(palette_radio, none_radio):
    if palette_radio.IsChecked:
        return 'palette'
    if none_radio.IsChecked:
        return 'none'
    return 'hsv'


def _filter_name(prefix, value, display_name):
    if value != display_name:
        return u"{}{} - {}".format(prefix, value, display_name)[:200]
    return u"{}{}".format(prefix, value)[:200]


def _normalize_search_text(text):
    text = (text or u'').lower()
    replacements = {
        u'á': u'a', u'à': u'a', u'â': u'a', u'ã': u'a', u'ä': u'a',
        u'é': u'e', u'è': u'e', u'ê': u'e', u'ë': u'e',
        u'í': u'i', u'ì': u'i', u'î': u'i', u'ï': u'i',
        u'ó': u'o', u'ò': u'o', u'ô': u'o', u'õ': u'o', u'ö': u'o',
        u'ú': u'u', u'ù': u'u', u'û': u'u', u'ü': u'u',
        u'ç': u'c',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for ch in [u'_', u'-', u'.', u'/', u'\\', u'(', u')', u'[', u']', u':', u';', u',']:
        text = text.replace(ch, u' ')
    return u' '.join(text.split())


def _fuzzy_match(query, text):
    query = _normalize_search_text(query)
    text = _normalize_search_text(text)
    if not query:
        return True
    tokens = query.split()
    return all(token in text for token in tokens)


def _project_filters_by_name(doc):
    result = {}
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        result[f.Name] = f
    return result


def _param_name_from_id(doc, param_id):
    try:
        int_val = param_id.IntegerValue
        if int_val < 0:
            return LabelUtils.GetLabelFor(BuiltInParameter(int_val))
        elem = doc.GetElement(param_id)
        if elem and hasattr(elem, 'GetDefinition'):
            return elem.GetDefinition().Name
    except Exception:
        pass
    return None


def _get_filterable_categories(doc):
    result = {}
    try:
        cat_ids = ParameterFilterUtilities.GetAllFilterableCategories()
        for cat_id in cat_ids:
            try:
                cat = Category.GetCategory(doc, cat_id)
                if cat and cat.Name:
                    result[cat.Name] = cat.Id
            except Exception:
                pass
    except Exception:
        result = revit_query.get_categories(doc)
    return result


def _get_strict_filterable_params(doc, cat_ids):
    result = {}
    if not cat_ids:
        return result
    try:
        param_ids = ParameterFilterUtilities.GetFilterableParametersInCommon(
            doc, List[ElementId](cat_ids))
    except Exception:
        return {}
    for pid in param_ids:
        name = _param_name_from_id(doc, pid)
        if name:
            result[name] = pid
    return result


def _get_all_params_with_categories_strict(doc, cat_map):
    result = {}
    for cat_name, cat_id in cat_map.items():
        for pname, pid in _get_strict_filterable_params(doc, [cat_id]).items():
            if pname not in result:
                result[pname] = [pid, []]
            result[pname][1].append(cat_id)
    return result


def _validate_override_view(view):
    if view is None:
        return True
    try:
        if hasattr(view, 'AreGraphicsOverridesAllowed') and not view.AreGraphicsOverridesAllowed():
            MessageBox.Show(
                u"O destino selecionado nao permite overrides graficos. Escolha outro destino ou mude de vista.",
                "Filter Manager")
            return False
    except Exception:
        pass
    return True


def _get_view_template(doc, view):
    try:
        template_id = view.ViewTemplateId
        if template_id and template_id != ElementId.InvalidElementId:
            return doc.GetElement(template_id)
    except Exception:
        pass
    return None


def _apply_named_filters_to_view(doc, view, filter_names, colors):
    if view is None or not filter_names:
        return 0, 0
    solid = ph.get_solid_fill_pattern_id(doc)
    by_name = _project_filters_by_name(doc)
    applied = 0
    failed = 0
    for i, name in enumerate(filter_names):
        f = by_name.get(name)
        if not f:
            failed += 1
            continue
        rgb = colors[i] if i < len(colors) else None
        pat_id = solid if rgb is not None else ElementId.InvalidElementId
        ov = ph.build_revit_override(rgb, solid, pat_id)
        ok, err = _apply_filter_override(view, f.Id, ov)
        if ok:
            applied += 1
        else:
            failed += 1
    return applied, failed


def _used_view_colors(doc, view):
    used = []
    if view is None:
        return used
    try:
        for fid in view.GetFilters():
            try:
                ogs = view.GetFilterOverrides(fid)
                hex_color = ph.revit_color_to_hex(ogs.SurfaceForegroundPatternColor)
                rgb = ph.parse_color_input(hex_color) if hex_color else None
                if rgb:
                    used.append(rgb)
            except Exception:
                pass
    except Exception:
        pass
    return used


def _palette_short_action(n, used_colors):
    pal = ph.palette_rgbs()
    available = [rgb for rgb in pal if rgb not in set(used_colors or [])]
    if len(available) >= n:
        return 'auto'
    result = MessageBox.Show(
        u"A paleta tem {} cor(es) disponiveis sem repetir, mas precisa de {}.\n\n"
        u"Sim: completar com Auto HSV\n"
        u"Nao: repetir a paleta\n"
        u"Cancelar: cancelar a criacao".format(len(available), n),
        "Paleta insuficiente",
        MessageBoxButton.YesNoCancel)
    if result == MessageBoxResult.Yes:
        return 'auto'
    if result == MessageBoxResult.No:
        return 'repeat'
    return 'cancel'


def _resolve_workflow_colors(n, mode, view, prompt_palette=True):
    used = _used_view_colors(revit.doc, view)
    action = 'auto'
    if mode == 'palette' and prompt_palette:
        action = _palette_short_action(n, used)
        if action == 'cancel':
            return None
    return ph.resolve_cores_distintas(n, mode, used, action)


def _filter_is_acceptable(doc, cat_ids, elem_filter):
    try:
        return ParameterFilterElement.ElementFilterIsAcceptableForParameterFilterElement(
            doc, cat_ids, elem_filter)
    except Exception:
        return True


def _create_filters_safely(doc, pairs, prefix, cat_ids, param_id):
    created = []
    reused = []
    failed = []
    existing = _project_filters_by_name(doc)
    for val, name in pairs:
        fname = _filter_name(prefix, val, name)
        if fname in existing:
            reused.append(fname)
            continue
        try:
            rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, val, False)
            elem_filter = ElementParameterFilter(rule)
        except Exception as e:
            failed.append((fname, u"regra invalida: " + str(e)))
            continue
        if not _filter_is_acceptable(doc, cat_ids, elem_filter):
            failed.append((fname, u"parametro nao aceite para as categorias"))
            continue
        try:
            with revit.Transaction("MTQ Filters - Criar filtro"):
                ParameterFilterElement.Create(doc, fname, cat_ids, elem_filter)
            created.append(fname)
            existing[fname] = True
        except Exception as e:
            failed.append((fname, str(e)))
    return created, reused, failed


def _create_filter_exact(doc, filter_name, value, cat_ids, param_id):
    existing = _project_filters_by_name(doc)
    if filter_name in existing:
        return None, u"ja existe"
    try:
        rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, value, False)
        elem_filter = ElementParameterFilter(rule)
    except Exception as e:
        return None, u"regra invalida: " + str(e)
    if not _filter_is_acceptable(doc, cat_ids, elem_filter):
        return None, u"parametro nao aceite para as categorias"
    try:
        with revit.Transaction("MTQ Scheme - Criar filtro"):
            f = ParameterFilterElement.Create(doc, filter_name, cat_ids, elem_filter)
        return f, ''
    except Exception as e:
        return None, str(e)


class FilterEntry(object):
    def __init__(self, filter_id, name, color_hex='', fill_pattern=PATTERN_NONE,
                 enabled=True, visible=True, in_view=False):
        self.FilterId = filter_id
        self.Name = name
        self.ColorHex = color_hex
        self.FillPattern = fill_pattern
        self.Enabled = bool(enabled)
        self.Visible = bool(visible)
        self.InView = bool(in_view)
        self.refresh_brush()

    def refresh_brush(self):
        rgb = ph.parse_color_input(self.ColorHex)
        if not rgb:
            self.ColorBrush = Brushes.Transparent
            return
        self.ColorBrush = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))


class PatternOption(object):
    def __init__(self, name, label, pattern_id=None):
        self.Name = name
        self.Label = label
        self.PatternId = pattern_id
        self.PreviewBrush = self._make_preview(name, pattern_id)

    def _make_preview(self, name, pattern_id):
        if name == PATTERN_NONE:
            return Brushes.Transparent
        if name == PATTERN_SOLID:
            return SolidColorBrush(WpfColor.FromRgb(90, 90, 90))
        lname = (name or u'').lower()
        group = GeometryGroup()
        if 'vertical' in lname:
            for x in (2, 6, 10, 14):
                group.Children.Add(LineGeometry(Point(x, 0), Point(x, 16)))
        elif 'horizontal' in lname:
            for y in (3, 7, 11):
                group.Children.Add(LineGeometry(Point(0, y), Point(16, y)))
        elif 'cross' in lname:
            for x in (2, 7, 12):
                group.Children.Add(LineGeometry(Point(x, 0), Point(x, 16)))
            for y in (3, 8, 13):
                group.Children.Add(LineGeometry(Point(0, y), Point(16, y)))
        elif 'down' in lname:
            for x in (-8, -2, 4, 10):
                group.Children.Add(LineGeometry(Point(x, 0), Point(x + 16, 16)))
        else:
            for x in (0, 6, 12):
                group.Children.Add(LineGeometry(Point(x, 16), Point(x + 16, 0)))
        drawing = GeometryDrawing(
            Brushes.Transparent,
            Pen(SolidColorBrush(WpfColor.FromRgb(70, 70, 70)), 1),
            group)
        brush = DrawingBrush(drawing)
        brush.TileMode = TileMode.Tile
        brush.Viewport = Rect(0, 0, 16, 16)
        brush.ViewportUnits = System.Windows.Media.BrushMappingMode.Absolute
        return brush


class ColorItem(object):
    def __init__(self, hex_color, label):
        self.HexColor = hex_color
        self.Label = label


class SchemeItem(object):
    def __init__(self, data):
        self.Data = data
        self.Active = bool(data.get('active', True))
        self.Value = data.get('value', '')
        self.FilterName = data.get('filter_name', data.get('name', ''))
        self.ColorHex = data.get('color', '') or ''
        self.FillPattern = data.get('pattern', PATTERN_NONE) or PATTERN_NONE
        self.refresh_brush()

    def refresh_brush(self):
        rgb = ph.parse_color_input(self.ColorHex)
        if not rgb:
            self.ColorBrush = Brushes.Transparent
            return
        self.ColorBrush = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))

    def sync(self):
        self.Data['active'] = bool(self.Active)
        self.Data['value'] = self.Value
        self.Data['filter_name'] = self.FilterName
        self.Data['color'] = self.ColorHex
        self.Data['pattern'] = self.FillPattern


def _get_revit_fill_patterns(doc):
    patterns = {}
    ordered = []
    try:
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements():
            try:
                pat = fp.GetFillPattern()
                if pat.IsSolidFill:
                    continue
                # Match the patterns Revit accepts in filter/view overrides.
                # This is closer to the Revit UI than a raw FillPattern list.
                if not _pattern_is_accepted_by_filter_override(fp.Id):
                    continue
                if fp.Name not in patterns:
                    patterns[fp.Name] = fp.Id
                    ordered.append(fp.Name)
            except Exception:
                pass
    except Exception:
        pass
    return patterns, ordered


def _get_revit_fill_pattern_map(doc):
    patterns, ordered = _get_revit_fill_patterns(doc)
    return patterns


def _pattern_id_from_export(doc, fill_patterns, pattern_name, solid_id):
    if not pattern_name or pattern_name == PATTERN_NONE:
        return ElementId.InvalidElementId
    if pattern_name == PATTERN_SOLID:
        return solid_id
    return fill_patterns.get(pattern_name, ElementId.InvalidElementId)


def _pattern_is_accepted_by_filter_override(pattern_id):
    try:
        if pattern_id is None or pattern_id == ElementId.InvalidElementId:
            return True
        test = OverrideGraphicSettings()
        test.SetSurfaceForegroundPatternId(pattern_id)
        test.SetCutForegroundPatternId(pattern_id)
        return True
    except Exception:
        return False


def _is_valid_override_pattern(doc, pattern_id, solid_id):
    try:
        if pattern_id is None or pattern_id == ElementId.InvalidElementId:
            return True
        if solid_id is not None and pattern_id == solid_id:
            return True
        return _pattern_is_accepted_by_filter_override(pattern_id)
    except Exception:
        return False


def _find_parent_of_type(obj, type_name):
    current = obj
    while current is not None:
        try:
            if current.GetType().Name == type_name:
                return current
            current = VisualTreeHelper.GetParent(current)
        except Exception:
            return None
    return None


def _ask_text(owner, title, prompt, default_value=''):
    dlg = TextInputWindow(title, prompt, default_value)
    try:
        dlg.Owner = owner
    except Exception:
        pass
    dlg.ShowDialog()
    return dlg.Result


class PaletteColorPickerWindow(forms.WPFWindow):
    def __init__(self, current_hex='#4472C4', used_colors=None):
        self.Result = None
        self.ManagePalette = False
        self._used_colors = set((c or '').upper() for c in (used_colors or []))
        self._syncing = False
        forms.WPFWindow.__init__(self, 'picker_cor.xaml')
        self._build_swatches()
        self._set_hex((current_hex or '#4472C4').lstrip('#'))

    def _build_swatches(self):
        from System.Windows.Controls import Button
        from System.Windows import Thickness
        self.pnlSwatches.Children.Clear()
        for entry in ph.load_palette():
            rgb = ph.parse_color_input(entry.get('hex', '#000000'))
            if not rgb:
                continue
            btn = Button()
            btn.Width = 24
            btn.Height = 24
            btn.Margin = Thickness(2)
            btn.Padding = Thickness(0)
            hex_value = entry.get('hex', '#000000')
            if hex_value.upper() in self._used_colors:
                btn.BorderThickness = Thickness(3)
                btn.BorderBrush = Brushes.Black
            else:
                btn.BorderThickness = Thickness(1)
            btn.Background = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))
            btn.ToolTip = u"{} {}".format(entry.get('name', ''), entry.get('hex', ''))
            def make_handler(hx):
                def handler(sender, args):
                    self._set_hex(hx.lstrip('#'))
                return handler
            btn.Click += make_handler(hex_value)
            self.pnlSwatches.Children.Add(btn)

    def _set_hex(self, hex6):
        hex6 = hex6.upper().lstrip('#')
        self._syncing = True
        self.txtHex.Text = hex6
        rgb = ph.parse_color_input('#' + hex6)
        if rgb:
            self.txtR.Text = str(rgb[0])
            self.txtG.Text = str(rgb[1])
            self.txtB.Text = str(rgb[2])
            self.colorPreview.Background = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))
        self._syncing = False

    def hex_changed(self, s, a):
        if self._syncing:
            return
        h = self.txtHex.Text.strip()
        if len(h) == 6:
            rgb = ph.parse_color_input('#' + h)
            if rgb:
                self._syncing = True
                self.txtR.Text = str(rgb[0])
                self.txtG.Text = str(rgb[1])
                self.txtB.Text = str(rgb[2])
                self.colorPreview.Background = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))
                self._syncing = False

    def hex_got_focus(self, s, a):
        self.txtHex.SelectAll()

    def rgb_text_changed(self, s, a):
        if self._syncing:
            return
        try:
            r = max(0, min(255, int(self.txtR.Text or '0')))
            g = max(0, min(255, int(self.txtG.Text or '0')))
            b = max(0, min(255, int(self.txtB.Text or '0')))
            self._syncing = True
            self.txtHex.Text = '{:02X}{:02X}{:02X}'.format(r, g, b)
            self.colorPreview.Background = SolidColorBrush(WpfColor.FromRgb(r, g, b))
            self._syncing = False
        except Exception:
            self._syncing = False

    def abrir_misturador(self, s, a):
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import ColorDialog
        from System.Drawing import Color as DrawColor
        import System.Windows.Forms as WF
        dlg = ColorDialog()
        dlg.FullOpen = True
        rgb = ph.parse_color_input('#' + self.txtHex.Text)
        if rgb:
            dlg.Color = DrawColor.FromArgb(rgb[0], rgb[1], rgb[2])
        if dlg.ShowDialog() == WF.DialogResult.OK:
            c = dlg.Color
            self._set_hex(ph.rgb_to_hex(c.R, c.G, c.B).lstrip('#'))

    def gerir_paleta(self, s, a):
        self.ManagePalette = True
        self.Close()

    def sem_cor(self, s, a):
        self.Result = ''
        self.Close()

    def ok_click(self, s, a):
        h = self.txtHex.Text.strip().lstrip('#')
        if len(h) == 6 and ph.parse_color_input('#' + h):
            self.Result = '#{}'.format(h.upper())
        self.Close()

    def cancelar(self, s, a):
        self.Close()

    def picker_preview_key_down(self, s, a):
        if a.Key == Key.Escape:
            a.Handled = True
            self.Close()


class TextInputWindow(forms.WPFWindow):
    def __init__(self, title, prompt, default_value=''):
        self.Result = None
        forms.WPFWindow.__init__(self, 'text_input.xaml')
        self.Title = title or 'Editar texto'
        self.lblPrompt.Text = prompt or 'Texto'
        self.txtValue.Text = default_value or ''
        try:
            self.txtValue.Focus()
            self.txtValue.SelectAll()
        except Exception:
            pass

    def ok_click(self, s, a):
        self.Result = self.txtValue.Text
        self.Close()

    def cancel_click(self, s, a):
        self.Close()

    def text_input_preview_key_down(self, s, a):
        if a.Key == Key.Enter:
            a.Handled = True
            self.ok_click(None, None)
        elif a.Key == Key.Escape:
            a.Handled = True
            self.Close()


class MainWindow(forms.WPFWindow):
    def __init__(self):
        self._ui_loading = True
        self.doc = revit.doc
        self._filterable_categories_cache = None
        self._strict_params_cache = {}
        self._all_params_with_categories_cache = None
        self._cat_map = {}
        self._param_map = {}
        self._inverse_mode = False
        self._param_cat_map = {}
        self._all_values = []
        self._sel_values = set()
        self._loading = False
        self._file_cat_map = {}
        self._file_param_map = {}
        self._file_available_param_map = {}
        self._file_inverse_mode = False
        self._file_param_cat_map = {}
        self._file_sheet_names = []
        self._file_selected_sheet = None
        self._file_sheet_rows = []
        self._file_header_row = []
        self._file_header_row_number = None
        self._file_stats = {}
        self._file_range_issue = u''
        self._file_rows = []
        self._file_preview_pairs = []
        self._file_preview_ready = True
        self._file_preview_total = 0
        self._file_path = ''
        self._edit_fill_patterns = {}
        self._edit_pattern_names = []
        self._edit_pattern_options = []
        self._edit_entries = []
        self._edit_bulk_targets = []
        self._edit_dirty = True
        self._edit_last_search = None
        self._edit_last_view_id = None
        self._clean_filter_map = {}
        self._exp_map = {}
        self._imp_data = []
        self._schemes = []
        self._scheme_items = []
        self._current_scheme = None
        self._scheme_bulk_targets = []
        self._schemes_dirty = True
        self._colors = []
        self._color_syncing = False
        forms.WPFWindow.__init__(self, 'main_window.xaml')
        self._ui_loading = False
        self._wire_live_search_events()

        self._init_header()
        self._init_create_page()
        self._init_file_page()
        self._init_edit_page()
        self._init_transfer_page()
        self._init_clean_page()
        self._init_schemes_page()
        self._init_colors_page()
        self.mainTabs.SelectedIndex = 0

    def _wire_live_search_events(self):
        try:
            self.l_txtPrefix.TextChanged += self.l_search_changed
        except Exception:
            pass
        try:
            self.e_txtPrefix.TextChanged += self.e_search_changed
        except Exception:
            pass

    def _set_status(self, text):
        self.lblGlobalStatus.Text = text

    def _fill_apply_target_options(self, combo, allow_none):
        try:
            combo.Items.Clear()
            if allow_none:
                combo.Items.Add(APPLY_NONE)
            combo.Items.Add(APPLY_ACTIVE_VIEW)
            combo.Items.Add(APPLY_ACTIVE_TEMPLATE)
            combo.SelectedItem = APPLY_ACTIVE_VIEW if not allow_none else APPLY_NONE
        except Exception:
            pass

    def _selected_apply_target(self, combo):
        try:
            choice = str(combo.SelectedItem) if combo.SelectedItem else APPLY_NONE
        except Exception:
            choice = APPLY_NONE
        active_view = self.doc.ActiveView
        if choice == APPLY_ACTIVE_VIEW:
            return active_view, APPLY_ACTIVE_VIEW, None
        if choice == APPLY_ACTIVE_TEMPLATE:
            template = _get_view_template(self.doc, active_view)
            if template is None:
                return None, APPLY_ACTIVE_TEMPLATE, u"A vista ativa nao tem template associado."
            return template, APPLY_ACTIVE_TEMPLATE, None
        return None, APPLY_NONE, None

    def _init_header(self):
        try:
            project = self.doc.Title or os.path.basename(self.doc.PathName)
        except Exception:
            project = u"Projeto"
        try:
            view_name = self.doc.ActiveView.Name
        except Exception:
            view_name = u"Vista ativa"
        self.lblProjectInfo.Text = u"{}  |  {}".format(project, view_name)

    def _nav(self, index, status):
        self._init_header()
        self.mainTabs.SelectedIndex = index
        self._set_status(status)

    def nav_create(self, s, a):
        self._refresh_create_page()
        self._nav(0, u"Criar filtros do projeto")

    def nav_file(self, s, a):
        self._refresh_file_page()
        self._nav(1, u"Listas Excel / CSV")

    def nav_edit(self, s, a):
        self._refresh_edit_page()
        self._nav(2, u"Editar filtros existentes")

    def nav_transfer(self, s, a):
        self._transfer_load_project_filters()
        self._nav(4, u"Transferir filtros")

    def nav_clean(self, s, a):
        self.l_procurar(None, None)
        self._nav(5, u"Limpar filtros")

    def nav_schemes(self, s, a):
        self._schemes_refresh()
        self._nav(3, u"Biblioteca de esquemas")

    def nav_colors(self, s, a):
        self._refresh_colors_page()
        self._nav(6, u"Configurar paleta")

    def nav_about(self, s, a): self._nav(7, u"Sobre")
    def main_close(self, s, a): self.Close()

    def main_preview_key_down(self, s, a):
        if a.Key != Key.Escape:
            return
        a.Handled = True
        for combo_name in ('cmbParam', 'f_cmbColVal', 'f_cmbColNome', 'f_cmbParam'):
            try:
                combo = getattr(self, combo_name)
                if combo.IsDropDownOpen:
                    combo.IsDropDownOpen = False
                    return
            except Exception:
                pass
        if self._clear_current_selection():
            self._set_status(u"Selecao limpa.")
        else:
            self._set_status(u"Esc nao fecha o plugin. Use o X da janela para fechar.")

    def _clear_current_selection(self):
        try:
            tab = self.mainTabs.SelectedIndex
        except Exception:
            return False
        controls_by_tab = {
            0: ('lstCategories', 'lstValues'),
            1: ('f_lstCategories',),
            2: ('e_dgFiltros',),
            3: ('sch_lstSchemes', 'sch_dgItems'),
            4: ('x_lstExpFilters', 'x_lstImpFilters'),
            5: ('l_lstFilters',),
            6: ('co_lstColors',),
        }
        cleared = False
        for name in controls_by_tab.get(tab, ()):
            try:
                control = getattr(self, name)
                count = control.SelectedItems.Count if hasattr(control, 'SelectedItems') else 0
                if count:
                    control.UnselectAll()
                    cleared = True
            except Exception:
                try:
                    control.SelectedIndex = -1
                    cleared = True
                except Exception:
                    pass
        if tab == 0 and cleared:
            try:
                self._sel_values = set(str(i) for i in self.lstValues.SelectedItems)
                self.runValueCount.Text = u"({} de {})".format(len(self._sel_values), self.lstValues.Items.Count)
                self._update_status()
            except Exception:
                pass
        if tab == 4 and cleared:
            try:
                self._transfer_update_exp_count()
            except Exception:
                pass
        return cleared

    def _select_list_items(self, list_box, names):
        wanted = set(names or [])
        try:
            list_box.UnselectAll()
            for i in range(list_box.Items.Count):
                item = list_box.Items.GetItemAt(i)
                if str(item) in wanted:
                    list_box.SelectedItems.Add(item)
        except Exception:
            pass

    def _current_edit_search(self):
        try:
            return self.e_txtPrefix.Text.strip()
        except Exception:
            return ''

    def _current_view_id(self):
        try:
            return self.doc.ActiveView.Id.IntegerValue
        except Exception:
            return None

    def _refresh_edit_page(self, force=False):
        search = self._current_edit_search()
        view_id = self._current_view_id()
        should_reload = (
            force or
            self._edit_dirty or
            self._edit_last_search != search or
            self._edit_last_view_id != view_id or
            not self._edit_entries
        )
        if not self._edit_fill_patterns:
            self._edit_fill_patterns, self._edit_pattern_names = _get_revit_fill_patterns(self.doc)
            self._edit_build_pattern_options()
        if not should_reload:
            return
        self._edit_load_filters(search)
        self._edit_last_search = search
        self._edit_last_view_id = view_id
        self._edit_dirty = False

    def _refresh_filter_pages(self):
        try:
            self._edit_dirty = True
            self._refresh_edit_page(True)
        except Exception:
            pass

    def _get_cached_filterable_categories(self):
        if self._filterable_categories_cache is None:
            self._filterable_categories_cache = _get_filterable_categories(self.doc)
        return dict(self._filterable_categories_cache)

    def _get_cached_strict_params(self, cat_ids):
        key = tuple(sorted([cid.IntegerValue for cid in (cat_ids or [])]))
        if key not in self._strict_params_cache:
            self._strict_params_cache[key] = _get_strict_filterable_params(self.doc, cat_ids)
        return dict(self._strict_params_cache[key])

    def _get_cached_all_params_with_categories(self):
        if self._all_params_with_categories_cache is None:
            self._all_params_with_categories_cache = _get_all_params_with_categories_strict(
                self.doc, self._get_cached_filterable_categories())
        return self._all_params_with_categories_cache
        try:
            self._transfer_load_project_filters()
        except Exception:
            pass
        try:
            self.l_procurar(None, None)
        except Exception:
            pass

    # Create from project
    def _init_create_page(self):
        self._fill_apply_target_options(self.cmbCreateApplyTarget, True)
        self._cat_map = self._get_cached_filterable_categories()
        self._render_categories("")

    def _refresh_create_page(self):
        if self._sel_values:
            return
        selected_cats = [str(i) for i in self.lstCategories.SelectedItems]
        selected_param = str(self.cmbParam.SelectedItem) if self.cmbParam.SelectedItem else None
        cat_filter = self.txtCatFilter.Text if self.txtCatFilter.Text != CAT_PH else ""
        self._cat_map = self._get_cached_filterable_categories()
        if self._inverse_mode:
            self._param_cat_map = self._get_cached_all_params_with_categories()
            self.cmbParam.Items.Clear()
            for name in sorted(self._param_cat_map):
                self.cmbParam.Items.Add(name)
            for i in range(self.cmbParam.Items.Count):
                if str(self.cmbParam.Items.GetItemAt(i)) == selected_param:
                    self.cmbParam.SelectedIndex = i
                    break
            self._render_categories(cat_filter)
            self._select_list_items(self.lstCategories, selected_cats)
        else:
            self._render_categories(cat_filter)
            self._select_list_items(self.lstCategories, selected_cats)
            if selected_cats:
                self.cats_selection_changed(None, None)
                for i in range(self.cmbParam.Items.Count):
                    if str(self.cmbParam.Items.GetItemAt(i)) == selected_param:
                        self.cmbParam.SelectedIndex = i
                        break

    def _render_categories(self, filt):
        self.lstCategories.Items.Clear()
        if self._inverse_mode and self.cmbParam.SelectedItem is not None:
            param_name = str(self.cmbParam.SelectedItem)
            entry = self._param_cat_map.get(param_name)
            if entry:
                supported = set(cid.IntegerValue for cid in entry[1])
                for name in sorted(self._cat_map):
                    if self._cat_map[name].IntegerValue in supported:
                        if _fuzzy_match(filt, name):
                            self.lstCategories.Items.Add(name)
                return
        for name in sorted(self._cat_map):
            if _fuzzy_match(filt, name):
                self.lstCategories.Items.Add(name)

    def mode_changed(self, s, a):
        if getattr(self, '_ui_loading', False) or not self._cat_map:
            return
        self._inverse_mode = bool(self.rdoInverse.IsChecked)
        self._all_values = []
        self._sel_values = set()
        self.lstValues.Items.Clear()
        self.lstCategories.UnselectAll()
        self._update_status()

        if self._inverse_mode:
            self.lblCatHeader.Text = u"1. Categorias (filtradas por parametro)"
            if not self._param_cat_map:
                self._param_cat_map = self._get_cached_all_params_with_categories()
            self.cmbParam.Items.Clear()
            for name in sorted(self._param_cat_map):
                self.cmbParam.Items.Add(name)
            self._render_categories("")
        else:
            self.lblCatHeader.Text = u"1. Categorias"
            self.cmbParam.Items.Clear()
            self._param_map = {}
            self._render_categories("")

    def cat_search_got_focus(self, s, a):
        if self.txtCatFilter.Text == CAT_PH:
            self.txtCatFilter.Text = ""
            self.txtCatFilter.Foreground = Brushes.Black

    def cat_search_lost_focus(self, s, a):
        if not self.txtCatFilter.Text.strip():
            self.txtCatFilter.Text = CAT_PH
            self.txtCatFilter.Foreground = Brushes.Gray

    def cat_filter_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self.txtCatFilter.Text != CAT_PH:
            self._render_categories(self.txtCatFilter.Text)

    def cats_selection_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self._inverse_mode:
            self._update_status()
            return
        cats = [str(i) for i in self.lstCategories.SelectedItems]
        self.cmbParam.Items.Clear()
        self._param_map = {}
        if not cats:
            self._all_values = []
            self._sel_values = set()
            self.lstValues.Items.Clear()
            self._update_status()
            return
        self._param_map = self._get_cached_strict_params([self._cat_map[c] for c in cats])
        for name in sorted(self._param_map):
            self.cmbParam.Items.Add(name)
        self._all_values = []
        self._sel_values = set()
        self.lstValues.Items.Clear()
        self._update_status()

    def param_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._all_values = []
        self._sel_values = set()
        self.lstValues.Items.Clear()
        if self._inverse_mode:
            param_name = str(self.cmbParam.SelectedItem) if self.cmbParam.SelectedItem else None
            if param_name and param_name in self._param_cat_map:
                entry = self._param_cat_map[param_name]
                self._param_map = {param_name: entry[0]}
                cat_filt = self.txtCatFilter.Text if self.txtCatFilter.Text != CAT_PH else ""
                self._render_categories(cat_filt)
                self.lstCategories.SelectAll()
            else:
                self._param_map = {}
                self._render_categories("")
        self._update_status()

    def detect_values(self, s, a):
        cats = [str(i) for i in self.lstCategories.SelectedItems]
        param_name = str(self.cmbParam.SelectedItem) if self.cmbParam.SelectedItem else None
        if not cats or not param_name:
            MessageBox.Show(u"Selecione categorias e um parametro primeiro.", "Filter Manager")
            return
        param_id = self._param_map.get(param_name)
        if not param_id:
            MessageBox.Show(u"Parametro nao encontrado no mapa.", "Filter Manager")
            return
        self._all_values = revit_query.get_unique_values(
            self.doc, [self._cat_map[c] for c in cats], param_id)
        self._sel_values = set(self._all_values)
        self._render_values("")
        self._update_status()

    def _render_values(self, filt):
        self._loading = True
        self.lstValues.Items.Clear()
        for v in self._all_values:
            if _fuzzy_match(filt, v):
                self.lstValues.Items.Add(v)
        for i in range(self.lstValues.Items.Count):
            item = self.lstValues.Items.GetItemAt(i)
            if str(item) in self._sel_values:
                self.lstValues.SelectedItems.Add(item)
        self._loading = False
        self.runValueCount.Text = u"({} de {})".format(len(self._sel_values), self.lstValues.Items.Count)

    def values_selection_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if not self._loading:
            self._sel_values = set(str(i) for i in self.lstValues.SelectedItems)
            self.runValueCount.Text = u"({} de {})".format(len(self._sel_values), self.lstValues.Items.Count)
            self._update_status()

    def val_search_got_focus(self, s, a):
        if self.txtValueFilter.Text == VAL_PH:
            self.txtValueFilter.Text = ""
            self.txtValueFilter.Foreground = Brushes.Black

    def val_search_lost_focus(self, s, a):
        if not self.txtValueFilter.Text.strip():
            self.txtValueFilter.Text = VAL_PH
            self.txtValueFilter.Foreground = Brushes.Gray

    def value_filter_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self.txtValueFilter.Text != VAL_PH:
            self._render_values(self.txtValueFilter.Text)

    def select_all(self, s, a):
        self._sel_values = set(self._all_values)
        filt = self.txtValueFilter.Text if self.txtValueFilter.Text != VAL_PH else ""
        self._render_values(filt)
        self._update_status()

    def clear_all(self, s, a):
        self._sel_values = set()
        self._loading = True
        self.lstValues.UnselectAll()
        self._loading = False
        self.runValueCount.Text = u"(0 de {})".format(self.lstValues.Items.Count)
        self._update_status()

    def _update_status(self):
        n = len(self._sel_values)
        self.lblStatus.Text = u"{} filtro(s) a criar".format(n) if n else u""

    def create_color_option_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if _color_mode(self.rdoPalette, self.rdoNoColor) != 'none':
            try:
                if not self.cmbCreateApplyTarget.SelectedItem or str(self.cmbCreateApplyTarget.SelectedItem) == APPLY_NONE:
                    self.cmbCreateApplyTarget.SelectedItem = APPLY_ACTIVE_VIEW
            except Exception:
                pass

    def criar_filtros(self, s, a):
        cats = [str(i) for i in self.lstCategories.SelectedItems]
        param_name = str(self.cmbParam.SelectedItem) if self.cmbParam.SelectedItem else None
        if not cats:
            MessageBox.Show(u"Selecione pelo menos uma categoria.", "Filter Manager"); return
        if not param_name:
            MessageBox.Show(u"Selecione um parametro.", "Filter Manager"); return
        if not self._sel_values:
            MessageBox.Show(u"Clique em Detetar e selecione valores.", "Filter Manager"); return

        param_id = self._param_map.get(param_name)
        if not param_id:
            MessageBox.Show(u"Parametro nao encontrado no mapa.", "Filter Manager"); return

        prefix = self.txtPrefix.Text.strip()
        cat_ids = List[ElementId]([self._cat_map[c] for c in cats])
        pairs = [(v, v) for v in sorted(self._sel_values)]
        mode = _color_mode(self.rdoPalette, self.rdoNoColor)
        view, target_label, target_err = self._selected_apply_target(self.cmbCreateApplyTarget)
        if target_err:
            MessageBox.Show(target_err, "Filter Manager"); return
        if mode != 'none' and view is None:
            try:
                self.cmbCreateApplyTarget.SelectedItem = APPLY_ACTIVE_VIEW
            except Exception:
                pass
            view, target_label, target_err = self._selected_apply_target(self.cmbCreateApplyTarget)
        if not _validate_override_view(view):
            return
        cores = _resolve_workflow_colors(len(pairs), mode, view)
        if cores is None:
            MessageBox.Show(u"Criacao cancelada ou paleta vazia.", "Filter Manager"); return

        names = [_filter_name(prefix, v, n) for v, n in pairs]
        created_names, reused_names, failed_items = _create_filters_safely(self.doc, pairs, prefix, cat_ids, param_id)

        applied = 0
        failed = 0
        if view is not None:
            with revit.Transaction("MTQ Filters - Aplicar filtros a vista"):
                applied, failed = _apply_named_filters_to_view(self.doc, view, names, cores)

        msg = u"{} criados".format(len(created_names))
        if reused_names:
            msg += u", {} reutilizados".format(len(reused_names))
        if view is not None:
            msg += u", {} aplicados a {}".format(applied, target_label.lower())
            if failed:
                msg += u", {} falharam".format(failed)
        if failed_items:
            msg += u", {} falharam na criacao".format(len(failed_items))
        msg += u" com '{}'.".format(param_name)
        self.lblStatus.Text = msg
        self._set_status(msg)
        self._refresh_filter_pages()

    def recolorir_filtros(self, s, a):
        prefix = self.txtPrefix.Text.strip()
        if not prefix:
            MessageBox.Show(u"Introduza um prefixo para identificar os filtros.", "Recolorir"); return
        filters = sorted(
            [f for f in FilteredElementCollector(self.doc).OfClass(ParameterFilterElement)
             if f.Name.startswith(prefix)],
            key=lambda x: x.Name)
        if not filters:
            MessageBox.Show(u"Nenhum filtro encontrado com prefixo '{}'.".format(prefix), "Recolorir"); return
        mode = _color_mode(self.rdoPalette, self.rdoNoColor)
        view, target_label, target_err = self._selected_apply_target(self.cmbCreateApplyTarget)
        if target_err:
            MessageBox.Show(target_err, "Recolorir"); return
        if view is None:
            MessageBox.Show(u"Escolha um destino em 'Aplicar a'.", "Recolorir"); return
        if not _validate_override_view(view):
            return
        colors = _resolve_workflow_colors(len(filters), mode, view)
        if colors is None:
            MessageBox.Show(u"Recolorizacao cancelada ou paleta vazia.", "Recolorir"); return
        solid = ph.get_solid_fill_pattern_id(self.doc)
        done = 0
        failed = 0
        with revit.Transaction("MTQ Filters - Recolorir"):
            for i, f in enumerate(filters):
                rgb = colors[i] if i < len(colors) else None
                pat_id = solid if rgb is not None else ElementId.InvalidElementId
                ov = ph.build_revit_override(rgb, solid, pat_id)
                ok, err = _apply_filter_override(view, f.Id, ov)
                if ok:
                    done += 1
                else:
                    failed += 1
        msg = u"{} de {} filtros recoloridos em {}".format(done, len(filters), target_label.lower())
        if failed:
            msg += u"; {} falharam".format(failed)
        self.lblStatus.Text = msg
        self._set_status(msg)

    # File workflow
    def _init_file_page(self):
        self._file_inverse_mode = bool(self.f_rdoInverse.IsChecked)
        self.f_lblCatHeader.Text = u"Categorias que suportam o parametro" if self._file_inverse_mode else u"Categorias"
        self.f_lblSummary.Text = u""
        self.f_lblIssues.Text = u""
        self._file_set_sheet_visibility()
        self._file_load_categories()

    def _file_cat_filter_text(self):
        try:
            text = self.f_txtCatFilter.Text
            return '' if text == CAT_PH else text
        except Exception:
            return ''

    def _file_param_filter_text(self):
        try:
            text = self.f_txtParamFilter.Text
            return '' if text == CAT_PH else text
        except Exception:
            return ''

    def _file_current_param_name(self):
        try:
            return str(self.f_cmbParam.SelectedItem) if self.f_cmbParam.SelectedItem else None
        except Exception:
            return None

    def _file_selected_sheet_name(self):
        try:
            if not self.f_cmbSheet.SelectedItem:
                return None
            name = str(self.f_cmbSheet.SelectedItem)
            if name == u"(selecionar folha...)":
                return None
            return name
        except Exception:
            return None

    def _file_parse_row_number(self, text, default_value=None):
        try:
            value = int((text or '').strip())
            return value if value > 0 else default_value
        except Exception:
            return default_value

    def _file_set_sheet_visibility(self):
        try:
            self.f_pnlSheet.Visibility = Visibility.Visible if len(self._file_sheet_names) > 1 else Visibility.Collapsed
        except Exception:
            pass

    def _file_normalize_text(self, value):
        text = (value or u'')
        replacements = [
            (u'\r', u' '),
            (u'\n', u' '),
            (u'\t', u' '),
            (u'\xa0', u' '),
            (u'\u200b', u''),
            (u'\u200c', u''),
            (u'\u200d', u''),
            (u'\ufeff', u''),
        ]
        for old, new in replacements:
            try:
                text = text.replace(old, new)
            except Exception:
                pass
        return u' '.join(text.split())

    def _file_load_sheet_names(self):
        self._file_sheet_names = []
        if not self._file_path or excel_io is None:
            self._file_set_sheet_visibility()
            return
        try:
            self._file_sheet_names = list(excel_io.list_sheets(self._file_path) or [])
        except Exception as e:
            self._file_sheet_names = []
            try:
                self.f_lblIssues.Text = u"Nao foi possivel listar as folhas: {}".format(e)
            except Exception:
                pass
        try:
            self.f_cmbSheet.Items.Clear()
            if len(self._file_sheet_names) > 1:
                self.f_cmbSheet.Items.Add(u"(selecionar folha...)")
                for name in self._file_sheet_names:
                    self.f_cmbSheet.Items.Add(name)
                self.f_cmbSheet.SelectedIndex = 0
                self._file_selected_sheet = None
            elif self._file_sheet_names:
                self.f_cmbSheet.Items.Add(self._file_sheet_names[0])
                self.f_cmbSheet.SelectedIndex = 0
                self._file_selected_sheet = self._file_sheet_names[0]
            else:
                self._file_selected_sheet = None
        except Exception:
            pass
        try:
            self.f_expAdvanced.IsExpanded = bool(len(self._file_sheet_names) > 1)
        except Exception:
            pass
        try:
            if len(self._file_sheet_names) > 1:
                self.f_lblIssues.Text = u"Este ficheiro tem varias folhas. Escolha a folha antes de continuar."
            elif len(self._file_sheet_names) == 1:
                self.f_lblIssues.Text = u""
            elif self._file_path and os.path.splitext(self._file_path)[1].lower() in ('.xlsx', '.xls', '.xlsm', '.xlsb'):
                self.f_lblIssues.Text = u"Nao foi encontrada nenhuma folha legivel neste ficheiro."
        except Exception:
            pass
        self._file_set_sheet_visibility()

    def _file_load_sheet_rows(self):
        self._file_sheet_rows = []
        if not self._file_path or excel_io is None:
            return
        try:
            self._file_selected_sheet = self._file_selected_sheet_name()
        except Exception:
            pass
        if self._file_sheet_names and len(self._file_sheet_names) > 1 and not self._file_selected_sheet:
            return
        try:
            sheet_name = self._file_selected_sheet if self._file_sheet_names else None
            self._file_sheet_rows = excel_io.read_file(self._file_path, sheet_name)
        except TypeError:
            self._file_sheet_rows = excel_io.read_file(self._file_path)
        except Exception as e:
            self._file_sheet_rows = []
            self.f_lblIssues.Text = u"Erro ao ler a folha: {}".format(e)

    def _file_apply_row_window(self):
        self._file_rows = []
        self._file_header_row = []
        self._file_header_row_number = None
        self._file_range_issue = u''
        rows = list(self._file_sheet_rows or [])
        if not rows:
            return
        start = self._file_parse_row_number(self.f_txtRowStart.Text, 1)
        end = self._file_parse_row_number(self.f_txtRowEnd.Text, None)
        if start is None:
            start = 1
        start_idx = max(0, start - 1)
        end_idx = len(rows) if end is None else min(len(rows), end)
        if end is not None and end < start:
            self._file_range_issue = u"Linha final menor do que a linha inicial."
            self._file_rows = []
            return
        if start_idx >= len(rows):
            self._file_range_issue = u"Linha inicial fora da zona lida."
            self._file_rows = []
            return
        if start <= 1:
            self._file_header_row = list(rows[0] if rows else [])
            self._file_header_row_number = 1 if rows else None
            data_start_idx = 1
        else:
            header_idx = start_idx - 1
            while header_idx >= 0:
                try:
                    if any((c or u'').strip() for c in rows[header_idx]):
                        break
                except Exception:
                    pass
                header_idx -= 1
            if header_idx < 0:
                header_idx = max(0, start_idx - 1)
            self._file_header_row = list(rows[header_idx] if rows else [])
            self._file_header_row_number = header_idx + 1 if rows else None
            data_start_idx = start_idx
        if data_start_idx >= end_idx:
            self._file_rows = []
            self._file_range_issue = u"Nao existem linhas de dados dentro da janela escolhida."
            return
        self._file_rows = rows[data_start_idx:end_idx]

    def _file_refresh_source(self, keep_columns=True):
        prev_val = self.f_cmbColVal.SelectedIndex if keep_columns else -1
        prev_nome = self.f_cmbColNome.SelectedIndex if keep_columns else -1
        self._file_load_sheet_rows()
        self._file_apply_row_window()
        self._file_populate_columns()
        try:
            if keep_columns and prev_val >= 0 and self.f_cmbColVal.Items.Count > prev_val:
                self.f_cmbColVal.SelectedIndex = prev_val
            if keep_columns and prev_nome >= 0 and self.f_cmbColNome.Items.Count > prev_nome:
                self.f_cmbColNome.SelectedIndex = prev_nome
        except Exception:
            pass

    def _file_refresh_window(self, keep_columns=True):
        prev_val = self.f_cmbColVal.SelectedIndex if keep_columns else -1
        prev_nome = self.f_cmbColNome.SelectedIndex if keep_columns else -1
        self._file_apply_row_window()
        self._file_populate_columns()
        try:
            if keep_columns and prev_val >= 0 and self.f_cmbColVal.Items.Count > prev_val:
                self.f_cmbColVal.SelectedIndex = prev_val
            if keep_columns and prev_nome >= 0 and self.f_cmbColNome.Items.Count > prev_nome:
                self.f_cmbColNome.SelectedIndex = prev_nome
        except Exception:
            pass

    def _file_render_params(self, selected_param=None):
        query = self._file_param_filter_text()
        self.f_cmbParam.Items.Clear()
        self._file_param_map = {}
        for name in sorted(self._file_available_param_map):
            if not _fuzzy_match(query, name):
                continue
            self.f_cmbParam.Items.Add(name)
            self._file_param_map[name] = self._file_available_param_map[name]
        if selected_param:
            for i in range(self.f_cmbParam.Items.Count):
                if str(self.f_cmbParam.Items.GetItemAt(i)) == selected_param:
                    self.f_cmbParam.SelectedIndex = i
                    break
        try:
            has_query = bool(query.strip())
            has_items = self.f_cmbParam.Items.Count > 0
            self.f_cmbParam.IsDropDownOpen = bool(has_query and has_items)
        except Exception:
            pass

    def _file_load_all_params(self, selected_param=None):
        self._file_param_cat_map = self._get_cached_all_params_with_categories()
        self._file_available_param_map = {}
        for name in sorted(self._file_param_cat_map):
            self._file_available_param_map[name] = self._file_param_cat_map[name][0]
        self._file_render_params(selected_param)

    def _file_load_categories(self, filt=''):
        selected_cats = [str(i) for i in self.f_lstCategories.SelectedItems]
        self._file_cat_map = {}
        self.f_lstCategories.Items.Clear()
        all_cats = self._get_cached_filterable_categories()
        allowed_ids = None
        if self._file_inverse_mode:
            param_name = self._file_current_param_name()
            info = self._file_param_cat_map.get(param_name) if param_name else None
            if info:
                allowed_ids = set([cid.IntegerValue for cid in info[1]])
            else:
                allowed_ids = set()
        for name, cat_id in sorted(all_cats.items()):
            if allowed_ids is not None and cat_id.IntegerValue not in allowed_ids:
                continue
            self._file_cat_map[name] = cat_id
            if _fuzzy_match(filt, name):
                self.f_lstCategories.Items.Add(name)
        if self._file_inverse_mode and self._file_current_param_name():
            try:
                self.f_lstCategories.SelectAll()
            except Exception:
                self._select_list_items(self.f_lstCategories, [str(i) for i in self.f_lstCategories.Items])
        else:
            self._select_list_items(self.f_lstCategories, selected_cats)

    def _refresh_file_page(self):
        selected_cats = [str(i) for i in self.f_lstCategories.SelectedItems]
        selected_param = str(self.f_cmbParam.SelectedItem) if self.f_cmbParam.SelectedItem else None
        self._file_inverse_mode = bool(self.f_rdoInverse.IsChecked)
        self._file_set_sheet_visibility()
        if self._file_inverse_mode:
            self._file_load_all_params(selected_param)
        self._file_load_categories(self._file_cat_filter_text())
        if not self._file_inverse_mode:
            self._select_list_items(self.f_lstCategories, selected_cats)
        if selected_cats and not self._file_inverse_mode:
            self.f_cats_selection_changed(None, None)
            for i in range(self.f_cmbParam.Items.Count):
                if str(self.f_cmbParam.Items.GetItemAt(i)) == selected_param:
                    self.f_cmbParam.SelectedIndex = i
                    break
        self._file_refresh_preview_and_status()

    def f_cat_search_got_focus(self, s, a):
        if self.f_txtCatFilter.Text == CAT_PH:
            self.f_txtCatFilter.Text = ""
            self.f_txtCatFilter.Foreground = Brushes.Black

    def f_cat_search_lost_focus(self, s, a):
        if not self.f_txtCatFilter.Text.strip():
            self.f_txtCatFilter.Text = CAT_PH
            self.f_txtCatFilter.Foreground = Brushes.Gray

    def f_cat_filter_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._file_load_categories(self._file_cat_filter_text())

    def f_param_search_got_focus(self, s, a):
        if self.f_txtParamFilter.Text == CAT_PH:
            self.f_txtParamFilter.Text = ""
            self.f_txtParamFilter.Foreground = Brushes.Black
        try:
            if self.f_cmbParam.Items.Count > 0:
                self.f_cmbParam.IsDropDownOpen = True
        except Exception:
            pass

    def f_param_search_lost_focus(self, s, a):
        if not self.f_txtParamFilter.Text.strip():
            self.f_txtParamFilter.Text = CAT_PH
            self.f_txtParamFilter.Foreground = Brushes.Gray

    def f_param_search_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        selected_param = self._file_current_param_name()
        self._file_render_params(selected_param)
        if self._file_inverse_mode:
            self._file_load_categories(self._file_cat_filter_text())

    def f_mode_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        selected_param = self._file_current_param_name()
        self._file_inverse_mode = bool(self.f_rdoInverse.IsChecked)
        if self._file_inverse_mode:
            self.f_lblCatHeader.Text = u"Categorias que suportam o parametro"
            self._file_load_all_params(selected_param)
            self._file_load_categories(self._file_cat_filter_text())
        else:
            self.f_lblCatHeader.Text = u"Categorias"
            self.f_cmbParam.Items.Clear()
            self._file_param_map = {}
            self._file_available_param_map = {}
            self._file_load_categories(self._file_cat_filter_text())
            self.f_cats_selection_changed(None, None)
        self._file_refresh_preview_and_status()

    def f_param_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        try:
            if self.f_cmbParam.SelectedItem is not None:
                self.f_cmbParam.IsDropDownOpen = False
        except Exception:
            pass
        if self._file_inverse_mode:
            param_name = self._file_current_param_name()
            self._file_param_map = {}
            if param_name and param_name in self._file_param_cat_map:
                self._file_param_map[param_name] = self._file_available_param_map.get(
                    param_name, self._file_param_cat_map[param_name][0])
            self._file_load_categories(self._file_cat_filter_text())
        self._file_refresh_preview_and_status()

    def f_browse_file(self, s, a):
        if excel_io is None:
            MessageBox.Show(u"Modulo excel_io nao disponivel.", "Filter Manager"); return
        path = forms.pick_file(title=u"Selecione ficheiro Excel ou CSV")
        if not path:
            return
        self._file_path = path
        self.f_txtFile.Text = os.path.basename(path)
        self.f_txtFile.Foreground = Brushes.Black
        self.f_lblIssues.Text = u""
        self._file_load_sheet_names()
        self._file_refresh_source(keep_columns=False)
        self._file_refresh_preview_and_status()

    def _file_populate_columns(self):
        self.f_cmbColVal.Items.Clear()
        self.f_cmbColNome.Items.Clear()
        self.f_cmbColNome.Items.Add(u"(mesmo que o valor)")
        header_row = self._file_header_row or []
        if not header_row and self._file_rows:
            header_row = self._file_rows[0]
        if not header_row:
            return
        for i, cell in enumerate(header_row):
            label = u"{}: {}".format(chr(65 + i), cell or u"Col {}".format(i + 1))
            self.f_cmbColVal.Items.Add(label)
            self.f_cmbColNome.Items.Add(label)
        if self.f_cmbColVal.Items.Count > 0:
            self.f_cmbColVal.SelectedIndex = 0
        self.f_cmbColNome.SelectedIndex = 2 if self.f_cmbColNome.Items.Count > 2 else 0

    def f_sheet_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._file_selected_sheet = self._file_selected_sheet_name()
        self._file_refresh_source()
        self._file_refresh_preview_and_status()

    def f_range_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._file_refresh_window()
        self._file_refresh_preview_and_status()

    def f_cleaning_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._file_refresh_preview_and_status()

    def f_col_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._file_refresh_preview_and_status()

    def f_option_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        try:
            if _color_mode(self.f_rdoPalette, self.f_rdoNoColor) != 'none':
                self.f_chkAplicarVista.IsChecked = True
        except Exception:
            pass
        self._file_refresh_preview_and_status()

    def _file_indices(self):
        return self.f_cmbColVal.SelectedIndex, self.f_cmbColNome.SelectedIndex - 1

    def _file_build_pairs(self):
        val_idx, nome_idx = self._file_indices()
        if val_idx < 0:
            return []
        stats = {
            'zone_rows': len(self._file_rows or []),
            'data_rows': 0,
            'blank_rows': 0,
            'empty_values': 0,
            'duplicates': 0,
            'valid': 0,
        }
        pairs = []
        seen = set()
        rows = self._file_rows or []
        for row in rows:
            stats['data_rows'] += 1
            cleaned_row = [self._file_normalize_text(c) if bool(self.f_chkTrimText.IsChecked) else (c or u'') for c in row]
            if bool(self.f_chkDropBlankRows.IsChecked) and not any(cleaned_row):
                stats['blank_rows'] += 1
                continue
            if val_idx >= len(cleaned_row):
                stats['empty_values'] += 1
                continue
            val = cleaned_row[val_idx] if bool(self.f_chkTrimText.IsChecked) else (row[val_idx].strip() if row[val_idx] else u'')
            nome = cleaned_row[nome_idx] if (0 <= nome_idx < len(cleaned_row)) else val
            if bool(self.f_chkDropEmptyValues.IsChecked) and not val:
                stats['empty_values'] += 1
                continue
            key = val
            if bool(self.f_chkDeduplicate.IsChecked) and key in seen:
                stats['duplicates'] += 1
                continue
            seen.add(key)
            pairs.append((val, nome or val))
            stats['valid'] += 1
        self._file_stats = stats
        return pairs

    def _file_scan_filtered_pairs(self, pairs):
        if not bool(self.f_chkScanFilter.IsChecked):
            return pairs, True
        cats = [str(i) for i in self.f_lstCategories.SelectedItems]
        param_name = self._file_current_param_name()
        if not cats or not param_name:
            return [], False
        param_id = self._file_param_map.get(param_name)
        if not param_id:
            return [], False
        try:
            raw_cat_ids = [self._file_cat_map[c] for c in cats if c in self._file_cat_map]
            project_vals = set(revit_query.get_unique_values(self.doc, raw_cat_ids, param_id))
            return [(v, n) for v, n in pairs if v in project_vals], True
        except Exception:
            return [], False

    def _file_recompute_preview_state(self):
        base_pairs = self._file_build_pairs()
        self._file_preview_total = len(base_pairs)
        self._file_preview_pairs, self._file_preview_ready = self._file_scan_filtered_pairs(base_pairs)

    def _file_refresh_preview_and_status(self):
        self._file_recompute_preview_state()
        self._file_update_preview()
        self._file_update_status()

    def _file_update_preview(self):
        self.f_lstPreview.Items.Clear()
        pairs, ready = self._file_preview_pairs, self._file_preview_ready
        if not ready:
            if bool(self.f_chkScanFilter.IsChecked):
                self.f_lstPreview.Items.Add(u"Escolha categorias e parametro.")
            return
        for val, nome in pairs[:8]:
            self.f_lstPreview.Items.Add(u"{} -> {}".format(val, nome) if val != nome else val)

    def _file_update_status(self):
        if self._file_sheet_names and len(self._file_sheet_names) > 1 and not self._file_selected_sheet:
            self.f_lblStatus.Text = u"Escolha uma folha para carregar os dados."
            self.f_lblSummary.Text = u""
            if not self.f_lblIssues.Text:
                self.f_lblIssues.Text = u"Este ficheiro tem varias folhas. Escolha a folha antes de continuar."
            return
        pairs, ready = self._file_preview_pairs, self._file_preview_ready
        if not ready:
            self.f_lblStatus.Text = u"Escolha categorias e parametro para validar valores existentes."
            self.f_lblSummary.Text = u""
            if not self.f_lblIssues.Text:
                self.f_lblIssues.Text = u""
            return
        total = self._file_preview_total
        stats = self._file_stats or {}
        n = len(pairs)
        if bool(self.f_chkScanFilter.IsChecked):
            self.f_lblStatus.Text = u"{} de {} filtro(s) a criar".format(n, total)
        else:
            self.f_lblStatus.Text = u"{} filtro(s) a criar".format(n) if n else u""
        self.f_lblSummary.Text = u"{} linha(s) na zona | {} valida(s) | {} vazia(s) | {} sem valor | {} duplicada(s)".format(
            stats.get('zone_rows', 0),
            stats.get('valid', 0),
            stats.get('blank_rows', 0),
            stats.get('empty_values', 0),
            stats.get('duplicates', 0))
        issues = []
        if self._file_header_row_number:
            issues.append(u"Cabecalho: linha {}".format(self._file_header_row_number))
        if self._file_range_issue:
            issues.append(self._file_range_issue)
        if bool(self.f_chkScanFilter.IsChecked):
            ignored_existing = max(0, total - n)
            if ignored_existing:
                issues.append(u"{} valor(es) nao existem no projeto".format(ignored_existing))
        if stats.get('blank_rows', 0):
            issues.append(u"{} linha(s) vazia(s) ignorada(s)".format(stats.get('blank_rows', 0)))
        if stats.get('empty_values', 0):
            issues.append(u"{} valor(es) vazio(s) ignorado(s)".format(stats.get('empty_values', 0)))
        if stats.get('duplicates', 0):
            issues.append(u"{} duplicado(s) removido(s)".format(stats.get('duplicates', 0)))
        self.f_lblIssues.Text = u" | ".join(issues[:3])

    def f_cats_selection_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self._file_inverse_mode:
            self._file_refresh_preview_and_status()
            return
        cats = [str(i) for i in self.f_lstCategories.SelectedItems]
        selected_param = self._file_current_param_name()
        self._file_available_param_map = {}
        if not cats:
            self.f_cmbParam.Items.Clear()
            self._file_param_map = {}
            self._file_refresh_preview_and_status()
            return
        self._file_available_param_map = self._get_cached_strict_params([self._file_cat_map[c] for c in cats])
        self._file_render_params(selected_param)
        self._file_refresh_preview_and_status()

    def f_criar_filtros(self, s, a):
        if not self._file_rows:
            MessageBox.Show(u"Selecione um ficheiro.", "Filter Manager"); return
        cats = [str(i) for i in self.f_lstCategories.SelectedItems]
        if not cats:
            MessageBox.Show(u"Selecione pelo menos uma categoria.", "Filter Manager"); return
        param_name = str(self.f_cmbParam.SelectedItem) if self.f_cmbParam.SelectedItem else None
        if not param_name:
            MessageBox.Show(u"Selecione um parametro.", "Filter Manager"); return
        pairs = self._file_build_pairs()
        if not pairs:
            MessageBox.Show(u"Nenhum valor encontrado no ficheiro.", "Filter Manager"); return
        mode = _color_mode(self.f_rdoPalette, self.f_rdoNoColor)
        val_idx, nome_idx = self._file_indices()
        prefix = self.f_txtPrefix.Text.strip()
        raw_cat_ids = [self._file_cat_map[c] for c in cats]
        param_id = self._file_param_map.get(param_name)
        if not param_id:
            MessageBox.Show(u"O parametro selecionado nao e valido para as categorias selecionadas.", "Filter Manager"); return
        if bool(self.f_chkScanFilter.IsChecked):
            pairs, ready = self._file_scan_filtered_pairs(pairs)
            if not ready:
                MessageBox.Show(u"Escolha categorias e parametro para validar valores existentes.", "Filter Manager"); return
            if not pairs:
                MessageBox.Show(u"Nenhum valor do ficheiro encontrado no projeto.", "Filter Manager"); return
        apply_view = bool(self.f_chkAplicarVista.IsChecked)
        if mode != 'none':
            apply_view = True
            self.f_chkAplicarVista.IsChecked = True
        view = self.doc.ActiveView if apply_view else None
        if not _validate_override_view(view):
            return
        colors = _resolve_workflow_colors(len(pairs), mode, view)
        if colors is None:
            MessageBox.Show(u"Criacao cancelada ou paleta vazia.", "Filter Manager"); return

        names = [_filter_name(prefix, v, n) for v, n in pairs]
        created_names, reused_names, failed_items = _create_filters_safely(
            self.doc, pairs, prefix, List[ElementId](raw_cat_ids), param_id)
        applied = 0
        failed = 0
        if view is not None:
            with revit.Transaction("MTQ Filters - Aplicar filtros a vista"):
                applied, failed = _apply_named_filters_to_view(self.doc, view, names, colors)

        msg = u"{} criados".format(len(created_names))
        if reused_names:
            msg += u", {} reutilizados".format(len(reused_names))
        if view is not None:
            msg += u", {} aplicados a vista".format(applied)
            if failed:
                msg += u", {} falharam".format(failed)
        if failed_items:
            msg += u", {} falharam na criacao".format(len(failed_items))
        msg += u" com '{}'.".format(param_name)
        self.f_lblStatus.Text = msg
        self._set_status(msg)
        self._refresh_filter_pages()

    # Edit filters
    def _init_edit_page(self):
        self._fill_apply_target_options(self.cmbEditApplyTarget, False)
        self._refresh_edit_page(True)

    def _edit_build_pattern_options(self):
        self._edit_pattern_options = [
            PatternOption(PATTERN_NONE, PATTERN_NONE),
            PatternOption(PATTERN_SOLID, PATTERN_SOLID),
        ]
        for name in self._edit_pattern_names:
            if name in (PATTERN_SOLID, PATTERN_NONE):
                continue
            self._edit_pattern_options.append(
                PatternOption(name, name, self._edit_fill_patterns.get(name)))

    def _edit_load_filters(self, prefix):
        view, target_label, target_err = self._selected_apply_target(self.cmbEditApplyTarget)
        if view is None and target_label != APPLY_ACTIVE_TEMPLATE:
            view = self.doc.ActiveView
        solid = ph.get_solid_fill_pattern_id(self.doc)
        entries = []
        filters = sorted(
            [f for f in FilteredElementCollector(self.doc).OfClass(ParameterFilterElement)
             if _fuzzy_match(prefix, f.Name)],
            key=lambda x: x.Name)
        for f in filters:
            color_hex = ''
            fill_name = PATTERN_NONE
            in_view = _view_has_filter(view, f.Id) if view is not None else False
            enabled = _get_filter_enabled(view, f.Id) if in_view else False
            visible = _get_filter_visibility(view, f.Id) if in_view else True
            try:
                if in_view:
                    ogs = view.GetFilterOverrides(f.Id)
                    rc = ogs.SurfaceForegroundPatternColor
                    if rc.IsValid:
                        color_hex = ph.revit_color_to_hex(rc) or color_hex
                    pat_id = ogs.SurfaceForegroundPatternId
                    if pat_id == ElementId.InvalidElementId:
                        fill_name = PATTERN_NONE
                    elif solid is not None and pat_id == solid:
                        fill_name = PATTERN_SOLID
                    elif pat_id and pat_id.IntegerValue > 0:
                        for nm, pid in self._edit_fill_patterns.items():
                            if pid is not None and pid == pat_id:
                                fill_name = nm
                                break
            except Exception:
                pass
            entries.append(FilterEntry(
                f.Id, f.Name, color_hex, fill_name,
                enabled=enabled, visible=visible, in_view=in_view))
        self._edit_entries = entries
        self.e_dgFiltros.ItemsSource = None
        self.e_dgFiltros.ItemsSource = entries
        if target_err:
            self.e_lblStatus.Text = u"{} {} filtro(s) carregados do projeto.".format(
                target_err,
                len(entries))
        else:
            self.e_lblStatus.Text = (
                u"{} filtro(s) carregados".format(len(entries))
                if entries else
                u"Nenhum filtro encontrado"
            )

    def _edit_targets_for_entry(self, entry):
        try:
            if self._edit_bulk_targets and entry in self._edit_bulk_targets:
                return list(self._edit_bulk_targets)
        except Exception:
            pass
        try:
            selected = [i for i in self.e_dgFiltros.SelectedItems]
            if entry in selected and selected:
                return selected
        except Exception:
            pass
        return [entry]

    def _edit_capture_bulk_targets(self, entry=None):
        try:
            selected = [i for i in self.e_dgFiltros.SelectedItems]
            if selected and (entry is None or entry in selected):
                self._edit_bulk_targets = selected
            elif entry is not None:
                self._edit_bulk_targets = [entry]
            else:
                self._edit_bulk_targets = []
        except Exception:
            self._edit_bulk_targets = [entry] if entry is not None else []

    def _edit_control_preview_mouse_down(self, sender, args):
        try:
            self._edit_capture_bulk_targets(sender.DataContext)
        except Exception:
            self._edit_capture_bulk_targets(None)

    def e_edit_control_preview_mouse_down(self, sender, args):
        try:
            self._edit_capture_bulk_targets(sender.Tag)
        except Exception:
            self._edit_capture_bulk_targets(None)

    def e_toggle_preview_mouse_down(self, sender, args):
        try:
            self._edit_capture_bulk_targets(sender.Tag)
        except Exception:
            self._edit_capture_bulk_targets(None)

    def e_enabled_click(self, sender, args):
        entry = getattr(sender, 'Tag', None)
        if entry is None:
            return
        value = bool(sender.IsChecked)
        for target in self._edit_targets_for_entry(entry):
            target.Enabled = value
        try:
            self.e_dgFiltros.Items.Refresh()
        except Exception:
            pass

    def e_visible_click(self, sender, args):
        entry = getattr(sender, 'Tag', None)
        if entry is None:
            return
        value = bool(sender.IsChecked)
        for target in self._edit_targets_for_entry(entry):
            target.Visible = value
        try:
            self.e_dgFiltros.Items.Refresh()
        except Exception:
            pass

    def _edit_used_colors(self):
        used = []
        for entry in self._edit_entries:
            if entry.ColorHex:
                used.append(entry.ColorHex)
        return used

    def e_carregar(self, s, a):
        self._edit_dirty = True
        self._refresh_edit_page(True)

    def e_search_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._refresh_edit_page()

    def e_target_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._edit_dirty = True
        self._refresh_edit_page(True)

    def e_grid_right_click(self, sender, args):
        row = _find_parent_of_type(args.OriginalSource, 'DataGridRow')
        if row is None:
            return
        try:
            selected = [i for i in self.e_dgFiltros.SelectedItems]
            if row.Item not in selected:
                self.e_dgFiltros.SelectedItem = row.Item
            self._edit_capture_bulk_targets(row.Item)
        except Exception:
            pass

    def e_rename_filter(self, s, a):
        entry = self.e_dgFiltros.SelectedItem
        if entry is None:
            MessageBox.Show(u"Selecione um filtro para renomear.", "Editar Filtros"); return
        old_name = entry.Name
        new_name = _ask_text(self, u"Renomear filtro", u"Novo nome do filtro:", old_name)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        existing = _project_filters_by_name(self.doc)
        other = existing.get(new_name)
        if other and other.Id != entry.FilterId:
            MessageBox.Show(u"Ja existe um filtro com esse nome no projeto.", "Editar Filtros"); return
        try:
            with revit.Transaction("MTQ Filters - Renomear filtro"):
                self.doc.GetElement(entry.FilterId).Name = new_name
            entry.Name = new_name
            self.e_dgFiltros.Items.Refresh()
            self._edit_last_search = self._current_edit_search()
            try:
                self._transfer_load_project_filters()
                self.l_procurar(None, None)
            except Exception:
                pass
            self._set_status(u"Filtro renomeado.")
        except Exception as e:
            MessageBox.Show(u"Nao foi possivel renomear o filtro.\n" + str(e), "Editar Filtros")

    def e_delete_filter(self, s, a):
        entry = self.e_dgFiltros.SelectedItem
        if entry is None:
            MessageBox.Show(u"Selecione pelo menos um filtro para apagar.", "Editar Filtros"); return
        targets = self._edit_targets_for_entry(entry)
        if not targets:
            MessageBox.Show(u"Selecione pelo menos um filtro para apagar.", "Editar Filtros"); return
        count = len(targets)
        prompt = (
            u"Apagar {} filtro do projeto?".format(count)
            if count == 1 else
            u"Apagar {} filtros do projeto?".format(count)
        )
        if MessageBox.Show(prompt, "Editar Filtros", MessageBoxButton.YesNo) != MessageBoxResult.Yes:
            return
        deleted = 0
        failed = 0
        with revit.Transaction("MTQ Filters - Apagar filtros"):
            for target in targets:
                try:
                    self.doc.Delete(target.FilterId)
                    deleted += 1
                except Exception:
                    failed += 1
        self._edit_dirty = True
        self._refresh_edit_page(True)
        try:
            self._transfer_load_project_filters()
            self.l_procurar(None, None)
        except Exception:
            pass
        msg = (
            u"{} filtro apagado".format(deleted)
            if deleted == 1 else
            u"{} filtros apagados".format(deleted)
        )
        if failed:
            msg += u"; {} falharam".format(failed)
        self.e_lblStatus.Text = msg
        self._set_status(msg)

    def e_color_btn_click(self, sender, args):
        entry = sender.Tag
        if entry is None:
            return
        dlg = PaletteColorPickerWindow(entry.ColorHex, self._edit_used_colors())
        dlg.Owner = self
        dlg.ShowDialog()
        if dlg.ManagePalette:
            self.nav_colors(None, None)
            self._colors_refresh()
            return
        targets = self._edit_targets_for_entry(entry)
        if dlg.Result:
            for target in targets:
                target.ColorHex = dlg.Result
                if target.FillPattern == PATTERN_NONE:
                    target.FillPattern = PATTERN_SOLID
                target.refresh_brush()
            self.e_dgFiltros.Items.Refresh()
        elif dlg.Result == '':
            for target in targets:
                target.ColorHex = ''
                target.FillPattern = PATTERN_NONE
                target.refresh_brush()
            self.e_dgFiltros.Items.Refresh()

    def e_fill_pattern_loaded(self, sender, args):
        try:
            sender.SelectionChanged -= self._edit_fill_pattern_changed
        except Exception:
            pass
        try:
            sender.DropDownClosed -= self._edit_fill_pattern_committed
        except Exception:
            pass
        sender.ItemsSource = self._edit_pattern_options
        entry = sender.DataContext
        sender.Tag = entry
        if entry and hasattr(entry, 'FillPattern'):
            selected = None
            for opt in self._edit_pattern_options:
                if opt.Name == entry.FillPattern:
                    selected = opt
                    break
            sender.SelectedItem = selected or self._edit_pattern_options[0]
        try:
            sender.PreviewMouseDown -= self._edit_control_preview_mouse_down
        except Exception:
            pass
        try:
            sender.PreviewMouseDown += self._edit_control_preview_mouse_down
        except Exception:
            pass
        sender.DropDownClosed += self._edit_fill_pattern_committed

    def _edit_fill_pattern_changed(self, sender, args):
        entry = sender.DataContext
        if entry and hasattr(entry, 'FillPattern') and sender.SelectedItem is not None:
            for target in self._edit_targets_for_entry(entry):
                target.FillPattern = sender.SelectedItem.Name
            try:
                self.e_dgFiltros.Items.Refresh()
            except Exception:
                pass

    def _edit_fill_pattern_committed(self, sender, args):
        entry = getattr(sender, 'Tag', None)
        if not entry or not hasattr(entry, 'FillPattern') or sender.SelectedItem is None:
            return
        selected_name = sender.SelectedItem.Name
        if entry.FillPattern == selected_name:
            return
        for target in self._edit_targets_for_entry(entry):
            target.FillPattern = selected_name
        try:
            self.e_dgFiltros.Items.Refresh()
        except Exception:
            pass

    def e_aplicar(self, s, a):
        if not self._edit_entries:
            MessageBox.Show(u"Carregue filtros primeiro.", "Editar Filtros"); return
        view, target_label, target_err = self._selected_apply_target(self.cmbEditApplyTarget)
        if target_err:
            MessageBox.Show(target_err, "Editar Filtros"); return
        if view is None:
            MessageBox.Show(u"Escolha um destino em 'Aplicar a'.", "Editar Filtros"); return
        if not _validate_override_view(view):
            return
        solid = ph.get_solid_fill_pattern_id(self.doc)
        done = 0
        skipped = 0
        failed = 0
        with revit.Transaction("MTQ Filters - Editar cores"):
            for entry in self._edit_entries:
                try:
                    should_apply_to_view = bool(entry.InView) or bool(entry.Enabled)
                    if not should_apply_to_view:
                        skipped += 1
                        continue
                    rgb = ph.parse_color_input(entry.ColorHex)
                    pat_id = self._edit_fill_patterns.get(entry.FillPattern)
                    if entry.FillPattern == PATTERN_NONE:
                        pat_id = ElementId.InvalidElementId
                    elif pat_id is None and entry.FillPattern == PATTERN_SOLID:
                        pat_id = solid
                    if not _is_valid_override_pattern(self.doc, pat_id, solid):
                        failed += 1
                        continue
                    ov = ph.build_revit_override(rgb, solid, pat_id)
                    ok, err = _apply_filter_override(view, entry.FilterId, ov)
                    if not ok:
                        failed += 1
                        continue
                    vis_ok, vis_err = _set_filter_visibility(view, entry.FilterId, entry.Visible)
                    en_ok, en_err = _set_filter_enabled(view, entry.FilterId, entry.Enabled)
                    if not vis_ok or not en_ok:
                        failed += 1
                        continue
                    entry.InView = True
                    done += 1
                except Exception:
                    failed += 1
        msg = u"{} de {} filtros atualizados em {}".format(done, len(self._edit_entries), target_label.lower())
        if skipped:
            msg += u"; {} sem alterar".format(skipped)
        if failed:
            msg += u"; {} falharam".format(failed)
        self.e_lblStatus.Text = msg
        self._set_status(msg)
        self._edit_dirty = True
        self._refresh_edit_page(True)

    # Export/import
    def _init_transfer_page(self):
        self._transfer_load_project_filters()

    def _transfer_load_project_filters(self):
        selected = set(str(i) for i in self.x_lstExpFilters.SelectedItems)
        query = self.x_txtExpSearch.Text.strip()
        if query == "pesquisar...":
            query = ""
        self.x_lstExpFilters.Items.Clear()
        self._exp_map = {}
        for f in FilteredElementCollector(self.doc).OfClass(ParameterFilterElement):
            self._exp_map[f.Name] = f
        for name in sorted(self._exp_map):
            if _fuzzy_match(query, name):
                self.x_lstExpFilters.Items.Add(name)
                if name in selected:
                    self.x_lstExpFilters.SelectedItems.Add(name)
        self._transfer_update_exp_count()

    def _transfer_update_exp_count(self):
        self.x_lblExpCount.Text = u"{} / {} selecionados".format(
            self.x_lstExpFilters.SelectedItems.Count, self.x_lstExpFilters.Items.Count)

    def x_tab_changed(self, s, a):
        try:
            self.x_btnAcao.Content = "Importar" if self.x_tabControl.SelectedIndex == 1 else "Exportar"
        except Exception:
            pass

    def x_exp_search_focus(self, s, a):
        if self.x_txtExpSearch.Text == "pesquisar...":
            self.x_txtExpSearch.Text = ""
            self.x_txtExpSearch.Foreground = Brushes.Black

    def x_exp_search_unfocus(self, s, a):
        if not self.x_txtExpSearch.Text.strip():
            self.x_txtExpSearch.Text = "pesquisar..."
            self.x_txtExpSearch.Foreground = Brushes.Gray

    def x_exp_search_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        filt = self.x_txtExpSearch.Text.lower()
        if filt == "pesquisar...":
            return
        self.x_lstExpFilters.Items.Clear()
        for name in sorted(self._exp_map):
            if _fuzzy_match(filt, name):
                self.x_lstExpFilters.Items.Add(name)
        self._transfer_update_exp_count()

    def x_exp_selection_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._transfer_update_exp_count()

    def x_exp_select_all(self, s, a):
        self.x_lstExpFilters.SelectAll()
        self._transfer_update_exp_count()

    def x_exp_clear_all(self, s, a):
        self.x_lstExpFilters.UnselectAll()
        self._transfer_update_exp_count()

    def _project_dir(self):
        try:
            p = self.doc.PathName
            return os.path.dirname(p) if p else ''
        except Exception:
            return ''

    def _project_stem(self):
        try:
            p = self.doc.PathName
            return os.path.splitext(os.path.basename(p))[0] if p else u'filtros'
        except Exception:
            return u'filtros'

    def x_browse_import(self, s, a):
        from Microsoft.Win32 import OpenFileDialog
        dlg = OpenFileDialog()
        dlg.Title = u"Selecione ficheiro JSON de filtros"
        dlg.Filter = u"Filter Manager JSON|*.json|Todos os ficheiros|*.*"
        proj_dir = self._project_dir()
        if proj_dir and os.path.isdir(proj_dir):
            dlg.InitialDirectory = proj_dir
        if not dlg.ShowDialog():
            return
        try:
            with open(dlg.FileName, 'r') as f:
                self._imp_data = json.load(f)
        except Exception as e:
            MessageBox.Show(u"Erro ao ler ficheiro:\n" + str(e), "Filter Manager"); return
        self.x_txtImpFile.Text = os.path.basename(dlg.FileName)
        self.x_txtImpFile.Foreground = Brushes.Black
        self.x_lstImpFilters.Items.Clear()
        for entry in self._imp_data:
            self.x_lstImpFilters.Items.Add(entry.get('name', '?'))
        self.x_lstImpFilters.SelectAll()
        self.x_lblImpCount.Text = u"{} filtro(s)".format(len(self._imp_data))

    def x_imp_select_all(self, s, a): self.x_lstImpFilters.SelectAll()
    def x_imp_clear_all(self, s, a): self.x_lstImpFilters.UnselectAll()

    def x_acao_click(self, s, a):
        if self.x_tabControl.SelectedIndex == 0:
            self._transfer_export()
        else:
            self._transfer_import()

    def _transfer_export(self):
        sel_names = [str(i) for i in self.x_lstExpFilters.SelectedItems]
        if not sel_names:
            MessageBox.Show(u"Selecione filtros para exportar.", "Filter Manager"); return
        data = ph.export_filters_to_dict(
            self.doc,
            [self._exp_map[n] for n in sel_names if n in self._exp_map],
            bool(self.x_chkExpCores.IsChecked),
            False)
        from Microsoft.Win32 import SaveFileDialog
        dlg = SaveFileDialog()
        dlg.Title = u"Guardar filtros exportados"
        dlg.Filter = u"Filter Manager JSON|*.json|Todos os ficheiros|*.*"
        dlg.DefaultExt = u"json"
        proj_dir = self._project_dir()
        if proj_dir and os.path.isdir(proj_dir):
            dlg.InitialDirectory = proj_dir
        dlg.FileName = u"{}_MTQ_filtros.json".format(self._project_stem())
        if not dlg.ShowDialog():
            return
        try:
            with open(dlg.FileName, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=True)
            msg = u"{} filtros exportados.".format(len(data))
            self._set_status(msg)
            MessageBox.Show(msg + u"\n" + dlg.FileName, "Filter Manager")
        except Exception as e:
            MessageBox.Show(u"Erro ao guardar:\n" + str(e), "Filter Manager")

    def _transfer_import(self):
        sel_idx = [self.x_lstImpFilters.Items.IndexOf(i) for i in self.x_lstImpFilters.SelectedItems]
        if not sel_idx:
            MessageBox.Show(u"Selecione filtros para importar.", "Filter Manager"); return
        cat_map = revit_query.get_categories(self.doc)
        ok = 0
        skipped = []
        created_filters = []
        fill_patterns = _get_revit_fill_pattern_map(self.doc)
        solid = ph.get_solid_fill_pattern_id(self.doc)
        import_overrides = bool(self.x_chkImpCores.IsChecked)
        for idx in sel_idx:
            entry = self._imp_data[idx]
            name = entry.get('name', '')
            rules_lst = entry.get('rules', [])
            if len(rules_lst) != 1:
                skipped.append(name + u" (regra complexa)")
                continue
            cat_ids = [cat_map[c] for c in entry.get('categories', []) if c in cat_map]
            if not cat_ids:
                skipped.append(name + u" (categorias nao encontradas)")
                continue
            pname = rules_lst[0].get('param', '')
            value = rules_lst[0].get('value', '')
            param_id = revit_query.get_filterable_params(self.doc, cat_ids).get(pname)
            if not param_id:
                skipped.append(name + u" (parametro nao encontrado)")
                continue
            try:
                prefix_imp = name[:-len(value)] if (value and name.endswith(value)) else ''
                fname = _filter_name(prefix_imp, value, value)
                color_hex = entry.get('color') if import_overrides else None
                color_rgb = ph.parse_color_input(color_hex) if color_hex else None
                pattern_name = entry.get('pattern') if import_overrides else PATTERN_NONE
                pattern_id = _pattern_id_from_export(self.doc, fill_patterns, pattern_name, solid)
                if import_overrides and not _is_valid_override_pattern(self.doc, pattern_id, solid):
                    skipped.append(name + u" (padrao nao valido para overrides)")
                    continue
                created_names, reused_names, failed_items = _create_filters_safely(
                    self.doc, [(value, value)], prefix_imp, List[ElementId](cat_ids), param_id)
                should_apply_override = import_overrides and bool(self.x_chkImpVista.IsChecked)
                if created_names or reused_names:
                    ok += 1
                    if should_apply_override:
                        created_filters.append((fname, color_rgb, pattern_id))
                elif failed_items:
                    reason = failed_items[0][1]
                    skipped.append(name + u" (" + reason + u")")
                else:
                    skipped.append(name + u" (ja existe ou erro ao criar)")
            except Exception as e:
                skipped.append(name + u": " + str(e))
        if bool(self.x_chkImpVista.IsChecked) and created_filters:
            view = self.doc.ActiveView
            with revit.Transaction("MTQ Filters - Aplicar filtros importados"):
                override_map = dict((n, (rgb, pat)) for n, rgb, pat in created_filters)
                for f in FilteredElementCollector(self.doc).OfClass(ParameterFilterElement):
                    if f.Name in override_map:
                        color_rgb, pattern_id = override_map[f.Name]
                        ov = ph.build_revit_override(color_rgb, solid, pattern_id)
                        _apply_filter_override(view, f.Id, ov)
        msg = u"{} filtros importados.".format(ok)
        if skipped:
            msg += u" Ignorados: {}.".format(len(skipped))
        self._set_status(msg)
        self._refresh_filter_pages()
        MessageBox.Show(msg, "Filter Manager")

    # Clean
    def _init_clean_page(self):
        self.l_rdoView.Checked += lambda s, a: self._clean_update_scope()
        self.l_rdoProject.Checked += lambda s, a: self._clean_update_scope()
        self._clean_update_scope()
        self.l_procurar(None, None)

    def _clean_update_scope(self):
        if self.l_rdoView.IsChecked:
            self.l_lblScope.Text = u"Remove os filtros da vista ativa e mantem os filtros no projeto."
        else:
            self.l_lblScope.Text = u"Apaga os filtros do projeto. Esta acao e definitiva."
        try:
            self.l_procurar(None, None)
        except Exception:
            pass

    def l_procurar(self, s, a):
        query = self.l_txtPrefix.Text.strip()
        self._clean_filter_map = {}
        self.l_lstFilters.Items.Clear()
        if bool(self.l_rdoProject.IsChecked):
            filters = FilteredElementCollector(self.doc).OfClass(ParameterFilterElement)
        else:
            filters = []
            try:
                for fid in self.doc.ActiveView.GetFilters():
                    f = self.doc.GetElement(fid)
                    if f is not None and hasattr(f, 'Name') and hasattr(f, 'Id'):
                        filters.append(f)
            except Exception:
                filters = []
        for f in filters:
            if _fuzzy_match(query, f.Name):
                self._clean_filter_map[f.Name] = f.Id
        for name in sorted(self._clean_filter_map):
            self.l_lstFilters.Items.Add(name)
        self.l_lblCount.Text = u"{} filtro(s)".format(self.l_lstFilters.Items.Count)

    def l_search_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self.l_procurar(None, None)

    def l_select_all(self, s, a): self.l_lstFilters.SelectAll()
    def l_clear_sel(self, s, a): self.l_lstFilters.UnselectAll()

    def l_apagar(self, s, a):
        sel = [str(i) for i in self.l_lstFilters.SelectedItems]
        if not sel:
            MessageBox.Show(u"Selecione filtros para limpar.", "Filter Manager"); return
        delete_proj = bool(self.l_rdoProject.IsChecked)
        action = u"apagados do projeto" if delete_proj else u"removidos da vista ativa"
        if MessageBox.Show(
            u"{} filtro(s) serao {}.\nContinuar?".format(len(sel), action),
            "Confirmar", MessageBoxButton.YesNo) != MessageBoxResult.Yes:
            return
        view = self.doc.ActiveView
        done = 0
        skipped = 0
        failed = 0
        processed = []
        with revit.Transaction("MTQ Filters - Limpar filtros"):
            for name in sel:
                fid = self._clean_filter_map.get(name)
                if not fid:
                    continue
                try:
                    if delete_proj:
                        self.doc.Delete(fid)
                    else:
                        if not _view_has_filter(view, fid):
                            skipped += 1
                            processed.append(name)
                            continue
                        view.RemoveFilter(fid)
                    done += 1
                    processed.append(name)
                except Exception:
                    failed += 1
        for name in processed:
            self._clean_filter_map.pop(name, None)
            try:
                self.l_lstFilters.Items.Remove(name)
            except Exception:
                pass
        msg = u"{} filtros processados".format(done)
        if skipped:
            msg += u"; {} ja nao estavam na vista".format(skipped)
        if failed:
            msg += u"; {} falharam".format(failed)
            MessageBox.Show(msg, "Filter Manager")
        self.l_lblCount.Text = msg
        self._set_status(msg)
        if delete_proj:
            try:
                self._refresh_edit_page()
                self._transfer_load_project_filters()
            except Exception:
                pass

    # Schemes
    def _init_schemes_page(self):
        self._schemes_refresh(True)

    def _scheme_search_text(self):
        try:
            text = self.sch_txtSearch.Text
            return '' if text == CAT_PH else text
        except Exception:
            return ''

    def _schemes_refresh(self, force=False):
        if scheme_helpers is None:
            return
        selected = None
        try:
            selected = str(self.sch_lstSchemes.SelectedItem) if self.sch_lstSchemes.SelectedItem else None
        except Exception:
            pass
        if force or self._schemes_dirty or self._schemes is None:
            self._schemes = scheme_helpers.load_schemes()
            self._schemes_dirty = False
        query = self._scheme_search_text()
        self.sch_lstSchemes.Items.Clear()
        for scheme in self._schemes:
            name = scheme.get('name', '')
            if _fuzzy_match(query, name):
                self.sch_lstSchemes.Items.Add(name)
                if name == selected:
                    self.sch_lstSchemes.SelectedItem = name
        self.sch_lblStatus.Text = u"{} esquema(s)".format(len(self._schemes))
        try:
            if self.sch_lstSchemes.SelectedIndex < 0 and self.sch_lstSchemes.Items.Count > 0:
                self.sch_lstSchemes.SelectedIndex = 0
        except Exception:
            pass

    def _scheme_current_data(self):
        if scheme_helpers is None:
            return None
        name = str(self.sch_lstSchemes.SelectedItem) if self.sch_lstSchemes.SelectedItem else None
        return scheme_helpers.find_scheme(self._schemes, name) if name else None

    def _scheme_load_to_ui(self, scheme):
        self._current_scheme = scheme
        self._scheme_items = []
        if not scheme:
            self.sch_txtName.Text = ''
            self.sch_txtPrefix.Text = ''
            self.sch_lblInfo.Text = ''
            self.sch_dgItems.ItemsSource = None
            return
        self.sch_txtName.Text = scheme.get('name', '')
        self.sch_txtPrefix.Text = scheme.get('prefix', '')
        self.sch_chkApplyView.IsChecked = scheme.get('apply_view', True)
        self.sch_chkReplace.IsChecked = scheme.get('replace_existing', True)
        for item in scheme.get('items', []):
            self._scheme_items.append(SchemeItem(item))
        self.sch_dgItems.ItemsSource = None
        self.sch_dgItems.ItemsSource = self._scheme_items
        cats = scheme.get('categories', [])
        param = scheme.get('param_name', '')
        self.sch_lblInfo.Text = u"{} categoria(s) | {}".format(len(cats), param or u"Parametro desconhecido")

    def _scheme_sync_from_ui(self):
        scheme = self._current_scheme
        if not scheme:
            return None
        old_name = scheme.get('name', '')
        scheme['name'] = self.sch_txtName.Text.strip() or old_name or u"Esquema"
        scheme['prefix'] = self.sch_txtPrefix.Text.strip()
        scheme['apply_view'] = bool(self.sch_chkApplyView.IsChecked)
        scheme['replace_existing'] = bool(self.sch_chkReplace.IsChecked)
        for item in self._scheme_items:
            item.sync()
        scheme['items'] = [item.Data for item in self._scheme_items]
        return scheme

    def _scheme_filter_name(self, scheme, item):
        prefix = (scheme.get('prefix', '') or '').strip()
        if not prefix:
            return item.FilterName
        value = item.Value
        try:
            rules = item.Data.get('rules', [])
            if rules:
                value = rules[0].get('value', value)
        except Exception:
            pass
        value = value or item.FilterName
        display = value
        if item.FilterName and u" - " in item.FilterName:
            display = item.FilterName.split(u" - ", 1)[1]
        return _filter_name(prefix, value, display)

    def sch_search_got_focus(self, s, a):
        if self.sch_txtSearch.Text == CAT_PH:
            self.sch_txtSearch.Text = ''
            self.sch_txtSearch.Foreground = Brushes.Black

    def sch_search_lost_focus(self, s, a):
        if not self.sch_txtSearch.Text.strip():
            self.sch_txtSearch.Text = CAT_PH
            self.sch_txtSearch.Foreground = Brushes.Gray

    def sch_search_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._schemes_refresh()

    def sch_selection_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        self._scheme_load_to_ui(self._scheme_current_data())

    def sch_create_from_edit_selection(self, s, a):
        if scheme_helpers is None:
            MessageBox.Show(u"Modulo de esquemas nao disponivel.", "Esquemas"); return
        selected_entries = [i for i in self.e_dgFiltros.SelectedItems]
        if not selected_entries:
            MessageBox.Show(u"Selecione filtros no menu Editar primeiro.", "Esquemas"); return
        filters = []
        by_id = {}
        for f in FilteredElementCollector(self.doc).OfClass(ParameterFilterElement):
            by_id[f.Id.IntegerValue] = f
        for entry in selected_entries:
            f = by_id.get(entry.FilterId.IntegerValue)
            if f:
                filters.append(f)
        if not filters:
            MessageBox.Show(u"Nenhum filtro selecionado encontrado no projeto.", "Esquemas"); return
        default_name = u"Esquema {}".format(len(self._schemes) + 1)
        name = _ask_text(self, u"Novo esquema", u"Nome do esquema:", default_name)
        if not name:
            return
        data = ph.export_filters_to_dict(self.doc, filters, True, False)
        categories = data[0].get('categories', []) if data else []
        param_name = ''
        items = []
        for entry in data:
            rules = entry.get('rules', [])
            if rules and not param_name:
                param_name = rules[0].get('param', '')
            value = rules[0].get('value', entry.get('name', '')) if rules else entry.get('name', '')
            items.append({
                'active': True,
                'value': value,
                'filter_name': entry.get('name', ''),
                'categories': entry.get('categories', categories),
                'rules': rules,
                'color': entry.get('color') or '',
                'pattern': entry.get('pattern') or PATTERN_NONE,
            })
        scheme = {
            'name': scheme_helpers.unique_name(name, self._schemes),
            'prefix': '',
            'categories': categories,
            'param_name': param_name,
            'apply_view': True,
            'replace_existing': True,
            'items': items,
        }
        self._schemes.append(scheme)
        scheme_helpers.save_schemes(self._schemes)
        self._schemes_dirty = False
        self._schemes_refresh()
        self.sch_lstSchemes.SelectedItem = scheme['name']
        self._set_status(u"Esquema criado a partir da selecao.")

    def sch_duplicate(self, s, a):
        if scheme_helpers is None or not self._current_scheme:
            return
        import copy
        dup = copy.deepcopy(self._scheme_sync_from_ui())
        dup['name'] = scheme_helpers.unique_name(dup.get('name', 'Esquema') + u" copia", self._schemes)
        self._schemes.append(dup)
        scheme_helpers.save_schemes(self._schemes)
        self._schemes_dirty = False
        self._schemes_refresh()
        self.sch_lstSchemes.SelectedItem = dup['name']

    def sch_delete(self, s, a):
        if scheme_helpers is None or not self._current_scheme:
            return
        name = self._current_scheme.get('name', '')
        if MessageBox.Show(u"Apagar o esquema '{}'?".format(name), "Esquemas", MessageBoxButton.YesNo) != MessageBoxResult.Yes:
            return
        self._schemes = [s for s in self._schemes if s.get('name') != name]
        scheme_helpers.save_schemes(self._schemes)
        self._schemes_dirty = False
        self._current_scheme = None
        self._schemes_refresh()
        self._scheme_load_to_ui(None)

    def sch_save_current(self, s, a):
        if scheme_helpers is None or not self._current_scheme:
            MessageBox.Show(u"Selecione um esquema primeiro.", "Esquemas"); return
        scheme = self._scheme_sync_from_ui()
        names = [s.get('name') for s in self._schemes if s is not scheme]
        if scheme.get('name') in names:
            scheme['name'] = scheme_helpers.unique_name(scheme.get('name'), self._schemes)
            self.sch_txtName.Text = scheme['name']
        scheme_helpers.save_schemes(self._schemes)
        self._schemes_dirty = False
        self._schemes_refresh()
        self.sch_lstSchemes.SelectedItem = scheme['name']
        self.sch_lblStatus.Text = u"Esquema guardado."

    def _scheme_used_colors(self):
        used = []
        for item in self._scheme_items:
            if item.ColorHex:
                used.append(item.ColorHex)
        return used

    def _scheme_targets_for_item(self, item):
        try:
            if self._scheme_bulk_targets and item in self._scheme_bulk_targets:
                return list(self._scheme_bulk_targets)
        except Exception:
            pass
        try:
            selected = [i for i in self.sch_dgItems.SelectedItems]
            if item in selected and selected:
                return selected
        except Exception:
            pass
        return [item]

    def _scheme_capture_bulk_targets(self, item=None):
        try:
            selected = [i for i in self.sch_dgItems.SelectedItems]
            if selected and (item is None or item in selected):
                self._scheme_bulk_targets = selected
            elif item is not None:
                self._scheme_bulk_targets = [item]
            else:
                self._scheme_bulk_targets = []
        except Exception:
            self._scheme_bulk_targets = [item] if item is not None else []

    def sch_control_preview_mouse_down(self, sender, args):
        try:
            item = getattr(sender, 'Tag', None) or sender.DataContext
            self._scheme_capture_bulk_targets(item)
        except Exception:
            self._scheme_capture_bulk_targets(None)

    def sch_active_click(self, sender, args):
        item = getattr(sender, 'Tag', None)
        if item is None:
            return
        value = bool(sender.IsChecked)
        for target in self._scheme_targets_for_item(item):
            target.Active = value
        try:
            self.sch_dgItems.Items.Refresh()
        except Exception:
            pass

    def sch_grid_right_click(self, sender, args):
        row = _find_parent_of_type(args.OriginalSource, 'DataGridRow')
        if row is None:
            return
        try:
            self.sch_dgItems.SelectedItem = row.Item
            self._scheme_capture_bulk_targets(row.Item)
        except Exception:
            pass

    def sch_rename_filter(self, s, a):
        item = self.sch_dgItems.SelectedItem
        if item is None:
            MessageBox.Show(u"Selecione um filtro do esquema para renomear.", "Esquemas"); return
        old_name = item.FilterName
        new_name = _ask_text(self, u"Renomear filtro do esquema", u"Novo nome do filtro:", old_name)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if any(other is not item and other.FilterName == new_name for other in self._scheme_items):
            MessageBox.Show(u"Ja existe um filtro com esse nome neste esquema.", "Esquemas"); return
        item.FilterName = new_name
        item.sync()
        self.sch_dgItems.Items.Refresh()
        self.sch_lblStatus.Text = u"Nome do filtro atualizado no esquema."
        self._set_status(self.sch_lblStatus.Text)

    def sch_color_btn_click(self, sender, args):
        item = sender.Tag
        if item is None:
            return
        dlg = PaletteColorPickerWindow(item.ColorHex, self._scheme_used_colors())
        dlg.Owner = self
        dlg.ShowDialog()
        if dlg.ManagePalette:
            self.nav_colors(None, None)
            return
        targets = self._scheme_targets_for_item(item)
        if dlg.Result:
            for target in targets:
                target.ColorHex = dlg.Result
                if target.FillPattern == PATTERN_NONE:
                    target.FillPattern = PATTERN_SOLID
                target.refresh_brush()
        elif dlg.Result == '':
            for target in targets:
                target.ColorHex = ''
                target.FillPattern = PATTERN_NONE
                target.refresh_brush()
        self.sch_dgItems.Items.Refresh()

    def sch_pattern_loaded(self, sender, args):
        try:
            sender.DropDownClosed -= self.sch_pattern_committed
        except Exception:
            pass
        sender.ItemsSource = self._edit_pattern_options
        item = sender.DataContext
        sender.Tag = item
        if item and hasattr(item, 'FillPattern'):
            selected = None
            for opt in self._edit_pattern_options:
                if opt.Name == item.FillPattern:
                    selected = opt
                    break
            sender.SelectedItem = selected or self._edit_pattern_options[0]
        try:
            sender.PreviewMouseDown -= self.sch_control_preview_mouse_down
        except Exception:
            pass
        try:
            sender.PreviewMouseDown += self.sch_control_preview_mouse_down
        except Exception:
            pass
        sender.DropDownClosed += self.sch_pattern_committed

    def sch_pattern_committed(self, sender, args):
        item = getattr(sender, 'Tag', None)
        if not item or not hasattr(item, 'FillPattern') or sender.SelectedItem is None:
            return
        targets = self._scheme_targets_for_item(item)
        for target in targets:
            target.FillPattern = sender.SelectedItem.Name
        self.sch_dgItems.Items.Refresh()

    def sch_apply(self, s, a):
        if scheme_helpers is None:
            MessageBox.Show(u"Modulo de esquemas nao disponivel.", "Esquemas"); return
        if not self._current_scheme:
            MessageBox.Show(u"Selecione um esquema primeiro.", "Esquemas"); return
        scheme = self._scheme_sync_from_ui()
        active_items = [i for i in self._scheme_items if i.Active]
        if not active_items:
            MessageBox.Show(u"O esquema nao tem itens ativos.", "Esquemas"); return
        cat_map = revit_query.get_categories(self.doc)
        fill_patterns = _get_revit_fill_pattern_map(self.doc)
        solid = ph.get_solid_fill_pattern_id(self.doc)
        created = 0
        updated = 0
        applied = 0
        skipped = 0
        failed = 0
        names = [self._scheme_filter_name(scheme, i) for i in active_items]
        existing = _project_filters_by_name(self.doc)
        existing_names = [name for name in names if name in existing]
        if bool(scheme.get('replace_existing', True)) and existing_names:
            msg = u"{} filtro(s) do projeto com o mesmo nome serao substituidos. Continuar?".format(len(existing_names))
            if MessageBox.Show(msg, "Esquemas", MessageBoxButton.YesNo) != MessageBoxResult.Yes:
                return
        if bool(scheme.get('replace_existing', True)):
            with revit.Transaction("MTQ Scheme - Substituir filtros"):
                for name in names:
                    f = existing.get(name)
                    if f:
                        try:
                            self.doc.Delete(f.Id)
                        except Exception:
                            pass
        for item in active_items:
            rules = item.Data.get('rules', [])
            if len(rules) != 1:
                skipped += 1
                continue
            cats = item.Data.get('categories') or scheme.get('categories', [])
            cat_ids = [cat_map[c] for c in cats if c in cat_map]
            if not cat_ids:
                skipped += 1
                continue
            pname = rules[0].get('param', '')
            value = rules[0].get('value', item.Value)
            param_id = revit_query.get_filterable_params(self.doc, cat_ids).get(pname)
            if not param_id:
                skipped += 1
                continue
            target_name = self._scheme_filter_name(scheme, item)
            f, err = _create_filter_exact(self.doc, target_name, value, List[ElementId](cat_ids), param_id)
            if f:
                created += 1
            elif err == u"ja existe":
                updated += 1
            else:
                failed += 1
        if bool(scheme.get('apply_view', True)):
            by_name = _project_filters_by_name(self.doc)
            view = self.doc.ActiveView
            if _validate_override_view(view):
                with revit.Transaction("MTQ Scheme - Aplicar overrides"):
                    for item in active_items:
                        f = by_name.get(self._scheme_filter_name(scheme, item))
                        if not f:
                            continue
                        rgb = ph.parse_color_input(item.ColorHex) if item.ColorHex else None
                        pat_id = _pattern_id_from_export(self.doc, fill_patterns, item.FillPattern, solid)
                        if not _is_valid_override_pattern(self.doc, pat_id, solid):
                            failed += 1
                            continue
                        ov = ph.build_revit_override(rgb, solid, pat_id)
                        ok, err = _apply_filter_override(view, f.Id, ov)
                        if not ok:
                            failed += 1
                        else:
                            applied += 1
        scheme_helpers.save_schemes(self._schemes)
        self._refresh_filter_pages()
        self.sch_lblStatus.Text = u"{} criados, {} existentes, {} aplicados, {} ignorados, {} falharam".format(created, updated, applied, skipped, failed)
        self._set_status(self.sch_lblStatus.Text)

    # Colors
    def _init_colors_page(self):
        self._refresh_colors_page()

    def _refresh_colors_page(self):
        selected_keys = []
        try:
            for item in self.co_lstColors.SelectedItems:
                selected_keys.append((item.HexColor, item.Label))
        except Exception:
            pass
        self._colors = ph.load_palette()
        self._colors_refresh(selected_keys=selected_keys)
        self._colors_build_swatches()
        self._colors_update_preview_from_rgb()

    def _colors_refresh(self, selected_indices=None, selected_keys=None):
        self.co_lstColors.Items.Clear()
        for entry in self._colors:
            self.co_lstColors.Items.Add(ColorItem(entry.get('hex', '#000000'), entry.get('name', '')))
        if selected_indices:
            try:
                for idx in selected_indices:
                    if 0 <= idx < self.co_lstColors.Items.Count:
                        self.co_lstColors.SelectedItems.Add(self.co_lstColors.Items.GetItemAt(idx))
            except Exception:
                pass
        elif selected_keys:
            remaining = list(selected_keys)
            try:
                for i in range(self.co_lstColors.Items.Count):
                    item = self.co_lstColors.Items.GetItemAt(i)
                    key = (getattr(item, 'HexColor', None), getattr(item, 'Label', None))
                    if key in remaining:
                        self.co_lstColors.SelectedItems.Add(item)
                        remaining.remove(key)
            except Exception:
                pass
        self.co_lblCount.Text = u"{} cor(es) na paleta".format(len(self._colors))

    def _colors_selected_indices(self):
        try:
            selected = []
            for i in range(self.co_lstColors.Items.Count):
                item = self.co_lstColors.Items.GetItemAt(i)
                if self.co_lstColors.SelectedItems.Contains(item):
                    selected.append(i)
            return selected
        except Exception:
            idx = self.co_lstColors.SelectedIndex
            return [idx] if idx >= 0 else []

    def co_remove_color(self, s, a):
        indices = self._colors_selected_indices()
        if not indices:
            MessageBox.Show(u"Selecione pelo menos uma cor para remover.", "Cores"); return
        index_set = set(indices)
        self._colors = [entry for i, entry in enumerate(self._colors) if i not in index_set]
        self._colors_refresh()

    def co_move_up(self, s, a):
        indices = self._colors_selected_indices()
        if not indices or indices[0] <= 0:
            return
        for idx in indices:
            self._colors[idx-1], self._colors[idx] = self._colors[idx], self._colors[idx-1]
        self._colors_refresh(selected_indices=[idx - 1 for idx in indices])

    def co_move_down(self, s, a):
        indices = self._colors_selected_indices()
        if not indices or indices[-1] >= len(self._colors) - 1:
            return
        for idx in reversed(indices):
            self._colors[idx], self._colors[idx+1] = self._colors[idx+1], self._colors[idx]
        self._colors_refresh(selected_indices=[idx + 1 for idx in indices])

    def co_clear_all(self, s, a):
        if MessageBox.Show(u"Limpar toda a paleta?", "Cores", MessageBoxButton.YesNo) == MessageBoxResult.Yes:
            self._colors = []
            self._colors_refresh()

    def co_load_defaults(self, s, a):
        if self._colors:
            if MessageBox.Show(u"Substituir a paleta atual pelas cores padrao?", "Cores", MessageBoxButton.YesNo) != MessageBoxResult.Yes:
                return
        self._colors = [{'hex': d['hex'], 'name': d['name']} for d in ph.DEFAULT_COLORS]
        self._colors_refresh()

    def _colors_build_swatches(self):
        from System.Windows.Controls import Button
        from System.Windows import Thickness
        self.co_basicSwatches.Children.Clear()
        for entry in ph.DEFAULT_COLORS:
            rgb = ph.parse_color_input(entry['hex'])
            if not rgb:
                continue
            btn = Button()
            btn.Width = 22
            btn.Height = 22
            btn.Margin = Thickness(2)
            btn.Padding = Thickness(0)
            btn.BorderThickness = Thickness(1)
            btn.Background = SolidColorBrush(WpfColor.FromRgb(rgb[0], rgb[1], rgb[2]))
            btn.ToolTip = u"{} {}".format(entry['name'], entry['hex'])
            def make_handler(hex_value):
                def handler(sender, args):
                    self._colors_set_from_hex(hex_value)
                return handler
            btn.Click += make_handler(entry['hex'])
            self.co_basicSwatches.Children.Add(btn)

    def _colors_set_from_hex(self, hex_str):
        rgb = ph.parse_color_input(hex_str)
        if not rgb:
            return
        self._color_syncing = True
        self.co_txtR.Text = str(rgb[0])
        self.co_txtG.Text = str(rgb[1])
        self.co_txtB.Text = str(rgb[2])
        self.co_txtHex.Text = hex_str.lstrip('#')
        self._color_syncing = False
        self._colors_update_preview_from_rgb()

    def _colors_update_preview_from_rgb(self):
        try:
            r = max(0, min(255, int(self.co_txtR.Text or '0')))
            g = max(0, min(255, int(self.co_txtG.Text or '0')))
            b = max(0, min(255, int(self.co_txtB.Text or '0')))
            self.co_colorPreview.Background = SolidColorBrush(WpfColor.FromRgb(r, g, b))
        except Exception:
            pass

    def co_rgb_text_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self._color_syncing:
            return
        try:
            r = max(0, min(255, int(self.co_txtR.Text or '0')))
            g = max(0, min(255, int(self.co_txtG.Text or '0')))
            b = max(0, min(255, int(self.co_txtB.Text or '0')))
            self._color_syncing = True
            self.co_txtHex.Text = '{:02X}{:02X}{:02X}'.format(r, g, b)
            self._color_syncing = False
            self._colors_update_preview_from_rgb()
        except Exception:
            self._color_syncing = False

    def co_hex_text_changed(self, s, a):
        if getattr(self, '_ui_loading', False):
            return
        if self._color_syncing:
            return
        try:
            h = self.co_txtHex.Text.strip().lstrip('#')
            if len(h) == 6:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                self._color_syncing = True
                self.co_txtR.Text = str(r)
                self.co_txtG.Text = str(g)
                self.co_txtB.Text = str(b)
                self.co_txtHex.Text = h.upper()
                self._color_syncing = False
                self._colors_update_preview_from_rgb()
        except Exception:
            self._color_syncing = False

    def co_hex_got_focus(self, s, a):
        self.co_txtHex.SelectAll()

    def co_open_mixer(self, s, a):
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import ColorDialog
        from System.Drawing import Color as DrawColor
        import System.Windows.Forms as WF
        dlg = ColorDialog()
        dlg.FullOpen = True
        try:
            r = max(0, min(255, int(self.co_txtR.Text or '0')))
            g = max(0, min(255, int(self.co_txtG.Text or '0')))
            b = max(0, min(255, int(self.co_txtB.Text or '0')))
            dlg.Color = DrawColor.FromArgb(r, g, b)
        except Exception:
            pass
        if dlg.ShowDialog() == WF.DialogResult.OK:
            c = dlg.Color
            self._color_syncing = True
            self.co_txtR.Text = str(c.R)
            self.co_txtG.Text = str(c.G)
            self.co_txtB.Text = str(c.B)
            self.co_txtHex.Text = ph.rgb_to_hex(c.R, c.G, c.B).lstrip('#')
            self._color_syncing = False
            self._colors_update_preview_from_rgb()

    def co_add_color(self, s, a):
        try:
            r = max(0, min(255, int(self.co_txtR.Text or '0')))
            g = max(0, min(255, int(self.co_txtG.Text or '0')))
            b = max(0, min(255, int(self.co_txtB.Text or '0')))
        except Exception:
            MessageBox.Show(u"Valores R/G/B invalidos.", "Cores"); return
        hex_val = ph.rgb_to_hex(r, g, b)
        label = ''
        for d in ph.DEFAULT_COLORS:
            if ph.parse_color_input(d['hex']) == (r, g, b):
                label = d['name']
                break
        self._colors.append({'hex': hex_val, 'name': label})
        self._colors_refresh()

    def co_save_palette(self, s, a):
        ok, err = ph.save_palette(self._colors)
        if not ok:
            MessageBox.Show(err, "Cores"); return
        msg = u"Paleta guardada com {} cor(es).".format(len(self._colors))
        self.co_lblCount.Text = msg
        self._set_status(msg)
