import sys
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Final, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView
from django.views.generic.edit import FormView

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    STATEMENT_RECONCILIATION_PAGE_SIZE,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.forms import CategoryForm
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.forms import (
    BankStatementUploadForm,
    RepaymentTransferLinkForm,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.protocols.services import (
    BankStatementImportServiceProtocol,
    BankStatementReconciliationServiceProtocol,
    StatementMarkupServiceProtocol,
    StatementRowLinkServiceProtocol,
)
from hasta_la_vista_money.users.services.bank_statement import (
    RosDorBankRowKind,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    InvalidReconciliationDecisionError,
    ReconciliationDecisionConflictError,
    ReconciliationExpiredError,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.services.statement_markup import (
    REFUND_CATEGORY_NAME,
    StatementMarkupConflictError,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


logger = structlog.get_logger(__name__)

TRANSFER_ROW_KINDS: Final = frozenset(
    {RosDorBankRowKind.OWN_C2C, RosDorBankRowKind.UNKNOWN},
)

ROW_KIND_LABELS: Final[dict[str, Any]] = {
    RosDorBankRowKind.CARD: _('Оплата картой'),
    RosDorBankRowKind.CANCEL: _('Отмена'),
    RosDorBankRowKind.OWN_C2C: _('Перевод между своими счетами'),
    RosDorBankRowKind.C2C: _('Перевод по СБП'),
    RosDorBankRowKind.C2B: _('Оплата по СБП'),
    RosDorBankRowKind.UNKNOWN: _('Прочее'),
}


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.users.views']


def _import_service(
    request: HttpRequest,
) -> BankStatementImportServiceProtocol:
    """Resolve statement import through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'BankStatementImportServiceProtocol',
        request_with_container.container.users.bank_statement_import_service(),
    )


def _reconciliation_service(
    request: HttpRequest,
) -> BankStatementReconciliationServiceProtocol:
    """Resolve statement reconciliation through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'BankStatementReconciliationServiceProtocol',
        request_with_container.container.users.bank_statement_reconciliation_service(),
    )


def _markup_service(request: HttpRequest) -> StatementMarkupServiceProtocol:
    """Resolve statement row markup through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'StatementMarkupServiceProtocol',
        request_with_container.container.users.statement_markup_service(),
    )


def _link_service(request: HttpRequest) -> StatementRowLinkServiceProtocol:
    """Resolve statement row links through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'StatementRowLinkServiceProtocol',
        request_with_container.container.users.statement_row_link_service(),
    )


class BankStatementUploadView(
    LoginRequiredMixin,
    SuccessMessageMixin[BankStatementUploadForm],
    FormView[BankStatementUploadForm],
):
    """View for uploading bank statements in PDF format."""

    template_name = 'users/bank_statement_upload.html'
    form_class = BankStatementUploadForm
    success_message = _(
        'Банковская выписка загружена и будет обработана в фоновом режиме. '
        'Данные появятся в расходах и доходах в течение нескольких минут.',
    )

    def get_form_kwargs(self) -> dict[str, Any]:
        """Add user to form kwargs."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = cast('User', self.request.user)
        return kwargs

    def form_valid(self, form: BankStatementUploadForm) -> HttpResponse:
        """Process uploaded PDF file asynchronously."""
        user = cast('User', self.request.user)
        pdf_file = form.cleaned_data['pdf_file']
        account = form.cleaned_data['account']
        digest = sha256()
        for chunk in pdf_file.chunks():
            digest.update(chunk)
        pdf_file.seek(0)
        file_hash = digest.hexdigest()

        try:
            logger.info(
                'bank_statement_upload_creating',
                user_id=user.pk,
                account_id=account.pk,
            )

            # Create upload record
            upload, created = BankStatementUpload.objects.get_or_create(
                user=user,
                account=account,
                file_hash=file_hash,
                defaults={
                    'pdf_file': pdf_file,
                    'status': BankStatementUpload.Status.PENDING,
                },
            )

            logger.info(
                'bank_statement_upload_created',
                upload_id=upload.pk,
                user_id=user.pk,
            )

            restart = not created and _import_service(
                self.request,
            ).restart_if_stale(upload)

            if created or restart:
                task_runner = cast(
                    'Any',
                    _views_module().process_bank_statement_task,
                )
                task = task_runner.delay(upload.pk)
                logger.info(
                    'bank_statement_task_enqueued',
                    upload_id=upload.pk,
                    task_id=task.id,
                )
            else:
                messages.warning(
                    self.request,
                    _('Эта выписка уже была загружена.'),
                )

            # Store upload ID in session for progress tracking
            self.request.session['last_upload_id'] = upload.pk

            if created or restart:
                messages.success(self.request, str(self.success_message))

        except Exception as e:
            logger.exception(
                'bank_statement_upload_failed',
                user_id=user.pk,
            )
            messages.error(
                self.request,
                f'Произошла ошибка при загрузке файла: {e!s}',
            )
            return self.form_invalid(form)

        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add extra context data."""
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        context['upload_history'] = _reconciliation_service(
            self.request,
        ).upload_history(user.pk)
        # Check if there's an ongoing upload
        last_upload_id = self.request.session.get('last_upload_id')
        if last_upload_id:
            try:
                upload = BankStatementUpload.objects.get(
                    id=last_upload_id,
                    user=user,
                )
                # Show progress if not completed
                if upload.status in [
                    BankStatementUpload.Status.PENDING,
                    BankStatementUpload.Status.PROCESSING,
                    BankStatementUpload.Status.AWAITING_CONFIRMATION,
                ]:
                    context['show_progress'] = True
                    context['upload_id'] = upload.pk
                elif upload.status in {
                    BankStatementUpload.Status.COMPLETED,
                    BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
                }:
                    # Clear session if completed
                    self.request.session.pop('last_upload_id', None)
            except BankStatementUpload.DoesNotExist:
                # Clear invalid session data
                self.request.session.pop('last_upload_id', None)
        return context

    def get_success_url(self) -> str:
        """Return URL to redirect after successful upload."""
        # Redirect back to the same page to show progress
        return str(reverse_lazy('users:bank_statement_upload'))


class BankStatementUploadStatusView(LoginRequiredMixin, View):
    """View for checking bank statement upload progress."""

    def get(
        self,
        request: HttpRequest,
        upload_id: int,
    ) -> JsonResponse:
        """Get upload status and progress.

        Args:
            request: HTTP request.
            upload_id: ID of the upload to check.

        Returns:
            JSON response with upload status and progress.
        """
        try:
            upload = BankStatementUpload.objects.get(
                id=upload_id,
                user=cast('User', request.user),
                account__user=cast('User', request.user),
            )

            def _decimal_or_none(value: Decimal | None) -> str | None:
                return str(value) if value is not None else None

            return JsonResponse(
                {
                    'status': upload.status,
                    'progress': upload.progress,
                    'total_transactions': upload.total_transactions,
                    'processed_transactions': upload.processed_transactions,
                    'income_count': upload.income_count,
                    'expense_count': upload.expense_count,
                    'skipped_count': upload.skipped_count,
                    'needs_transfer_count': upload.needs_transfer_count,
                    'error_message': upload.error_message,
                    'statement_closing_balance': _decimal_or_none(
                        upload.statement_closing_balance,
                    ),
                    'account_balance_after': _decimal_or_none(
                        upload.account_balance_after,
                    ),
                    'balance_discrepancy': _decimal_or_none(
                        upload.balance_discrepancy,
                    ),
                    'reconciliation_url': (
                        reverse(
                            'users:bank_statement_markup'
                            if _markup_service(request)
                            .pending_rows(upload)
                            .exists()
                            else 'users:bank_statement_reconciliation',
                            args=[upload.pk],
                        )
                        if upload.status
                        == BankStatementUpload.Status.AWAITING_CONFIRMATION
                        else None
                    ),
                    'outcomes': {
                        'imported': upload.imported_count,
                        'linked': upload.linked_count,
                        'awaiting_decision': (upload.awaiting_decision_count),
                        'needs_transfer': upload.needs_transfer_count,
                        'expired': upload.expired_count,
                        'failed': upload.failed_count,
                    },
                },
            )

        except BankStatementUpload.DoesNotExist:
            return JsonResponse(
                {'error': 'Upload not found'},
                status=404,
            )


class BankStatementReconciliationView(
    LoginRequiredMixin,
    DetailView[BankStatementUpload],
):
    template_name = 'users/bank_statement_reconciliation.html'
    context_object_name = 'upload'

    def get_queryset(self) -> QuerySet[BankStatementUpload]:
        user = cast('User', self.request.user)
        return BankStatementUpload.objects.filter(
            user=user,
            account__user=user,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        outcome = self.request.GET.get(
            'outcome',
            BankStatementRow.Decision.PENDING,
        )
        rows = _reconciliation_service(self.request).reconciliation_rows(
            self.object,
            outcome,
        )
        if outcome not in BankStatementRow.Decision.values:
            outcome = BankStatementRow.Decision.PENDING
        context['page_obj'] = Paginator(
            rows,
            STATEMENT_RECONCILIATION_PAGE_SIZE,
        ).get_page(
            self.request.GET.get('page'),
        )
        context['outcome'] = outcome
        context['reconciliation_active'] = (
            timezone.now() < self.object.expires_at
        )
        return context


class BankStatementMarkupView(
    LoginRequiredMixin,
    DetailView[BankStatementUpload],
):
    """Rows of an upload awaiting the user's markup."""

    template_name = 'users/bank_statement_markup.html'
    context_object_name = 'upload'

    def get_queryset(self) -> QuerySet[BankStatementUpload]:
        user = cast('User', self.request.user)
        return BankStatementUpload.objects.filter(
            user=user,
            account__user=user,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        service = _markup_service(self.request)
        categories = {
            transaction_type: service.categories(user, transaction_type)
            for transaction_type in BankStatementRow.TransactionType.values
        }
        accounts = list(
            Account.objects.filter(
                user=user,
                archived_at__isnull=True,
            )
            .exclude(
                pk=self.object.account_id,
            )
            .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
            .order_by('name_account'),
        )
        by_number = {a.account_number: a for a in accounts if a.account_number}
        remembered = service.remembered_categories(self.object)
        duplicates = service.probable_duplicates(self.object)
        page = Paginator(
            service.pending_rows(self.object),
            STATEMENT_RECONCILIATION_PAGE_SIZE,
        ).get_page(self.request.GET.get('page'))
        context['page_obj'] = page
        context['accounts'] = accounts
        context['bulk_categories'] = [
            {'label': label, 'categories': categories[value]}
            for value, label in BankStatementRow.TransactionType.choices
        ]

        context['remembered_count'] = len(remembered)
        context['rows'] = [
            {
                'row': row,
                'can_transfer': row.kind in TRANSFER_ROW_KINDS,
                'transfer_account': (
                    by_number.get(row.counterparty_account)
                    if row.kind == RosDorBankRowKind.OWN_C2C
                    else None
                ),
                'categories': categories.get(row.transaction_type or '', []),
                'remembered_id': remembered.get(row.pk),
                'duplicate': duplicates.get(row.pk),
                'kind_label': ROW_KIND_LABELS.get(row.kind, ''),
                'refund_default': row.kind == RosDorBankRowKind.CANCEL
                and not any(
                    c.name == REFUND_CATEGORY_NAME
                    for c in categories.get(row.transaction_type or '', [])
                ),
            }
            for row in page
        ]
        return context


def _markup_message(reason: str) -> str:
    if reason == 'selection':
        return str(
            _('Выберите строки одного направления, кроме своих переводов.'),
        )
    if reason == 'category':
        return str(_('Выберите категорию подходящего типа.'))
    if reason == 'account':
        return str(_('Выберите свой счёт для перевода.'))
    if reason == 'account_number':
        return str(_('Номер счёта выбранного счёта не подходит.'))
    return str(_('Строка уже размечена или срок разметки истёк.'))


def _skip_marked_rows(request: HttpRequest, upload_id: int) -> set[int]:
    """Skip rows ticked «Пропустить»; every page action submits the marks."""
    marked = {
        int(value)
        for value in request.POST.getlist('row')
        if value.isdigit() and request.POST.get(f'skip-{value}')
    }
    if marked:
        _markup_service(request).decide_many(
            upload_id,
            cast('User', request.user).pk,
            dict.fromkeys(marked, ('skip', None)),
        )
    return marked


class BankStatementMarkupDecisionView(LoginRequiredMixin, View):
    """Apply the decisions chosen for every row of the markup page."""

    def post(self, request: HttpRequest, upload_id: int) -> HttpResponse:
        user = cast('User', request.user)
        get_object_or_404(
            BankStatementUpload,
            pk=upload_id,
            user=user,
            account__user=user,
        )
        decisions: dict[int, tuple[str, int | None]] = {}
        for value in request.POST.getlist('row'):
            if not value.isdigit():
                continue
            account = request.POST.get(f'account-{value}', '')
            category = request.POST.get(f'category-{value}', '')
            if request.POST.get(f'skip-{value}'):
                decisions[int(value)] = ('skip', None)
            elif account.isdigit():
                decisions[int(value)] = ('transfer', int(account))
            elif category == 'refund':
                decisions[int(value)] = ('post', None)
            elif category.isdigit():
                decisions[int(value)] = ('post', int(category))
        if not decisions:
            messages.error(
                request,
                _('Выберите категорию хотя бы для одной строки.'),
            )
        else:
            decided, failed = _markup_service(request).decide_many(
                upload_id,
                user.pk,
                decisions,
            )
            if decided:
                messages.success(
                    request,
                    _('Размечено строк: %(count)s') % {'count': decided},
                )
            if failed:
                messages.error(
                    request,
                    _('Не удалось разметить строк: %(count)s')
                    % {'count': failed},
                )
        return redirect(
            reverse('users:bank_statement_markup', args=[upload_id]),
        )


class BankStatementMarkupBulkView(LoginRequiredMixin, View):
    """Post the selected rows of one direction with one category."""

    def post(self, request: HttpRequest, upload_id: int) -> HttpResponse:
        user = cast('User', request.user)
        get_object_or_404(
            BankStatementUpload,
            pk=upload_id,
            user=user,
            account__user=user,
        )
        skipped = _skip_marked_rows(request, upload_id)
        row_ids = [
            int(value)
            for value in request.POST.getlist('rows')
            if value.isdigit() and int(value) not in skipped
        ]
        if skipped and not row_ids:
            return redirect(
                reverse('users:bank_statement_markup', args=[upload_id]),
            )
        category = request.POST.get('category', '')
        try:
            _markup_service(request).post_many(
                list(
                    BankStatementRow.objects.filter(
                        pk__in=row_ids,
                        upload_id=upload_id,
                    ).values_list('pk', flat=True),
                ),
                user.pk,
                int(category) if category.isdigit() else None,
            )
        except StatementMarkupConflictError as error:
            messages.error(
                request,
                _markup_message(str(error)),
            )
        except ValidationError:
            messages.error(request, _('Не удалось провести строки.'))
        return redirect(
            reverse('users:bank_statement_markup', args=[upload_id]),
        )


class BankStatementMarkupRememberedView(LoginRequiredMixin, View):
    """Post every row of the upload with a remembered category."""

    def post(self, request: HttpRequest, upload_id: int) -> HttpResponse:
        user = cast('User', request.user)
        get_object_or_404(
            BankStatementUpload,
            pk=upload_id,
            user=user,
            account__user=user,
        )
        _skip_marked_rows(request, upload_id)
        posted, skipped = _markup_service(request).post_remembered(
            upload_id,
            user.pk,
        )
        messages.success(
            request,
            _('Проведено строк: %(count)s') % {'count': posted},
        )
        if skipped:
            messages.error(
                request,
                _('Не удалось провести строк: %(count)s') % {'count': skipped},
            )
        return redirect(
            reverse('users:bank_statement_markup', args=[upload_id]),
        )


class BankStatementMarkupCategoryView(LoginRequiredMixin, View):
    """HTMX modal creating a category of the row type."""

    modal_template = 'users/partials/statement_category_modal.html'
    created_template = 'users/partials/statement_category_created.html'

    def get(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = self._row(request, upload_id, row_id)
        if 'close' in request.GET:
            return HttpResponse()
        return self._modal(
            request,
            row,
            CategoryForm(
                **self._form_kwargs(cast('User', request.user), row),
            ),
        )

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = self._row(request, upload_id, row_id)
        user = cast('User', request.user)
        data = request.POST.copy()
        data['type'] = row.transaction_type or ''
        form = CategoryForm(data, **self._form_kwargs(user, row))
        if not form.is_valid():
            return self._modal(request, row, form)
        request_with_container = cast('RequestWithContainer', request)
        category_service = (
            request_with_container.container.transactions.category_service()
        )
        try:
            with transaction.atomic():
                category = category_service.create_category(user, form)
        except IntegrityError:
            form.add_error('name', _('Такая категория уже существует.'))
            return self._modal(request, row, form)
        return render(
            request,
            self.created_template,
            {'category': category, 'row': row},
        )

    @staticmethod
    def _row(
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> BankStatementRow:
        user = cast('User', request.user)
        row = get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=user,
            upload__account__user=user,
        )
        if row.transaction_type not in BankStatementRow.TransactionType.values:
            raise Http404
        return row

    @staticmethod
    def _form_kwargs(user: User, row: BankStatementRow) -> dict[str, Any]:
        return {
            'initial': {'type': row.transaction_type},
            'category_queryset': Category.objects.filter(
                user=user,
                type=row.transaction_type,
                system_kind='',
            ),
        }

    def _modal(
        self,
        request: HttpRequest,
        row: BankStatementRow,
        form: CategoryForm,
    ) -> HttpResponse:
        return render(request, self.modal_template, {'form': form, 'row': row})


class BankStatementReconciliationDecisionView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=request.user,
            upload__account__user=request.user,
        )
        try:
            _reconciliation_service(request).decide(
                row.pk,
                request.POST.get('decision', ''),
                cast('User', request.user).pk,
                self._candidate_id(request),
            )
        except InvalidReconciliationDecisionError as error:
            if str(error) != 'candidate':
                return HttpResponse(status=400)
            messages.error(
                request,
                _('Выберите учтённую операцию перед подтверждением.'),
            )
            return redirect(
                reverse(
                    'users:bank_statement_reconciliation',
                    args=[upload_id],
                ),
            )
        except ReconciliationDecisionConflictError:
            return HttpResponse(status=409)
        except ReconciliationExpiredError:
            return HttpResponse(status=410)
        except StaleStatementCandidateError:
            return self._stale_response(request, row)
        return redirect(
            reverse(
                'users:bank_statement_reconciliation',
                args=[upload_id],
            ),
        )

    def _candidate_id(self, request: HttpRequest) -> int | None:
        value = request.POST.get('candidate')
        return int(value) if value and value.isdigit() else None

    def _stale_response(
        self,
        request: HttpRequest,
        row: BankStatementRow,
    ) -> JsonResponse:
        candidates = _reconciliation_service(request).current_candidates(row)
        return JsonResponse(
            {'candidates': list(candidates.values_list('pk', flat=True))},
            status=409,
        )


class BankStatementReconciliationBulkView(LoginRequiredMixin, View):
    """Apply one reconciliation decision to selected rows independently."""

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
    ) -> JsonResponse:
        """Return a separate outcome for every selected statement row."""
        upload = get_object_or_404(
            BankStatementUpload,
            pk=upload_id,
            user=request.user,
            account__user=request.user,
        )
        decision = request.POST.get('decision', '')
        if (
            decision == BankStatementRow.Decision.NEW
            and request.POST.get('confirm_risk') != 'true'
        ):
            return JsonResponse(
                {'error': 'confirmation_required'},
                status=400,
            )
        row_ids = [
            int(value)
            for value in request.POST.getlist('rows')
            if value.isdigit()
        ]
        results = _reconciliation_service(request).bulk_decide(
            row_ids,
            decision,
            cast('User', request.user).pk,
            upload_id,
        )
        upload.refresh_from_db(
            fields=[
                'imported_count',
                'linked_count',
                'awaiting_decision_count',
                'needs_transfer_count',
                'expired_count',
                'failed_count',
            ],
        )
        return JsonResponse(
            {
                'results': [result.as_dict() for result in results],
                'outcomes': {
                    'imported': upload.imported_count,
                    'linked': upload.linked_count,
                    'awaiting_decision': upload.awaiting_decision_count,
                    'needs_transfer': upload.needs_transfer_count,
                    'expired': upload.expired_count,
                    'failed': upload.failed_count,
                },
            },
        )


class BankStatementReconciliationRevisionView(LoginRequiredMixin, View):
    """Revise a linked statement row to a newly imported transaction."""

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        """Apply an owner-authorized linked-to-new revision."""
        get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=request.user,
            upload__account__user=request.user,
        )
        try:
            _reconciliation_service(request).revise_linked_to_new(
                row_id,
                cast('User', request.user).pk,
            )
        except ReconciliationExpiredError:
            return HttpResponse(status=410)
        except ReconciliationDecisionConflictError:
            return HttpResponse(status=409)
        return redirect(
            reverse(
                'users:bank_statement_reconciliation',
                args=[upload_id],
            ),
        )


class BankStatementPendingTransferDismissView(LoginRequiredMixin, View):
    """Close an unperformed repayment row without creating a movement."""

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        """Mark a pending repayment as not a repayment."""
        get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=request.user,
            upload__account__user=request.user,
        )
        try:
            _reconciliation_service(request).mark_not_payment(
                row_id,
                cast('User', request.user).pk,
            )
        except ReconciliationExpiredError:
            return HttpResponse(status=410)
        except ReconciliationDecisionConflictError:
            return HttpResponse(status=409)
        return redirect('finance_account:list')


class BankStatementPendingTransferLinkView(LoginRequiredMixin, View):
    """Close an unperformed repayment row by a recorded transfer."""

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        """Link the pending repayment to the transfer the owner picked."""
        get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=request.user,
            upload__account__user=request.user,
        )
        form = RepaymentTransferLinkForm(request.POST)
        if not form.is_valid():
            return self._reject(request)
        try:
            _link_service(request).link_repayment(
                row_id,
                form.cleaned_data['transfer'],
                cast('User', request.user).pk,
            )
        except BankStatementRow.DoesNotExist as error:
            raise Http404 from error
        except ReconciliationDecisionConflictError:
            return HttpResponse(status=409)
        except StaleStatementCandidateError:
            return self._reject(request)
        messages.success(request, _('Погашение связано с переводом.'))
        return redirect('finance_account:list')

    @staticmethod
    def _reject(request: HttpRequest) -> HttpResponse:
        messages.error(
            request,
            _('Перевод не подходит для этой строки выписки.'),
        )
        return redirect('finance_account:list')
