"""Tests for RBAC/ABAC authorization system."""
import pytest
from src.security.authz import (
    Permission,
    Role,
    User,
    Resource,
    Policy,
    PolicyEngine,
    AuthorizationService,
    AccessRequest,
    AccessDecision,
    Effect,
    PolicyEvaluationError,
)


# ── RBAC Tests ──────────────────────────────────────────────────────────────

class TestRBAC:
    """Role-based access control tests."""

    def test_user_with_role_has_permission(self):
        """User with a role that grants a permission should have access."""
        perm = Permission("read", "document")
        role = Role("reader", permissions={perm})
        user = User("alice", roles={role})

        assert user.has_permission("read", "document") is True

    def test_user_without_role_lacks_permission(self):
        """User without the role should not have the permission."""
        user = User("bob", roles=set())

        assert user.has_permission("read", "document") is False

    def test_user_with_multiple_roles(self):
        """User with multiple roles should have all their permissions."""
        read_perm = Permission("read", "document")
        write_perm = Permission("write", "document")
        reader = Role("reader", permissions={read_perm})
        writer = Role("writer", permissions={write_perm})
        user = User("carol", roles={reader, writer})

        assert user.has_permission("read", "document") is True
        assert user.has_permission("write", "document") is True

    def test_role_inheritance(self):
        """Child role should inherit parent role permissions."""
        base_perm = Permission("read", "document")
        child_perm = Permission("write", "document")
        parent = Role("parent", permissions={base_perm})
        child = Role("child", permissions={child_perm}, parents={parent})
        user = User("dave", roles={child})

        assert user.has_permission("read", "document") is True
        assert user.has_permission("write", "document") is True

    def test_permission_equality(self):
        """Permissions with same action and resource should be equal."""
        p1 = Permission("read", "document")
        p2 = Permission("read", "document")
        p3 = Permission("write", "document")

        assert p1 == p2
        assert p1 != p3
        assert hash(p1) == hash(p2)

    def test_permission_wildcard(self):
        """Wildcard permission should match any action on a resource."""
        wildcard = Permission("*", "document")
        role = Role("admin", permissions={wildcard})
        user = User("eve", roles={role})

        assert user.has_permission("read", "document") is True
        assert user.has_permission("delete", "document") is True
        assert user.has_permission("read", "other") is False


# ── ABAC Tests ──────────────────────────────────────────────────────────────

