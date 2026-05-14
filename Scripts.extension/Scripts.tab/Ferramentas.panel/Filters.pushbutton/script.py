# -*- coding: utf-8 -*-
"""Filter Manager entrypoint."""
__title__ = "Filters"
__author__ = "Vitor Hugo"

import os
import sys

_HERE = os.path.dirname(__file__)
_cursor = _HERE
while _cursor and not _cursor.lower().endswith('.extension'):
    parent = os.path.dirname(_cursor)
    if parent == _cursor:
        break
    _cursor = parent
if _cursor and _cursor.lower().endswith('.extension'):
    _lib = os.path.join(_cursor, 'lib')
    if os.path.isdir(_lib) and _lib not in sys.path:
        sys.path.insert(0, _lib)

import main_window_logic
reload(main_window_logic)
main_window_logic.MainWindow().ShowDialog()
