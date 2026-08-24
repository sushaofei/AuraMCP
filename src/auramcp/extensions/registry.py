from __future__ import annotations

from auramcp.contracts.errors import CatalogConflictError
from auramcp.contracts.extensions import ExtensionPackage
from auramcp.domain.acl import assert_canonical_name, assert_resource_uri


class ExtensionRegistry:
    def __init__(self, packages: tuple[ExtensionPackage, ...]) -> None:
        seen_packages: set[str] = set()
        names: set[str] = set()
        for package in packages:
            if package.name in seen_packages:
                raise CatalogConflictError(f"duplicate extension package {package.name}")
            seen_packages.add(package.name)
            for tool in package.tools:
                assert_canonical_name(tool.descriptor.name)
                _claim(names, tool.descriptor.name)
            for resource in package.resources:
                uri = resource.descriptor.uri or ""
                assert_resource_uri(uri)
                _claim(names, uri)
            for template in package.resource_templates:
                uri_template = template.descriptor.uri_template or ""
                if not uri_template.startswith("auramcp://"):
                    raise ValueError("resource template must use auramcp://")
                _claim(names, uri_template)
            for prompt in package.prompts:
                assert_canonical_name(prompt.descriptor.name)
                _claim(names, prompt.descriptor.name)
        self._packages = {package.name: package for package in packages}

    @property
    def packages(self) -> tuple[ExtensionPackage, ...]:
        return tuple(self._packages.values())

    def get(self, name: str) -> ExtensionPackage:
        package = self._packages.get(name)
        if package is None:
            raise KeyError(name)
        return package


def _claim(names: set[str], key: str) -> None:
    if key in names:
        raise CatalogConflictError(f"duplicate canonical name {key}")
    names.add(key)