class TestABAC:
    """Attribute-based access control tests."""

    def test_user_attribute_condition(self):
        """Policy should grant access based on user attributes."""
        user = User("frank", roles=set(), attributes={"department": "engineering"})
        resource = Resource("doc1", attributes={"department": "engineering"})
        policy = Policy(
            name="eng-only",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_user_attribute_mismatch_denies(self):
        """Policy should deny when user attributes don't match."""
        user = User("grace", roles=set(), attributes={"department": "marketing"})
        resource = Resource("doc1", attributes={"department": "engineering"})
        policy = Policy(
            name="eng-only",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False

    def test_resource_attribute_condition(self):
        """Policy should evaluate resource attributes."""
        user = User("heidi", roles=set(), attributes={})
        resource = Resource("doc1", attributes={"classification": "public"})
        policy = Policy(
            name="public-docs",
            permissions={Permission("read", "document")},
            resource_attrs={"classification": "public"},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_combined_user_and_resource_attributes(self):
        """Policy should require both user and resource attributes to match."""
        user = User("ivan", roles=set(), attributes={"department": "engineering"})
        resource = Resource("doc1", attributes={"department": "engineering"})
        policy = Policy(
            name="same-dept",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
            resource_attrs={"department": "engineering"},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_combined_mismatch_denies(self):
        """Policy should deny when only one attribute matches."""
        user = User("judy", roles=set(), attributes={"department": "engineering"})
        resource = Resource("doc1", attributes={"department": "marketing"})
        policy = Policy(
            name="same-dept",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
            resource_attrs={"department": "engineering"},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False


# ── Policy Engine Tests ─────────────────────────────────────────────────────

class TestPolicyEngine:
    """Policy engine evaluation tests."""

    def test_deny_overrides_allow(self):
        """Explicit deny policy should override allow policies."""
        user = User("karl", roles=set(), attributes={"name": "karl"})
        resource = Resource("doc1", attributes={})
        allow_policy = Policy(
            name="allow-all",
            permissions={Permission("read", "document")},
            effect=Effect.ALLOW,
        )
        deny_policy = Policy(
            name="deny-karl",
            permissions={Permission("read", "document")},
            user_attrs={"name": "karl"},
            effect=Effect.DENY,
        )
        engine = PolicyEngine(policies=[allow_policy, deny_policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False

    def test_no_matching_policy_denies(self):
        """When no policy matches, access should be denied by default."""
        user = User("leo", roles=set(), attributes={})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="unrelated",
            permissions={Permission("write", "document")},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False

    def test_multiple_policies_any_allow(self):
        """If any matching policy allows, access should be granted."""
        user = User("mia", roles=set(), attributes={"department": "engineering"})
        resource = Resource("doc1", attributes={})
        deny_policy = Policy(
            name="deny-marketing",
            permissions={Permission("read", "document")},
            user_attrs={"department": "marketing"},
            effect=Effect.DENY,
        )
        allow_policy = Policy(
            name="allow-eng",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
            effect=Effect.ALLOW,
        )
        engine = PolicyEngine(policies=[deny_policy, allow_policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_policy_with_no_conditions_always_matches(self):
        """Policy with no attribute conditions should always match."""
        user = User("nina", roles=set(), attributes={})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="always",
            permissions={Permission("read", "document")},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_policy_effect_allow(self):
        """Allow effect should grant access when conditions match."""
        user = User("oscar", roles=set(), attributes={"role": "admin"})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="admin-allow",
            permissions={Permission("delete", "document")},
            user_attrs={"role": "admin"},
            effect=Effect.ALLOW,
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="delete")
        decision = engine.evaluate(request)

        assert decision.allowed is True

    def test_policy_effect_deny(self):
        """Deny effect should deny access when conditions match."""
        user = User("paul", roles=set(), attributes={"role": "banned"})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="banned-deny",
            permissions={Permission("*", "*")},
            user_attrs={"role": "banned"},
            effect=Effect.DENY,
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False


# ── Authorization Service Tests ─────────────────────────────────────────────

class TestAuthorizationService:
    """High-level authorization service tests."""

    def test_service_allows_with_matching_role(self):
        """Service should allow access when user has a matching role."""
        perm = Permission("read", "document")
        role = Role("reader", permissions={perm})
        user = User("quinn", roles={role})
        resource = Resource("document")
        service = AuthorizationService()

        assert service.authorize(user, resource, "read") is True

    def test_service_denies_without_matching_role(self):
        """Service should deny access when no role matches."""
        user = User("rachel", roles=set())
        resource = Resource("doc1")
        service = AuthorizationService()

        assert service.authorize(user, resource, "read") is False

    def test_service_with_custom_engine(self):
        """Service should use a custom policy engine when provided."""
        user = User("sam", roles=set(), attributes={"department": "engineering"})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="eng-read",
            permissions={Permission("read", "document")},
            user_attrs={"department": "engineering"},
        )
        engine = PolicyEngine(policies=[policy])
        service = AuthorizationService(engine=engine)

        assert service.authorize(user, resource, "read") is True

    def test_service_authorize_all(self):
        """Service should check all actions and return True only if all allowed."""
        read_perm = Permission("read", "document")
        write_perm = Permission("write", "document")
        role = Role("editor", permissions={read_perm, write_perm})
        user = User("tina", roles={role})
        resource = Resource("document")
        service = AuthorizationService()

        assert service.authorize_all(user, resource, ["read", "write"]) is True
        assert service.authorize_all(user, resource, ["read", "delete"]) is False

    def test_service_authorize_any(self):
        """Service should return True if any action is allowed."""
        read_perm = Permission("read", "document")
        role = Role("reader", permissions={read_perm})
        user = User("ursula", roles={role})
        resource = Resource("document")
        service = AuthorizationService()

        assert service.authorize_any(user, resource, ["read", "write"]) is True
        assert service.authorize_any(user, resource, ["write", "delete"]) is False


# ── Edge Case Tests ─────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_empty_roles_and_policies(self):
        """User with no roles and engine with no policies should deny."""
        user = User("victor", roles=set(), attributes={})
        resource = Resource("doc1", attributes={})
        engine = PolicyEngine(policies=[])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.allowed is False

    def test_circular_role_inheritance(self):
        """Circular role inheritance should not cause infinite loop."""
        perm = Permission("read", "document")
        role_a = Role("a", permissions=set())
        role_b = Role("b", permissions={perm}, parents={role_a})
        role_a.parents = {role_b}  # circular
        user = User("wendy", roles={role_a})

        # Should not raise, should find permission via B
        assert user.has_permission("read", "document") is True

    def test_permission_with_wildcard_resource(self):
        """Wildcard resource should match any resource."""
        wildcard = Permission("read", "*")
        role = Role("super", permissions={wildcard})
        user = User("xander", roles={role})

        assert user.has_permission("read", "document") is True
        assert user.has_permission("read", "database") is True
        assert user.has_permission("write", "document") is False

    def test_decision_reason_populated(self):
        """Decision should include a reason string."""
        user = User("yara", roles=set(), attributes={})
        resource = Resource("doc1", attributes={})
        policy = Policy(
            name="test-policy",
            permissions={Permission("read", "document")},
        )
        engine = PolicyEngine(policies=[policy])

        request = AccessRequest(user=user, resource=resource, action="read")
        decision = engine.evaluate(request)

        assert decision.reason is not None
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0

    def test_invalid_action_denies(self):
        """Request with empty action should deny."""
        user = User("zack", roles=set(), attributes={})
        resource = Resource("doc1", attributes={})
        engine = PolicyEngine(policies=[])

        request = AccessRequest(user=user, resource=resource, action="")
        decision = engine.evaluate(request)

        assert decision.allowed is False
