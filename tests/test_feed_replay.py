"""Tests for Feed Replay — historical market data replay for backtesting."""

import pytest
from src.feed.replay import FeedReplay, ReplayTick


class TestFeedReplayBasic:
    """Basic replay functionality."""

    def test_replay_yields_ticks_in_order(self):
        """Replay should yield ticks in the order they were provided."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=2, price=101.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=3, price=102.0, volume=30),
        ]
        replay = FeedReplay(ticks)
        result = list(replay)
        assert len(result) == 3
        assert result[0].price == 100.0
        assert result[1].price == 101.0
        assert result[2].price == 102.0

    def test_replay_is_empty_when_no_ticks(self):
        """Replay with no ticks should yield nothing."""
        replay = FeedReplay([])
        assert list(replay) == []

    def test_replay_can_be_iterated_multiple_times(self):
        """Replay should support multiple iterations."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=2, price=101.0, volume=20),
        ]
        replay = FeedReplay(ticks)
        first_pass = list(replay)
        second_pass = list(replay)
        assert len(first_pass) == 2
        assert len(second_pass) == 2
        assert first_pass[0].price == second_pass[0].price

    def test_replay_preserves_tick_data(self):
        """Replay should not modify tick data."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10, bid=99.5, ask=100.5),
        ]
        replay = FeedReplay(ticks)
        result = list(replay)
        assert result[0].symbol == "AAPL"
        assert result[0].timestamp == 1
        assert result[0].price == 100.0
        assert result[0].volume == 10
        assert result[0].bid == 99.5
        assert result[0].ask == 100.5


class TestFeedReplayFiltering:
    """Filtering capabilities."""

    def test_replay_filter_by_symbol(self):
        """Replay should filter ticks by symbol."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="GOOG", timestamp=2, price=200.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=3, price=101.0, volume=30),
        ]
        replay = FeedReplay(ticks, symbol="AAPL")
        result = list(replay)
        assert len(result) == 2
        assert all(t.symbol == "AAPL" for t in result)

    def test_replay_filter_by_time_range(self):
        """Replay should filter ticks by time range."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=5, price=101.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=10, price=102.0, volume=30),
            ReplayTick(symbol="AAPL", timestamp=15, price=103.0, volume=40),
        ]
        replay = FeedReplay(ticks, start_time=5, end_time=10)
        result = list(replay)
        assert len(result) == 2
        assert result[0].timestamp == 5
        assert result[1].timestamp == 10

    def test_replay_filter_by_symbol_and_time(self):
        """Replay should support combined filtering."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="GOOG", timestamp=5, price=200.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=10, price=101.0, volume=30),
            ReplayTick(symbol="GOOG", timestamp=15, price=201.0, volume=40),
        ]
        replay = FeedReplay(ticks, symbol="AAPL", start_time=1, end_time=10)
        result = list(replay)
        assert len(result) == 2
        assert all(t.symbol == "AAPL" for t in result)


class TestFeedReplayControl:
    """Replay control and state."""

    def test_replay_limit_ticks(self):
        """Replay should support limiting number of ticks."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=i, price=100.0 + i, volume=10)
            for i in range(10)
        ]
        replay = FeedReplay(ticks, limit=3)
        result = list(replay)
        assert len(result) == 3

    def test_replay_tracks_position(self):
        """Replay should track current position."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=2, price=101.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=3, price=102.0, volume=30),
        ]
        replay = FeedReplay(ticks)
        assert replay.position == 0
        next(replay)
        assert replay.position == 1
        next(replay)
        assert replay.position == 2

    def test_replay_can_be_reset(self):
        """Replay should support reset to beginning."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=2, price=101.0, volume=20),
        ]
        replay = FeedReplay(ticks)
        next(replay)
        next(replay)
        assert replay.position == 2
        replay.reset()
        assert replay.position == 0
        result = list(replay)
        assert len(result) == 2

    def test_replay_seek_to_position(self):
        """Replay should support seeking to a specific position."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=i, price=100.0 + i, volume=10)
            for i in range(5)
        ]
        replay = FeedReplay(ticks)
        replay.seek(2)
        assert replay.position == 2
        result = [next(replay), next(replay), next(replay)]
        assert len(result) == 3
        assert result[0].timestamp == 2

    def test_replay_seek_beyond_end_raises(self):
        """Seeking beyond the end should raise an error."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
        ]
        replay = FeedReplay(ticks)
        with pytest.raises(IndexError):
            replay.seek(10)


class TestFeedReplayCallback:
    """Callback support."""

    def test_replay_with_callback(self):
        """Replay should support a callback function."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="AAPL", timestamp=2, price=101.0, volume=20),
        ]
        collected = []
        replay = FeedReplay(ticks, callback=collected.append)
        list(replay)
        assert len(collected) == 2
        assert collected[0].price == 100.0
        assert collected[1].price == 101.0


class TestFeedReplayStats:
    """Replay statistics."""

    def test_replay_tick_count(self):
        """Replay should report total tick count."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=i, price=100.0 + i, volume=10)
            for i in range(7)
        ]
        replay = FeedReplay(ticks)
        assert replay.tick_count == 7

    def test_replay_filtered_tick_count(self):
        """Replay should report filtered tick count."""
        ticks = [
            ReplayTick(symbol="AAPL", timestamp=1, price=100.0, volume=10),
            ReplayTick(symbol="GOOG", timestamp=2, price=200.0, volume=20),
            ReplayTick(symbol="AAPL", timestamp=3, price=101.0, volume=30),
        ]
        replay = FeedReplay(ticks, symbol="AAPL")
        assert replay.tick_count == 2
