from typing import TypeVar, Optional, Type, cast, Any

from wiring.resource import ResourceType
from wiring.module.module_type import ModuleType
from wiring.provider.provider_type import ProviderType, ProviderMethod
from wiring.container.errors import (
    UnknownResource,
    ModuleAlreadyRegistered,
    ProviderModuleMismatch,
    CannotRegisterProviderToUnknownModule,
    ModuleProviderAlreadyRegistered,
    ModuleWithoutProvider,
    CannotProvideUntilContainerIsSealed,
    CannotRegisterAfterContainerIsSealed,
    CannotProvideRawType,
    CircularDependency,
    ResolutionStep,
)

T = TypeVar("T")


class Container:
    def __init__(self) -> None:
        self._public_modules: set[ModuleType] = set()
        self._private_modules: set[ModuleType] = set()
        self._providers_by_module: dict[ModuleType, ProviderType] = {}
        self._modules_without_providers: set[ModuleType] = set()
        self._providers_yet_to_solve: set[ProviderType] = set()
        self._is_sealed = False
        self._instances_by_resource: dict[ResourceType[Any], Any] = {}

    def register(
        self, module: ModuleType, provider: Optional[ProviderType] = None
    ) -> None:
        if self._is_sealed:
            raise CannotRegisterAfterContainerIsSealed(module)
        self._register_public_module(module)
        if provider is not None:
            if provider.module is not module:
                raise ProviderModuleMismatch(provider, module)
            self._register_provider(provider, target=module)

    def register_provider(self, provider: ProviderType) -> None:
        if self._is_sealed:
            raise CannotRegisterAfterContainerIsSealed(provider)
        if provider.module not in self._public_modules:
            raise CannotRegisterProviderToUnknownModule(provider, self._public_modules)
        self._register_provider(provider, target=provider.module)

    def seal(self) -> None:
        self._solve_rest_of_graph()
        self._is_sealed = True

    def provide(self, resource: Type[T]) -> T:
        if not self._is_sealed:
            raise CannotProvideUntilContainerIsSealed()
        if not isinstance(resource, ResourceType):
            raise CannotProvideRawType(resource)
        as_resource = cast(ResourceType[T], resource)
        return self._provide(as_resource)

    def _provide(self, resource: ResourceType[T]) -> T:
        if resource in self._instances_by_resource:
            return cast(T, self._instances_by_resource[resource])
        target_module = resource.module
        if target_module not in self._providers_by_module:
            raise UnknownResource(resource, self._public_modules)
        provider = self._providers_by_module[target_module]
        provider_method: ProviderMethod[T] = provider._get_provider_method(resource)
        method_parameters = {
            name: self._provide(resource)
            for name, resource in provider_method.dependencies.items()
        }
        instance = provider_method.method(None, **method_parameters)
        self._instances_by_resource[resource] = instance
        return instance

    def _register_provider(self, provider: ProviderType, target: ModuleType) -> None:
        if target in self._providers_by_module:
            raise ModuleProviderAlreadyRegistered(target, provider)
        self._providers_by_module[target] = provider
        self._modules_without_providers.remove(target)
        self._providers_yet_to_solve.add(provider)

    def _register_public_module(self, module: ModuleType) -> None:
        if module in self._public_modules:
            raise ModuleAlreadyRegistered(module, self._public_modules)
        self._public_modules.add(module)
        self._modules_without_providers.add(module)

    def _register_private_module(self, module: ModuleType) -> None:
        self._private_modules.add(module)
        self._modules_without_providers.add(module)

    def _register_default_providers(self) -> None:
        for module in self._modules_without_providers.copy():
            provider = module.default_provider
            if provider is None:
                raise ModuleWithoutProvider(module)
            self._register_provider(provider, target=module)

    def _solve_rest_of_graph(self) -> None:
        while len(self._modules_without_providers) > 0:
            self._register_default_providers()
            self._solve_providers()

        self._find_circular_dependencies()

    def _solve_providers(self) -> None:
        for provider in self._providers_yet_to_solve.copy():
            self._solve_provider(provider)

    def _solve_provider(self, provider: ProviderType) -> None:
        self._providers_yet_to_solve.remove(provider)
        for provider_method in provider._list_provider_methods():
            for parameter_name, dependency in provider_method.dependencies.items():
                module = dependency.module
                if module not in self._providers_by_module:
                    self._register_private_module(module)

    def _find_circular_dependencies(self) -> None:
        solved: set[ResourceType[Any]] = set()
        for module in self._providers_by_module.keys():
            for resource in module._list_resources():
                loop = self._find_circular_dependency(
                    resource, in_stack=set(), solved=solved
                )
                if loop is not None:
                    raise CircularDependency(loop)

    def _find_circular_dependency(
        self,
        target: ResourceType[Any],
        in_stack: set[ResourceType[Any]],
        solved: set[ResourceType[Any]],
    ) -> Optional[list[ResolutionStep]]:
        if target in solved:
            return None
        provider = self._providers_by_module[target.module]
        provider_method = provider._get_provider_method(target)
        in_stack.add(target)
        for parameter_name, depends_on in provider_method.dependencies.items():
            if depends_on in in_stack:
                return [
                    ResolutionStep(target, provider_method, parameter_name, depends_on)
                ]
            loop = self._find_circular_dependency(depends_on, in_stack, solved)
            if loop is not None:
                loop.insert(
                    0,
                    ResolutionStep(target, provider_method, parameter_name, depends_on),
                )
                return loop
        in_stack.remove(target)
        solved.add(target)
        return None
