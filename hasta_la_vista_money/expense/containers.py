from dependency_injector import containers, providers

from hasta_la_vista_money.expense.protocols.services import (
    ExpenseServiceProtocol,
)
from hasta_la_vista_money.expense.repositories import (
    ExpenseCategoryRepository,
    ExpenseRepository,
)
from hasta_la_vista_money.expense.services.expense_services import (
    ExpenseCategoryService,
    ExpenseService,
    ReceiptExpenseService,
)


class ExpenseContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()
    finance_account = providers.DependenciesContainer()
    receipts = providers.DependenciesContainer()

    expense_repository = providers.Singleton(ExpenseRepository)
    expense_category_repository = providers.Singleton(ExpenseCategoryRepository)

    receipt_expense_service = providers.Factory(
        ReceiptExpenseService,
        expense_category_repository=expense_category_repository,
        receipt_repository=receipts.receipt_repository,
    )
    expense_category_service = providers.Factory(
        ExpenseCategoryService,
        expense_category_repository=expense_category_repository,
    )

    expense_service: providers.Factory[ExpenseServiceProtocol] = (
        providers.Factory(
            ExpenseService,
            account_service=core.account_service,
            account_repository=finance_account.account_repository,
            expense_repository=expense_repository,
            expense_category_repository=expense_category_repository,
            receipt_repository=receipts.receipt_repository,
            receipt_expense_service_factory=receipt_expense_service.provider,
        )
    )
