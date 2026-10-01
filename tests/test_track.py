"""Tests for Track Management — M-of-N initiation, confirmation, deletion, quality.

Covers:
- Track initiation from detection
- M-of-N confirmation logic
- Track deletion on consecutive misses
- Quality score calculation
- Track association and gating
- Manual operations
- Edge cases
"""

import pytest

from src.fusion.track import (
    Track,
    TrackConfig,
    TrackManager,
    TrackStatus,
)


class TestTrackInitiation:
    """Tests for track initiation."""

    def setup_method(self):
        self.manager = TrackManager()

    def test_initiate_track_creates_tentative_track(self):
        track = self.manager.initiate_track((10.0, 20.0))
        assert track is not None
        assert track.status == TrackStatus.TENTATIVE
        assert track.position == (10.0, 20.0)
        assert track.hits == 1
        assert track.misses == 0

    def test_initiate_track_generates_unique_ids(self):
        t1 = self.manager.initiate_track((0.0, 0.0))
        t2 = self.manager.initiate_track((1.0, 1.0))
        assert t1.track_id != t2.track_id

    def test_initiate_track_with_velocity(self):
        track = self.manager.initiate_track((5.0, 5.0), velocity=(1.0, 2.0))
        assert track.velocity == (1.0, 2.0)

    def test_initiate_track_sets_timestamps(self):
        track = self.manager.initiate_track((0.0, 0.0), timestamp=100.0)
        assert track.created_at == 100.0
        assert track.last_update == 100.0

    def test_initiate_track_initial_quality(self):
        track = self.manager.initiate_track((0.0, 0.0))
        assert track.quality_score > 0.0
        assert track.quality_score < 1.0

    def test_initiate_track_adds_to_manager(self):
        track = self.manager.initiate_track((0.0, 0.0))
        assert self.manager.get_track(track.track_id) is track

    def test_initiate_track_history_recorded(self):
        track = self.manager.initiate_track((0.0, 0.0))
        assert len(track.history) == 1
        assert track.history[0]["event"] == "initiated"


