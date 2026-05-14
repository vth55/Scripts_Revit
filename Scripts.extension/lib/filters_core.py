# -*- coding: utf-8 -*-
"""Criação e remoção de filtros de visibilidade no Revit."""
import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    FilteredElementCollector, ParameterFilterElement,
    ParameterFilterRuleFactory, ElementParameterFilter,
    OverrideGraphicSettings, FillPatternElement, Color, ElementId,
)
from System.Collections.Generic import List


def get_solid_fill_id(doc):
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            pass
    return None


def apply_color_override(doc, view, filter_elem, rgb, solid_fill_id,
                         fg_pattern_id=None):
    ogs = OverrideGraphicSettings()
    if rgb is not None:
        r, g, b = rgb
        color = Color(r, g, b)
        pat_id = fg_pattern_id if fg_pattern_id is not None else solid_fill_id
        use_pat = pat_id is not None and pat_id != ElementId.InvalidElementId
        try:
            ogs.SetSurfaceForegroundPatternColor(color)
            ogs.SetSurfaceForegroundPatternVisible(use_pat)
            if use_pat:
                ogs.SetSurfaceForegroundPatternId(pat_id)
        except Exception:
            pass
        try:
            ogs.SetCutForegroundPatternColor(color)
            ogs.SetCutForegroundPatternVisible(use_pat)
            if use_pat:
                ogs.SetCutForegroundPatternId(pat_id)
        except Exception:
            pass
        try:
            ogs.SetCutBackgroundPatternVisible(False)
        except Exception:
            pass
    if view is not None:
        try:
            view.AddFilter(filter_elem.Id)
            view.SetFilterOverrides(filter_elem.Id, ogs)
        except Exception:
            pass


def delete_by_prefix(doc, prefix):
    """Apaga do projeto todos os ParameterFilterElement cujo nome começa com prefix."""
    deleted = 0
    for f in list(FilteredElementCollector(doc).OfClass(ParameterFilterElement)):
        if f.Name.startswith(prefix):
            try:
                doc.Delete(f.Id)
                deleted += 1
            except Exception:
                pass
    return deleted


def create_filters(doc, view, pairs, prefix, cat_ids, param_id, colors,
                   fp_ids=None):
    """
    Cria um filtro por cada (value, display_name) em pairs.
    pairs   : lista de (valor_parametro, nome_display)
    prefix  : prefixo do nome do filtro
    cat_ids : List[ElementId]
    param_id: ElementId do parâmetro
    colors  : lista de (r, g, b) ou None
    fp_ids  : lista de ElementId de fill patterns (opcional, mesmo comprimento que colors)
    Devolve número de filtros criados.
    """
    solid_fill_id = get_solid_fill_id(doc)
    created = 0
    for i, (val, nome) in enumerate(pairs):
        try:
            fname = u"{}{} - {}".format(prefix, val, nome) if val != nome \
                else u"{}{}".format(prefix, val)
            fname = fname[:200]
            rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, val, False)
            pfe = ParameterFilterElement.Create(
                doc, fname, cat_ids, ElementParameterFilter(rule)
            )
            created += 1
        except Exception:
            continue
        try:
            fg_id = fp_ids[i] if (fp_ids and i < len(fp_ids)) else None
            apply_color_override(doc, view, pfe, colors[i], solid_fill_id, fg_id)
        except Exception:
            pass
    return created
