# -*- coding: utf-8 -*-
"""Palette helpers for MTQ Filter Manager.
Merged from ColorFilterManager (color utilities, solid fill, default palette).
"""
import os, json
import codecs
import colorsys

# ── Default palette (Revit standard + architecture extras) ─────────────────────
# Merged from ColorFilterManager — these are the 30 curated Revit-compatible colors
DEFAULT_COLORS = [
    {"name": "Vermelho",        "hex": "#FF0000"},
    {"name": "Verde",           "hex": "#00FF00"},
    {"name": "Azul",            "hex": "#0000FF"},
    {"name": "Ciano",           "hex": "#00FFFF"},
    {"name": "Magenta",         "hex": "#FF00FF"},
    {"name": "Amarelo",         "hex": "#FFFF00"},
    {"name": "Preto",           "hex": "#000000"},
    {"name": "Branco",          "hex": "#FFFFFF"},
    {"name": "Cinza Escuro",    "hex": "#808080"},
    {"name": "Cinza Claro",     "hex": "#C0C0C0"},
    {"name": "Vermelho Escuro", "hex": "#800000"},
    {"name": "Verde Escuro",    "hex": "#008000"},
    {"name": "Azul Escuro",     "hex": "#000080"},
    {"name": "Azul Aço",        "hex": "#4682B4"},
    {"name": "Laranja",         "hex": "#FF8000"},
    {"name": "Castanho",        "hex": "#804000"},
    {"name": "Roxo",            "hex": "#800080"},
    {"name": "Azul Royal",      "hex": "#4169E1"},
    {"name": "Verde Lima",      "hex": "#00C000"},
    {"name": "Rosa",            "hex": "#FF80C0"},
    {"name": "Laranja Claro",   "hex": "#FFB347"},
    {"name": "Verde Água",      "hex": "#00B4D8"},
    {"name": "Salmão",          "hex": "#FA8072"},
    {"name": "Lavanda",         "hex": "#967BB6"},
    {"name": "Turquesa",        "hex": "#40E0D0"},
    {"name": "Coral",           "hex": "#FF6B6B"},
    {"name": "Petróleo",        "hex": "#006064"},
    {"name": "Dourado",         "hex": "#DAA520"},
    {"name": "Verde Oliva",     "hex": "#808000"},
    {"name": "Índigo",          "hex": "#4B0082"},
]

PALETTE_FILE = os.path.join(os.environ.get('APPDATA', ''), 'pyRevit', 'MTQ_colors.json')


def _to_text(value):
    if value is None:
        return u''
    try:
        if isinstance(value, unicode):
            return value
    except NameError:
        try:
            return str(value)
        except Exception:
            return ''
    try:
        if isinstance(value, str):
            for enc in ('utf-8', 'cp1252', 'latin-1'):
                try:
                    return unicode(value, enc)
                except Exception:
                    pass
            return unicode(value, 'latin-1', 'ignore')
    except Exception:
        pass
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return unicode(str(value), 'latin-1', 'ignore')
    except Exception:
        return u''


def _ascii_safe(value):
    text = _to_text(value)
    try:
        return text.encode('ascii', 'ignore').decode('ascii')
    except Exception:
        try:
            return ''.join([c for c in text if ord(c) < 128])
        except Exception:
            return ''


def _safe_hex(value):
    text = _ascii_safe(value).strip().upper()
    if not text.startswith('#'):
        text = '#' + text
    if len(text) == 7:
        try:
            int(text[1:], 16)
            return text
        except Exception:
            pass
    return '#000000'


def load_palette():
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with codecs.open(PALETTE_FILE, 'r', enc) as f:
                raw = json.load(f)
            clean = []
            for entry in raw:
                clean.append({
                    'hex': _safe_hex(entry.get('hex', '#000000')),
                    'name': _to_text(entry.get('name', ''))
                })
            return clean
        except Exception:
            pass
    return [{'hex': d['hex'], 'name': d['name']} for d in DEFAULT_COLORS]

def save_palette(colors):
    try:
        d = os.path.dirname(PALETTE_FILE)
        if not os.path.exists(d):
            os.makedirs(d)
        clean_colors = []
        for entry in colors:
            clean_colors.append({
                'hex': _safe_hex(entry.get('hex', '#000000')),
                'name': _ascii_safe(entry.get('name', ''))
            })
        with codecs.open(PALETTE_FILE, 'w', 'utf-8') as f:
            data = json.dumps(clean_colors, indent=2, ensure_ascii=True)
            f.write(_to_text(data))
        return True, ''
    except Exception as e:
        return False, u"Nao foi possivel guardar a paleta em:\n{}\n\n{}".format(PALETTE_FILE, e)

