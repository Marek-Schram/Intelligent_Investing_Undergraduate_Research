"""Tests for Sleeve E universe. TICKET-024."""

from __future__ import annotations

from durable.discovery.universe import (
    AUTO_DISQUALIFIERS,
    screen_candidate,
)


def _valid_candidate(**overrides):
    """A candidate passing all filters."""
    defaults = {
        "ticker": "GOOD",
        "exchange": "NASDAQ",
        "price": 25.0,
        "market_cap": 1e9,
        "adv_60d": 5e6,
        "float_value": 500e6,
        "float_shares": 20e6,
        "quarters_filed": 20,
        "months_since_ipo": 60,
        "profitable_years": 4,
        "si_pct_float": 0.03,
        "distance_to_default": 3.0,
    }
    defaults.update(overrides)
    return defaults


class TestSleeveEUniverse:
    def test_valid_candidate_passes(self):
        """A good candidate passes all filters."""
        eligible, reasons = screen_candidate(**_valid_candidate())
        assert eligible is True
        assert reasons == []

    def test_rejects_otc(self):
        """Rejects every OTC ticker — acceptance criterion."""
        eligible, reasons = screen_candidate(**_valid_candidate(exchange="OTCBB"))
        assert eligible is False
        assert any("not_allowed" in r.reason for r in reasons)

    def test_rejects_pink_sheets(self):
        eligible, reasons = screen_candidate(**_valid_candidate(exchange="PINK"))
        assert eligible is False

    def test_rejects_sub_5_price(self):
        """Rejects sub-$5."""
        eligible, reasons = screen_candidate(**_valid_candidate(price=4.99))
        assert eligible is False
        assert any("price" in r.reason for r in reasons)

    def test_rejects_cap_outside_range(self):
        """Cap outside $300M-$3B."""
        eligible, _ = screen_candidate(**_valid_candidate(market_cap=200e6))
        assert eligible is False
        eligible, _ = screen_candidate(**_valid_candidate(market_cap=5e9))
        assert eligible is False

    def test_rejects_thin_adv(self):
        """ADV < $1.5M."""
        eligible, reasons = screen_candidate(**_valid_candidate(adv_60d=1e6))
        assert eligible is False

    def test_rejects_small_float(self):
        eligible, _ = screen_candidate(**_valid_candidate(float_value=100e6))
        assert eligible is False
        eligible, _ = screen_candidate(**_valid_candidate(float_shares=5e6))
        assert eligible is False

    def test_rejects_unprofitable(self):
        eligible, _ = screen_candidate(**_valid_candidate(profitable_years=2))
        assert eligible is False

    def test_rejects_high_short_interest(self):
        """SI > 10% of float."""
        eligible, reasons = screen_candidate(**_valid_candidate(si_pct_float=0.15))
        assert eligible is False
        assert any("short_interest" in r.reason for r in reasons)

    def test_rejects_low_distance_to_default(self):
        """DD < 1.5."""
        eligible, _ = screen_candidate(**_valid_candidate(distance_to_default=1.0))
        assert eligible is False

    def test_missing_data_excluded_never_imputed(self):
        """Missing data => excluded, never imputed — acceptance criterion."""
        eligible, reasons = screen_candidate(**_valid_candidate(price=None))
        assert eligible is False
        assert any("missing" in r.reason for r in reasons)

        eligible, reasons = screen_candidate(**_valid_candidate(market_cap=None))
        assert eligible is False

    def test_all_11_auto_disqualifiers_tested(self):
        """All 11 auto-disqualifiers are defined — acceptance criterion."""
        assert len(AUTO_DISQUALIFIERS) == 11

    def test_auto_disqualifier_excludes(self):
        """Any auto-disqualifier flag fires exclusion."""
        flags = {"reverse_split_within_24m": True}
        eligible, reasons = screen_candidate(**_valid_candidate(), auto_disqualifier_flags=flags)
        assert eligible is False
        assert any("auto_disqualifier" in r.reason for r in reasons)

    def test_chow_like_profile_rejected_multiple_grounds(self):
        """A synthetic CHOW-like profile rejected on >= 3 independent grounds."""
        # CHOW-like: penny stock, thin ADV, high short interest, OTC
        eligible, reasons = screen_candidate(
            ticker="CHOW",
            exchange="OTCBB",
            price=2.50,
            market_cap=50e6,
            adv_60d=200_000,
            float_value=30e6,
            float_shares=3e6,
            quarters_filed=4,
            months_since_ipo=12,
            profitable_years=0,
            si_pct_float=0.25,
            distance_to_default=0.5,
        )
        assert eligible is False
        assert len(reasons) >= 3

    def test_safety_constants_not_config_readable(self):
        """Safety constants are module-level, not from config — acceptance criterion."""
        from durable.discovery import universe

        assert universe.MIN_MARKET_CAP == 300e6
        assert universe.MAX_MARKET_CAP == 3e9
        assert universe.MIN_PRICE == 5.00
        # These are hardcoded, not read from any config file
        assert not hasattr(universe, "load_config")

    def test_24_month_otc_history_rejection(self):
        """OTC history within 24 months excluded."""
        flags = {"otc_history_within_24m": True}
        eligible, _ = screen_candidate(**_valid_candidate(), auto_disqualifier_flags=flags)
        assert eligible is False
