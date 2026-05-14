# -*- coding: utf-8 -*-
"""Global filter schemes for MTQ Filter Manager."""
import os
import json
import codecs


SCHEMES_FILE = os.path.join(
    os.environ.get('APPDATA', ''), 'pyRevit', 'MTQ_filter_schemes.json'
)


def _ensure_dir():
    d = os.path.dirname(SCHEMES_FILE)
    if d and not os.path.exists(d):
        os.makedirs(d)


def load_schemes():
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with codecs.open(SCHEMES_FILE, 'r', enc) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _to_unicode(obj):
    """Recursively convert byte strings to unicode for safe JSON serialisation."""
    if isinstance(obj, bytes):
        for enc in ('utf-8', 'cp1252', 'latin-1'):
            try:
                return obj.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return obj.decode('latin-1', errors='replace')
    if isinstance(obj, list):
        return [_to_unicode(v) for v in obj]
    if isinstance(obj, dict):
        return {_to_unicode(k): _to_unicode(v) for k, v in obj.items()}
    return obj


def save_schemes(schemes):
    _ensure_dir()
    data = _to_unicode(schemes or [])
    with codecs.open(SCHEMES_FILE, 'w', 'utf-8') as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


def unique_name(base, schemes):
    base = (base or 'Novo esquema').strip() or 'Novo esquema'
    names = set(s.get('name', '') for s in schemes or [])
    if base not in names:
        return base
    i = 2
    while '{} {}'.format(base, i) in names:
        i += 1
    return '{} {}'.format(base, i)


def find_scheme(schemes, name):
    for scheme in schemes or []:
        if scheme.get('name') == name:
            return scheme
    return None
