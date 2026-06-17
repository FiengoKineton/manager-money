"""Lightweight invariants for future refactors.

Run from the repo root with:
    python -m unittest tests.test_financial_invariants
"""

from __future__ import annotations

import unittest

from money_manager.services.account_service import main_account_transactions
from money_manager.services.net_explanation_service import build_net_explanation_context
from money_manager.services.overview_service import _build_overview_context_uncached, build_overview_context
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals


class FinancialInvariantTests(unittest.TestCase):
    def test_cached_and_uncached_overview_match(self) -> None:
        cached = build_overview_context()
        uncached = _build_overview_context_uncached()
        keys = [
            "all_accounts_net",
            "cash_position",
            "stress_position",
            "adjusted_stress_position",
            "combined_visible_liquidity",
            "market_adjusted_position",
        ]
        self.assertEqual(cached["totals"], uncached["totals"])
        for key in keys:
            self.assertAlmostEqual(float(cached[key]), float(uncached[key]), places=6)

    def test_topbar_net_matches_main_account_summary(self) -> None:
        df = load_transactions()
        main_df = main_account_transactions(df)
        overview = _build_overview_context_uncached()
        self.assertAlmostEqual(float(summary_totals(main_df)["net"]), float(overview["totals"]["net"]), places=6)

    def test_net_explanation_reuses_overview_value(self) -> None:
        explanation = build_net_explanation_context()
        overview = _build_overview_context_uncached()
        self.assertAlmostEqual(
            float(explanation["overview"]["totals"]["net"]),
            float(overview["totals"]["net"]),
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
