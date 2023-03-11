from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TypeVar, Generic, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from wiring.module.module_type import ModuleType
    from wiring.provider.provider_type import ProviderType

T = TypeVar("T")


class ResourceKind(Enum):
    MODULE = 0
    PRIVATE = 1
    OVERRIDE = 2


class UnboundResource(Generic[T]):
    def __init__(self, t: Type[T], kind: ResourceKind):
        self.type = t
        self.kind = kind

    def __repr__(self) -> str:
        return f"UnboundResource({self.type.__name__})"


class BoundResource(Generic[T], ABC):
    def __init__(self, t: Type[T], name: str, module: ModuleType):
        self.type = t
        self.name = name
        self.module = module


class ModuleResource(BoundResource[T]):
    def __hash__(self) -> int:
        return hash((self.__class__, self.type, self.name, self.module))

    def __repr__(self) -> str:
        return f"ModuleResource('{self.name}', {self.type.__name__}, {self.module.__name__})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ModuleResource)
            and type(other) is ModuleResource
            and self.name == other.name
            and self.type == other.type
            and self.module is other.module
        )


class ProviderResource(BoundResource[T], ABC):
    def __init__(self, t: Type[T], name: str, provider: ProviderType):
        super().__init__(t, name, provider.module)
        self.provider = provider

    @abstractmethod
    def bound_to_sub_provider(self, provider: ProviderType) -> ProviderResource[T]:
        raise NotImplementedError()


class PrivateResource(ProviderResource[T]):
    def bound_to_sub_provider(self, provider: ProviderType) -> PrivateResource[T]:
        return PrivateResource(self.type, self.name, provider)

    def __hash__(self) -> int:
        return hash((self.__class__, self.type, self.name, self.provider))

    def __repr__(self) -> str:
        return f"PrivateResource('{self.name}', {self.type.__name__}, {self.provider.__name__})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PrivateResource)
            and type(other) is PrivateResource
            and self.type == other.type
            and self.name == other.name
            and self.provider is other.provider
        )


class OverridingResource(ProviderResource[T]):
    def __init__(self, t: Type[T], name: str, provider: ProviderType, overrides: ModuleResource[T]):
        assert provider.module is overrides.module
        super().__init__(t, name, provider)
        self.overrides = overrides

    def bound_to_sub_provider(self, provider: ProviderType) -> OverridingResource[T]:
        return OverridingResource(self.type, self.name, provider, self.overrides)

    def __hash__(self) -> int:
        return hash((self.__class__, self.type, self.name, self.provider, self.overrides))

    def __repr__(self) -> str:
        return (
            f"OverridingResource('{self.name}', {self.type.__name__}, "
            f"{self.provider.__name__}, {self.overrides})"
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, OverridingResource)
            and type(other) is OverridingResource
            and self.type == other.type
            and self.name == other.name
            and self.provider is other.provider
            and self.overrides == other.overrides
        )


def Resource(t: Type[T], kind: ResourceKind = ResourceKind.MODULE) -> Type[T]:
    return UnboundResource(t, kind)  # type: ignore
