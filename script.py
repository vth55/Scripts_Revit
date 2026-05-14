# -*- coding: utf-8 -*-
"""MTQ Filter Manager entrypoint."""
__title__ = "MTQ\nFilters"
__author__ = "Vitor Hugo"

import main_window_logic
reload(main_window_logic)
main_window_logic.MainWindow().ShowDialog()
