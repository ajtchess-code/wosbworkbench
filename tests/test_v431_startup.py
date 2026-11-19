"""Regression tests for the v4.3.1 desktop startup crash."""
import ast
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DesktopStartupSyntaxTests(unittest.TestCase):
    def test_no_accidental_subscript_on_iterable_functions(self):
        # Python lets us write enumerate[...] as a GenericAlias, but it is
        # *not* a call: the Overview then crashes before the window appears.
        for path in ROOT.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                    self.assertNotIn(node.value.id, {'enumerate','zip','range','map','filter','reversed'},
                                     f'{path.name}:{node.lineno}: possible function indexed instead of called')

    def test_overview_uses_enumerate_call(self):
        tree = ast.parse((ROOT/'workbench_ui.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_overview')
        route_loop = next(n for n in ast.walk(method)
            if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
               and len(n.target.elts) == 2
               and isinstance(n.target.elts[1], ast.Tuple)
               and [x.id for x in n.target.elts[1].elts] == ['title', 'route'])
        self.assertIsInstance(route_loop.iter, ast.Call)
        self.assertIsInstance(route_loop.iter.func, ast.Name)
        self.assertEqual(route_loop.iter.func.id, 'enumerate')
        self.assertEqual(len(route_loop.iter.args), 1)
        self.assertIsInstance(route_loop.iter.args[0], ast.List)
        self.assertEqual(len(route_loop.iter.args[0].elts), 8)  # v4.3.6 adds 'Wiki articles'

    def test_version_and_packaging_consistent(self):
        """v4.3.6: workbench_db.VERSION is the single source; packaging reads it instead of hard-coding."""
        version=re.search(r"VERSION = '([0-9.]+)'",(ROOT/'workbench_db.py').read_text(encoding='utf-8')).group(1)
        self.assertEqual(version,'4.9.1')
        for filename in ['Build-Update.cmd','packaging/Build-Windows.ps1','packaging/WoSBWorkbench.iss','.github/workflows/build-and-release.yml']:
            content=(ROOT/filename).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r"\b4\.\d+\.\d+\b",content),filename+' hard-codes a version')
        self.assertIn('from workbench_db import VERSION',(ROOT/'packaging/Build-Windows.ps1').read_text(encoding='utf-8'))
        self.assertIn('/DMyAppVersion=',(ROOT/'packaging/Build-Windows.ps1').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