def parse_color_input(text):
    """Parse #RRGGBB or R,G,B into (r,g,b) tuple. Returns None on failure."""
    text = text.strip()
    h = text.lstrip('#')
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except Exception:
            pass
    parts = [p.strip() for p in text.split(',')]
    if len(parts) == 3:
        try:
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            if all(0 <= x <= 255 for x in (r, g, b)):
                return (r, g, b)
        except Exception:
            pass
    return None

def rgb_to_hex(r, g, b):
    return '#{:02X}{:02X}{:02X}'.format(r, g, b)


def _rgb_key(rgb):
    try:
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    except Exception:
        return None


def _unique_rgbs(colors):
    result = []
    seen = set()
    for rgb in colors or []:
        key = _rgb_key(rgb)
        if key is not None and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def palette_rgbs():
    result = []
    for entry in load_palette():
        rgb = parse_color_input(entry.get('hex', '#000000'))
        if rgb:
            result.append(rgb)
    return _unique_rgbs(result)


def _dist2(a, b):
    return ((a[0] - b[0]) * (a[0] - b[0]) +
            (a[1] - b[1]) * (a[1] - b[1]) +
            (a[2] - b[2]) * (a[2] - b[2]))


def _hsv_candidates():
    candidates = []
    # Golden-ratio hue order gives good spread early in the sequence.
    step = 0.61803398875
    for sv in ((0.72, 0.86), (0.90, 0.78), (0.58, 0.94), (0.82, 0.62)):
        s, v = sv
        for i in range(96):
            h = (i * step) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            candidates.append((int(r * 255), int(g * 255), int(b * 255)))
    return _unique_rgbs(candidates)


def distinct_hsv_colors(n, avoid=None):
    avoid_list = _unique_rgbs(avoid or [])
    selected = []
    candidates = [c for c in _hsv_candidates() if c not in set(avoid_list)]
    for i in range(n):
        if not candidates:
            candidates = _hsv_candidates()
        base = avoid_list + selected
        if not base:
            chosen = candidates.pop(0)
        else:
            chosen = max(candidates, key=lambda c: min(_dist2(c, b) for b in base))
            candidates.remove(chosen)
        selected.append(chosen)
    return selected


def resolve_cores_distintas(n, mode, used_colors=None, palette_short_action='auto'):
    """Resolve colors with duplicate avoidance.

    palette_short_action: 'auto' completes with HSV, 'repeat' cycles palette,
    'cancel' returns None.
    """
    used = _unique_rgbs(used_colors or [])
    if mode == 'none':
        return [None] * n
    if mode == 'hsv':
        return distinct_hsv_colors(n, used)
    if mode == 'palette':
        pal = palette_rgbs()
        if not pal:
            return None
        used_set = set(used)
        unique_available = [rgb for rgb in pal if rgb not in used_set]
        if len(unique_available) >= n:
            return unique_available[:n]
        if palette_short_action == 'cancel':
            return None
        if palette_short_action == 'repeat':
            result = []
            for i in range(n):
                result.append(pal[i % len(pal)])
            return result
        result = list(unique_available)
        result.extend(distinct_hsv_colors(n - len(result), used + result + pal))
        return result
    return distinct_hsv_colors(n, used)

def resolve_cores(n, mode, colors_core_mod):
    """Return list of (r,g,b) tuples, list of None, or None (abort signal).
    mode: 'hsv' | 'palette' | 'none'
    """
    if mode == 'none':
        return [None] * n
    if mode == 'palette':
        pal = load_palette()
        if not pal:
            return None  # caller should warn user
        result = []
        for i in range(n):
            entry = pal[i % len(pal)]
            rgb = parse_color_input(entry.get('hex', '#FF0000'))
            result.append(rgb if rgb else (255, 0, 0))
        return result
    # 'hsv' — delegate to colors_core
    return colors_core_mod.get_colors(n, True)


# ── Revit color utilities (merged from ColorFilterManager) ─────────────────────

def revit_color_to_hex(rc):
    """Convert Revit Color object to #RRGGBB string. Returns None on failure."""
    try:
        if rc is None:
            return None
        r = max(0, min(255, int(rc.Red)))
        g = max(0, min(255, int(rc.Green)))
        b = max(0, min(255, int(rc.Blue)))
        return '#{:02X}{:02X}{:02X}'.format(r, g, b)
    except Exception:
        return None


_solid_fill_id_cache = None

def get_solid_fill_pattern_id(doc):
    """Returns the ElementId of the Solid Fill pattern (cached). Merged from CFM."""
    global _solid_fill_id_cache
    if _solid_fill_id_cache is not None:
        return _solid_fill_id_cache
    try:
        from Autodesk.Revit.DB import FillPatternElement
        from Autodesk.Revit.DB import FilteredElementCollector
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements():
            try:
                if fp.GetFillPattern().IsSolidFill:
                    _solid_fill_id_cache = fp.Id
                    return fp.Id
            except Exception:
                pass
    except Exception:
        pass
    return None


