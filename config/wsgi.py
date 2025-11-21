"""
WSGI config for hasta_la_vista_money project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from config.containers import ApplicationContainer

os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    'config.django.base',
)

application = get_wsgi_application()

container = ApplicationContainer()
container.wire(
    modules=[
        'hasta_la_vista_money.expense.services.expense_services',
        'hasta_la_vista_money.expense.views',
        'hasta_la_vista_money.loan.services.loan_calculation',
        'hasta_la_vista_money.loan.views',
        'hasta_la_vista_money.receipts.services.receipt_creator',
        'hasta_la_vista_money.receipts.services.receipt_import',
        'hasta_la_vista_money.receipts.services.receipt_updater',
        'hasta_la_vista_money.users.services.detailed_statistics',
        'hasta_la_vista_money.finance_account.models',
    ],
)
