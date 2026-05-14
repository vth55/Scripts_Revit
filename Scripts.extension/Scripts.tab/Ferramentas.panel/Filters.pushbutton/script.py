# -*- coding: utf-8 -*-
"""Filter Manager entrypoint."""
__title__ = "Filters"
__author__ = "Vitor Hugo"

import main_window_logic
reload(main_window_logic)
main_window_logic.MainWindow().ShowDialog()
