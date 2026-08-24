from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from auramcp.contracts.extensions import (
    ExtensionPackage,
    PromptArgument,
    PromptDescriptor,
    RegisteredPrompt,
    RegisteredResource,
    RegisteredResourceTemplate,
    RegisteredTool,
    ResourceContents,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
)
from auramcp.contracts.identity import TrustedContext
from auramcp.domain.ports import PlatformStore

_HANDBOOK = """# AuraMCP ops handbook

AuraMCP is the AuraClaw extension plane.

- Discover capabilities with server/discover, then tools/list.
- Call only auramcp.* names. Never supply server URLs or secrets.
- Disable/enable is an admin action; a disabled package disappears from list and call.
- Capability business data is not stored in the AuraMCP platform database.
"""


class OpsExtension:
    def __init__(
        self,
        store: PlatformStore,
        packages: Callable[[], Sequence[ExtensionPackage]],
    ) -> None:
        self._store = store
        self._packages = packages

    async def catalog_snapshot(
        self,
        _arguments: dict[str, Any],
        trusted: TrustedContext,
    ) -> ToolCallResult:
        statuses = await self._store.get_statuses()
        packages = []
        for package in self._packages():
            status = str(statuses.get(package.name) or "active")
            packages.append(
                {
                    "name": package.name,
                    "version": package.version,
                    "status": str(status),
                    "tools": [item.descriptor.name for item in package.tools],
                    "resources": [
                        item.descriptor.uri for item in package.resources if item.descriptor.uri
                    ],
                    "prompts": [item.descriptor.name for item in package.prompts],
                }
            )
        payload = {"tenant": trusted.tenant_id, "packages": packages}
        return ToolCallResult(structured=payload, text=f"{len(packages)} packages")

    async def read_handbook(
        self,
        uri: str,
        trusted: TrustedContext,
    ) -> tuple[ResourceContents, ...]:
        del trusted
        return (ResourceContents(uri=uri, mime_type="text/markdown", text=_HANDBOOK),)

    async def read_extension_status(
        self,
        uri: str,
        trusted: TrustedContext,
    ) -> tuple[ResourceContents, ...]:
        del trusted
        prefix = "auramcp://ops/extensions/"
        if not uri.startswith(prefix):
            return ()
        name = uri.removeprefix(prefix)
        package = next((item for item in self._packages() if item.name == name), None)
        if package is None:
            return ()
        statuses = await self._store.get_statuses()
        status = statuses.get(name)
        status_value = "active" if status is None else str(status)
        text = f"name={package.name}\nversion={package.version}\nstatus={status_value}\n"
        return (ResourceContents(uri=uri, mime_type="text/plain", text=text),)

    async def diagnose(self, arguments: dict[str, str], trusted: TrustedContext) -> dict[str, Any]:
        symptom = arguments.get("symptom") or "unknown extension failure"
        return {
            "description": "Diagnose an AuraMCP extension failure",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Tenant {trusted.tenant_id} reports: {symptom}. "
                            "Check auramcp.ops.catalog_snapshot, confirm the package is "
                            "active, and retry the original auramcp.* call. Do not contact "
                            "external identity systems."
                        ),
                    },
                }
            ],
        }

    def package(self) -> ExtensionPackage:
        return ExtensionPackage(
            name="ops",
            title="AuraClaw ops extensions",
            version="1.0.0",
            description="Operational catalog and diagnosis helpers for AuraClaw",
            tools=(
                RegisteredTool(
                    package="ops",
                    descriptor=ToolDescriptor(
                        name="auramcp.ops.catalog_snapshot",
                        description="List AuraMCP extension packages and their governance status",
                        input_schema={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                        output_schema={"type": "object"},
                        read_only=True,
                    ),
                    handler=self.catalog_snapshot,
                ),
            ),
            resources=(
                RegisteredResource(
                    package="ops",
                    descriptor=ResourceDescriptor(
                        name="handbook",
                        uri="auramcp://ops/handbook",
                        title="AuraMCP ops handbook",
                        mime_type="text/markdown",
                    ),
                    reader=self.read_handbook,
                ),
            ),
            resource_templates=(
                RegisteredResourceTemplate(
                    package="ops",
                    descriptor=ResourceDescriptor(
                        name="extension-status",
                        uri_template="auramcp://ops/extensions/{name}",
                        title="Extension package status",
                        mime_type="text/plain",
                    ),
                    reader=self.read_extension_status,
                ),
            ),
            prompts=(
                RegisteredPrompt(
                    package="ops",
                    descriptor=PromptDescriptor(
                        name="auramcp.ops.diagnose",
                        title="Diagnose AuraMCP extension failure",
                        arguments=(
                            PromptArgument(
                                name="symptom",
                                description="What failed",
                                required=False,
                            ),
                        ),
                    ),
                    renderer=self.diagnose,
                ),
            ),
        )