class TestTrackConfirmation:
    """Tests for M-of-N track confirmation."""

    def setup_method(self):
        self.config = TrackConfig(m_of_n=3, n_of_n=5, min_quality_score=0.3)
        self.manager = TrackManager(self.config)

    def test_track_confirms_after_m_hits(self):
        track = self.manager.initiate_track((0.0, 0.0))
        # First hit already counted, need 2 more
        self.manager.update_track(track.track_id, (1.0, 1.0))
        assert track.status == TrackStatus.TENTATIVE
        self.manager.update_track(track.track_id, (2.0, 2.0))
        assert track.status == TrackStatus.CONFIRMED

    def test_track_not_confirmed_before_m_hits(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.update_track(track.track_id, (1.0, 1.0))
        assert track.status == TrackStatus.TENTATIVE

    def test_confirmation_requires_min_quality(self):
        # Use impossible quality threshold — track should never auto-confirm
        config = TrackConfig(m_of_n=2, n_of_n=5, min_quality_score=1.1)
        manager = TrackManager(config)
        track = manager.initiate_track((0.0, 0.0))
        manager.update_track(track.track_id, (1.0, 1.0))
        manager.update_track(track.track_id, (2.0, 2.0))
        # Even with enough hits, quality can never reach 1.1
        assert track.status == TrackStatus.TENTATIVE

    def test_manual_confirmation(self):
        track = self.manager.initiate_track((0.0, 0.0))
        result = self.manager.confirm_track(track.track_id)
        assert result is True
        assert track.status == TrackStatus.CONFIRMED

    def test_manual_confirmation_nonexistent_track(self):
        result = self.manager.confirm_track("NONEXISTENT")
        assert result is False

    def test_confirmation_recorded_in_history(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.update_track(track.track_id, (1.0, 1.0))
        self.manager.update_track(track.track_id, (2.0, 2.0))
        events = [h["event"] for h in track.history]
        assert "confirmed" in events


class TestTrackDeletion:
    """Tests for track deletion."""

    def setup_method(self):
        self.config = TrackConfig(max_misses=3)
        self.manager = TrackManager(self.config)

    def test_track_deleted_after_max_misses(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.update_track(track.track_id)  # miss 1
        assert track.status != TrackStatus.DELETED
        self.manager.update_track(track.track_id)  # miss 2
        assert track.status != TrackStatus.DELETED
        self.manager.update_track(track.track_id)  # miss 3
        assert track.status == TrackStatus.DELETED

    def test_misses_reset_on_hit(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.update_track(track.track_id)  # miss 1
        self.manager.update_track(track.track_id)  # miss 2
        self.manager.update_track(track.track_id, (1.0, 1.0))  # hit resets
        assert track.misses == 0
        assert track.status != TrackStatus.DELETED

    def test_manual_deletion(self):
        track = self.manager.initiate_track((0.0, 0.0))
        result = self.manager.delete_track(track.track_id)
        assert result is True
        assert track.status == TrackStatus.DELETED

    def test_manual_deletion_nonexistent(self):
        result = self.manager.delete_track("NONEXISTENT")
        assert result is False

    def test_deleted_track_not_updated(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.delete_track(track.track_id)
        result = self.manager.update_track(track.track_id, (1.0, 1.0))
        assert result is None

    def test_deletion_recorded_in_history(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.delete_track(track.track_id)
        events = [h["event"] for h in track.history]
        assert "manually_deleted" in events


class TestQualityScoring:
    """Tests for track quality scoring."""

    def setup_method(self):
        self.manager = TrackManager()

    def test_quality_increases_with_hits(self):
        track = self.manager.initiate_track((0.0, 0.0))
        initial_quality = track.quality_score
        self.manager.update_track(track.track_id, (1.0, 1.0))
        assert track.quality_score > initial_quality

    def test_quality_decreases_with_misses(self):
        track = self.manager.initiate_track((0.0, 0.0))
        # Get some hits first
        for i in range(3):
            self.manager.update_track(track.track_id, (float(i), float(i)))
        quality_with_hits = track.quality_score
        # Now miss
        self.manager.update_track(track.track_id)
        assert track.quality_score < quality_with_hits

    def test_quality_bounded_0_to_1(self):
        track = self.manager.initiate_track((0.0, 0.0))
        for i in range(20):
            self.manager.update_track(track.track_id, (float(i), float(i)))
        assert 0.0 <= track.quality_score <= 1.0

    def test_quality_uses_hit_ratio(self):
        track = self.manager.initiate_track((0.0, 0.0))
        # 1 hit, 0 misses -> high hit ratio
        assert track.hits == 1
        assert track.misses == 0
        quality = track.quality_score
        assert quality > 0.0

    def test_quality_decay_on_misses(self):
        config = TrackConfig(quality_decay=0.5)
        manager = TrackManager(config)
        track = manager.initiate_track((0.0, 0.0))
        for i in range(3):
            manager.update_track(track.track_id, (float(i), float(i)))
        quality_before = track.quality_score
        manager.update_track(track.track_id)  # miss
        # Quality should drop significantly with decay=0.5
        assert track.quality_score < quality_before * 0.8


class TestTrackAssociation:
    """Tests for detection-to-track association."""

    def setup_method(self):
        self.config = TrackConfig(gating_threshold=10.0)
        self.manager = TrackManager(self.config)

    def test_detection_associates_with_existing_track(self):
        track = self.manager.initiate_track((0.0, 0.0))
        track2, is_new = self.manager.process_detection((1.0, 1.0))
        assert is_new is False
        assert track2.track_id == track.track_id

    def test_detection_creates_new_track_when_far(self):
        track = self.manager.initiate_track((0.0, 0.0))
        track2, is_new = self.manager.process_detection((100.0, 100.0))
        assert is_new is True
        assert track2.track_id != track.track_id

    def test_gating_threshold_respected(self):
        track = self.manager.initiate_track((0.0, 0.0))
        # Within threshold
        track2, is_new = self.manager.process_detection((5.0, 5.0))
        assert is_new is False
        # Outside threshold
        track3, is_new = self.manager.process_detection((50.0, 50.0))
        assert is_new is True

    def test_multiple_tracks_association(self):
        t1 = self.manager.initiate_track((0.0, 0.0))
        t2 = self.manager.initiate_track((100.0, 100.0))
        # Should associate with closest
        track, is_new = self.manager.process_detection((2.0, 2.0))
        assert is_new is False
        assert track.track_id == t1.track_id


class TestTrackManagerOperations:
    """Tests for track manager utility operations."""

    def setup_method(self):
        self.manager = TrackManager()

    def test_get_all_tracks(self):
        self.manager.initiate_track((0.0, 0.0))
        self.manager.initiate_track((1.0, 1.0))
        assert len(self.manager.get_all_tracks()) == 2

    def test_get_confirmed_tracks(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.confirm_track(track.track_id)
        self.manager.initiate_track((1.0, 1.0))
        confirmed = self.manager.get_confirmed_tracks()
        assert len(confirmed) == 1
        assert confirmed[0].track_id == track.track_id

    def test_get_tentative_tracks(self):
        track = self.manager.initiate_track((0.0, 0.0))
        self.manager.initiate_track((1.0, 1.0))
        self.manager.confirm_track(track.track_id)
        tentative = self.manager.get_tentative_tracks()
        assert len(tentative) == 1

    def test_get_active_tracks(self):
        t1 = self.manager.initiate_track((0.0, 0.0))
        self.manager.initiate_track((1.0, 1.0))
        self.manager.delete_track(t1.track_id)
        active = self.manager.get_active_tracks()
        assert len(active) == 1

    def test_reset_clears_all_tracks(self):
        self.manager.initiate_track((0.0, 0.0))
        self.manager.initiate_track((1.0, 1.0))
        self.manager.reset()
        assert len(self.manager.get_all_tracks()) == 0

    def test_get_stats(self):
        t1 = self.manager.initiate_track((0.0, 0.0))
        self.manager.initiate_track((1.0, 1.0))
        self.manager.confirm_track(t1.track_id)
        stats = self.manager.get_stats()
        assert stats["total"] == 2
        assert stats["confirmed"] == 1
        assert stats["tentative"] == 1
        assert stats["deleted"] == 0

    def test_get_track_nonexistent(self):
        result = self.manager.get_track("NONEXISTENT")
        assert result is None

    def test_update_track_nonexistent(self):
        result = self.manager.update_track("NONEXISTENT", (1.0, 1.0))
        assert result is None


class TestTrackConfig:
    """Tests for track configuration."""

    def test_default_config(self):
        config = TrackConfig()
        assert config.m_of_n == 3
        assert config.n_of_n == 5
        assert config.max_misses == 3
        assert config.min_quality_score == 0.3

    def test_custom_config(self):
        config = TrackConfig(m_of_n=5, n_of_n=10, max_misses=5)
        assert config.m_of_n == 5
        assert config.n_of_n == 10
        assert config.max_misses == 5

    def test_config_affects_confirmation(self):
        config = TrackConfig(m_of_n=5, min_quality_score=0.1)
        manager = TrackManager(config)
        track = manager.initiate_track((0.0, 0.0))
        for i in range(3):
            manager.update_track(track.track_id, (float(i), float(i)))
        # Only 4 hits total (1 initial + 3 updates), need 5
        assert track.status == TrackStatus.TENTATIVE


class TestTrackEdgeCases:
    """Edge case tests for track management."""

    def test_rapid_hits_and_misses(self):
        manager = TrackManager()
        track = manager.initiate_track((0.0, 0.0))
        for i in range(10):
            if i % 2 == 0:
                manager.update_track(track.track_id, (float(i), float(i)))
            else:
                manager.update_track(track.track_id)
        # hits counts all hits, misses is consecutive (resets on hit)
        assert track.hits == 6  # initial + 5 even-indexed updates
        assert track.misses == 1  # last update was a miss
        assert track.total_updates == 11  # initial + 10 updates

    def test_track_with_zero_velocity(self):
        track = Track(
            track_id="TEST",
            status=TrackStatus.TENTATIVE,
            position=(0.0, 0.0),
            velocity=(0.0, 0.0),
        )
        assert track.velocity == (0.0, 0.0)

    def test_track_history_grows(self):
        manager = TrackManager()
        track = manager.initiate_track((0.0, 0.0))
        initial_len = len(track.history)
        manager.update_track(track.track_id, (1.0, 1.0))
        assert len(track.history) > initial_len

    def test_multiple_managers_independent(self):
        m1 = TrackManager()
        m2 = TrackManager()
        t1 = m1.initiate_track((0.0, 0.0))
        t2 = m2.initiate_track((0.0, 0.0))
        # Each manager has its own track store
        assert len(m1.get_all_tracks()) == 1
        assert len(m2.get_all_tracks()) == 1
        # Deleting from one doesn't affect the other
        m1.delete_track(t1.track_id)
        assert len(m1.get_active_tracks()) == 0
        assert len(m2.get_active_tracks()) == 1

    def test_process_detection_returns_correct_tuple(self):
        manager = TrackManager()
        track, is_new = manager.process_detection((0.0, 0.0))
        assert is_new is True
        assert track is not None
        assert track.position == (0.0, 0.0)

    def test_quality_score_monotonic_with_consistent_hits(self):
        manager = TrackManager()
        track = manager.initiate_track((0.0, 0.0))
        qualities = [track.quality_score]
        for i in range(5):
            manager.update_track(track.track_id, (float(i), float(i)))
            qualities.append(track.quality_score)
        # Quality should generally increase with consistent hits
        assert qualities[-1] > qualities[0]
