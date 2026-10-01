"""APEX-OS Feature Flags, A/B Testing, and Dynamic Configuration.

Provides:
- FeatureFlag / FeatureFlagManager: boolean flags with env overrides
- Experiment / ABTestManager: deterministic variant assignment with traffic control
- DynamicConfig: typed, validated, observable key-value configuration
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Raised when a config value fails validation."""


class ConfigTypeError(Exception):
    """Raised when a config value cannot be coerced to the expected type."""


# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------


@dataclass
class FeatureFlag:
    """A single feature flag with environment-specific overrides."""

    name: str
    default_enabled: bool = False
    description: str = ""
    env_override: dict[str, bool] = field(default_factory=dict)

    def is_enabled(self, environment: str = "default") -> bool:
        """Check if the flag is enabled for the given environment."""
        if environment in self.env_override:
            return self.env_override[environment]
        return self.default_enabled


class FeatureFlagManager:
    """Manages a collection of feature flags."""

    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}

    def register(self, flag: FeatureFlag) -> None:
        """Register a feature flag."""
        if flag.name in self._flags:
            raise ValueError(f"Feature flag '{flag.name}' already registered")
        self._flags[flag.name] = flag
        logger.debug("Registered feature flag: %s", flag.name)

    def unregister(self, name: str) -> None:
        """Remove a feature flag."""
        if name not in self._flags:
            raise KeyError(f"Feature flag '{name}' not found")
        del self._flags[name]

    def is_enabled(self, name: str, environment: str = "default") -> bool:
        """Check if a feature flag is enabled."""
        flag = self._flags.get(name)
        if flag is None:
            return False
        # Check environment variable override: APEX_FEATURE_<NAME>
        env_var = f"APEX_FEATURE_{name.upper()}"
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value.lower() in ("true", "1", "yes", "on")
        return flag.is_enabled(environment)

    def enable(self, name: str) -> None:
        """Enable a feature flag."""
        if name not in self._flags:
            raise KeyError(f"Feature flag '{name}' not found")
        self._flags[name].default_enabled = True

    def disable(self, name: str) -> None:
        """Disable a feature flag."""
        if name not in self._flags:
            raise KeyError(f"Feature flag '{name}' not found")
        self._flags[name].default_enabled = False

    def toggle(self, name: str) -> None:
        """Toggle a feature flag."""
        if name not in self._flags:
            raise KeyError(f"Feature flag '{name}' not found")
        self._flags[name].default_enabled = not self._flags[name].default_enabled

    def get_flag(self, name: str) -> FeatureFlag:
        """Get a feature flag by name."""
        if name not in self._flags:
            raise KeyError(f"Feature flag '{name}' not found")
        return self._flags[name]

    def get_all_flags(self) -> dict[str, FeatureFlag]:
        """Get all registered feature flags."""
        return dict(self._flags)


# ---------------------------------------------------------------------------
# A/B Testing
# ---------------------------------------------------------------------------


@dataclass
class Experiment:
    """An A/B test experiment definition."""

    name: str
    variants: list[str]
    traffic_allocation: float = 1.0
    variant_weights: dict[str, float] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.variants) < 2:
            raise ValueError("Experiment must have at least 2 variants")
        if not 0.0 <= self.traffic_allocation <= 1.0:
            raise ValueError("traffic_allocation must be between 0.0 and 1.0")


@dataclass
class VariantAssignment:
    """Result of assigning a user to an experiment variant."""

    user_id: str
    experiment_name: str
    variant: str


class ABTestManager:
    """Manages A/B test experiments and variant assignments."""

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def create_experiment(self, experiment: Experiment) -> None:
        """Create a new experiment."""
        if experiment.name in self._experiments:
            raise ValueError(f"Experiment '{experiment.name}' already exists")
        self._experiments[experiment.name] = experiment
        logger.debug("Created experiment: %s", experiment.name)

    def remove_experiment(self, name: str) -> None:
        """Remove an experiment."""
        if name not in self._experiments:
            raise KeyError(f"Experiment '{name}' not found")
        del self._experiments[name]

    def get_experiment(self, name: str) -> Experiment:
        """Get an experiment by name."""
        if name not in self._experiments:
            raise KeyError(f"Experiment '{name}' not found")
        return self._experiments[name]

    def get_all_experiments(self) -> dict[str, Experiment]:
        """Get all experiments."""
        return dict(self._experiments)

    def is_in_experiment(self, user_id: str, experiment_name: str) -> bool:
        """Check if a user is assigned to an experiment."""
        return self.assign_variant(user_id, experiment_name) is not None

    def assign_variant(
        self, user_id: str, experiment_name: str
    ) -> str | None:
        """Assign a user to a variant. Returns None if not in experiment."""
        if experiment_name not in self._experiments:
            raise KeyError(f"Experiment '{experiment_name}' not found")

        exp = self._experiments[experiment_name]

        # Check date bounds
        now = datetime.now()
        if exp.start_date and now < exp.start_date:
            return None
        if exp.end_date and now > exp.end_date:
            return None

        # Check traffic allocation
        if exp.traffic_allocation <= 0.0:
            return None

        # Deterministic hash for traffic check
        hash_key = f"{user_id}:{experiment_name}:traffic"
        hash_val = int(hashlib.md5(hash_key.encode()).hexdigest(), 16)
        traffic_threshold = int(exp.traffic_allocation * (2**128 - 1))
        if hash_val > traffic_threshold:
            return None

        # Assign variant
        if exp.variant_weights:
            return self._assign_weighted(user_id, exp)
        return self._assign_uniform(user_id, exp)

    def _assign_uniform(self, user_id: str, exp: Experiment) -> str:
        """Uniform variant assignment."""
        hash_key = f"{user_id}:{exp.name}:variant"
        hash_val = int(hashlib.md5(hash_key.encode()).hexdigest(), 16)
        idx = hash_val % len(exp.variants)
        return exp.variants[idx]

    def _assign_weighted(self, user_id: str, exp: Experiment) -> str:
        """Weighted variant assignment."""
        assert exp.variant_weights is not None
        hash_key = f"{user_id}:{exp.name}:weighted"
        hash_val = int(hashlib.md5(hash_key.encode()).hexdigest(), 16)
        # Normalize to 0-1 range
        normalized = (hash_val % 10000) / 10000.0

        cumulative = 0.0
        for variant in exp.variants:
            weight = exp.variant_weights.get(variant, 1.0 / len(exp.variants))
            cumulative += weight
            if normalized <= cumulative:
                return variant
        return exp.variants[-1]


