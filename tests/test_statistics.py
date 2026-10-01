"""Unit tests for feed statistics (VWAP, TWAP, volatility)."""

import math

import pytest

from src.feed.statistics import FeedStatistics


def test_vwap_basic():
    """VWAP = sum(price * volume) / sum(volume)."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=10.0)
    stats.add_tick(price=110.0, volume=20.0)
    stats.add_tick(price=120.0, volume=30.0)
    # (100*10 + 110*20 + 120*30) / (10+20+30) = (1000+2200+3600)/60 = 6800/60
    assert stats.vwap() == pytest.approx(6800.0 / 60.0)


def test_twap_basic():
    """TWAP = simple average of prices."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    stats.add_tick(price=110.0, volume=1.0)
    stats.add_tick(price=120.0, volume=1.0)
    assert stats.twap() == pytest.approx(110.0)


def test_volatility_basic():
    """Volatility = population standard deviation of prices."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    stats.add_tick(price=110.0, volume=1.0)
    stats.add_tick(price=120.0, volume=1.0)
    # mean=110, variance=((100-110)^2+(110-110)^2+(120-110)^2)/3 = (100+0+100)/3 = 66.67
    # std = sqrt(66.67) ≈ 8.165
    assert stats.volatility() == pytest.approx(math.sqrt(200.0 / 3.0))


def test_vwap_empty():
    """VWAP with no ticks returns 0."""
    stats = FeedStatistics()
    assert stats.vwap() == 0.0


def test_twap_empty():
    """TWAP with no ticks returns 0."""
    stats = FeedStatistics()
    assert stats.twap() == 0.0


def test_volatility_empty():
    """Volatility with no ticks returns 0."""
    stats = FeedStatistics()
    assert stats.volatility() == 0.0


def test_volatility_single_tick():
    """Volatility with one tick returns 0 (no variance)."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    assert stats.volatility() == 0.0


def test_vwap_zero_volume():
    """VWAP with zero total volume returns 0."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=0.0)
    stats.add_tick(price=200.0, volume=0.0)
    assert stats.vwap() == 0.0


def test_vwap_single_tick():
    """VWAP with one tick equals that tick's price."""
    stats = FeedStatistics()
    stats.add_tick(price=150.0, volume=10.0)
    assert stats.vwap() == pytest.approx(150.0)


def test_twap_single_tick():
    """TWAP with one tick equals that tick's price."""
    stats = FeedStatistics()
    stats.add_tick(price=150.0, volume=10.0)
    assert stats.twap() == pytest.approx(150.0)


def test_vwap_weighted_correctly():
    """VWAP gives more weight to higher-volume ticks."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    stats.add_tick(price=200.0, volume=9.0)
    # (100*1 + 200*9) / 10 = 1900/10 = 190
    assert stats.vwap() == pytest.approx(190.0)


def test_twap_unweighted():
    """TWAP treats all ticks equally regardless of volume."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    stats.add_tick(price=200.0, volume=9.0)
    assert stats.twap() == pytest.approx(150.0)


def test_volatility_constant_prices():
    """Volatility is 0 when all prices are the same."""
    stats = FeedStatistics()
    stats.add_tick(price=100.0, volume=1.0)
    stats.add_tick(price=100.0, volume=2.0)
    stats.add_tick(price=100.0, volume=3.0)
    assert stats.volatility() == pytest.approx(0.0)


def test_volatility_two_ticks():
    """Volatility with two ticks."""
    stats = FeedStatistics()
    stats.add_tick(price=90.0, volume=1.0)
    stats.add_tick(price=110.0, volume=1.0)
    # mean=100, variance=((90-100)^2+(110-100)^2)/2 = (100+100)/2 = 100, std=10
    assert stats.volatility() == pytest.approx(10.0)


def test_many_ticks():
    """Statistics work correctly with many ticks."""
    stats = FeedStatistics()
    for i in range(100):
        stats.add_tick(price=float(i), volume=1.0)
    assert stats.twap() == pytest.approx(49.5)
    assert stats.vwap() == pytest.approx(49.5)
    # population std of 0..99
    expected_std = math.sqrt(sum((i - 49.5) ** 2 for i in range(100)) / 100)
    assert stats.volatility() == pytest.approx(expected_std)


def test_negative_prices():
    """Statistics handle negative prices (e.g., spread instruments)."""
    stats = FeedStatistics()
    stats.add_tick(price=-10.0, volume=1.0)
    stats.add_tick(price=10.0, volume=1.0)
    assert stats.twap() == pytest.approx(0.0)
    assert stats.vwap() == pytest.approx(0.0)
    assert stats.volatility() == pytest.approx(10.0)


def test_fractional_prices_and_volumes():
    """Statistics handle fractional values."""
    stats = FeedStatistics()
    stats.add_tick(price=100.5, volume=0.5)
    stats.add_tick(price=101.5, volume=1.5)
    # VWAP = (100.5*0.5 + 101.5*1.5) / 2.0 = (50.25 + 152.25) / 2 = 101.25
    assert stats.vwap() == pytest.approx(101.25)
    assert stats.twap() == pytest.approx(101.0)
