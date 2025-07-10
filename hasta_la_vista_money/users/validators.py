def validate_username_unique(value: str) -> None:
    """
    Validator to ensure the username is unique.
    Raise ValidationError if not unique.
    """
    # from .models import User
    # if User.objects.filter(username=value).exists():
    #     raise ValidationError(_("Пользователь с таким именем уже существует."))
    pass


# Добавляйте другие валидаторы по мере необходимости.
