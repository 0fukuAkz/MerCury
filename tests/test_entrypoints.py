"""Tests for entry points like __main__.py."""

import runpy
from unittest.mock import patch

def test_main_entrypoint():
    with patch("mercury.cli.main.main") as mock_main:
        runpy.run_module("mercury.__main__", run_name="__main__")
        mock_main.assert_called_once()