def build_revit_override(rgb_tuple, solid_fill_id, fg_pattern_id=None):
    """Build OverrideGraphicSettings with FILL ONLY (surface+cut). Lines unchanged.
    fg_pattern_id=None  → use solid fill (default).
    fg_pattern_id=InvalidElementId → no visible pattern.
    fg_pattern_id=<id> → use that hatch/pattern.
    """
    from Autodesk.Revit.DB import OverrideGraphicSettings, ElementId
    from Autodesk.Revit.DB import Color as RevitColor
    if rgb_tuple is None:
        ov = OverrideGraphicSettings()
        try:
            ov.SetSurfaceForegroundPatternVisible(False)
        except Exception:
            pass
        try:
            ov.SetCutForegroundPatternVisible(False)
        except Exception:
            pass
        try:
            ov.SetSurfaceForegroundPatternId(ElementId.InvalidElementId)
        except Exception:
            pass
        try:
            ov.SetCutForegroundPatternId(ElementId.InvalidElementId)
        except Exception:
            pass
        return ov
    r, g, b = rgb_tuple
    rc = RevitColor(r, g, b)
    ov = OverrideGraphicSettings()
    # Resolve which pattern to use
    pat_id = fg_pattern_id if fg_pattern_id is not None else solid_fill_id
    use_pat = pat_id is not None and pat_id != ElementId.InvalidElementId
    try:
        ov.SetSurfaceForegroundPatternColor(rc)
        ov.SetSurfaceForegroundPatternVisible(use_pat)
        if use_pat:
            ov.SetSurfaceForegroundPatternId(pat_id)
    except Exception:
        pass
    try:
        ov.SetCutForegroundPatternColor(rc)
        ov.SetCutForegroundPatternVisible(use_pat)
        if use_pat:
            ov.SetCutForegroundPatternId(pat_id)
    except Exception:
        pass
    try:
        ov.SetCutBackgroundPatternVisible(False)
    except Exception:
        pass
    return ov


def export_filters_to_dict(doc, filter_elements, include_colors, include_order):
    """Serialize a list of ParameterFilterElement to a list of dicts."""
    view = doc.ActiveView
    result = []
    order_idx = 0
    for f in filter_elements:
        cats = []
        try:
            from Autodesk.Revit.DB import Category
            for cid in f.GetCategories():
                cat = Category.GetCategory(doc, cid)
                if cat:
                    cats.append(cat.Name)
        except Exception:
            pass
        rules = []
        try:
            # Revit 2023+: GetRules() obsoleto — usar GetElementFilter().GetRules()
            rule_list = []
            try:
                ef = f.GetElementFilter()
                rule_list = list(ef.GetRules())
            except Exception:
                pass
            if not rule_list:
                try:
                    rule_list = list(f.GetRules())
                except Exception:
                    pass
            for rule in rule_list:
                pid = rule.GetRuleParameter()
                int_val = pid.IntegerValue
                if int_val < 0:
                    # Parâmetro built-in — usar LabelUtils igual ao revit_query
                    try:
                        from Autodesk.Revit.DB import BuiltInParameter, LabelUtils
                        pname = LabelUtils.GetLabelFor(BuiltInParameter(int_val))
                    except Exception:
                        pname = str(int_val)
                else:
                    # Parâmetro partilhado/projeto — usar GetDefinition().Name
                    elem = doc.GetElement(pid)
                    if elem and hasattr(elem, 'GetDefinition'):
                        pname = elem.GetDefinition().Name
                    else:
                        pname = str(int_val)
                val = ''
                try:
                    val = str(rule.RuleString)
                except Exception:
                    try:
                        val = str(rule.RuleValue)
                    except Exception:
                        pass
                rules.append({'param': pname, 'value': val})
        except Exception:
            pass
        entry = {
            'name': f.Name,
            'categories': cats,
            'rules': rules,
        }
        if include_colors:
            try:
                ogs = view.GetFilterOverrides(f.Id)
                rc = ogs.SurfaceForegroundPatternColor
                entry['color'] = revit_color_to_hex(rc) if rc.IsValid else None
                try:
                    from Autodesk.Revit.DB import ElementId
                    pat_id = ogs.SurfaceForegroundPatternId
                    solid_id = get_solid_fill_pattern_id(doc)
                    visible = True
                    try:
                        visible = bool(ogs.SurfaceForegroundPatternVisible)
                    except Exception:
                        pass
                    if (not visible) or pat_id == ElementId.InvalidElementId:
                        entry['pattern'] = 'None'
                    elif solid_id is not None and pat_id == solid_id:
                        entry['pattern'] = '<Solid fill>'
                    else:
                        pat = doc.GetElement(pat_id)
                        entry['pattern'] = pat.Name if pat else None
                except Exception:
                    entry['pattern'] = None
            except Exception:
                entry['color'] = None
                entry['pattern'] = None
        if include_order:
            entry['order'] = order_idx
        order_idx += 1
        result.append(entry)
    return result
