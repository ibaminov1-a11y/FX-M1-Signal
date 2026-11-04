"""Regression checks for the NORMAL basket global position limit.

Run from repository root:
    python -m unittest discover -s tests -p 'test_normal_basket_safety.py'

No MT5 terminal, Flask server, or credentials required.
"""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "mt5_bridge" / "bridge_v10_0.py"


class NormalBasketSafetyTests(unittest.TestCase):
    def test_bridge_parses(self):
        ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))

    def test_global_cap_is_checked_before_basket_snapshot(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        signal = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "signal")
        branches = [n for n in ast.walk(signal) if isinstance(n, ast.If) and
                    isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not) and
                    isinstance(n.test.operand, ast.Name) and n.test.operand.id == "basket_mode"]
        self.assertEqual(len(branches), 1)
        basket_branch = branches[0].orelse
        self.assertTrue(basket_branch)
        first = basket_branch[0]
        self.assertIsInstance(first, ast.If)
        self.assertIn("len(current_positions) >= max_positions", ast.unparse(first.test))
        self.assertIn("GLOBAL_POSITION_LIMIT", ast.unparse(first))
        self.assertIn("basket_snapshot", ast.unparse(basket_branch[1]))


if __name__ == "__main__":
    unittest.main()
