from __future__ import annotations

from dataclasses import dataclass

from agentforge.application.ports import PrincipalResolver
from agentforge.domain.enums import GovernanceMode, PrincipalType
from agentforge.domain.governance import PrincipalContext


@dataclass(frozen=True, slots=True)
class LegacyDevelopmentPrincipalResolver:
    principal_scope: str = "legacy-development"
    principal_id: str = "legacy-development"
    roles: tuple[str, ...] = ()

    @property
    def trusted_for_governed(self) -> bool:
        return False

    def resolve(self) -> PrincipalContext:
        return PrincipalContext(
            principal_id=self.principal_id,
            principal_type=PrincipalType.SERVICE,
            roles=self.roles,
            principal_scope=self.principal_scope,
            authn_source="legacy-development",
        )


def resolve_principal_for_mode(
    resolver: PrincipalResolver,
    governance_mode: GovernanceMode,
) -> PrincipalContext:
    if governance_mode is GovernanceMode.GOVERNED and not resolver.trusted_for_governed:
        raise PermissionError(
            "GOVERNED execution requires a trusted PrincipalResolver; "
            "legacy development identity is non-authoritative"
        )
    return resolver.resolve()
