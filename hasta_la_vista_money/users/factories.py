from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

import factory as _factory
from django.contrib.auth import get_user_model

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserModel
else:
    UserModel = get_user_model()

T_co = TypeVar('T_co', covariant=True)

factory = cast('Any', _factory)


class Factory(Protocol[T_co]):
    def __call__(self, *args: Any, **kwargs: Any) -> T_co: ...
    @classmethod
    def create(cls, *args: Any, **kwargs: Any) -> T_co: ...
    @classmethod
    def build(cls, *args: Any, **kwargs: Any) -> T_co: ...


class UserFactory(_factory.django.DjangoModelFactory[UserModel]):
    class Meta:  # type: ignore[misc]
        model = UserModel

    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@example.com')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True
    is_staff = False
    is_superuser = False
    theme = 'dark'
    password = factory.PostGenerationMethodCall('set_password', 'testpass123')


UserFactoryTyped: Factory[UserModel] = cast('Factory[UserModel]', UserFactory)
