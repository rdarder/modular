from typing import TypeAlias
from unittest import TestCase

from wiring.provider import Provider
from wiring.module import Module
from wiring.module.errors import (
    CannotUseBaseProviderAsDefaultProvider,
    DefaultProviderProvidesToAnotherModule,
    DefaultProviderIsNotAProvider,
    InvalidModuleResourceAnnotationInModule,
    InvalidAttributeAnnotationInModule,
    CannotUseExistingModuleResource,
    ModulesCannotBeInstantiated,
    InvalidPrivateResourceAnnotationInModule,
    InvalidOverridingResourceAnnotationInModule,
    CannotDefinePrivateResourceInModule,
    CannotDefineOverridingResourceInModule,
    ModulesMustInheritDirectlyFromModuleClass,
    InvalidModuleAttribute,
)
from wiring.errors import HelpfulException
from wiring.resource import Resource
from wiring.utils_for_tests import validate_output, TestCaseWithOutputFixtures


class TestModuleResourcesFromTypeAlias(TestCase):
    def test_module_collects_resources_from_implicit_type_aliases(self) -> None:
        class SomeModule(Module):
            a = int

        resources = list(SomeModule)
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertIs(resource, SomeModule.a)
        self.assertEqual(resource.name, "a")
        self.assertEqual(resource.type, int)
        self.assertEqual(resource.module, SomeModule)

    def test_module_collects_resources_from_explicit_type_aliases(self) -> None:
        class SomeModule(Module):
            a: TypeAlias = int

        resources = list(SomeModule)
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertIs(resource, SomeModule.a)
        self.assertEqual(resource.name, "a")
        self.assertEqual(resource.type, int)
        self.assertEqual(resource.module, SomeModule)


class TestModuleResourcesFromResourceInstances(TestCase):
    def test_module_collect_resource_instances_and_binds_them(self) -> None:
        class SomeModule(Module):
            a = Resource(int)

        resources = list(SomeModule)
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertIs(resource, SomeModule.a)
        self.assertEqual(resource.name, "a")
        self.assertEqual(resource.type, int)
        self.assertEqual(resource.module, SomeModule)

    def test_module_fails_on_a_resource_defined_as_another_modules_resource(
        self,
    ) -> None:
        class SomeModule(Module):
            a = Resource(int)

        with self.assertRaises(CannotUseExistingModuleResource) as ctx:

            class AnotherModule(Module):
                b = SomeModule.a

        self.assertEqual(ctx.exception.module.__name__, "AnotherModule")
        self.assertEqual(ctx.exception.name, "b")
        self.assertEqual(ctx.exception.resource.type, int)
        self.assertEqual(ctx.exception.resource.is_bound, True)
        self.assertEqual(ctx.exception.resource.module, SomeModule)
        self.assertEqual(ctx.exception.resource.name, "a")

    def test_module_refuses_definition_of_private_resource_in_it(self) -> None:
        with self.assertRaises(CannotDefinePrivateResourceInModule) as ctx:

            class SomeModule(Module):
                a = Resource(int, private=True)

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.type, int)

    def test_module_refuses_definition_of_overriding_resource_in_it(self) -> None:
        with self.assertRaises(CannotDefineOverridingResourceInModule) as ctx:

            class SomeModule(Module):
                a = Resource(int, override=True)

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.type, int)


class TestModuleResourcesFromAnnotations(TestCase):
    def test_module_fails_on_class_attribute_with_only_type_annotation(self) -> None:
        with self.assertRaises(InvalidAttributeAnnotationInModule) as ctx:

            class SomeModule(Module):
                a: int

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.annotation, int)

    def test_module_fails_on_class_attribute_annotated_with_module_resource_instance(
        self,
    ) -> None:
        with self.assertRaises(InvalidModuleResourceAnnotationInModule) as ctx:

            class SomeModule(Module):
                a: Resource(int)  # type: ignore

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.resource.type, int)
        self.assertEqual(ctx.exception.resource.is_bound, False)

    def test_module_fails_on_class_attribute_annotated_with_provider_resource_instance(
        self,
    ) -> None:
        with self.assertRaises(InvalidPrivateResourceAnnotationInModule) as ctx:

            class SomeModule(Module):
                a: Resource(int, private=True)  # type: ignore

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.resource.type, int)
        self.assertEqual(ctx.exception.resource.is_bound, False)

    def test_module_fails_on_a_resource_annotated_with_an_external_module_resource(
        self,
    ) -> None:
        class SomeModule(Module):
            a = Resource(int)

        with self.assertRaises(InvalidModuleResourceAnnotationInModule) as ctx:

            class AnotherModule(Module):
                b: SomeModule.a  # type: ignore

        self.assertEqual(ctx.exception.module.__name__, "AnotherModule")
        self.assertEqual(ctx.exception.name, "b")
        self.assertEqual(ctx.exception.resource.type, int)
        self.assertEqual(ctx.exception.resource.is_bound, True)
        self.assertEqual(ctx.exception.resource.module, SomeModule)
        self.assertEqual(ctx.exception.resource.name, "a")

    def test_module_fails_on_class_attribute_annotated_with_overriding_resource_instance(
        self,
    ) -> None:
        with self.assertRaises(InvalidOverridingResourceAnnotationInModule) as ctx:

            class SomeModule(Module):
                a: Resource(int, override=True)  # type: ignore

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.resource.type, int)
        self.assertEqual(ctx.exception.resource.is_bound, False)


