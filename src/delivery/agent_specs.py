"""Schema-validated role snapshots bounded by repository-owned role.json grants."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from delivery.adk_contracts import RestaurantBrain
from delivery.memory_profiles import MemoryProfile
from delivery.role_manifest import ROOT, manifest_data, manifest_names


class RoleLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    events_per_run: int = Field(default=100, ge=1, le=1000, strict=True)
    tool_calls_per_event: int = Field(default=8, ge=1, le=16, strict=True)
    tool_calls_per_run: int = Field(default=400, ge=1, le=2000, strict=True)
    memory_entries: int = Field(default=32, ge=1, le=100, strict=True)
    memory_bytes: int = Field(default=16384, ge=1, le=65536, strict=True)
    model_calls: int = Field(default=0, ge=0, le=100, strict=True)
    model_tokens: int = Field(default=0, ge=0, le=51200, strict=True)
    model_usd: Literal[0] = 0


class _RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    role: Literal[
        "inventory",
        "fulfillment",
        "dispatcher",
        "courier",
        "judge",
        "household",
        "restaurant",
        "market",
        "customer_service",
    ]
    display_name: str = Field(default="", max_length=80)
    mission: str = Field(default="", max_length=300)
    why_it_exists: str = Field(default="", max_length=500)
    design_decisions: tuple[str, ...] = ()
    known_limits: tuple[str, ...] = ()
    tool_profiles: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    service_events: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    environment_limits: dict[str, RoleLimits] = Field(default_factory=dict)
    recovery_tools: tuple[str, ...] = ()
    tool_descriptions: dict[str, str] = Field(default_factory=dict)
    version: str = Field(min_length=1, max_length=64)
    policy: Literal["deterministic", "gcp_ai", "adk"]
    brain: RestaurantBrain | None = None
    memory: MemoryProfile | None = None
    soul_file: Literal["SOUL.md"]
    accepts: tuple[str, ...]
    emits: tuple[str, ...]
    tools: tuple[str, ...]
    limits: RoleLimits = Field(default_factory=RoleLimits)

    @model_validator(mode="after")
    def model_authority(self) -> "_RoleConfig":
        trusted = manifest_data(self.role)
        for field in ("tool_profiles", "service_events"):
            for key, values in getattr(self, field).items():
                if len(values) != len(set(values)) or not set(values) <= set(
                    trusted.get(field, {}).get(key, ())
                ):
                    raise ValueError(f"{field} exceeds manifest authority")
        for name, limits in self.environment_limits.items():
            ceiling = trusted.get("environment_limits", {}).get(name)
            if ceiling is None or any(value > ceiling.get(key, 0)
                                      for key, value in limits.model_dump().items()):
                raise ValueError("environment_limits exceeds manifest authority")
        if len(self.recovery_tools) != len(set(self.recovery_tools)) or not set(
            self.recovery_tools
        ) <= set(trusted.get("recovery_tools", ())):
            raise ValueError("recovery_tools exceeds manifest authority")
        if self.policy == "adk":
            if self.role == "customer_service" and self.brain is None and not self.tools:
                pass  # Classifier only; recovery permissions are a separate turn.
            elif self.role != "restaurant" or self.brain is None:
                raise ValueError("ADK requires a restaurant template")
            elif set(self.tools) != set(self.brain.tools) or "supply.command" in self.tools:
                raise ValueError("ADK tools must match the frozen granular template")
        elif self.brain is not None:
            raise ValueError("A reasoning template requires ADK policy")
        if self.policy == "gcp_ai":
            if self.role != "judge" or not self.limits.model_calls or not self.limits.model_tokens:
                raise ValueError("Only the bounded recovery judge may use GCP AI")
        elif self.limits.model_calls or self.limits.model_tokens:
            raise ValueError("Deterministic roles cannot reserve model budgets")
        return self

    @field_validator("accepts", "emits", "tools")
    @classmethod
    def enforce_authority(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        assert info.field_name is not None
        authority = manifest_data(str(info.data["role"]))[info.field_name]
        if len(value) != len(set(value)) or not set(value).issubset(authority):
            raise ValueError(f"{info.field_name} exceeds server authority or contains duplicates")
        return value


class RoleSpec(_RoleConfig):
    """Run snapshot: SOUL is descriptive text and never grants authority."""

    soul: str

    @property
    def name(self) -> str:
        return self.role

    @property
    def digest(self) -> str:
        definition = self.model_dump(mode="json")
        # Frozen runs created before the explanation fields keep their original
        # identity hash; new manifests include and hash the new fields normally.
        for key in (
            "display_name", "mission", "why_it_exists", "design_decisions", "known_limits",
            "tool_profiles", "service_events", "recovery_tools", "tool_descriptions",
            "environment_limits",
        ):
            if key not in self.model_fields_set:
                definition.pop(key)
        if self.brain is None:
            definition.pop("brain")  # Preserve hashes of previously frozen definitions.
        if self.memory is None:
            definition.pop("memory")
        payload = json.dumps(definition, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_inventory_role(root: Path = ROOT / "inventory") -> RoleSpec:
    """Load only role.json and the fixed SOUL.md file; validate before reading SOUL."""
    config = _RoleConfig.model_validate_json((root / "role.json").read_text(encoding="utf-8"))
    soul_path = root / "SOUL.md"
    if soul_path.resolve().parent != root.resolve():
        raise ValueError("SOUL.md must remain inside the role directory")
    return RoleSpec(**config.model_dump(), soul=soul_path.read_text(encoding="utf-8"))


def load_role(name: str) -> RoleSpec:
    if name not in manifest_names():
        raise ValueError("Unknown role")
    role = load_inventory_role(ROOT / name)
    if role.name != ("judge" if name == "judge-gcp" else name):
        raise ValueError("Role directory does not match role identity")
    return role


def role_schema() -> dict:
    """Published JSON Schema generated from the same Pydantic runtime validator."""
    return _RoleConfig.model_json_schema()
