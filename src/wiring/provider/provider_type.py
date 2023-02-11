from __future__ import annotations

import inspect
from dataclasses import dataclass
from itertools import islice
from typing import (
    Any,
    Generic,
    Iterable,
    Callable,
    TypeVar,
    cast,
    TYPE_CHECKING,
    Optional,
)

from wiring.resource import (
    ModuleResource,
    PrivateResource,
    ResourceTypes,
    OverridingResource,
)
from wiring.provider.errors import (
    MissingProviderMethod,
    ProviderMethodNotCallable,
    ProvidersModuleIsNotAModule,
    CannotProvideBaseModule,
    UnrelatedResource,
    ProviderMethodMissingReturnTypeAnnotation,
    ProviderMethodReturnTypeMismatch,
    ProviderMethodParameterMissingTypeAnnotation,
    ProviderMethodParameterUnrelatedName,
    ProviderMethodParameterInvalidTypeAnnotation,
    ProviderMethodParameterResourceTypeMismatch,
    ProvidersCannotBeInstantiated,
    CannotUseExistingProviderResource,
    CannotDefinePublicResourceInProvider,
    InvalidAttributeAnnotationInProvider,
    InvalidPrivateResourceAnnotationInProvider,
    InvalidModuleResourceAnnotationInProvider,
    PrivateResourceCannotOccludeModuleResource,
    CannotDependOnResourceFromAnotherProvider,
    InvalidOverridingResourceAnnotationInProvider,
    OverridingResourceIncompatibleType,
    OverridingResourceNameDoesntMatchModuleResource,
    ProvidersDontSupportMultipleInheritance,
    ProviderDeclarationMissingModule,
    BaseProviderProvidesFromADifferentModule,
    ProvidersMustInheritFromProviderClass,
    IncompatibleResourceTypeForInheritedResource,
)

T = TypeVar("T")

if TYPE_CHECKING:
    from wiring.module.module_type import ModuleType