# ---------------------------------------------------------------------------
# Dynamic Configuration
# ---------------------------------------------------------------------------


@dataclass
class ConfigValue:
    """A typed configuration value with metadata."""

    key: str
    value: Any
    value_type: type = str
    description: str = ""
    mutable: bool = True


class DynamicConfig:
    """Dynamic, typed, validated configuration store."""

    def __init__(self) -> None:
        self._config: dict[str, ConfigValue] = {}
        self._listeners: list[Callable[[str, Any, Any], None]] = []

    def set(
        self,
        key: str,
        value: Any,
        value_type: type | None = None,
        description: str = "",
        validator: Callable[[Any], bool] | None = None,
        mutable: bool = True,
    ) -> None:
        """Set a configuration value with optional type coercion and validation."""
        old_value = self._config.get(key)

        # Check immutability
        if old_value is not None and not old_value.mutable:
            raise ValueError(f"Config key '{key}' is immutable")

        # Type coercion
        if value_type is not None:
            try:
                value = self._coerce_type(value, value_type)
            except (ValueError, TypeError) as exc:
                raise ConfigTypeError(
                    f"Cannot coerce value for '{key}' to {value_type.__name__}: {exc}"
                ) from exc

        # Validation
        if validator is not None and not validator(value):
            raise ConfigValidationError(
                f"Validation failed for config key '{key}' with value {value!r}"
            )

        # Store
        self._config[key] = ConfigValue(
            key=key,
            value=value,
            value_type=value_type or type(value),
            description=description,
            mutable=mutable,
        )

        # Notify listeners
        old = old_value.value if old_value else None
        self._notify(key, old, value)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        cv = self._config.get(key)
        if cv is None:
            if default is not None:
                return default
            raise KeyError(f"Config key '{key}' not found")
        return cv.value

    def has(self, key: str) -> bool:
        """Check if a config key exists."""
        return key in self._config

    def delete(self, key: str) -> None:
        """Delete a configuration key."""
        if key not in self._config:
            raise KeyError(f"Config key '{key}' not found")
        old = self._config.pop(key)
        self._notify(key, old.value, None)

    def get_all(self) -> dict[str, Any]:
        """Get all configuration values as a dict."""
        return {k: v.value for k, v in self._config.items()}

    def get_config_value(self, key: str) -> ConfigValue:
        """Get the full ConfigValue object."""
        if key not in self._config:
            raise KeyError(f"Config key '{key}' not found")
        return self._config[key]

    def bulk_update(self, updates: dict[str, Any]) -> None:
        """Update multiple config values at once."""
        for key, value in updates.items():
            self.set(key, value)

    def export(self) -> dict[str, Any]:
        """Export all config as a plain dict."""
        return self.get_all()

    def import_config(self, data: dict[str, Any]) -> None:
        """Import config from a dict."""
        for key, value in data.items():
            self.set(key, value)

    def clear(self) -> None:
        """Clear all configuration."""
        self._config.clear()

    def add_listener(self, listener: Callable[[str, Any, Any], None]) -> None:
        """Add a change listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, Any, Any], None]) -> None:
        """Remove a change listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, key: str, old: Any, new: Any) -> None:
        """Notify all listeners of a change."""
        for listener in self._listeners:
            try:
                listener(key, old, new)
            except Exception:
                logger.exception("Config change listener failed for key '%s'", key)

    @staticmethod
    def _coerce_type(value: Any, value_type: type) -> Any:
        """Coerce a value to the target type."""
        if value_type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return bool(value)
        if value_type is list:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [item.strip() for item in value.split(",")]
            return list(value)
        return value_type(value)
