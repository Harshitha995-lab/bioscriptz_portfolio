"""Spending guard for Apify's free plan ($5 of credit a month, no rollover).

Nothing here calls Apify. It estimates what a run would cost, compares that with what the month has already used (from
the vault's ledger), and works out how many results fit. The price per 1,000 results must come from the chosen actor's
page, because it differs between actors and changes; an assumed price is used only for a dry run and is labelled as such.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FREE_CREDIT_USD = 5.0
RESERVE_USD = 0.25                 # never plan to use the last bit; actual usage can differ slightly from the estimate
ASSUMED_PRICE_PER_1000 = 2.70      # top of the range third-party sources quote ($1.50 to $2.70); dry runs only
CREATOR_SHARE = 0.4                # share of the budget spent on creator profiles (they give each creator a baseline)


@dataclass
class Plan:
    keyword_runs: int
    per_keyword: int
    creators: int
    per_creator: int
    price_per_1000: float
    price_assumed: bool

    @property
    def results(self) -> int:
        return self.keyword_runs * self.per_keyword + self.creators * self.per_creator

    @property
    def est_cost(self) -> float:
        return self.results / 1000 * self.price_per_1000


def affordable_results(remaining_usd: float, price_per_1000: float) -> int:
    usable = max(remaining_usd - RESERVE_USD, 0.0)
    return int(usable / price_per_1000 * 1000) if price_per_1000 > 0 else 0


def recommend(remaining_usd: float, price_per_1000: float, n_keywords: int, n_creators: int, *, max_per_creator: int = 15) -> tuple[int, int]:
    """(per_keyword, per_creator) that fit the remaining budget, giving creator profiles up to 40% of it."""
    total = affordable_results(remaining_usd, price_per_1000)
    per_creator = 0
    if n_creators:
        per_creator = min(max_per_creator, int(total * CREATOR_SHARE) // n_creators)
        per_creator = per_creator if per_creator >= 5 else 0          # fewer than 5 Reels gives no usable baseline
    left = total - per_creator * n_creators
    per_keyword = left // n_keywords if n_keywords else 0
    return per_keyword, per_creator


def make_plan(n_keywords: int, n_creators: int, per_keyword: int, per_creator: int, price: float | None) -> Plan:
    assumed = price is None
    return Plan(n_keywords, per_keyword, n_creators, per_creator, ASSUMED_PRICE_PER_1000 if assumed else float(price), assumed)


def check(plan: Plan, month_spent: float, credit: float = FREE_CREDIT_USD) -> tuple[bool, float, str]:
    """(ok, remaining, message). A run is allowed only if its estimate fits inside what is left, less the reserve."""
    remaining = max(credit - month_spent, 0.0)
    if plan.est_cost > max(remaining - RESERVE_USD, 0.0) + 1e-9:
        fits = affordable_results(remaining, plan.price_per_1000)
        return False, remaining, (f"This run would cost about ${plan.est_cost:.2f} for {plan.results:,} results, but only ${remaining:.2f} of "
                                  f"${credit:.2f} is left this month (about {fits:,} results after a ${RESERVE_USD:.2f} reserve). "
                                  "Lower --per-keyword / --per-creator, or run less often.")
    return True, remaining, f"Estimated ${plan.est_cost:.2f} for {plan.results:,} results; ${remaining:.2f} left this month."


def per_run_cap(remaining_usd: float, n_runs: int) -> float:
    """What each Apify run is allowed to charge, so that all runs together cannot exceed the remaining budget."""
    return round(max(remaining_usd - RESERVE_USD, 0.0) / max(n_runs, 1), 4)


def runs_needed(n_keywords: int, n_creators: int, per_keyword: int, per_creator: int) -> int:
    return (n_keywords if per_keyword else 0) + (1 if n_creators and per_creator else 0)
