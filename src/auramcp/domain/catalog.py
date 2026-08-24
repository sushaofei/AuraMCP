from __future__ import annotations

from auramcp.contracts.errors import CatalogConflictError
from auramcp.contracts.extensions import (
    CapabilityKind,
    CapabilityRecord,
    CatalogSnapshot,
    ExtensionPackage,
    ExtensionStatus,
    RegisteredPrompt,
    RegisteredResource,
    RegisteredResourceTemplate,
    RegisteredTool,
)
from auramcp.domain.acl import assert_canonical_name, assert_resource_uri, visible_to_tenant
from auramcp.domain.digest import sha256_digest


def publish_catalog(
    packages: tuple[ExtensionPackage, ...],
    statuses: dict[str, ExtensionStatus],
    *,
    tenant_id: str,
) -> CatalogSnapshot:
    tools: list[RegisteredTool] = []
    resources: list[RegisteredResource] = []
    templates: list[RegisteredResourceTemplate] = []
    prompts: list[RegisteredPrompt] = []
    records: list[CapabilityRecord] = []
    seen: dict[str, str] = {}

    for package in packages:
        status = statuses.get(package.name, ExtensionStatus.ACTIVE)
        if status is not ExtensionStatus.ACTIVE:
            continue
        for tool in package.tools:
            assert_canonical_name(tool.descriptor.name)
            _claim(seen, tool.descriptor.name, package.name)
            tools.append(tool)
            records.append(
                _record(
                    package,
                    status,
                    CapabilityKind.TOOL,
                    tool.descriptor.name,
                    tool.descriptor.version,
                    tool.descriptor.description,
                    tool.descriptor.model_dump(mode="json"),
                )
            )
        for resource in package.resources:
            uri = resource.descriptor.uri or ""
            assert_resource_uri(uri)
            if not visible_to_tenant(resource.tenant_ids, tenant_id):
                continue
            _claim(seen, uri, package.name)
            resources.append(resource)
            records.append(
                _record(
                    package,
                    status,
                    CapabilityKind.RESOURCE,
                    uri,
                    package.version,
                    resource.descriptor.description or "",
                    resource.descriptor.model_dump(mode="json"),
                )
            )
        for template in package.resource_templates:
            uri_template = template.descriptor.uri_template or ""
            if not uri_template.startswith("auramcp://"):
                raise ValueError("resource template must use auramcp://")
            if not visible_to_tenant(template.tenant_ids, tenant_id):
                continue
            _claim(seen, uri_template, package.name)
            templates.append(template)
            records.append(
                _record(
                    package,
                    status,
                    CapabilityKind.RESOURCE_TEMPLATE,
                    uri_template,
                    package.version,
                    template.descriptor.description or "",
                    template.descriptor.model_dump(mode="json"),
                )
            )
        for prompt in package.prompts:
            assert_canonical_name(prompt.descriptor.name)
            if not visible_to_tenant(prompt.tenant_ids, tenant_id):
                continue
            _claim(seen, prompt.descriptor.name, package.name)
            prompts.append(prompt)
            records.append(
                _record(
                    package,
                    status,
                    CapabilityKind.PROMPT,
                    prompt.descriptor.name,
                    package.version,
                    prompt.descriptor.description or "",
                    prompt.descriptor.model_dump(mode="json"),
                )
            )

    records_tuple = tuple(records)
    return CatalogSnapshot(
        digest=sha256_digest([item.model_dump(mode="json") for item in records_tuple]),
        records=records_tuple,
        tools=tuple(tools),
        resources=tuple(resources),
        resource_templates=tuple(templates),
        prompts=tuple(prompts),
    )


def _claim(seen: dict[str, str], key: str, package: str) -> None:
    owner = seen.get(key)
    if owner is not None:
        raise CatalogConflictError(f"canonical name {key} conflicts between {owner} and {package}")
    seen[key] = package


def _record(
    package: ExtensionPackage,
    status: ExtensionStatus,
    kind: CapabilityKind,
    canonical_name: str,
    version: str,
    description: str,
    payload: dict[str, object],
) -> CapabilityRecord:
    digest = sha256_digest(payload)
    return CapabilityRecord(
        capability_id=f"{kind}:{canonical_name}:{digest[-12:]}",
        kind=kind,
        package=package.name,
        canonical_name=canonical_name,
        version=version,
        digest=digest,
        status=status,
        title=package.title,
        description=description,
    )
