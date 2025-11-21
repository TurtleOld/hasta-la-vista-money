from dependency_injector import containers, providers

from hasta_la_vista_money.expense.services.expense_services import (
    ExpenseCategoryService,
    ExpenseService,
    ReceiptExpenseService,
)


class ExpenseContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    expense_service = providers.Factory(
        ExpenseService,
        account_service=core.account_service,
        receipt_expense_service_factory=receipt_expense_service.provider,
    )
    expense_category_service = providers.Factory(ExpenseCategoryService)
    receipt_expense_service = providers.Factory(ReceiptExpenseService)
