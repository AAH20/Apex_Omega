"""Tests for Extended Kalman Filter — non-linear sensor fusion.

Covers:
- General EKF predict/update
- Linear system equivalence to KF
- Non-linear process and measurement models
- Bearing-only fusion
- Range-bearing fusion
- Covariance properties
- Edge cases
"""

import math
import numpy as np
import pytest

from src.fusion.ekf import ExtendedKalmanFilter, BearingOnlyEKF, RangeBearingEKF


# ──────────────────────────────────────────────────────────────
# General EKF Tests
# ──────────────────────────────────────────────────────────────


class TestExtendedKalmanFilter:
    """Tests for the general-purpose EKF."""

    def setup_method(self):
        """Set up a simple 2D constant-velocity EKF."""
        self.x0 = np.array([0.0, 0.0, 1.0, 0.0])  # x, y, vx, vy
        self.P0 = np.eye(4) * 10.0
        self.Q = np.eye(4) * 0.01
        self.R = np.eye(2) * 1.0
        self.ekf = ExtendedKalmanFilter(self.x0, self.P0, self.Q, self.R)

    def test_predict_updates_state(self):
        """Predict step should propagate state through process model."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        self.ekf.predict(f, F_jac)
        assert self.ekf.x[0] == pytest.approx(1.0)
        assert self.ekf.x[1] == pytest.approx(0.0)
        assert self.ekf.x[2] == pytest.approx(1.0)
        assert self.ekf.x[3] == pytest.approx(0.0)

    def test_predict_updates_covariance(self):
        """Predict step should increase covariance due to process noise."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        P_before = self.ekf.P.copy()
        self.ekf.predict(f, F_jac)
        # Covariance should grow
        assert np.all(np.diag(self.ekf.P) >= np.diag(P_before))

    def test_update_reduces_covariance(self):
        """Update step should reduce covariance."""
        P_before = self.ekf.P.copy()
        z = np.array([1.0, 0.5])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        self.ekf.update(z, h, H_jac)
        # Covariance should shrink
        assert np.all(np.diag(self.ekf.P) <= np.diag(P_before))

    def test_update_with_perfect_measurement(self):
        """Update with near-zero measurement noise should trust measurement."""
        ekf = ExtendedKalmanFilter(
            np.array([0.0, 0.0]),
            np.eye(2) * 100.0,
            np.eye(2) * 0.0,
            np.eye(2) * 1e-10,
        )
        z = np.array([5.0, 3.0])

        def h(x):
            return x.copy()

        def H_jac(x):
            return np.eye(2)

        ekf.update(z, h, H_jac)
        assert ekf.x[0] == pytest.approx(5.0, abs=1e-3)
        assert ekf.x[1] == pytest.approx(3.0, abs=1e-3)

    def test_linear_system_matches_kf(self):
        """EKF with linear models should match standard KF equations."""
        # Simple 1D system: x_{k+1} = x_k + w, z = x_k + v
        ekf = ExtendedKalmanFilter(
            np.array([0.0]),
            np.array([[1.0]]),
            np.array([[0.1]]),
            np.array([[0.5]]),
        )

        def f(x):
            return x.copy()

        def F_jac(x):
            return np.array([[1.0]])

        def h(x):
            return x.copy()

        def H_jac(x):
            return np.array([[1.0]])

        ekf.predict(f, F_jac)
        # After predict: P = 1.0 + 0.1 = 1.1
        assert ekf.P[0, 0] == pytest.approx(1.1)

        ekf.update(np.array([2.0]), h, H_jac)
        # K = 1.1 / (1.1 + 0.5) = 0.6875
        # x = 0 + 0.6875 * 2.0 = 1.375
        assert ekf.x[0] == pytest.approx(1.375)
        # P = (1 - 0.6875) * 1.1 = 0.34375
        assert ekf.P[0, 0] == pytest.approx(0.34375)

    def test_nonlinear_process_model(self):
        """EKF should handle non-linear process models (e.g., pendulum)."""
        # Simple non-linear model: x_{k+1} = x_k + sin(x_k)
        ekf = ExtendedKalmanFilter(
            np.array([0.5]),
            np.array([[1.0]]),
            np.array([[0.01]]),
            np.array([[0.1]]),
        )

        def f(x):
            return np.array([x[0] + np.sin(x[0])])

        def F_jac(x):
            return np.array([[1.0 + np.cos(x[0])]])

        ekf.predict(f, F_jac)
        expected = 0.5 + np.sin(0.5)
        assert ekf.x[0] == pytest.approx(expected)

    def test_nonlinear_measurement_model(self):
        """EKF should handle non-linear measurement models."""
        # Measurement: z = x^2
        ekf = ExtendedKalmanFilter(
            np.array([2.0]),
            np.array([[1.0]]),
            np.array([[0.0]]),
            np.array([[0.1]]),
        )

        def h(x):
            return np.array([x[0] ** 2])

        def H_jac(x):
            return np.array([[2.0 * x[0]]])

        ekf.update(np.array([4.0]), h, H_jac)
        # Should move toward x=2 (since 2^2 = 4)
        assert ekf.x[0] == pytest.approx(2.0, abs=0.5)

    def test_covariance_symmetry(self):
        """Covariance matrix should remain symmetric after predict/update."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        for _ in range(5):
            self.ekf.predict(f, F_jac)
            assert np.allclose(self.ekf.P, self.ekf.P.T)
            self.ekf.update(np.array([1.0, 0.5]), h, H_jac)
            assert np.allclose(self.ekf.P, self.ekf.P.T)

    def test_covariance_positive_semidefinite(self):
        """Covariance matrix should remain positive semi-definite."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        for _ in range(10):
            self.ekf.predict(f, F_jac)
            eigvals = np.linalg.eigvalsh(self.ekf.P)
            assert np.all(eigvals >= -1e-10)
            self.ekf.update(np.array([1.0, 0.5]), h, H_jac)
            eigvals = np.linalg.eigvalsh(self.ekf.P)
            assert np.all(eigvals >= -1e-10)

    def test_multiple_predict_update_cycles(self):
        """EKF should remain stable over many predict/update cycles."""
        dt = 0.1

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        for i in range(50):
            self.ekf.predict(f, F_jac)
            z = np.array([float(i) * 0.1, 0.5])
            self.ekf.update(z, h, H_jac)

        # Should not diverge
        assert np.all(np.isfinite(self.ekf.x))
        assert np.all(np.isfinite(self.ekf.P))

    def test_custom_Q_in_predict(self):
        """Predict should accept custom process noise."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        Q_custom = np.eye(4) * 1.0
        P_before = self.ekf.P.copy()
        self.ekf.predict(f, F_jac, Q=Q_custom)
        # With larger Q, covariance should grow more
        assert np.all(np.diag(self.ekf.P) > np.diag(P_before))

    def test_custom_R_in_update(self):
        """Update should accept custom measurement noise."""
        z = np.array([1.0, 0.5])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        R_small = np.eye(2) * 0.001
        R_large = np.eye(2) * 100.0

        ekf1 = ExtendedKalmanFilter(self.x0.copy(), self.P0.copy(), self.Q.copy(), R_small)
        ekf2 = ExtendedKalmanFilter(self.x0.copy(), self.P0.copy(), self.Q.copy(), R_large)

        ekf1.update(z, h, H_jac)
        ekf2.update(z, h, H_jac)

        # Smaller R should trust measurement more
        dist1 = np.linalg.norm(ekf1.x[:2] - z)
        dist2 = np.linalg.norm(ekf2.x[:2] - z)
        assert dist1 < dist2

    def test_state_dimension_preserved(self):
        """State dimension should not change through predict/update."""
        dt = 1.0

        def f(x):
            return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

        def F_jac(x):
            return np.array([
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        def h(x):
            return np.array([x[0], x[1]])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        self.ekf.predict(f, F_jac)
        assert len(self.ekf.x) == 4
        self.ekf.update(np.array([1.0, 0.5]), h, H_jac)
        assert len(self.ekf.x) == 4

    def test_innovation_computation(self):
        """Innovation should be z - h(x)."""
        z = np.array([3.0, 4.0])

        def h(x):
            return np.array([x[0] + 1.0, x[1] + 2.0])

        def H_jac(x):
            return np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ])

        # x = [0, 0, 1, 0], so h(x) = [1, 2]
        # innovation = [3, 4] - [1, 2] = [2, 2]
        self.ekf.update(z, h, H_jac)
        # State should move toward reducing innovation
        assert self.ekf.x[0] > 0.0
        assert self.ekf.x[1] > 0.0


# ──────────────────────────────────────────────────────────────
# Bearing-Only EKF Tests
# ──────────────────────────────────────────────────────────────


class TestBearingOnlyEKF:
    """Tests for bearing-only sensor fusion."""

    def setup_method(self):
        """Set up bearing-only EKF with sensor at origin."""
        self.sensor_pos = np.array([0.0, 0.0])
        self.x0 = np.array([10.0, 5.0, 0.0, 0.0])
        self.P0 = np.eye(4) * 5.0
        self.Q = np.eye(4) * 0.01
        self.R = np.array([[0.01]])  # bearing noise in radians^2
        self.ekf = BearingOnlyEKF(self.x0, self.P0, self.Q, self.R, self.sensor_pos)

    def test_bearing_only_predict(self):
        """Bearing-only predict should propagate state."""
        dt = 1.0
        self.ekf.predict(dt)
        assert self.ekf.x[0] == pytest.approx(10.0)
        assert self.ekf.x[1] == pytest.approx(5.0)

    def test_bearing_only_update(self):
        """Bearing-only update should adjust state based on bearing measurement."""
        # True bearing from origin to [10, 5] is atan2(5, 10) ≈ 0.4636 rad
        true_bearing = math.atan2(5.0, 10.0)
        self.ekf.update(np.array([true_bearing]))
        # State should remain close to true position
        assert self.ekf.x[0] == pytest.approx(10.0, abs=2.0)
        assert self.ekf.x[1] == pytest.approx(5.0, abs=2.0)

    def test_bearing_only_converges(self):
        """Bearing-only EKF should converge with multiple measurements."""
        true_pos = np.array([20.0, 10.0])
        true_bearing = math.atan2(true_pos[1] - self.sensor_pos[1],
                                   true_pos[0] - self.sensor_pos[0])

        ekf = BearingOnlyEKF(
            np.array([15.0, 8.0, 0.0, 0.0]),
            np.eye(4) * 10.0,
            np.eye(4) * 0.01,
            np.array([[0.001]]),
            self.sensor_pos,
        )

        for _ in range(20):
            ekf.predict(0.1)
            ekf.update(np.array([true_bearing]))

        # Should converge toward true bearing line
        est_bearing = math.atan2(ekf.x[1] - self.sensor_pos[1],
                                  ekf.x[0] - self.sensor_pos[0])
        assert est_bearing == pytest.approx(true_bearing, abs=0.1)

    def test_bearing_only_measurement_jacobian(self):
        """Measurement Jacobian should have correct structure."""
        H = self.ekf._measurement_jacobian(self.ekf.x)
        assert H.shape == (1, 4)
        # Bearing = atan2(y - sy, x - sx)
        # d(bearing)/dx = -(y - sx) / r^2
        # d(bearing)/dy = (x - sx) / r^2
        dx = self.ekf.x[0] - self.sensor_pos[0]
        dy = self.ekf.x[1] - self.sensor_pos[1]
        r_sq = dx**2 + dy**2
        expected_dH_dx = -dy / r_sq
        expected_dH_dy = dx / r_sq
        assert H[0, 0] == pytest.approx(expected_dH_dx)
        assert H[0, 1] == pytest.approx(expected_dH_dy)
        assert H[0, 2] == pytest.approx(0.0)
        assert H[0, 3] == pytest.approx(0.0)

    def test_bearing_only_multiple_sensors(self):
        """Bearing-only fusion should work with multiple sensor positions."""
        sensor_positions = [
            np.array([0.0, 0.0]),
            np.array([10.0, 0.0]),
            np.array([0.0, 10.0]),
        ]
        true_pos = np.array([5.0, 5.0])

        ekf = BearingOnlyEKF(
            np.array([3.0, 3.0, 0.0, 0.0]),
            np.eye(4) * 10.0,
            np.eye(4) * 0.01,
            np.array([[0.01]]),
            sensor_positions[0],
        )

        for sensor_pos in sensor_positions:
            ekf.sensor_pos = sensor_pos
            bearing = math.atan2(true_pos[1] - sensor_pos[1],
                                true_pos[0] - sensor_pos[0])
            ekf.update(np.array([bearing]))

        # Should be closer to true position than initial guess
        initial_error = np.linalg.norm(np.array([3.0, 3.0]) - true_pos)
        final_error = np.linalg.norm(ekf.x[:2] - true_pos)
        assert final_error < initial_error


# ──────────────────────────────────────────────────────────────
# Range-Bearing EKF Tests
# ──────────────────────────────────────────────────────────────


class TestRangeBearingEKF:
    """Tests for range-bearing sensor fusion."""

    def setup_method(self):
        """Set up range-bearing EKF with sensor at origin."""
        self.sensor_pos = np.array([0.0, 0.0])
        self.x0 = np.array([10.0, 5.0, 0.0, 0.0])
        self.P0 = np.eye(4) * 5.0
        self.Q = np.eye(4) * 0.01
        self.R = np.diag([1.0, 0.01])  # range noise, bearing noise
        self.ekf = RangeBearingEKF(self.x0, self.P0, self.Q, self.R, self.sensor_pos)

    def test_range_bearing_predict(self):
        """Range-bearing predict should propagate state."""
        dt = 1.0
        self.ekf.predict(dt)
        assert self.ekf.x[0] == pytest.approx(10.0)
        assert self.ekf.x[1] == pytest.approx(5.0)

    def test_range_bearing_update(self):
        """Range-bearing update should adjust state based on measurement."""
        true_range = math.sqrt(10.0**2 + 5.0**2)
        true_bearing = math.atan2(5.0, 10.0)
        z = np.array([true_range, true_bearing])
        self.ekf.update(z)
        # State should remain close to true position
        assert self.ekf.x[0] == pytest.approx(10.0, abs=1.0)
        assert self.ekf.x[1] == pytest.approx(5.0, abs=1.0)

    def test_range_bearing_converges(self):
        """Range-bearing EKF should converge with multiple measurements."""
        true_pos = np.array([15.0, 8.0])
        true_range = math.sqrt(true_pos[0]**2 + true_pos[1]**2)
        true_bearing = math.atan2(true_pos[1], true_pos[0])

        ekf = RangeBearingEKF(
            np.array([10.0, 5.0, 0.0, 0.0]),
            np.eye(4) * 10.0,
            np.eye(4) * 0.01,
            np.diag([0.1, 0.001]),
            self.sensor_pos,
        )

        for _ in range(10):
            ekf.predict(0.1)
            ekf.update(np.array([true_range, true_bearing]))

        # Should converge close to true position
        assert ekf.x[0] == pytest.approx(true_pos[0], abs=1.0)
        assert ekf.x[1] == pytest.approx(true_pos[1], abs=1.0)

    def test_range_bearing_measurement_jacobian(self):
        """Measurement Jacobian should have correct structure."""
        H = self.ekf._measurement_jacobian(self.ekf.x)
        assert H.shape == (2, 4)
        dx = self.ekf.x[0] - self.sensor_pos[0]
        dy = self.ekf.x[1] - self.sensor_pos[1]
        r = math.sqrt(dx**2 + dy**2)
        r_sq = dx**2 + dy**2
        # d(range)/dx = dx / r
        # d(range)/dy = dy / r
        assert H[0, 0] == pytest.approx(dx / r)
        assert H[0, 1] == pytest.approx(dy / r)
        # d(bearing)/dx = -dy / r^2
        # d(bearing)/dy = dx / r^2
        assert H[1, 0] == pytest.approx(-dy / r_sq)
        assert H[1, 1] == pytest.approx(dx / r_sq)

    def test_range_bearing_range_component(self):
        """Range component should help constrain distance."""
        true_pos = np.array([20.0, 0.0])
        true_range = 20.0
        true_bearing = 0.0

        ekf = RangeBearingEKF(
            np.array([10.0, 5.0, 0.0, 0.0]),
            np.eye(4) * 10.0,
            np.eye(4) * 0.01,
            np.diag([0.01, 0.01]),
            self.sensor_pos,
        )

        for _ in range(15):
            ekf.predict(0.1)
            ekf.update(np.array([true_range, true_bearing]))

        # Range measurement should pull estimate toward correct distance
        est_range = math.sqrt(ekf.x[0]**2 + ekf.x[1]**2)
        assert est_range == pytest.approx(true_range, abs=2.0)


# ──────────────────────────────────────────────────────────────
# Edge Case Tests
# ──────────────────────────────────────────────────────────────


class TestEKFEdgeCases:
    """Edge case tests for EKF implementations."""

    def test_zero_process_noise(self):
        """EKF should work with zero process noise."""
        ekf = ExtendedKalmanFilter(
            np.array([1.0]),
            np.array([[1.0]]),
            np.array([[0.0]]),
            np.array([[0.1]]),
        )

        def f(x):
            return x.copy()

        def F_jac(x):
            return np.array([[1.0]])

        def h(x):
            return x.copy()

        def H_jac(x):
            return np.array([[1.0]])

        ekf.predict(f, F_jac)
        assert ekf.P[0, 0] == pytest.approx(1.0)  # No growth without Q

    def test_large_measurement_noise(self):
        """EKF should handle large measurement noise gracefully."""
        ekf = ExtendedKalmanFilter(
            np.array([0.0]),
            np.array([[1.0]]),
            np.array([[0.1]]),
            np.array([[1000.0]]),
        )

        def h(x):
            return x.copy()

        def H_jac(x):
            return np.array([[1.0]])

        ekf.update(np.array([10.0]), h, H_jac)
        # With huge R, should barely move
        assert ekf.x[0] == pytest.approx(0.0, abs=0.1)

    def test_single_state_dimension(self):
        """EKF should work with 1D state."""
        ekf = ExtendedKalmanFilter(
            np.array([0.0]),
            np.array([[1.0]]),
            np.array([[0.1]]),
            np.array([[0.5]]),
        )

        def f(x):
            return np.array([x[0] + 0.1])

        def F_jac(x):
            return np.array([[1.0]])

        def h(x):
            return x.copy()

        def H_jac(x):
            return np.array([[1.0]])

        ekf.predict(f, F_jac)
        assert ekf.x[0] == pytest.approx(0.1)
        ekf.update(np.array([0.5]), h, H_jac)
        assert ekf.x[0] == pytest.approx(0.3, abs=0.1)

    def test_bearing_only_zero_velocity(self):
        """Bearing-only EKF should handle stationary targets."""
        sensor_pos = np.array([0.0, 0.0])
        ekf = BearingOnlyEKF(
            np.array([10.0, 0.0, 0.0, 0.0]),
            np.eye(4) * 5.0,
            np.eye(4) * 0.001,
            np.array([[0.001]]),
            sensor_pos,
        )

        true_bearing = 0.0  # On x-axis
        for _ in range(10):
            ekf.predict(0.1)
            ekf.update(np.array([true_bearing]))

        # Should stay near x-axis
        assert abs(ekf.x[1]) < 2.0

    def test_range_bearing_stationary_target(self):
        """Range-bearing EKF should handle stationary targets."""
        sensor_pos = np.array([0.0, 0.0])
        ekf = RangeBearingEKF(
            np.array([5.0, 5.0, 0.0, 0.0]),
            np.eye(4) * 5.0,
            np.eye(4) * 0.001,
            np.diag([0.1, 0.001]),
            sensor_pos,
        )

        true_range = math.sqrt(50.0)
        true_bearing = math.pi / 4
        for _ in range(10):
            ekf.predict(0.1)
            ekf.update(np.array([true_range, true_bearing]))

        est_range = math.sqrt(ekf.x[0]**2 + ekf.x[1]**2)
        assert est_range == pytest.approx(true_range, abs=1.0)
