from __future__ import annotations


class IdentityDeniedError(Exception):
    def __init__(self, message: str = "unauthorized") -> None:
        super().__init__(message)
        self.message = message


class IdentityConflictError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class CatalogConflictError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ExtensionNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class VersionConflictError(Exception):
    def __init__(self, message: str = "version conflict") -> None:
        super().__init__(message)
        self.message = message