class TestModuleClassDeclaration(TestCase):
    def test_modules_cannot_be_instantiated(self) -> None:
        class SomeModule(Module):
            pass

        with self.assertRaises(ModulesCannotBeInstantiated) as ctx:
            SomeModule()
        self.assertEqual(ctx.exception.module, SomeModule)

    def test_modules_cannot_be_instantiated_even_if_defining_constructor(self) -> None:
        class SomeModule(Module):
            def __init__(self) -> None:
                pass

        with self.assertRaises(ModulesCannotBeInstantiated) as ctx:
            SomeModule()
        self.assertEqual(ctx.exception.module, SomeModule)

    def test_modules_cannot_be_defined_as_a_subclass_of_another_module(self) -> None:
        class SomeModule(Module):
            pass

        with self.assertRaises(ModulesMustInheritDirectlyFromModuleClass) as ctx:

            class SubModule(SomeModule):
                pass

        self.assertEqual(ctx.exception.module_class_name, "SubModule")
        self.assertEqual(ctx.exception.inherits_from, (SomeModule,))

    def test_module_classes_cannot_have_private_attributes(self) -> None:
        with self.assertRaises(InvalidModuleAttribute) as ctx:

            class SomeModule(Module):
                _something = int

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "_something")
        self.assertEqual(ctx.exception.attribute_value, int)

    def test_module_classes_cannot_have_an_attribute_named_default_provider(
        self,
    ) -> None:
        with self.assertRaises(InvalidModuleAttribute) as ctx:

            class SomeModule(Module):
                default_provider = int

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "default_provider")
        self.assertEqual(ctx.exception.attribute_value, int)

    def test_module_classes_attributes_must_be_types_or_resources(self) -> None:
        with self.assertRaises(InvalidModuleAttribute) as ctx:

            class SomeModule(Module):
                a = 10

        self.assertEqual(ctx.exception.module.__name__, "SomeModule")
        self.assertEqual(ctx.exception.name, "a")
        self.assertEqual(ctx.exception.attribute_value, 10)


class TestModuleDefaultProvider(TestCaseWithOutputFixtures):
    @validate_output
    def test_cant_use_base_provider_as_default_provider(self) -> HelpfulException:
        class SomeModule(Module):
            pass

        with self.assertRaises(CannotUseBaseProviderAsDefaultProvider) as ctx:
            SomeModule.default_provider = Provider

        self.assertEqual(ctx.exception.module, SomeModule)
        return ctx.exception

    @validate_output
    def test_cant_set_a_default_provider_to_one_that_provides_to_another_module(
        self,
    ) -> HelpfulException:
        class SomeModule(Module):
            pass

        class AnotherModule(Module):
            pass

        class AnotherProvider(Provider, module=AnotherModule):
            pass

        with self.assertRaises(DefaultProviderProvidesToAnotherModule) as ctx:
            SomeModule.default_provider = AnotherProvider

        self.assertEqual(ctx.exception.module, SomeModule)
        self.assertEqual(ctx.exception.provider, AnotherProvider)
        self.assertEqual(ctx.exception.provider.module, AnotherModule)
        return ctx.exception

    @validate_output
    def test_cant_set_a_default_provider_to_something_not_a_provider(
        self,
    ) -> HelpfulException:
        class SomeModule(Module):
            pass

        class NotAProvider:
            pass

        with self.assertRaises(DefaultProviderIsNotAProvider) as ctx:
            SomeModule.default_provider = NotAProvider  # type: ignore

        self.assertEqual(ctx.exception.module, SomeModule)
        self.assertEqual(ctx.exception.not_provider, NotAProvider)
        return ctx.exception
