# -*- coding: utf-8 -*-
"""Consultas ao modelo Revit: categorias, parâmetros filtráveis, valores únicos."""
import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    SharedParameterElement, ParameterFilterUtilities,
    LabelUtils, BuiltInParameter, ElementId,
)
from System.Collections.Generic import List

ALL_BICS = [
    # Arquitetura
    BuiltInCategory.OST_Casework, BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Columns, BuiltInCategory.OST_CurtainWallPanels,
    BuiltInCategory.OST_CurtainWallMullions, BuiltInCategory.OST_Doors,
    BuiltInCategory.OST_Floors, BuiltInCategory.OST_Furniture,
    BuiltInCategory.OST_FurnitureSystems, BuiltInCategory.OST_GenericModel,
    BuiltInCategory.OST_Mass, BuiltInCategory.OST_Railings,
    BuiltInCategory.OST_Ramps, BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Stairs, BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Windows,
    # Estrutural
    BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_StructuralFoundation,
    BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_Rebar,
    BuiltInCategory.OST_FabricReinforcement,
    # MEP
    BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_MechanicalEquipment,
    BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_ElectricalEquipment, BuiltInCategory.OST_ElectricalFixtures,
    BuiltInCategory.OST_LightingFixtures, BuiltInCategory.OST_LightingDevices,
    BuiltInCategory.OST_CableTray, BuiltInCategory.OST_Conduit,
]


def get_categories(doc):
    """Devolve {nome: ElementId} de todas as categorias disponíveis."""
    result = {}
    for bic in ALL_BICS:
        cat = doc.Settings.Categories.get_Item(bic)
        if cat:
            result[cat.Name] = cat.Id
    return result


def get_filterable_params(doc, cat_ids):
    """
    Usa ParameterFilterUtilities para obter os parâmetros realmente filtráveis
    para o conjunto de categorias. Devolve {nome: ElementId}.
    """
    result = {}
    if not cat_ids:
        return result
    id_list = List[ElementId](cat_ids)
    try:
        param_ids = ParameterFilterUtilities.GetFilterableParametersInCommon(doc, id_list)
    except Exception:
        return _fallback_params(doc, cat_ids)

    for pid in param_ids:
        try:
            int_val = pid.IntegerValue
            if int_val < 0:
                # Parâmetro built-in
                bip = BuiltInParameter(int_val)
                name = LabelUtils.GetLabelFor(bip)
                if name:
                    result[name] = pid
            else:
                # Parâmetro partilhado ou de projeto
                elem = doc.GetElement(pid)
                if elem and hasattr(elem, 'GetDefinition'):
                    name = elem.GetDefinition().Name
                    if name:
                        result[name] = pid
        except Exception:
            pass

    # Sempre adicionar TODOS os parâmetros partilhados do projecto, mesmo que não
    # sejam comuns a todas as categorias seleccionadas. Garante que parâmetros
    # partilhados (ex: MTQ) nunca desaparecem ao seleccionar categorias mistas.
    for sp in FilteredElementCollector(doc).OfClass(SharedParameterElement):
        try:
            defn = sp.GetDefinition()
            name = defn.Name
            if name and name not in result:
                result[name] = defn.Id
        except Exception:
            pass

    return result


def _fallback_params(doc, cat_ids):
    """Fallback: parâmetros partilhados + scan de elementos."""
    from Autodesk.Revit.DB import StorageType
    result = {}
    for sp in FilteredElementCollector(doc).OfClass(SharedParameterElement):
        try:
            defn = sp.GetDefinition()
            if defn.Name not in result:
                result[defn.Name] = defn.Id
        except Exception:
            pass
    for cat_id in cat_ids:
        elems = list(
            FilteredElementCollector(doc).OfCategoryId(cat_id)
            .WhereElementIsNotElementType().ToElements()
        )[:3]
        for elem in elems:
            try:
                for p in elem.GetOrderedParameters():
                    if p.StorageType == StorageType.String and p.Definition.Name not in result:
                        result[p.Definition.Name] = p.Definition.Id
            except Exception:
                pass
    return result


