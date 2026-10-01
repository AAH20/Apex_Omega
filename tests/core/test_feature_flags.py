"""Tests for APEX-OS Feature Flags, A/B Testing, and Dynamic Configuration.

TDD: tests written before implementation.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from src.core.feature_flags import (
    FeatureFlag,
    FeatureFlagManager,
    Experiment,
    ABTestManager,
    VariantAssignment,
    DynamicConfig,
    ConfigValue,
    ConfigValidationError,
    ConfigTypeError,
)


# ---------------------------------------------------------------------------
# Feature Flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_flag_defaults_to_disabled(self):
        flag = FeatureFlag("test_flag", description="A test flag")
        assert flag.name == "test_flag"
        assert flag.default_enabled is False
        assert flag.description == "A test flag"

    def test_flag_with_default_enabled(self):
        flag = FeatureFlag("test_flag", default_enabled=True)
        assert flag.default_enabled is True

    def test_flag_environment_override(self):
        flag = FeatureFlag(
            "test_flag",
            default_enabled=False,
            env_override={"production": True},
        )
        assert flag.env_override == {"production": True}

    def test_flag_is_enabled_default(self):
        flag = FeatureFlag("test_flag", default_enabled=True)
        assert flag.is_enabled(environment="development") is True

    def test_flag_is_disabled_default(self):
        flag = FeatureFlag("test_flag", default_enabled=False)
        assert flag.is_enabled(environment="development") is False

    def test_flag_environment_override_enables(self):
        flag = FeatureFlag(
            "test_flag",
            default_enabled=False,
            env_override={"production": True},
        )
        assert flag.is_enabled(environment="production") is True
        assert flag.is_enabled(environment="staging") is False

    def test_flag_environment_override_disables(self):
        flag = FeatureFlag(
            "test_flag",
            default_enabled=True,
            env_override={"production": False},
        )
        assert flag.is_enabled(environment="production") is False
        assert flag.is_enabled(environment="staging") is True


class TestFeatureFlagManager:
    def test_register_flag(self):
        mgr = FeatureFlagManager()
        flag = FeatureFlag("test_flag")
        mgr.register(flag)
        assert "test_flag" in mgr._flags

    def test_register_duplicate_raises(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag"))
        with pytest.raises(ValueError, match="already registered"):
            mgr.register(FeatureFlag("test_flag"))

    def test_is_enabled_returns_bool(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag", default_enabled=True))
        assert mgr.is_enabled("test_flag") is True

    def test_is_enabled_unknown_flag_returns_false(self):
        mgr = FeatureFlagManager()
        assert mgr.is_enabled("nonexistent") is False

    def test_enable_flag(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag", default_enabled=False))
        mgr.enable("test_flag")
        assert mgr.is_enabled("test_flag") is True

    def test_disable_flag(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag", default_enabled=True))
        mgr.disable("test_flag")
        assert mgr.is_enabled("test_flag") is False

    def test_enable_unknown_flag_raises(self):
        mgr = FeatureFlagManager()
        with pytest.raises(KeyError):
            mgr.enable("nonexistent")

    def test_disable_unknown_flag_raises(self):
        mgr = FeatureFlagManager()
        with pytest.raises(KeyError):
            mgr.disable("nonexistent")

    def test_get_all_flags(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("flag_a"))
        mgr.register(FeatureFlag("flag_b"))
        flags = mgr.get_all_flags()
        assert len(flags) == 2
        assert "flag_a" in flags
        assert "flag_b" in flags

    def test_get_flag(self):
        mgr = FeatureFlagManager()
        flag = FeatureFlag("test_flag", default_enabled=True)
        mgr.register(flag)
        assert mgr.get_flag("test_flag") is flag

    def test_get_flag_unknown_raises(self):
        mgr = FeatureFlagManager()
        with pytest.raises(KeyError):
            mgr.get_flag("nonexistent")

    def test_environment_variable_override(self):
        """APEX_FEATURE_<NAME>=true should enable a flag."""
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("new_ui", default_enabled=False))
        with patch.dict(os.environ, {"APEX_FEATURE_NEW_UI": "true"}):
            assert mgr.is_enabled("new_ui") is True

    def test_environment_variable_disable(self):
        """APEX_FEATURE_<NAME>=false should disable a flag."""
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("new_ui", default_enabled=True))
        with patch.dict(os.environ, {"APEX_FEATURE_NEW_UI": "false"}):
            assert mgr.is_enabled("new_ui") is False

    def test_unregister_flag(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag"))
        mgr.unregister("test_flag")
        assert "test_flag" not in mgr._flags

    def test_unregister_unknown_raises(self):
        mgr = FeatureFlagManager()
        with pytest.raises(KeyError):
            mgr.unregister("nonexistent")

    def test_toggle_flag(self):
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag("test_flag", default_enabled=False))
        mgr.toggle("test_flag")
        assert mgr.is_enabled("test_flag") is True
        mgr.toggle("test_flag")
        assert mgr.is_enabled("test_flag") is False

    def test_toggle_unknown_raises(self):
        mgr = FeatureFlagManager()
        with pytest.raises(KeyError):
            mgr.toggle("nonexistent")


# ---------------------------------------------------------------------------
# A/B Testing tests
# ---------------------------------------------------------------------------


class TestExperiment:
    def test_experiment_creation(self):
        exp = Experiment(
            name="button_color",
            variants=["red", "blue"],
            traffic_allocation=1.0,
        )
        assert exp.name == "button_color"
        assert exp.variants == ["red", "blue"]
        assert exp.traffic_allocation == 1.0

    def test_experiment_default_traffic(self):
        exp = Experiment(name="test", variants=["a", "b"])
        assert exp.traffic_allocation == 1.0

    def test_experiment_invalid_traffic_raises(self):
        with pytest.raises(ValueError, match="traffic_allocation"):
            Experiment(name="test", variants=["a", "b"], traffic_allocation=1.5)

    def test_experiment_negative_traffic_raises(self):
        with pytest.raises(ValueError, match="traffic_allocation"):
            Experiment(name="test", variants=["a", "b"], traffic_allocation=-0.1)

    def test_experiment_empty_variants_raises(self):
        with pytest.raises(ValueError, match="variants"):
            Experiment(name="test", variants=[])

    def test_experiment_single_variant_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            Experiment(name="test", variants=["only"])


class TestABTestManager:
    def test_create_experiment(self):
        mgr = ABTestManager()
        exp = Experiment(name="exp1", variants=["a", "b"])
        mgr.create_experiment(exp)
        assert "exp1" in mgr._experiments

    def test_create_duplicate_raises(self):
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b"]))
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_experiment(Experiment(name="exp1", variants=["c", "d"]))

    def test_assign_variant_deterministic(self):
        """Same user + experiment always gets same variant."""
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b"]))
        v1 = mgr.assign_variant("user123", "exp1")
        v2 = mgr.assign_variant("user123", "exp1")
        assert v1 == v2

    def test_assign_variant_different_users(self):
        """Different users may get different variants."""
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b"]))
        results = set()
        for i in range(50):
            v = mgr.assign_variant(f"user{i}", "exp1")
            results.add(v)
        # With 50 users and 2 variants, we should see both
        assert len(results) >= 1

    def test_assign_variant_returns_valid_variant(self):
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b", "c"]))
        v = mgr.assign_variant("user1", "exp1")
        assert v in ["a", "b", "c"]

    def test_assign_variant_unknown_experiment_raises(self):
        mgr = ABTestManager()
        with pytest.raises(KeyError):
            mgr.assign_variant("user1", "nonexistent")

    def test_assign_variant_zero_traffic(self):
        """User should not be assigned when traffic is 0%."""
        mgr = ABTestManager()
        mgr.create_experiment(
            Experiment(name="exp1", variants=["a", "b"], traffic_allocation=0.0)
        )
        v = mgr.assign_variant("user1", "exp1")
        assert v is None

    def test_is_in_experiment(self):
        mgr = ABTestManager()
        mgr.create_experiment(
            Experiment(name="exp1", variants=["a", "b"], traffic_allocation=1.0)
        )
        assert mgr.is_in_experiment("user1", "exp1") is True

    def test_not_in_experiment_zero_traffic(self):
        mgr = ABTestManager()
        mgr.create_experiment(
            Experiment(name="exp1", variants=["a", "b"], traffic_allocation=0.0)
        )
        assert mgr.is_in_experiment("user1", "exp1") is False

    def test_get_experiment(self):
        mgr = ABTestManager()
        exp = Experiment(name="exp1", variants=["a", "b"])
        mgr.create_experiment(exp)
        assert mgr.get_experiment("exp1") is exp

    def test_get_experiment_unknown_raises(self):
        mgr = ABTestManager()
        with pytest.raises(KeyError):
            mgr.get_experiment("nonexistent")

    def test_remove_experiment(self):
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b"]))
        mgr.remove_experiment("exp1")
        assert "exp1" not in mgr._experiments

    def test_remove_unknown_experiment_raises(self):
        mgr = ABTestManager()
        with pytest.raises(KeyError):
            mgr.remove_experiment("nonexistent")

    def test_get_all_experiments(self):
        mgr = ABTestManager()
        mgr.create_experiment(Experiment(name="exp1", variants=["a", "b"]))
        mgr.create_experiment(Experiment(name="exp2", variants=["c", "d"]))
        exps = mgr.get_all_experiments()
        assert len(exps) == 2

    def test_variant_assignment_dataclass(self):
        va = VariantAssignment(
            user_id="u1",
            experiment_name="exp1",
            variant="a",
        )
        assert va.user_id == "u1"
        assert va.experiment_name == "exp1"
        assert va.variant == "a"

    def test_assign_variant_with_weights(self):
        """Weighted variants should respect approximate distribution."""
        mgr = ABTestManager()
        mgr.create_experiment(
            Experiment(
                name="weighted",
                variants=["a", "b"],
                variant_weights={"a": 0.8, "b": 0.2},
            )
        )
        results = {"a": 0, "b": 0}
        for i in range(200):
            v = mgr.assign_variant(f"user{i}", "weighted")
            results[v] += 1
        # 80/20 split — a should be significantly more common
        assert results["a"] > results["b"]

    def test_experiment_with_start_date(self):
        """Experiment should not assign before start date."""
        from datetime import datetime, timedelta

        mgr = ABTestManager()
        future = datetime.now() + timedelta(days=1)
        mgr.create_experiment(
            Experiment(
                name="future_exp",
                variants=["a", "b"],
                start_date=future,
            )
        )
        v = mgr.assign_variant("user1", "future_exp")
        assert v is None

    def test_experiment_with_end_date(self):
        """Experiment should not assign after end date."""
        from datetime import datetime, timedelta

        mgr = ABTestManager()
        past = datetime.now() - timedelta(days=1)
        mgr.create_experiment(
            Experiment(
                name="past_exp",
                variants=["a", "b"],
                end_date=past,
            )
        )
        v = mgr.assign_variant("user1", "past_exp")
        assert v is None


# ---------------------------------------------------------------------------
# Dynamic Configuration tests
# ---------------------------------------------------------------------------


class TestConfigValue:
    def test_config_value_creation(self):
        cv = ConfigValue(
            key="max_connections",
            value=100,
            value_type=int,
            description="Max DB connections",
        )
        assert cv.key == "max_connections"
        assert cv.value == 100
        assert cv.value_type is int
        assert cv.description == "Max DB connections"

    def test_config_value_mutable_default(self):
        cv = ConfigValue(key="test", value="hello")
        assert cv.mutable is True

    def test_config_value_immutable(self):
        cv = ConfigValue(key="test", value="hello", mutable=False)
        assert cv.mutable is False


class TestDynamicConfig:
    def test_set_and_get(self):
        cfg = DynamicConfig()
        cfg.set("key1", "value1")
        assert cfg.get("key1") == "value1"

    def test_get_default(self):
        cfg = DynamicConfig()
        assert cfg.get("nonexistent", default="fallback") == "fallback"

    def test_get_nonexistent_no_default_raises(self):
        cfg = DynamicConfig()
        with pytest.raises(KeyError):
            cfg.get("nonexistent")

    def test_set_with_type_coercion_int(self):
        cfg = DynamicConfig()
        cfg.set("port", "8080", value_type=int)
        assert cfg.get("port") == 8080
        assert isinstance(cfg.get("port"), int)

    def test_set_with_type_coercion_float(self):
        cfg = DynamicConfig()
        cfg.set("rate", "0.95", value_type=float)
        assert cfg.get("rate") == 0.95
        assert isinstance(cfg.get("rate"), float)

    def test_set_with_type_coercion_bool(self):
        cfg = DynamicConfig()
        cfg.set("enabled", "true", value_type=bool)
        assert cfg.get("enabled") is True

    def test_set_with_type_coercion_str(self):
        cfg = DynamicConfig()
        cfg.set("name", 123, value_type=str)
        assert cfg.get("name") == "123"

    def test_type_coercion_failure_raises(self):
        cfg = DynamicConfig()
        with pytest.raises(ConfigTypeError):
            cfg.set("port", "not_a_number", value_type=int)

    def test_set_with_validation(self):
        cfg = DynamicConfig()
        cfg.set(
            "port",
            8080,
            value_type=int,
            validator=lambda v: 1024 <= v <= 65535,
        )
        assert cfg.get("port") == 8080

    def test_validation_failure_raises(self):
        cfg = DynamicConfig()
        with pytest.raises(ConfigValidationError):
            cfg.set(
                "port",
                80,
                value_type=int,
                validator=lambda v: 1024 <= v <= 65535,
            )

    def test_set_immutable_raises(self):
        cfg = DynamicConfig()
        cfg.set("api_key", "secret123", mutable=False)
        with pytest.raises(ValueError, match="immutable"):
            cfg.set("api_key", "new_secret")

    def test_delete_key(self):
        cfg = DynamicConfig()
        cfg.set("temp", "value")
        cfg.delete("temp")
        with pytest.raises(KeyError):
            cfg.get("temp")

    def test_delete_unknown_raises(self):
        cfg = DynamicConfig()
        with pytest.raises(KeyError):
            cfg.delete("nonexistent")

    def test_has_key(self):
        cfg = DynamicConfig()
        cfg.set("exists", "yes")
        assert cfg.has("exists") is True
        assert cfg.has("nonexistent") is False

    def test_get_all_config(self):
        cfg = DynamicConfig()
        cfg.set("a", 1)
        cfg.set("b", 2)
        cfg.set("c", 3)
        all_cfg = cfg.get_all()
        assert all_cfg == {"a": 1, "b": 2, "c": 3}

    def test_change_listener(self):
        cfg = DynamicConfig()
        changes = []
        cfg.add_listener(lambda key, old, new: changes.append((key, old, new)))
        cfg.set("key1", "value1")
        cfg.set("key1", "value2")
        assert len(changes) == 2
        assert changes[0] == ("key1", None, "value1")
        assert changes[1] == ("key1", "value1", "value2")

    def test_remove_listener(self):
        cfg = DynamicConfig()
        changes = []

        def listener(key, old, new):
            changes.append((key, old, new))

        cfg.add_listener(listener)
        cfg.set("key1", "value1")
        cfg.remove_listener(listener)
        cfg.set("key1", "value2")
        assert len(changes) == 1

    def test_bulk_update(self):
        cfg = DynamicConfig()
        cfg.set("a", 1)
        cfg.set("b", 2)
        cfg.bulk_update({"a": 10, "b": 20, "c": 30})
        assert cfg.get("a") == 10
        assert cfg.get("b") == 20
        assert cfg.get("c") == 30

    def test_export_config(self):
        cfg = DynamicConfig()
        cfg.set("host", "localhost")
        cfg.set("port", 8080)
        exported = cfg.export()
        assert exported["host"] == "localhost"
        assert exported["port"] == 8080

    def test_import_config(self):
        cfg = DynamicConfig()
        cfg.import_config({"host": "localhost", "port": 8080})
        assert cfg.get("host") == "localhost"
        assert cfg.get("port") == 8080

    def test_import_overwrites_existing(self):
        cfg = DynamicConfig()
        cfg.set("host", "old_host")
        cfg.import_config({"host": "new_host"})
        assert cfg.get("host") == "new_host"

    def test_clear(self):
        cfg = DynamicConfig()
        cfg.set("a", 1)
        cfg.set("b", 2)
        cfg.clear()
        assert cfg.get_all() == {}

    def test_set_with_description(self):
        cfg = DynamicConfig()
        cfg.set("timeout", 30, description="Connection timeout in seconds")
        val = cfg.get_config_value("timeout")
        assert val.description == "Connection timeout in seconds"

    def test_get_config_value(self):
        cfg = DynamicConfig()
        cfg.set("retries", 3, value_type=int)
        cv = cfg.get_config_value("retries")
        assert isinstance(cv, ConfigValue)
        assert cv.key == "retries"
        assert cv.value == 3

    def test_get_config_value_unknown_raises(self):
        cfg = DynamicConfig()
        with pytest.raises(KeyError):
            cfg.get_config_value("nonexistent")

    def test_bool_coercion_variants(self):
        cfg = DynamicConfig()
        for truthy in ["true", "True", "1", "yes", "on"]:
            cfg.set(f"flag_{truthy}", truthy, value_type=bool)
            assert cfg.get(f"flag_{truthy}") is True, f"Failed for {truthy}"

        for falsy in ["false", "False", "0", "no", "off"]:
            cfg.set(f"flag_{falsy}", falsy, value_type=bool)
            assert cfg.get(f"flag_{falsy}") is False, f"Failed for {falsy}"

    def test_list_type_coercion(self):
        cfg = DynamicConfig()
        cfg.set("servers", "host1,host2,host3", value_type=list)
        result = cfg.get("servers")
        assert result == ["host1", "host2", "host3"]

    def test_multiple_listeners(self):
        cfg = DynamicConfig()
        changes1 = []
        changes2 = []
        cfg.add_listener(lambda k, o, n: changes1.append((k, o, n)))
        cfg.add_listener(lambda k, o, n: changes2.append((k, o, n)))
        cfg.set("key", "val")
        assert len(changes1) == 1
        assert len(changes2) == 1

    def test_listener_error_does_not_propagate(self):
        """A failing listener should not break config updates."""
        cfg = DynamicConfig()

        def bad_listener(key, old, new):
            raise RuntimeError("listener error")

        cfg.add_listener(bad_listener)
        # Should not raise
        cfg.set("key", "value")
        assert cfg.get("key") == "value"
