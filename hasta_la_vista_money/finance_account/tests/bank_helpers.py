from hasta_la_vista_money.finance_account.models import Bank


def get_bank_by_code(code: str) -> Bank:
    return Bank.objects.get(code=code)


def get_or_create_bank(code: str, name: str, is_system: bool = False) -> Bank:
    bank, _ = Bank.objects.get_or_create(
        code=code,
        defaults={'name': name, 'is_system': is_system},
    )
    return bank
