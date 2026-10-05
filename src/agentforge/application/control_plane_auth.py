from __future__ import annotations

from agentforge.application.ports import PrincipalResolver
from agentforge.domain.governance import PrincipalContext
from agentforge.domain.models import Run

ROLE_RUN_CREATE = "runtime:run:create"
ROLE_RUN_READ_ANY = "runtime:run:read:any"
ROLE_CANCEL_ANY = "runtime:cancel:any"
ROLE_RESOLVE_ACTION = "runtime:resolve_action"


class GovernedResourceHiddenError(LookupError):
    """The resource is intentionally hidden from this governed principal."""


class GovernedForbiddenError(PermissionError):
    """The governed principal can see the scope but lacks required authority."""


def resolve_trusted_principal(resolver: PrincipalResolver) -> PrincipalContext:
    if not resolver.trusted_for_governed:
        raise GovernedForbiddenError("trusted governed principal is required")
    return resolver.resolve()


def require_role(principal: PrincipalContext, role: str) -> None:
    if role not in principal.roles:
        raise GovernedForbiddenError("governed principal lacks required authority")


def authorize_create(principal: PrincipalContext) -> None:
    require_role(principal, ROLE_RUN_CREATE)


def _require_visible_scope(run: Run, principal: PrincipalContext) -> None:
    if run.requester_scope is None or run.requester_scope != principal.principal_scope:
        raise GovernedResourceHiddenError("run not found")


def authorize_read(run: Run, principal: PrincipalContext) -> None:
    _require_visible_scope(run, principal)
    if run.requester_principal_id == principal.principal_id:
        return
    require_role(principal, ROLE_RUN_READ_ANY)


def authorize_cancel(run: Run, principal: PrincipalContext) -> None:
    _require_visible_scope(run, principal)
    if run.requester_principal_id == principal.principal_id:
        return
    require_role(principal, ROLE_CANCEL_ANY)


def authorize_action_resolution(run: Run, principal: PrincipalContext) -> None:
    _require_visible_scope(run, principal)
    require_role(principal, ROLE_RESOLVE_ACTION)
