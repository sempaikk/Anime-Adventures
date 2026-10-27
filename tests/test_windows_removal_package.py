"""Removal delivery is allowlisted, readable, and includes no project data."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.build_windows_removal import build,ROOT


class RemovalPackageTests(unittest.TestCase):
    def test_package_contains_exactly_the_readable_removal_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'removal.zip';info=build(target)
            self.assertGreater(info['bytes'],0)
            with zipfile.ZipFile(target) as bundle:
                self.assertEqual(set(bundle.namelist()),{'REMOVER-PYTHON-E-BOT.cmd','remove_python_windows.ps1','LEIA-ME-REMOCAO.txt'})
                self.assertEqual(bundle.read('remove_python_windows.ps1'),(ROOT/'scripts/remove_python_windows.ps1').read_bytes())
                self.assertEqual(bundle.read('REMOVER-PYTHON-E-BOT.cmd'),(ROOT/'REMOVER-PYTHON-E-BOT.cmd').read_bytes())