def _get_param_on_element(elem, param_id, doc):
    """Tenta obter um parâmetro num elemento dado o seu ElementId."""
    int_val = param_id.IntegerValue
    if int_val < 0:
        try:
            return elem.get_Parameter(BuiltInParameter(int_val))
        except Exception:
            return None
    else:
        try:
            sp = doc.GetElement(param_id)
            if sp and hasattr(sp, 'GetDefinition'):
                return elem.get_Parameter(sp.GetDefinition())
        except Exception:
            pass
        # Fallback: match by Id in all parameters
        try:
            for p in elem.Parameters:
                if p.Definition.Id == param_id:
                    return p
        except Exception:
            pass
        return None


def _collect_value(elem, param_id, doc, values):
    """Tenta extrair o valor de um parâmetro num elemento e adiciona ao set."""
    try:
        p = _get_param_on_element(elem, param_id, doc)
        if p is not None:
            val = None
            try:
                val = p.AsString()
            except Exception:
                pass
            if not val:
                try:
                    val = p.AsValueString()
                except Exception:
                    pass
            if val and val.strip():
                values.add(val.strip())
    except Exception:
        pass


def _get_params_strict(doc, cat_id):
    """GetFilterableParametersInCommon para UMA categoria, sem fallback."""
    result = {}
    id_list = List[ElementId]([cat_id])
    try:
        param_ids = ParameterFilterUtilities.GetFilterableParametersInCommon(doc, id_list)
    except Exception:
        return result
    for pid in param_ids:
        try:
            int_val = pid.IntegerValue
            if int_val < 0:
                name = LabelUtils.GetLabelFor(BuiltInParameter(int_val))
            else:
                elem = doc.GetElement(pid)
                name = elem.GetDefinition().Name if (elem and hasattr(elem, 'GetDefinition')) else None
            if name:
                result[name] = pid
        except Exception:
            pass
    return result


def get_all_params_with_categories(doc):
    """Devolve {param_name: [param_id, [cat_id, ...]]} — mapa inverso parâmetro→categorias."""
    cat_map = get_categories(doc)
    result = {}
    for cat_name, cat_id in cat_map.items():
        for pname, pid in _get_params_strict(doc, cat_id).items():
            if pname not in result:
                result[pname] = [pid, []]
            result[pname][1].append(cat_id)
    return result


def get_fill_patterns(doc):
    """Devolve OrderedDict {nome: ElementId|None} de fill patterns de rascunho.
    None = solid fill (resolvido em runtime via get_solid_fill_pattern_id).
    ElementId.InvalidElementId = sem padrão.
    """
    try:
        from collections import OrderedDict
        from Autodesk.Revit.DB import FillPatternElement, FillPatternTarget
    except Exception:
        return {}
    result = OrderedDict()
    result[u'<Solid fill>'] = None
    result[u'<Sem padrão>'] = ElementId.InvalidElementId
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            pat = fp.GetFillPattern()
            if pat.Target == FillPatternTarget.Drafting and not pat.IsSolidFill:
                result[fp.Name] = fp.Id
        except Exception:
            pass
    return result


def get_unique_values(doc, cat_ids, param_id):
    """Devolve lista ordenada de valores únicos do parâmetro nos elementos do projeto.
    Procura em instâncias E nos seus tipos (cobre 'Type Name' e similares).
    """
    values = set()
    seen_type_ids = set()
    for cat_id in cat_ids:
        instances = []
        try:
            instances = list(
                FilteredElementCollector(doc).OfCategoryId(cat_id)
                .WhereElementIsNotElementType().ToElements()
            )
        except Exception:
            pass

        for elem in instances:
            # Tentar no próprio elemento (parâmetros de instância)
            _collect_value(elem, param_id, doc, values)
            # Tentar no tipo do elemento (cobre Type Name, Family Name, etc.)
            try:
                tid = elem.GetTypeId()
                if tid is not None and tid not in seen_type_ids:
                    seen_type_ids.add(tid)
                    type_elem = doc.GetElement(tid)
                    if type_elem is not None:
                        _collect_value(type_elem, param_id, doc, values)
            except Exception:
                pass

    return sorted(values)
