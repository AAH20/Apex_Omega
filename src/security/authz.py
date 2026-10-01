"""RBAC/ABAC authorization system for APEX-OS."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyEvaluationError(Exception):
    """Raised when policy evaluation fails."""


class Effect(Enum):
    """Policy effect: allow or deny."""
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class Permission:
    """A permission grants an action on a resource type."""
    action: str
    resource: str

    def matches(self, action: str, resource: str) -> bool:
        """Check if this permission covers the given action and resource."""
        action_match = self.action == "*" or self.action == action
        resource_match = self.resource == "*" or self.resource == resource
        return action_match and resource_match


@dataclass(eq=False)
class Role:
    """A role groups permissions and can inherit from parent roles."""
    name: str
    permissions: set[Permission] = field(default_factory=set)
    parents: set[Role] = field(default_factory=set)

    def __hash__(self) -> int:
        return hash(self.name)

    def all_permissions(self) -> set[Permission]:
        """Get all permissions including inherited ones."""
        result = set(self.permissions)
        visited: set[Role] = {self}
        queue = list(self.parents)
        while queue:
            parent = queue.pop(0)
            if parent in visited:
                continue
            visited.add(parent)
            result.update(parent.permissions)
            queue.extend(parent.parents)
        return result


@dataclass
class User:
    """A user with roles and attributes."""
    name: str
    roles: set[Role] = field(default_factory=set)
    attributes: dict[str, Any] = field(default_factory=dict)

    def has_permission(self, action: str, resource: str) -> bool:
        """Check if user has permission via any of their roles."""
        for role in self.roles:
            for perm in role.all_permissions():
                if perm.matches(action, resource):
                    return True
        return False


@dataclass
class Resource:
    """A resource with attributes for ABAC evaluation."""
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Policy:
    """An ABAC policy with conditions and effect."""
    name: str
    permissions: set[Permission] = field(default_factory=set)
    user_attrs: dict[str, Any] = field(default_factory=dict)
    resource_attrs: dict[str, Any] = field(default_factory=dict)
    effect: Effect = Effect.ALLOW

    def matches_user(self, user: User) -> bool:
        """Check if user attributes match policy conditions."""
        return all(
            user.attributes.get(k) == v
            for k, v in self.user_attrs.items()
        )

    def matches_resource(self, resource: Resource) -> bool:
        """Check if resource attributes match policy conditions."""
        return all(
            resource.attributes.get(k) == v
            for k, v in self.resource_attrs.items()
        )

    def matches_action(self, action: str) -> bool:
        """Check if any permission in this policy covers the action."""
        return any(
            p.matches(action, "*") or p.action == action
            for p in self.permissions
        )


@dataclass
class AccessRequest:
    """A request for access to a resource."""
    user: User
    resource: Resource
    action: str


@dataclass
class AccessDecision:
    """The result of an access evaluation."""
    allowed: bool
    reason: str


class PolicyEngine:
    """Evaluates access requests against a set of policies."""

    def __init__(self, policies: list[Policy] | None = None):
        self.policies = policies or []

    def evaluate(self, request: AccessRequest) -> AccessDecision:
        """Evaluate an access request against all policies."""
        if not request.action:
            return AccessDecision(False, "No action specified")

        # Check deny policies first (deny overrides allow)
        for policy in self.policies:
            if policy.effect == Effect.DENY:
                if (
                    policy.matches_user(request.user)
                    and policy.matches_resource(request.resource)
                    and policy.matches_action(request.action)
                ):
                    return AccessDecision(
                        False,
                        f"Denied by policy: {policy.name}",
                    )

        # Check allow policies
        for policy in self.policies:
            if policy.effect == Effect.ALLOW:
                if (
                    policy.matches_user(request.user)
                    and policy.matches_resource(request.resource)
                    and policy.matches_action(request.action)
                ):
                    return AccessDecision(
                        True,
                        f"Allowed by policy: {policy.name}",
                    )

        return AccessDecision(False, "No matching policy found")


class AuthorizationService:
    """High-level authorization service combining RBAC and ABAC."""

    def __init__(self, engine: PolicyEngine | None = None):
        self.engine = engine or PolicyEngine()

    def authorize(self, user: User, resource: Resource, action: str) -> bool:
        """Check if user is authorized to perform action on resource."""
        # First check RBAC
        if user.has_permission(action, resource.name):
            return True

        # Then check ABAC via policy engine
        request = AccessRequest(user=user, resource=resource, action=action)
        decision = self.engine.evaluate(request)
        return decision.allowed

    def authorize_all(
        self, user: User, resource: Resource, actions: list[str]
    ) -> bool:
        """Check if user is authorized for all specified actions."""
        return all(self.authorize(user, resource, action) for action in actions)

    def authorize_any(
        self, user: User, resource: Resource, actions: list[str]
    ) -> bool:
        """Check if user is authorized for any of the specified actions."""
        return any(self.authorize(user, resource, action) for action in actions)