class ProviderType(type):
    _resources_by_name: dict[str, OverridingResource[Any] | PrivateResource[Any]]
    _resources: set[OverridingResource[Any] | PrivateResource[Any]]
    _provider_methods_by_resource: dict[ResourceTypes[Any], ProviderMethod[Any]]

    def __init__(
        self,
        name: str,
        bases: tuple[type, ...],
        dct: dict[str, Any],
        *,
        module: Optional[ModuleType] = None,
    ) -> None:
        type.__init__(self, name, bases, dct)
        self._provider_methods_by_resource = {}
        self._resources_by_name = {}
        self._resources = set()
        if len(bases) == 0:
            return
        if len(bases) > 1:
            raise ProvidersDontSupportMultipleInheritance(self, bases)
        base_provider = bases[0]
        self.module = self._get_module_from_class_declaration(base_provider, module)
        self._collect_resources(
            dct, inspect.get_annotations(self), cast(ProviderType, base_provider)
        )
        self._collect_provider_methods()

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        raise ProvidersCannotBeInstantiated(self)

    def _get_module_from_class_declaration(
        self, base: type, module: Optional[ModuleType]
    ) -> ModuleType:
        from wiring.module.module_type import ModuleType, Module

        if base is Provider:
            if module is None:
                raise ProviderDeclarationMissingModule(self)
            elif module is Module:
                raise CannotProvideBaseModule(self)
            elif isinstance(module, ModuleType):
                return module
            else:
                raise ProvidersModuleIsNotAModule(self, module)
        elif issubclass(base, Provider):
            if module is not None and module is not base.module:
                raise BaseProviderProvidesFromADifferentModule(self, base, module)
            return base.module
        else:
            raise ProvidersMustInheritFromProviderClass(self)

    def _collect_provider_methods(self) -> None:
        for provider_resource in self._resources:
            provider_method = self._build_provider_method(provider_resource)
            self._add_provider_method(provider_method)
        for module_resource in self.module:
            if module_resource.name in self._resources_by_name:
                continue
            provider_method = self._build_provider_method(module_resource)
            self._add_provider_method(provider_method)

    def _build_provider_method(
        self,
        resource: ResourceTypes[T],
    ) -> ProviderMethod[T]:
        method = getattr(self, f"provide_{resource.name}", None)
        if method is None:
            raise MissingProviderMethod(resource, self)
        if not callable(method):
            raise ProviderMethodNotCallable(resource, self)
        signature = inspect.signature(method)
        if signature.return_annotation is signature.empty:
            raise ProviderMethodMissingReturnTypeAnnotation(self, resource, method)
        if not issubclass(signature.return_annotation, resource.type):
            raise ProviderMethodReturnTypeMismatch(
                self, resource, method, mismatched_type=signature.return_annotation
            )
        method_dependencies = self._get_parameter_resources(signature, resource, method)

        bound_resource = (
            resource.overrides if isinstance(resource, OverridingResource) else resource
        )
        return ProviderMethod(
            provider=self,
            method=method,
            resource=bound_resource,
            dependencies=method_dependencies,
        )

    def _get_parameter_resources(
        self,
        signature: inspect.Signature,
        target: ResourceTypes[Any],
        method: Any,
    ) -> dict[str, ResourceTypes[Any]]:
        method_dependencies: dict[str, ResourceTypes[Any]] = {}

        # exclude first parameter (self)
        for name, parameter in islice(signature.parameters.items(), 1, None):
            method_dependencies[name] = self._get_parameter_resource(
                name, parameter, target, method
            )

        return method_dependencies

    def _get_parameter_resource(
        self,
        name: str,
        parameter: inspect.Parameter,
        target: ResourceTypes[Any],
        method: Any,
    ) -> ResourceTypes[Any]:
        parameter_type = parameter.annotation
        if parameter_type is inspect.Signature.empty:
            raise ProviderMethodParameterMissingTypeAnnotation(
                self, target, method, parameter_name=name
            )
        if type(parameter_type) is ModuleResource:
            return parameter_type

        if type(parameter_type) is PrivateResource:
            # when providers can be subclassed, part of this is a valid use case.
            raise CannotDependOnResourceFromAnotherProvider(
                target, parameter_type, name
            )

        if not isinstance(parameter_type, type):
            raise ProviderMethodParameterInvalidTypeAnnotation(
                self, target, method, name, parameter_type
            )

        # the parameter type is not a resource. We match the parameter's name with
        # the module's resource names.

        if name in self._resources_by_name:
            provider_resource = self._resources_by_name[name]
            self._ensure_parameter_type_satisfies_resource_type(
                parameter_type, provider_resource, target, name
            )
            return provider_resource
        elif name in self.module:
            module_resource = self.module[name]
            self._ensure_parameter_type_satisfies_resource_type(
                parameter_type, module_resource, target, name
            )
            return module_resource
        else:
            raise ProviderMethodParameterUnrelatedName(
                self, target, method, parameter_name=name
            )

    def _ensure_parameter_type_satisfies_resource_type(
        self,
        parameter_type: type,
        resource: ResourceTypes[Any],
        target: ResourceTypes[Any],
        parameter_name: str,
    ) -> None:
        if not issubclass(resource.type, parameter_type):
            raise ProviderMethodParameterResourceTypeMismatch(
                self,
                target,
                parameter_name=parameter_name,
                refers_to=resource,
                mismatched_type=parameter_type,
            )

    def _get_provider_method(self, resource: ResourceTypes[T]) -> ProviderMethod[T]:
        self._ensure_related_resource(resource)
        target_resource = (
            resource.overrides if type(resource) is OverridingResource else resource
        )
        provider_method = self._provider_methods_by_resource[target_resource]
        return provider_method

    def _list_provider_methods(self) -> Iterable[ProviderMethod[Any]]:
        return self._provider_methods_by_resource.values()

    def _collect_resources(
        self,
        dct: dict[str, Any],
        annotations: dict[str, Any],
        base_provider: ProviderType,
    ) -> None:
        for name, candidate in dct.items():
            if name.startswith("_"):
                continue
            candidate_type = type(candidate)
            if candidate_type is PrivateResource:
                if candidate.is_bound:
                    raise CannotUseExistingProviderResource(self, name, candidate)
                candidate.bind(name=name, provider=self)
                if name in self.module:
                    raise PrivateResourceCannotOccludeModuleResource(self, candidate)
                self._add_resource(candidate)
            elif candidate_type is OverridingResource:
                if name not in self.module:
                    raise OverridingResourceNameDoesntMatchModuleResource(
                        candidate.type, name, self, self.module
                    )
                candidate.bind(name=name, provider=self, overrides=self.module[name])
                self._add_resource(candidate)
            elif candidate_type is ModuleResource:
                raise CannotDefinePublicResourceInProvider(self, name, candidate.type)
            elif isinstance(candidate, type):
                if name in self.module:
                    overrides = self.module[name]
                    overriding_resource: OverridingResource[
                        Any
                    ] = OverridingResource.make_bound(
                        t=candidate,  # pyright: ignore
                        name=name,
                        provider=self,
                        overrides=overrides,
                    )
                    if not issubclass(candidate, overrides.type):
                        raise OverridingResourceIncompatibleType(overriding_resource)
                    self._add_resource(overriding_resource)
                else:
                    private_resource: PrivateResource[Any] = PrivateResource.make_bound(
                        t=candidate, name=name, provider=self  # pyright: ignore
                    )
                    self._add_resource(private_resource)

        for base_resource in base_provider._list_resources():
            existing = self._resources_by_name.get(base_resource.name)
            if existing is not None:
                if not issubclass(existing.type, base_resource.type):
                    raise IncompatibleResourceTypeForInheritedResource(
                        self,
                        existing,
                        base_provider=base_provider,
                        base_resource=base_resource,
                    )
            else:
                self._add_resource(base_resource.bound_to_sub_provider(self))

        for name, annotation in annotations.items():
            if name.startswith("_") or name in self._resources_by_name:
                continue
            t = type(annotation)
            if t is ModuleResource:
                raise InvalidModuleResourceAnnotationInProvider(self, name, annotation)
            elif t is PrivateResource:
                raise InvalidPrivateResourceAnnotationInProvider(self, name, annotation)
            elif t is OverridingResource:
                raise InvalidOverridingResourceAnnotationInProvider(
                    self, name, annotation
                )
            if isinstance(annotation, type):
                raise InvalidAttributeAnnotationInProvider(self, name, annotation)

    def _add_resource(
        self, resource: OverridingResource[Any] | PrivateResource[Any]
    ) -> None:
        self._resources_by_name[resource.name] = resource
        self._resources.add(resource)
        setattr(self, resource.name, resource)

    def _list_resources(
        self,
    ) -> Iterable[OverridingResource[Any] | PrivateResource[Any]]:
        return self._resources

    def _add_provider_method(self, provider_method: ProviderMethod[Any]) -> None:
        self._provider_methods_by_resource[provider_method.resource] = provider_method

    def _ensure_related_resource(self, resource: ResourceTypes[Any]) -> None:
        resource_type = type(resource)
        if resource_type is ModuleResource:
            if cast(ModuleResource[Any], resource) not in self.module:
                raise UnrelatedResource(self, resource)
        elif resource_type is PrivateResource or resource_type is OverridingResource:
            if resource not in self._resources:
                raise UnrelatedResource(self, resource)
        else:
            raise TypeError()


@dataclass
class ProviderMethod(Generic[T]):
    method: Callable[..., T]
    provider: ProviderType
    resource: ResourceTypes[Any]
    dependencies: dict[str, ResourceTypes[Any]]


M = TypeVar("M")


class Provider(metaclass=ProviderType):
    def __init_subclass__(cls, *, module: Optional[ModuleType] = None) -> None:
        pass
