# -*- coding: utf-8 -*-
"""子模块测试 conftest：把 tests/ 加入 sys.path 以便 import _llm_mock。"""
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
