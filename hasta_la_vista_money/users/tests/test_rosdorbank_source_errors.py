"""RosDorBank source positions and visible parse errors.

Synthetic ``_PdfLine`` input only: no real statements, no PDF fixtures.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    StatementParseResult,
    _PdfLine,
    _RosDorBankParser,
    _RosDorBankRow,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
    ReconciliationExpiredError,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)

NUMBER_X = (10.0, 40.0)
BODY_X = (100.0, 300.0)
DEBIT_X = (500.0, 560.0)
CREDIT_X = (610.0, 680.0)
HEADER = 'Выписка по счету 40817810000000000001 с 01.03.2026 по 03.03.2026'


def _line(
    top: float,
    text: str,
    x: tuple[float, float] = BODY_X,
    *,
    page: int = 0,
) -> _PdfLine:
    return _PdfLine(page=page, top=top, x0=x[0], x1=x[1], text=text)


def _lines(*blocks: str) -> list[_PdfLine]:
    """Build synthetic parser lines from compact row specifications.

    Each block starts with ``date=DD.MM.YYYY`` or a row given as
    ``number|amount|credit|body``; ``-`` means the field is absent.
    A ``nobik:`` prefix builds the same row without its ``БИК:`` line.
    """
    result = [_line(0.0, HEADER)]
    result.extend(
        _line(1.0, text, x)
        for text, x in (
            ('№', NUMBER_X),
            ('Контрагент/Операция', BODY_X),
            ('Списание', DEBIT_X),
            ('Зачисление', CREDIT_X),
        )
    )
    top = 10.0
    for block in blocks:
        if block.startswith('date='):
            result.append(_line(top, block.removeprefix('date=')))
            top += 10
            continue
        if block.startswith('total='):
            label, amount = block.removeprefix('total=').split('|')
            result.append(_line(top, label))
            result.append(_line(top, amount, DEBIT_X))
            top += 10
            continue
        has_bik = not block.startswith('nobik:')
        number, amount, credit, body = block.removeprefix('nobik:').split('|')
        if number != '-':
            result.append(_line(top, number, NUMBER_X))
        top += 2
        if has_bik:
            result.append(
                _line(top, 'БИК: 044525000 р/с: 40817810000000000001'),
            )
        for body_line in body.split('~'):
            top += 2
            result.append(_line(top, body_line))
        if amount != '-':
            result.append(
                _line(top, amount, CREDIT_X if credit == '1' else DEBIT_X),
            )
        top += 10
    return result


class _SyntheticRosDorParser(_RosDorBankParser):
    """RosDorBank parser fed with synthetic lines instead of a PDF."""

    def __init__(self, lines: list[_PdfLine]) -> None:
        self.pdf_path = Path('/synthetic/statement.pdf')
        self._synthetic_lines = lines

    def _read_lines(self) -> list[_PdfLine]:
        return self._synthetic_lines


def _body(label: str) -> str:
    return f'ИНН: 7700000000~Оплата товаров~Владелец устройства: {label}'


def _parsed(*blocks: str) -> StatementParseResult:
    return _SyntheticRosDorParser(_lines(*blocks)).parse()


class RosDorBankSourcePositionTest(SimpleTestCase):
    def test_malformed_row_keeps_source_position(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            '1|350.00|0|PMP SHOP',
            '2|-|0|PMP BROKEN',
            '3|120.00|0|PMP OTHER',
        )

        self.assertEqual(len(result.transactions), 3)
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1, 2],
        )
        broken = result.transactions[1]
        self.assertEqual(broken['parse_error_code'], 'missing_amount')
        self.assertIsNone(broken['amount'])
        self.assertEqual(broken['date'].date(), date(2026, 3, 1))
        self.assertEqual(result.transactions[0]['amount'], Decimal('-350.00'))
        self.assertEqual(result.transactions[2]['amount'], Decimal('-120.00'))

    def test_parser_fix_keeps_positions(self) -> None:
        broken = _parsed(
            'date=01.03.2026',
            '1|350.00|0|PMP SHOP',
            '2|-|0|PMP BROKEN',
            '3|120.00|0|PMP OTHER',
        )
        fixed = _parsed(
            'date=01.03.2026',
            '1|350.00|0|PMP SHOP',
            '2|80.00|0|PMP BROKEN',
            '3|120.00|0|PMP OTHER',
        )

        self.assertEqual(
            [row['row_position'] for row in fixed.transactions],
            [row['row_position'] for row in broken.transactions],
        )
        self.assertEqual(fixed.transactions[1]['amount'], Decimal('-80.00'))
        self.assertEqual(fixed.transactions[1]['parse_error_code'], '')

    def test_unknown_date_amount_and_direction_stay_none(self) -> None:
        result = _parsed(
            '-|-|-|Строка без реквизитов',
            'total=Обороты|0.00',
            'date=02.03.2026',
            '1|100.00|0|PMP SHOP',
        )

        broken = result.transactions[0]
        self.assertIsNone(broken['date'])
        self.assertIsNone(broken['amount'])
        self.assertEqual(broken['date_precision'], 'unknown')
        self.assertEqual(broken['parse_error_code'], 'missing_date')
        self.assertEqual(result.transactions[1]['date_precision'], 'day')

    def test_headers_and_totals_are_not_operations(self) -> None:
        result = _parsed(
            'total=Входящий остаток:|1 000.00',
            'date=01.03.2026',
            '1|350.00|0|PMP SHOP',
            'total=Обороты|350.00',
            'total=Исходящий остаток:|56 000.00',
        )

        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.closing_balance, Decimal('56000.00'))

    def test_missing_header_is_upload_error(self) -> None:
        parser = _SyntheticRosDorParser(
            [_line(0.0, 'Строка 100.00', DEBIT_X)],
        )

        with self.assertRaises(BankStatementParseError):
            parser.parse()

    def test_repeated_representations_are_not_dropped(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            '7|350.00|0|PMP SHOP',
            '7|350.00|0|PMP SHOP',
        )

        self.assertEqual(len(result.transactions), 2)
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1],
        )

    def test_operation_without_bik_keeps_its_own_fields(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP SHOP")}',
            f'nobik:2|80.00|0|{_body("PMP NO BIK")}',
            f'3|120.00|0|{_body("PMP OTHER")}',
        )

        self.assertEqual(len(result.transactions), 3)
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1, 2],
        )
        first, broken, last = result.transactions
        self.assertEqual(first['source_ref'], '1-01.03.2026')
        self.assertEqual(first['amount'], Decimal('-350.00'))
        self.assertEqual(first['description'], 'PMP SHOP')
        self.assertEqual(first['parse_error_code'], '')
        self.assertEqual(broken['source_ref'], '2-01.03.2026')
        self.assertEqual(broken['amount'], Decimal('-80.00'))
        self.assertEqual(broken['description'], 'PMP NO BIK')
        self.assertEqual(broken['parse_error_code'], 'missing_operation')
        self.assertEqual(last['source_ref'], '3-01.03.2026')
        self.assertEqual(last['amount'], Decimal('-120.00'))
        self.assertEqual(last['description'], 'PMP OTHER')
        self.assertEqual(last['parse_error_code'], '')

    def test_operation_without_number_does_not_take_next_number(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            f'-|80.00|0|{_body("PMP NO NUMBER")}',
            f'2|120.00|0|{_body("PMP VALID")}',
        )

        self.assertEqual(len(result.transactions), 2)
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1],
        )
        broken, valid = result.transactions
        self.assertIsNone(broken['source_ref'])
        self.assertEqual(broken['parse_error_code'], 'missing_number')
        self.assertEqual(broken['amount'], Decimal('-80.00'))
        self.assertEqual(broken['transaction_type'], 'expense')
        self.assertEqual(broken['description'], 'PMP NO NUMBER')
        self.assertEqual(broken['date'].date(), date(2026, 3, 1))
        self.assertEqual(valid['source_ref'], '2-01.03.2026')
        self.assertEqual(valid['parse_error_code'], '')
        self.assertEqual(valid['amount'], Decimal('-120.00'))
        self.assertEqual(valid['transaction_type'], 'expense')
        self.assertEqual(valid['description'], 'PMP VALID')
        self.assertEqual(valid['date'].date(), date(2026, 3, 1))

    def test_missing_number_fix_keeps_positions_and_neighbours(self) -> None:
        broken = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP FIRST")}',
            f'-|80.00|0|{_body("PMP NO NUMBER")}',
            f'3|120.00|1|{_body("PMP LAST")}',
        )
        fixed = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP FIRST")}',
            f'2|80.00|0|{_body("PMP NO NUMBER")}',
            f'3|120.00|1|{_body("PMP LAST")}',
        )

        self.assertEqual(
            [row['row_position'] for row in fixed.transactions],
            [row['row_position'] for row in broken.transactions],
        )
        self.assertEqual(fixed.transactions[1]['parse_error_code'], '')
        self.assertEqual(
            fixed.transactions[1]['source_ref'],
            '2-01.03.2026',
        )
        for index in (0, 2):
            self.assertEqual(
                fixed.transactions[index],
                broken.transactions[index],
            )

    def test_valid_rows_keep_their_numbers_in_order(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP FIRST")}',
            f'2|80.00|0|{_body("PMP SECOND")}',
            f'3|120.00|1|{_body("PMP THIRD")}',
        )

        self.assertEqual(
            [row['source_ref'] for row in result.transactions],
            ['1-01.03.2026', '2-01.03.2026', '3-01.03.2026'],
        )
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1, 2],
        )
        self.assertEqual(
            [row['amount'] for row in result.transactions],
            [Decimal('-350.00'), Decimal('-80.00'), Decimal('120.00')],
        )
        self.assertEqual(
            [row['description'] for row in result.transactions],
            ['PMP FIRST', 'PMP SECOND', 'PMP THIRD'],
        )

    def test_row_continues_across_page_without_losing_its_number(self) -> None:
        lines = [
            _line(0.0, HEADER),
            _line(1.0, '№', NUMBER_X),
            _line(1.0, 'Контрагент/Операция', BODY_X),
            _line(1.0, 'Списание', DEBIT_X),
            _line(1.0, 'Зачисление', CREDIT_X),
            _line(10.0, '01.03.2026'),
            _line(20.0, '1', NUMBER_X),
            _line(22.0, 'БИК: 044500001 р/с: 40817810000000000001'),
            _line(24.0, 'ИНН: 0 PMP FIRST'),
            _line(24.0, '350.00', DEBIT_X),
            _line(30.0, 'БИК: 044500001 р/с: 40817810000000000001'),
            _line(10.0, '2', NUMBER_X, page=1),
            _line(10.0, '120.00', CREDIT_X, page=1),
            _line(12.0, 'ИНН: 0 PMP SECOND', page=1),
        ]
        result = _SyntheticRosDorParser(lines).parse()

        self.assertEqual(
            [row['source_ref'] for row in result.transactions],
            ['1-01.03.2026', '2-01.03.2026'],
        )
        self.assertEqual(
            [row['row_position'] for row in result.transactions],
            [0, 1],
        )
        self.assertEqual(
            [row['amount'] for row in result.transactions],
            [Decimal('-350.00'), Decimal('120.00')],
        )

    def test_missing_bik_fix_keeps_positions_and_neighbours(self) -> None:
        broken = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP SHOP")}',
            f'nobik:2|80.00|0|{_body("PMP NO BIK")}',
            f'3|120.00|0|{_body("PMP OTHER")}',
        )
        fixed = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP SHOP")}',
            f'2|80.00|0|{_body("PMP NO BIK")}',
            f'3|120.00|0|{_body("PMP OTHER")}',
        )

        self.assertEqual(
            [row['row_position'] for row in fixed.transactions],
            [row['row_position'] for row in broken.transactions],
        )
        self.assertEqual(fixed.transactions[1]['parse_error_code'], '')
        for index in (0, 2):
            self.assertEqual(
                fixed.transactions[index],
                broken.transactions[index],
            )

    def test_invalid_table_day_leaves_rows_unknown_until_next_day(self) -> None:
        result = _parsed(
            'date=31.02.2026',
            f'1|100.00|0|{_body("PMP BAD DAY")}',
            'date=02.03.2026',
            f'2|200.00|0|{_body("PMP GOOD DAY")}',
        )

        self.assertEqual(len(result.transactions), 2)
        broken, fixed = result.transactions
        self.assertIsNone(broken['date'])
        self.assertEqual(broken['date_precision'], 'unknown')
        self.assertEqual(broken['amount'], Decimal('-100.00'))
        self.assertEqual(broken['description'], 'PMP BAD DAY')
        self.assertEqual(broken['parse_error_code'], 'missing_date')
        self.assertEqual(fixed['date'].date(), date(2026, 3, 2))
        self.assertEqual(fixed['date_precision'], 'day')
        self.assertEqual(fixed['amount'], Decimal('-200.00'))
        self.assertEqual(fixed['parse_error_code'], '')

    def test_valid_rows_expose_explicit_transaction_type(self) -> None:
        result = _parsed(
            'date=01.03.2026',
            f'1|350.00|0|{_body("PMP SHOP")}',
            f'2|120.00|1|{_body("PMP REFUND")}',
        )

        expense, income = result.transactions
        self.assertEqual(expense['amount'], Decimal('-350.00'))
        self.assertEqual(expense['transaction_type'], 'expense')
        self.assertEqual(income['amount'], Decimal('120.00'))
        self.assertEqual(income['transaction_type'], 'income')

    def test_known_amount_with_unknown_direction_is_not_lost(self) -> None:
        transaction = _SyntheticRosDorParser([])._build_transaction(
            _RosDorBankRow(
                date=date(2026, 3, 1),
                lines=['БИК: 044525000 р/с: 40817810000000000001', 'PMP SHOP'],
                number='1',
                amount=Decimal('80.00'),
                position=0,
            ),
        )

        self.assertEqual(transaction['amount'], Decimal('80.00'))
        self.assertIsNone(transaction['transaction_type'])
        self.assertEqual(transaction['parse_error_code'], 'missing_direction')

    def test_known_direction_without_amount_is_kept(self) -> None:
        transaction = _SyntheticRosDorParser([])._build_transaction(
            _RosDorBankRow(
                date=date(2026, 3, 1),
                lines=['БИК: 044525000 р/с: 40817810000000000001', 'PMP SHOP'],
                number='1',
                is_credit=False,
                position=0,
            ),
        )

        self.assertIsNone(transaction['amount'])
        self.assertEqual(transaction['transaction_type'], 'expense')
        self.assertEqual(transaction['parse_error_code'], 'missing_amount')


def _synthetic_result(
    *,
    broken: bool,
) -> StatementParseResult:
    valid = {
        'row_position': 0,
        'date': datetime(2026, 3, 1, tzinfo=timezone.get_current_timezone()),
        'date_precision': 'day',
        'amount': Decimal('-350.00'),
        'description': 'PMP SHOP',
        'source_ref': '1-01.03.2026',
        'source': 'rosdorbank',
        'kind': 'card',
        'merchant_key': 'SHOP',
        'counterparty_account': '30232810000000000001',
        'parse_error_code': '',
    }
    errored = {
        'row_position': 1,
        'date': None,
        'date_precision': 'unknown',
        'amount': None,
        'description': 'Строка без реквизитов',
        'source_ref': None,
        'source': 'rosdorbank',
        'kind': 'unknown',
        'merchant_key': '',
        'counterparty_account': '',
        'parse_error_code': 'missing_date',
    }
    fixed = dict(
        errored,
        amount=Decimal('-80.00'),
        parse_error_code='',
        source_ref='2-01.03.2026',
    )
    return StatementParseResult(
        transactions=[valid, fixed if not broken else errored],
        closing_balance=Decimal('56000.00'),
        requires_markup=True,
        bank_code=constants.BANK_CODE_ROSDORBANK,
    )


class RosDorBankErrorImportTest(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.import_service = (
            ApplicationContainer().users.bank_statement_import_service()
        )

    def _upload(self) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'synthetic.pdf',
                b'%PDF-1.4 synthetic statement',
                content_type='application/pdf',
            ),
        )

    def _import(self, upload: BankStatementUpload, *, broken: bool) -> None:
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.BankStatementParser',
        ) as parser_class:
            parser_class.return_value.parse.return_value = _synthetic_result(
                broken=broken,
            )
            generation = self.import_service.capture_generation(upload)
            self.import_service.import_statement(
                upload,
                generation=generation,
            )
            self.import_service.finalize_import(
                upload,
                generation,
                closing_balance=Decimal('56000.00'),
            )

    def _error_row(self, upload: BankStatementUpload) -> BankStatementRow:
        return BankStatementRow.objects.get(
            upload=upload,
            decision=BankStatementRow.Decision.PARSE_ERROR,
        )

    @statement_identity_settings
    def test_partial_error_keeps_rows_and_posts_nothing(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        upload.refresh_from_db()
        self.account.refresh_from_db()

        rows = list(
            BankStatementRow.objects.filter(upload=upload).order_by(
                'source_row_position',
            ),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row.source_row_position for row in rows],
            [0, 1],
        )
        self.assertEqual(
            rows[0].decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(rows[0].date_precision, 'day')
        self.assertEqual(rows[1].amount, None)
        self.assertEqual(rows[1].transaction_type, None)
        self.assertEqual(rows[1].transaction_date, None)
        self.assertEqual(rows[1].parse_error_code, 'missing_date')
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(upload.awaiting_decision_count, 1)
        self.assertIsNone(upload.balance_discrepancy)

    @statement_identity_settings
    def test_rerun_does_not_duplicate_rows_or_money(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        self._import(upload, broken=True)
        self.account.refresh_from_db()

        self.assertEqual(
            BankStatementRow.objects.filter(upload=upload).count(),
            2,
        )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    @statement_identity_settings
    def test_error_row_cannot_be_posted_or_linked(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        error = self._error_row(upload)

        with self.assertRaises(StatementMarkupConflictError):
            ApplicationContainer().users.statement_markup_service().post(
                error.pk,
                self.user.pk,
                None,
            )
        with self.assertRaises(ReconciliationDecisionConflictError):
            container = ApplicationContainer()
            reconciliation = (
                container.users.bank_statement_reconciliation_service()
            )
            reconciliation.decide(
                error.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())

    @statement_identity_settings
    def test_error_row_defer_exclude_and_resume_keep_history(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        error = self._error_row(upload)
        links = ApplicationContainer().users.statement_row_link_service()

        links.defer(error.pk, self.user.pk)
        error.refresh_from_db()
        self.assertEqual(error.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            error.resume_decision,
            BankStatementRow.Decision.PARSE_ERROR,
        )

        links.resume(error.pk, self.user.pk)
        error.refresh_from_db()
        self.assertEqual(error.decision, BankStatementRow.Decision.PARSE_ERROR)

        links.exclude(error.pk, self.user.pk, 'Не операция')
        error.refresh_from_db()
        self.assertEqual(error.decision, BankStatementRow.Decision.EXCLUDED)
        self.assertEqual(error.decision_reason, 'Не операция')
        self.assertTrue(error.decision_audits.exists())

        links.resume(error.pk, self.user.pk)
        error.refresh_from_db()
        self.assertEqual(error.decision, BankStatementRow.Decision.PARSE_ERROR)
        self.assertTrue(error.decision_audits.exists())

    @statement_identity_settings
    def test_error_row_is_visible_with_unknown_placeholders(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[upload.pk],
            ),
            {'outcome': 'parse_error'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Не удалось определить дату')
        self.assertContains(response, 'Дата неизвестна')
        self.assertContains(response, 'Сумма неизвестна')
        self.assertContains(response, 'Направление неизвестно')
        self.assertEqual(len(response.context['page_obj']), 1)

    @statement_identity_settings
    def test_error_row_is_owner_only(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        error = self._error_row(upload)
        stranger = User.objects.create_user(username='stranger')
        links = ApplicationContainer().users.statement_row_link_service()

        with self.assertRaises(BankStatementRow.DoesNotExist):
            links.defer(error.pk, stranger.pk)

        error.refresh_from_db()
        self.assertEqual(error.decision, BankStatementRow.Decision.PARSE_ERROR)

    @statement_identity_settings
    def test_retention_keeps_safe_code_position_and_decision(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        error = self._error_row(upload)
        position = error.source_row_position
        expires_at = upload.expires_at

        retention = (
            ApplicationContainer().users.bank_statement_retention_service()
        )
        self.assertEqual(retention.cleanup_expired(expires_at), 1)

        error.refresh_from_db()
        self.assertIsNone(error.amount)
        self.assertEqual(error.parse_error_code, 'missing_date')
        self.assertEqual(error.source_row_position, position)
        self.assertEqual(error.decision, BankStatementRow.Decision.PARSE_ERROR)
        self.assertIsNotNone(error.data_cleaned_at)

        links = ApplicationContainer().users.statement_row_link_service()
        with self.assertRaises(ReconciliationExpiredError):
            links.defer(error.pk, self.user.pk)

    @statement_identity_settings
    def test_parser_fix_rerun_reuses_source_positions(self) -> None:
        upload = self._upload()
        self._import(upload, broken=True)
        self._import(upload, broken=False)

        rows = list(
            BankStatementRow.objects.filter(upload=upload).order_by(
                'source_row_position',
            ),
        )
        self.assertEqual(
            [row.source_row_position for row in rows],
            [0, 1],
        )
        self.assertFalse(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.PARSE_ERROR,
            ).exists(),
        )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
