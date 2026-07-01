# QR Camera Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a mobile user scan a receipt's FNS QR code with their camera, decoding it client-side and skipping the photo-upload + server-side `pyzbar` decode step entirely.

**Architecture:** A new esbuild-bundled JS module (`jsQR`) reads camera frames into a canvas and decodes the QR in the browser. On success it submits the raw QR string to a new Django view, which validates it, creates a `PendingReceipt` with no image file, and enqueues a new Celery task that reuses the existing FNS-lookup tail of the photo pipeline (skipping only the `QRCodeExtractor.extract` step).

**Tech Stack:** Django (forms/views), Celery (background task), jsQR (npm, bundled via esbuild), Alpine.js (tab/camera UI state), existing FNS integration (`FNSClient`, `fns_mapper`, `fns_qr.parse_fns_qr`).

## Global Constraints

- Camera scan tab is visible only below a 768px viewport width, via a plain CSS media query (this app's `receipts.css` uses custom classes + `@media (max-width: ...)`, not Tailwind utility classes) — no camera-capability detection.
- No preview/confirmation step before submitting a decoded QR — submission is immediate, same asynchronous nature as photo upload (queued, visible in the receipts list once ready).
- QR dedup reuses the existing `PendingReceipt.image_hash` field and `PendingReceiptService.find_duplicate()` unchanged — store `sha256(raw_qr_string)` there. No schema migration.
- Desktop behavior and the AI photo-inference pipeline (`analyze_image_with_ai`) are untouched.
- On camera/permission failure: show an error message and let the user fall back to the file tab — camera is never the only way in.
- Test command: `uv run python manage.py test -v 2`. JS lint: `npm run lint:js` (covers `static/js/pages/**/*.js` automatically). JS build: `npm run build:js`.

---

### Task 1: Split the FNS pipeline so it can start from a raw QR string

**Files:**
- Modify: `hasta_la_vista_money/receipts/tasks.py:158-178` (the `_run_fns_pipeline` function)
- Test: `hasta_la_vista_money/receipts/tests/test_fns_integration.py`

**Interfaces:**
- Produces: `_run_fns_pipeline_from_raw(pending: PendingReceipt, raw_qr: str) -> dict[str, Any]` — the FNS-lookup → mapper → categorize → validate tail, usable by both the existing photo pipeline and the new QR-scan pipeline (Task 2).
- `_run_fns_pipeline(pending: PendingReceipt) -> dict[str, Any]` keeps its existing signature and behavior (extracts QR from the image, then delegates).

This is a pure refactor — no behavior change for the existing photo-upload path. The existing test suite (`ProcessPendingReceiptFNSTests` in `test_fns_integration.py`, `ProcessPendingReceiptTaskTests` in `test_pending_receipt_flow.py`) must keep passing unmodified, since they mock `_run_fns_pipeline` and `QRCodeExtractor.extract` exactly as before.

- [ ] **Step 1: Write the failing test for the new function**

Add to `hasta_la_vista_money/receipts/tests/test_fns_integration.py`, inside the existing `@override_settings(...)` block right after `ProcessPendingReceiptFNSTests` (same decorator, same fixtures):

```python
@override_settings(
    CACHES=TEST_CACHES,
    FNS_INN='123456789012',
    FNS_PASSWORD='password',  # nosec B106: test-only password
    FNS_CLIENT_SECRET='secret',  # nosec B106: test-only secret
    FNS_POLL_INTERVAL_SECONDS=0,
)
class RunFnsPipelineFromRawTests(TestCase):
    """The shared FNS-lookup tail, called directly with a raw QR string."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='raw-qr-user',
            password='pass',  # nosec B106: test-only password
            email='raw-qr@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )

    def test_runs_fns_lookup_without_qr_extraction(self) -> None:
        from hasta_la_vista_money.receipts.tasks import (
            _run_fns_pipeline_from_raw,
        )

        pending = PendingReceipt.objects.create(
            user=self.user,
            account=self.account,
            status=PendingReceiptStatus.PROCESSING,
            image_hash='deadbeef',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks.FNSClient.fetch_receipt',
            return_value=_fns_payload(),
        ) as fetch_mock:
            receipt_data = _run_fns_pipeline_from_raw(
                pending,
                't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
            )

        fetch_mock.assert_called_once_with(
            't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
        )
        self.assertEqual(receipt_data['name_seller'], 'Магазин')
        self.assertIn('_fns_raw', receipt_data)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration.RunFnsPipelineFromRawTests -v 2`
Expected: FAIL — `ImportError` or `AttributeError`, `_run_fns_pipeline_from_raw` does not exist yet.

- [ ] **Step 3: Refactor `_run_fns_pipeline` in `tasks.py`**

Replace the current function (lines 158-178):

```python
def _run_fns_pipeline(pending: PendingReceipt) -> dict[str, Any]:
    """Process a pending receipt through QR -> FNS -> mapper pipeline."""
    with pending.image_file.open('rb') as image_fp:
        qr_data = QRCodeExtractor().extract(image_fp)

    fns_payload = FNSClient().fetch_receipt(qr_data.raw)
    receipt_data = map_fns_receipt_to_receipt_data(fns_payload)
    receipt_data['items'] = ReceiptItemCategoryService().categorize_items(
        user=pending.user,
        items=receipt_data.get('items', []),
    )

    inn = receipt_data.get('inn')
    if inn and not receipt_data.get('retail_place'):
        seller = SellerRepository().find_by_inn(user=pending.user, inn=inn)
        if seller and seller.retail_place not in (None, '', 'Нет данных'):
            receipt_data['retail_place'] = seller.retail_place

    validated = validate_receipt_parse_payload(receipt_data).to_dict()
    validated['_fns_raw'] = fns_payload
    return validated
```

with:

```python
def _run_fns_pipeline_from_raw(
    pending: PendingReceipt,
    raw_qr: str,
) -> dict[str, Any]:
    """Run the FNS lookup -> mapper -> validate tail from a decoded QR string.

    Shared by the photo-upload pipeline (which extracts ``raw_qr`` from the
    image first) and the browser-camera-scan pipeline (which already has
    the decoded string and skips extraction entirely).
    """
    fns_payload = FNSClient().fetch_receipt(raw_qr)
    receipt_data = map_fns_receipt_to_receipt_data(fns_payload)
    receipt_data['items'] = ReceiptItemCategoryService().categorize_items(
        user=pending.user,
        items=receipt_data.get('items', []),
    )

    inn = receipt_data.get('inn')
    if inn and not receipt_data.get('retail_place'):
        seller = SellerRepository().find_by_inn(user=pending.user, inn=inn)
        if seller and seller.retail_place not in (None, '', 'Нет данных'):
            receipt_data['retail_place'] = seller.retail_place

    validated = validate_receipt_parse_payload(receipt_data).to_dict()
    validated['_fns_raw'] = fns_payload
    return validated


def _run_fns_pipeline(pending: PendingReceipt) -> dict[str, Any]:
    """Process a pending receipt through QR -> FNS -> mapper pipeline."""
    with pending.image_file.open('rb') as image_fp:
        qr_data = QRCodeExtractor().extract(image_fp)
    return _run_fns_pipeline_from_raw(pending, qr_data.raw)
```

- [ ] **Step 4: Run the new test, then the full pipeline-related suites**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration.RunFnsPipelineFromRawTests -v 2`
Expected: PASS

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration hasta_la_vista_money.receipts.tests.test_pending_receipt_flow -v 2`
Expected: PASS (all existing tests still green — confirms the refactor changed no behavior)

- [ ] **Step 5: Commit**

```bash
git add hasta_la_vista_money/receipts/tasks.py hasta_la_vista_money/receipts/tests/test_fns_integration.py
git commit -m "refactor: split FNS pipeline tail into _run_fns_pipeline_from_raw"
```

---

### Task 2: Add the `process_pending_receipt_from_qr` Celery task

**Files:**
- Modify: `hasta_la_vista_money/receipts/tasks.py` (add new task + shared finalize helper, after `_run_fns_pipeline`/before `process_pending_receipt`)
- Modify: `hasta_la_vista_money/receipts/views/__init__.py` (export the new task)
- Test: `hasta_la_vista_money/receipts/tests/test_fns_integration.py`

**Interfaces:**
- Consumes: `_run_fns_pipeline_from_raw` (Task 1), `_classify_failure`, `_get_pending_receipt_service` (existing in `tasks.py`).
- Produces: `process_pending_receipt_from_qr(_self: Any, pending_receipt_id: int, raw_qr: str) -> None`, a `@shared_task(name='receipts.process_pending_receipt_from_qr', bind=True, ...)`. Exported from `hasta_la_vista_money.receipts.views` so it can be referenced (and mocked in tests) the same way `process_pending_receipt` is, via `_views_module().process_pending_receipt_from_qr`.

To avoid duplicating the try/classify/mark_failed/mark_ready boilerplate between the two tasks, this task also extracts a shared `_finalize_pipeline` helper and updates `process_pending_receipt` to use it. Behavior of `process_pending_receipt` must not change — verified by re-running its existing test suite unmodified.

- [ ] **Step 1: Write the failing tests**

Add to `hasta_la_vista_money/receipts/tests/test_fns_integration.py`, after `RunFnsPipelineFromRawTests` (Task 1):

```python
@override_settings(
    CACHES=TEST_CACHES,
    FNS_INN='123456789012',
    FNS_PASSWORD='password',  # nosec B106: test-only password
    FNS_CLIENT_SECRET='secret',  # nosec B106: test-only secret
    FNS_POLL_INTERVAL_SECONDS=0,
)
class ProcessPendingReceiptFromQRTests(TestCase):
    """The QR-scan Celery task: no image, no QR extraction step."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='qr-task-user',
            password='pass',  # nosec B106: test-only password
            email='qr-task@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.raw_qr = 't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1'

    def _create_pending(self) -> PendingReceipt:
        return PendingReceipt.objects.create(
            user=self.user,
            account=self.account,
            status=PendingReceiptStatus.PROCESSING,
            image_hash='qr-hash-1',
        )

    def test_task_marks_ready_from_raw_qr(self) -> None:
        from hasta_la_vista_money.receipts.tasks import (
            process_pending_receipt_from_qr,
        )

        pending = self._create_pending()
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks.FNSClient.fetch_receipt',
            return_value=_fns_payload(),
        ):
            process_pending_receipt_from_qr(pending.pk, self.raw_qr)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.READY)
        self.assertEqual(pending.receipt_data['name_seller'], 'Магазин')

    def test_task_marks_failed_on_fns_error(self) -> None:
        from hasta_la_vista_money.receipts.services.fns_client import (
            FNSMalformedResponseError,
        )
        from hasta_la_vista_money.receipts.tasks import (
            process_pending_receipt_from_qr,
        )

        pending = self._create_pending()
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks.FNSClient.fetch_receipt',
            side_effect=FNSMalformedResponseError('bad payload'),
        ):
            process_pending_receipt_from_qr(pending.pk, self.raw_qr)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.FAILED)
        self.assertNotEqual(pending.error_message, '')

    def test_task_noop_when_pending_missing(self) -> None:
        from hasta_la_vista_money.receipts.tasks import (
            process_pending_receipt_from_qr,
        )

        process_pending_receipt_from_qr(999999, self.raw_qr)
        # No exception raised — just logs and returns.
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration.ProcessPendingReceiptFromQRTests -v 2`
Expected: FAIL — `process_pending_receipt_from_qr` does not exist yet.

- [ ] **Step 3: Add the shared finalize helper and the new task in `tasks.py`**

First, add `Callable` to the existing `typing` import at the top of `tasks.py`:

```python
from typing import Any, Callable
```

Then, immediately after the `_run_fns_pipeline` function (end of Task 1's edit) and before `_run_processing_pipeline`, add:

```python
def _finalize_pipeline(
    pending: PendingReceipt,
    pending_receipt_id: int,
    service: PendingReceiptServiceProtocol,
    run_pipeline: Callable[[], dict[str, Any]],
) -> None:
    """Run a pipeline callable and transition the pending receipt.

    Shared tail for both processing tasks: catches pipeline failures,
    classifies them, and marks the pending receipt failed or ready.
    """
    try:
        receipt_data = run_pipeline()
    except Exception as exc:
        event, message = _classify_failure(exc)
        service.mark_failed(
            pending_receipt=pending,
            error_message=message,
        )
        logger.warning(
            event,
            pending_receipt_id=pending_receipt_id,
            error=str(exc),
        )
        return
    service.mark_ready(
        pending_receipt=pending,
        receipt_data=receipt_data,
    )
```

Now replace the body of `process_pending_receipt` (currently lines ~222-260) so it delegates to `_finalize_pipeline`:

```python
def process_pending_receipt(_self: Any, pending_receipt_id: int) -> None:
    """Run inference for a pending receipt and update its state.

    Loads the persisted image, calls ``analyze_image_with_ai`` (which uses the
    local receipt inference service), parses the result and transitions the
    PendingReceipt to ``ready`` or ``failed``.

    Args:
        _self: Bound Celery task instance (unused, present for ``bind=True``).
        pending_receipt_id: Primary key of the PendingReceipt to process.
    """
    try:
        pending = PendingReceipt.objects.select_related('user').get(
            pk=pending_receipt_id,
        )
    except PendingReceipt.DoesNotExist:
        logger.warning(
            'pending_receipt_missing',
            pending_receipt_id=pending_receipt_id,
        )
        return

    service = _get_pending_receipt_service()

    if not pending.image_file:
        service.mark_failed(
            pending_receipt=pending,
            error_message=str(_MISSING_FILE_MESSAGE),
        )
        return

    _finalize_pipeline(
        pending,
        pending_receipt_id,
        service,
        lambda: _run_processing_pipeline(pending),
    )
```

Finally, add the new task directly after `process_pending_receipt` (before `cleanup_stale_pending_receipts`):

```python
@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name='receipts.process_pending_receipt_from_qr',
    autoretry_for=(ConnectionError,),
    max_retries=2,
    retry_backoff=True,
    acks_late=True,
)
def process_pending_receipt_from_qr(
    _self: Any,
    pending_receipt_id: int,
    raw_qr: str,
) -> None:
    """Run the FNS lookup for a pending receipt scanned via browser camera.

    The QR was already decoded client-side, so this task starts straight
    from the FNS lookup — no image, no ``QRCodeExtractor`` step.

    Args:
        _self: Bound Celery task instance (unused, present for ``bind=True``).
        pending_receipt_id: Primary key of the PendingReceipt to process.
        raw_qr: Raw FNS QR string decoded in the browser.
    """
    try:
        pending = PendingReceipt.objects.select_related('user').get(
            pk=pending_receipt_id,
        )
    except PendingReceipt.DoesNotExist:
        logger.warning(
            'pending_receipt_missing',
            pending_receipt_id=pending_receipt_id,
        )
        return

    service = _get_pending_receipt_service()

    _finalize_pipeline(
        pending,
        pending_receipt_id,
        service,
        lambda: _run_fns_pipeline_from_raw(pending, raw_qr),
    )
```

- [ ] **Step 4: Export the task from the views package**

Edit `hasta_la_vista_money/receipts/views/__init__.py` — change the import line:

```python
from hasta_la_vista_money.receipts.tasks import process_pending_receipt
```

to:

```python
from hasta_la_vista_money.receipts.tasks import (
    process_pending_receipt,
    process_pending_receipt_from_qr,
)
```

and add `'process_pending_receipt_from_qr'` to the `__all__` list (alphabetically, next to `'process_pending_receipt'`).

- [ ] **Step 5: Run the new tests, then the full task suite**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration.ProcessPendingReceiptFromQRTests -v 2`
Expected: PASS

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_fns_integration hasta_la_vista_money.receipts.tests.test_pending_receipt_flow -v 2`
Expected: PASS (confirms `process_pending_receipt`'s refactor didn't change its observable behavior)

- [ ] **Step 6: Commit**

```bash
git add hasta_la_vista_money/receipts/tasks.py hasta_la_vista_money/receipts/views/__init__.py hasta_la_vista_money/receipts/tests/test_fns_integration.py
git commit -m "feat: add process_pending_receipt_from_qr Celery task"
```

---

### Task 3: Add `PendingReceiptService.create_processing_job_from_qr`

**Files:**
- Modify: `hasta_la_vista_money/receipts/services/pending_receipt_service.py` (add method after `create_processing_job`, ~line 164)
- Modify: `hasta_la_vista_money/receipts/protocols/services.py` (add matching protocol method)
- Test: `hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py`

**Interfaces:**
- Produces: `PendingReceiptService.create_processing_job_from_qr(*, user: User, account: Account, image_hash: str) -> PendingReceipt` — creates a `PendingReceipt` in `processing` state with `image_file=None`. Reuses the existing `find_duplicate(*, user, image_hash)` for dedup (no changes needed there).

- [ ] **Step 1: Write the failing test**

Add to `hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py`, inside `PendingReceiptServiceHashTests` (after `test_find_duplicate_pending_returns_existing_processing`):

```python
    def test_create_processing_job_from_qr_has_no_image_file(self) -> None:
        pending = self.service.create_processing_job_from_qr(
            user=self.user,
            account=self.account,
            image_hash='a' * 64,
        )

        self.assertFalse(pending.image_file)
        self.assertEqual(pending.image_hash, 'a' * 64)
        self.assertEqual(pending.status, PendingReceiptStatus.PROCESSING)

    def test_create_processing_job_from_qr_is_deduplicated_like_photos(
        self,
    ) -> None:
        image_hash = 'b' * 64
        self.service.create_processing_job_from_qr(
            user=self.user,
            account=self.account,
            image_hash=image_hash,
        )

        match = self.service.find_duplicate(
            user=self.user,
            image_hash=image_hash,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, 'pending')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_pending_receipt_flow.PendingReceiptServiceHashTests -v 2`
Expected: FAIL — `AttributeError: 'PendingReceiptService' object has no attribute 'create_processing_job_from_qr'`

- [ ] **Step 3: Add the method to `PendingReceiptService`**

In `hasta_la_vista_money/receipts/services/pending_receipt_service.py`, add immediately after `create_processing_job` (after its closing `)` around line 163):

```python
    def create_processing_job_from_qr(
        self,
        *,
        user: User,
        account: Account,
        image_hash: str,
    ) -> PendingReceipt:
        """Persist a new PendingReceipt from a browser camera QR scan.

        Unlike ``create_processing_job``, there is no uploaded image: the QR
        was already decoded client-side, so ``image_file`` stays empty and
        ``image_hash`` is the SHA-256 of the raw QR string — reusing the
        same dedup mechanism as photo uploads.

        Args:
            user: Owner of the receipt.
            account: Account that will be charged for the receipt.
            image_hash: SHA-256 hex digest of the raw QR string.

        Returns:
            Newly created PendingReceipt.
        """
        return PendingReceipt.objects.create(
            user=user,
            account=account,
            status=PendingReceiptStatus.PROCESSING,
            image_hash=image_hash,
        )
```

- [ ] **Step 4: Add the matching protocol method**

In `hasta_la_vista_money/receipts/protocols/services.py`, add to `PendingReceiptServiceProtocol`, right after `create_processing_job`:

```python
    def create_processing_job_from_qr(
        self,
        *,
        user: User,
        account: Account,
        image_hash: str,
    ) -> PendingReceipt: ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_pending_receipt_flow.PendingReceiptServiceHashTests -v 2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hasta_la_vista_money/receipts/services/pending_receipt_service.py hasta_la_vista_money/receipts/protocols/services.py hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py
git commit -m "feat: add PendingReceiptService.create_processing_job_from_qr"
```

---

### Task 4: Add `ScanQRForm` and `ScanQRReceiptView`

**Files:**
- Modify: `hasta_la_vista_money/receipts/forms.py` (add `ScanQRForm` after `UploadImageForm`, ~line 562; add `HiddenInput` to the existing `django.forms` import; add `fns_qr` imports)
- Modify: `hasta_la_vista_money/receipts/views/upload.py` (add `ScanQRReceiptView`; add `get_context_data` to both views so the template can render both forms regardless of which view handled the request)
- Modify: `hasta_la_vista_money/receipts/views/__init__.py` (export `ScanQRReceiptView`)
- Modify: `hasta_la_vista_money/receipts/urls.py` (add `scan-qr/` route)
- Test: `hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py`

**Interfaces:**
- Consumes: `parse_fns_qr`, `QRCodeDecodeError` (`fns_qr.py`, unchanged), `PendingReceiptService.create_processing_job_from_qr` (Task 3), `process_pending_receipt_from_qr` (Task 2, accessed via `_views_module()` exactly like `UploadImageView` accesses `process_pending_receipt`).
- Produces: `ScanQRForm` (fields: `account` — `ModelChoiceField`, filtered by user; `qr_raw` — hidden `CharField`, validated via `parse_fns_qr` in `clean_qr_raw`). `ScanQRReceiptView` (`LoginRequiredMixin`, `FormView[ScanQRForm]`, POST-only in practice via `FormView`, template `receipts/upload_image.html`, redirects to `receipts:list` on success with `django.contrib.messages`). URL name `receipts:scan_qr`.
- Context contract for the shared template (Task 6 depends on this): both `UploadImageView` and `ScanQRReceiptView` provide **both** `upload_form` (an `UploadImageForm`) and `scan_form` (a `ScanQRForm`) in context — whichever view handled the request supplies its *bound* form under the matching key; the other key gets a fresh unbound form of the right type. This lets the template always reference `upload_form.account` / `scan_form.account` / `scan_form.qr_raw` regardless of which view rendered the page.

- [ ] **Step 1: Write the failing tests**

Add to `hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py`, after the `UploadImageViewTests` class:

```python
class ScanQRReceiptViewTests(TestCase):
    """The camera-scan view validates the QR, dedups, and enqueues."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='scan-user',
            password='pass',  # nosec B106: test-only password
            email='scan@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.raw_qr = 't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1'

    def test_scan_creates_processing_pending_and_dispatches(self) -> None:
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt_from_qr',
        ) as task_mock:
            task_mock.delay.return_value = mock.Mock(id='qr-task-id-1')
            response = self.client.post(
                reverse('receipts:scan_qr'),
                {'qr_raw': self.raw_qr, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:list'))
        pending = PendingReceipt.objects.get(user=self.user)
        self.assertEqual(pending.status, PendingReceiptStatus.PROCESSING)
        self.assertFalse(pending.image_file)
        self.assertEqual(pending.task_id, 'qr-task-id-1')
        task_mock.delay.assert_called_once_with(pending.pk, self.raw_qr)

    def test_scan_rejects_invalid_qr_string(self) -> None:
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt_from_qr',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:scan_qr'),
                {'qr_raw': 'not-a-fns-qr', 'account': self.account.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            PendingReceipt.objects.filter(user=self.user).exists(),
        )
        task_mock.delay.assert_not_called()

    def test_scan_rejects_duplicate_qr(self) -> None:
        image_hash = hashlib.sha256(self.raw_qr.encode()).hexdigest()
        PendingReceipt.objects.create(
            user=self.user,
            account=self.account,
            status=PendingReceiptStatus.PROCESSING,
            image_hash=image_hash,
        )

        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt_from_qr',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:scan_qr'),
                {'qr_raw': self.raw_qr, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:list'))
        self.assertEqual(
            PendingReceipt.objects.filter(user=self.user).count(),
            1,
        )
        task_mock.delay.assert_not_called()

    def test_scan_requires_login(self) -> None:
        self.client.logout()
        response = self.client.post(
            reverse('receipts:scan_qr'),
            {'qr_raw': self.raw_qr, 'account': self.account.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PendingReceipt.objects.exists())
```

Add `import hashlib` to the top of the test file's import block (alongside the existing `import io`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_pending_receipt_flow.ScanQRReceiptViewTests -v 2`
Expected: FAIL — `NoReverseMatch: Reverse for 'scan_qr' not found`

- [ ] **Step 3: Add `ScanQRForm` to `forms.py`**

In `hasta_la_vista_money/receipts/forms.py`, add `HiddenInput` to the existing `django.forms` import block (it currently imports `CharField, ChoiceField, ClearableFileInput, DateTimeField, DateTimeInput, DecimalField, FileField, Form, ModelChoiceField, ModelForm, NumberInput, Select, TextInput, formset_factory` — add `HiddenInput` to that list, keeping alphabetical order).

Add a new import below the existing `from hasta_la_vista_money.receipts.parsers.date_parser import (...)` block:

```python
from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeDecodeError,
    parse_fns_qr,
)
```

Then add the form class right after `UploadImageForm` (after its `clean_file` method, before `class PendingReceiptReviewForm`):

```python
class ScanQRForm(Form):
    """Form for submitting a QR string decoded by the browser camera."""

    account = ModelChoiceField(
        label=_('Счёт'),
        queryset=Account.objects.all(),
        widget=Select(attrs={'class': _SELECT_CLASSES}),
    )
    qr_raw = CharField(
        widget=HiddenInput(),
        max_length=512,
    )

    def __init__(self, user: User, *args: Any, **kwargs: Any) -> None:
        kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(user=user)  # type: ignore[attr-defined]
        if self.fields['account'].queryset.exists():  # type: ignore[attr-defined]
            self.fields['account'].initial = self.fields[
                'account'
            ].queryset.first()  # type: ignore[attr-defined]

    def clean_qr_raw(self) -> str:
        qr_raw = (self.cleaned_data.get('qr_raw') or '').strip()
        if not qr_raw:
            raise ValidationError(_('QR-код не распознан.'))
        try:
            parse_fns_qr(qr_raw)
        except QRCodeDecodeError as exc:
            raise ValidationError(str(exc)) from exc
        return qr_raw
```

- [ ] **Step 4: Add `ScanQRReceiptView` and shared context to `views/upload.py`**

Replace the full content of `hasta_la_vista_money/receipts/views/upload.py` with:

```python
import hashlib
import sys
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    FormView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins.base import FormErrorHandlingMixin
from hasta_la_vista_money.receipts.forms import (
    ScanQRForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    compute_image_hash,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.receipts.views']


class UploadImageView(
    LoginRequiredMixin,
    FormView[UploadImageForm],
    FormErrorHandlingMixin,
):
    """Accept a receipt image and enqueue background processing.

    The view does not block on inference: it computes the file hash, rejects
    duplicates, persists a PendingReceipt + the image, dispatches the Celery
    task and redirects the user back to the receipts list. The background
    worker transitions the row to ``ready`` (or ``failed``) on its own.
    """

    template_name = 'receipts/upload_image.html'
    form_class: type[UploadImageForm] = UploadImageForm
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))  # type: ignore[misc]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['upload_form'] = context.pop('form')
        context.setdefault(
            'scan_form',
            ScanQRForm(user=self.request.user),
        )
        return context

    def form_valid(self, form: UploadImageForm) -> HttpResponse:
        request = cast('RequestWithContainer', self.request)
        user = cast('User', request.user)
        account = form.cleaned_data.get('account')
        if account is None:
            messages.error(request, constants.INVALID_FILE_FORMAT)
            return super().form_invalid(form)

        uploaded_files = self._get_uploaded_files()
        if not uploaded_files:
            messages.error(request, constants.INVALID_FILE_FORMAT)
            return super().form_invalid(form)

        pending_receipt_service = (
            request.container.receipts.pending_receipt_service()
        )

        queued_count = 0
        duplicate_count = 0

        for uploaded_file in uploaded_files:
            image_hash = compute_image_hash(uploaded_file)
            uploaded_file.seek(0)

            duplicate = pending_receipt_service.find_duplicate(
                user=user,
                image_hash=image_hash,
            )
            if duplicate is not None:
                duplicate_count += 1
                continue

            try:
                pending_receipt = pending_receipt_service.create_processing_job(
                    user=user,
                    account=account,
                    image_file=uploaded_file,
                    image_hash=image_hash,
                )
            except Exception as exc:
                logger.exception(
                    'Error queuing receipt for processing',
                    error=exc,
                )
                return self.handle_form_error_with_message(
                    form,
                    exc,
                    constants.ERROR_PROCESSING_RECEIPT,
                )

            async_result = _views_module().process_pending_receipt.delay(
                pending_receipt.pk,
            )
            pending_receipt_service.attach_task_id(
                pending_receipt=pending_receipt,
                task_id=async_result.id,
            )
            queued_count += 1

        if queued_count:
            messages.success(
                request,
                _(
                    'Чеков поставлено в обработку: %(count)s. '
                    'Когда распознавание завершится, они появятся в списке.',
                )
                % {'count': queued_count},
            )
        if duplicate_count:
            messages.warning(
                request,
                _('Дубликатов пропущено: %(count)s.')
                % {'count': duplicate_count},
            )
        if not queued_count and duplicate_count:
            messages.warning(request, _('Все выбранные чеки уже загружены.'))
        return redirect('receipts:list')

    def _get_uploaded_files(self) -> list[Any]:
        """Extract all uploaded files from request."""
        return list(self.request.FILES.getlist('file'))


class ScanQRReceiptView(
    LoginRequiredMixin,
    FormView[ScanQRForm],
    FormErrorHandlingMixin,
):
    """Accept a QR string decoded in-browser and enqueue an FNS lookup.

    Mirrors UploadImageView but skips the image upload + pyzbar decode step
    entirely: the QR is already decoded client-side (camera scan), so only
    the raw QR string and target account are submitted.
    """

    template_name = 'receipts/upload_image.html'
    form_class: type[ScanQRForm] = ScanQRForm
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))  # type: ignore[misc]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['scan_form'] = context.pop('form')
        context.setdefault(
            'upload_form',
            UploadImageForm(user=self.request.user),
        )
        return context

    def form_valid(self, form: ScanQRForm) -> HttpResponse:
        request = cast('RequestWithContainer', self.request)
        user = cast('User', request.user)
        account = form.cleaned_data['account']
        qr_raw = form.cleaned_data['qr_raw']
        image_hash = hashlib.sha256(qr_raw.encode()).hexdigest()

        pending_receipt_service = (
            request.container.receipts.pending_receipt_service()
        )

        duplicate = pending_receipt_service.find_duplicate(
            user=user,
            image_hash=image_hash,
        )
        if duplicate is not None:
            messages.warning(request, _('Этот чек уже загружен.'))
            return redirect('receipts:list')

        try:
            pending_receipt = (
                pending_receipt_service.create_processing_job_from_qr(
                    user=user,
                    account=account,
                    image_hash=image_hash,
                )
            )
        except Exception as exc:
            logger.exception(
                'Error queuing scanned receipt for processing',
                error=exc,
            )
            return self.handle_form_error_with_message(
                form,
                exc,
                constants.ERROR_PROCESSING_RECEIPT,
            )

        async_result = (
            _views_module().process_pending_receipt_from_qr.delay(
                pending_receipt.pk,
                qr_raw,
            )
        )
        pending_receipt_service.attach_task_id(
            pending_receipt=pending_receipt,
            task_id=async_result.id,
        )
        messages.success(
            request,
            _(
                'Чек поставлен в обработку. Когда распознавание '
                'завершится, он появится в списке.',
            ),
        )
        return redirect('receipts:list')
```

- [ ] **Step 5: Export `ScanQRReceiptView` from `views/__init__.py`**

Add `ScanQRReceiptView` to the import from `hasta_la_vista_money.receipts.views.upload` and to `__all__` (alphabetically, next to `'ReviewPendingReceiptView'` works since `S` sorts after `R`... place it next to `'SellerCreateView'` alphabetically — `__all__` is already alphabetized, so insert `'ScanQRReceiptView'` right before `'SellerCreateView'`):

```python
from hasta_la_vista_money.receipts.views.upload import (
    ScanQRReceiptView,
    UploadImageView,
)
```

```python
__all__ = [
    'PendingReceiptCounterView',
    'PendingReceiptDeleteView',
    'PendingReceiptRetryView',
    'ProductByMonthView',
    'ReceiptCreateView',
    'ReceiptDeleteView',
    'ReceiptDetailView',
    'ReceiptUpdateView',
    'ReceiptView',
    'ReviewPendingReceiptView',
    'ScanQRReceiptView',
    'SellerCreateView',
    'SellerUpdateView',
    'UploadImageView',
    'process_pending_receipt',
    'process_pending_receipt_from_qr',
]
```

- [ ] **Step 6: Add the URL route**

In `hasta_la_vista_money/receipts/urls.py`, add `ScanQRReceiptView` to the import from `hasta_la_vista_money.receipts.views` (alphabetically, before `'SellerCreateView'` — i.e. right after `ReviewPendingReceiptView` in the import list):

```python
from hasta_la_vista_money.receipts.views import (
    PendingReceiptCounterView,
    PendingReceiptDeleteView,
    PendingReceiptRetryView,
    ProductByMonthView,
    ReceiptCreateView,
    ReceiptDeleteView,
    ReceiptDetailView,
    ReceiptUpdateView,
    ReceiptView,
    ReviewPendingReceiptView,
    ScanQRReceiptView,
    SellerCreateView,
    SellerUpdateView,
    UploadImageView,
)
```

Add the new path right after the `upload/` path:

```python
    path(
        'upload/',
        UploadImageView.as_view(),
        name='upload',
    ),
    path(
        'scan-qr/',
        ScanQRReceiptView.as_view(),
        name='scan_qr',
    ),
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python manage.py test hasta_la_vista_money.receipts.tests.test_pending_receipt_flow -v 2`
Expected: PASS (all `ScanQRReceiptViewTests` plus existing `UploadImageViewTests`, which must still pass since `get_context_data` was added without touching `form_valid`'s redirect/messages behavior)

- [ ] **Step 8: Commit**

```bash
git add hasta_la_vista_money/receipts/forms.py hasta_la_vista_money/receipts/views/upload.py hasta_la_vista_money/receipts/views/__init__.py hasta_la_vista_money/receipts/urls.py hasta_la_vista_money/receipts/tests/test_pending_receipt_flow.py
git commit -m "feat: add ScanQRForm and ScanQRReceiptView for camera QR scans"
```

---

### Task 5: Add the `jsQR`-based camera scanner JS module

**Files:**
- Modify: `package.json` (add `jsqr` dependency)
- Modify: `esbuild.config.mjs` (add `pages/receipt-qr-scan` entry point)
- Create: `static/js/pages/receipt-qr-scan.js`

**Interfaces:**
- Produces: two Alpine components registered globally — `receiptUploadTabs` (tab switching between `'file'` and `'scan'`, dispatches `document` `CustomEvent`s `receipt-scan:activate` / `receipt-scan:deactivate`) and `receiptQRScanPage` (owns the camera stream, the scan loop, and decoded-QR submission). Bundled output: `static/js/dist/pages/receipt-qr-scan.js` (IIFE, matching the existing `pages/*` entries).
- Consumes (at runtime, from the template built in Task 6): `x-ref="video"` (a `<video>` element), `x-ref="canvas"` (a `<canvas>` element), `x-ref="scanForm"` (a `<form>` containing a hidden `input[name="qr_raw"]`).

- [ ] **Step 1: Add the `jsqr` dependency**

Run: `npm install jsqr --save`
Expected: `package.json` `dependencies` gains `"jsqr": "^1.4.0"` (or current latest 1.x), `package-lock.json` updates.

- [ ] **Step 2: Add the esbuild entry point**

In `esbuild.config.mjs`, add to the `entryPoints` object (after `'pages/receipt-update': 'static/js/pages/receipt-update.js',`):

```js
    'pages/receipt-qr-scan': 'static/js/pages/receipt-qr-scan.js',
```

- [ ] **Step 3: Write the scanner module**

Create `static/js/pages/receipt-qr-scan.js`:

```js
import jsQR from 'jsqr';

const SCAN_INTERVAL_MS = 200;
const CAMERA_UNAVAILABLE_MESSAGE = 'Камера недоступна в этом браузере.';
const CAMERA_DENIED_MESSAGE = 'Нет доступа к камере. Используйте загрузку файла.';

function registerReceiptUploadTabs(Alpine) {
    Alpine.data('receiptUploadTabs', function () {
        return {
            activeTab: 'file',

            selectFile() {
                this.activeTab = 'file';
                document.dispatchEvent(new CustomEvent('receipt-scan:deactivate'));
            },

            selectScan() {
                this.activeTab = 'scan';
                document.dispatchEvent(new CustomEvent('receipt-scan:activate'));
            },
        };
    });
}

function registerReceiptQRScanPage(Alpine) {
    Alpine.data('receiptQRScanPage', function () {
        return {
            errorMessage: '',
            stream: null,
            scanTimer: null,

            init() {
                document.addEventListener('receipt-scan:activate', this.start.bind(this));
                document.addEventListener('receipt-scan:deactivate', this.stop.bind(this));
                window.addEventListener('beforeunload', this.stop.bind(this));
            },

            async start() {
                this.errorMessage = '';
                if (this.stream) {
                    return;
                }
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    this.errorMessage = CAMERA_UNAVAILABLE_MESSAGE;
                    return;
                }
                try {
                    this.stream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: 'environment' },
                    });
                } catch (error) {
                    this.errorMessage = CAMERA_DENIED_MESSAGE;
                    return;
                }
                const video = this.$refs.video;
                if (!video) {
                    this.stop();
                    return;
                }
                video.srcObject = this.stream;
                await video.play();
                this.scanTimer = window.setInterval(this.scanFrame.bind(this), SCAN_INTERVAL_MS);
            },

            scanFrame() {
                const video = this.$refs.video;
                const canvas = this.$refs.canvas;
                if (!video || !canvas || video.readyState !== video.HAVE_ENOUGH_DATA) {
                    return;
                }
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const context = canvas.getContext('2d');
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
                const decoded = jsQR(imageData.data, imageData.width, imageData.height);
                if (decoded && decoded.data) {
                    this.submitDecoded(decoded.data);
                }
            },

            submitDecoded(rawValue) {
                this.stop();
                const form = this.$refs.scanForm;
                const qrInput = form ? form.querySelector('[name="qr_raw"]') : null;
                if (qrInput) {
                    qrInput.value = rawValue;
                }
                if (form) {
                    form.submit();
                }
            },

            stop() {
                if (this.scanTimer) {
                    window.clearInterval(this.scanTimer);
                    this.scanTimer = null;
                }
                if (this.stream) {
                    this.stream.getTracks().forEach(track => track.stop());
                    this.stream = null;
                }
            },
        };
    });
}

if (window.Alpine) {
    registerReceiptUploadTabs(window.Alpine);
    registerReceiptQRScanPage(window.Alpine);
} else {
    document.addEventListener('alpine:init', function () {
        registerReceiptUploadTabs(window.Alpine);
        registerReceiptQRScanPage(window.Alpine);
    });
}
```

- [ ] **Step 4: Lint and build**

Run: `npm run lint:js`
Expected: no errors (the new file matches the existing `static/js/pages/**/*.js` glob in `eslint.config.mjs`, so it's linted automatically).

Run: `npm run build:js`
Expected: build succeeds; `static/js/dist/pages/receipt-qr-scan.js` is created.

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json esbuild.config.mjs static/js/pages/receipt-qr-scan.js
git commit -m "feat: add jsQR-based camera scanner Alpine module"
```

---

### Task 6: Wire the scan tab into `upload_image.html` and style it

**Files:**
- Modify: `hasta_la_vista_money/receipts/templates/receipts/upload_image.html`
- Modify: `hasta_la_vista_money/receipts/static/receipts/css/receipts.css` (add new rules after the `.receipts-upload-card` / `.receipts-dropzone` block, ~line 1140, before the `/* Review */` comment)

**Interfaces:**
- Consumes: `upload_form` / `scan_form` context variables (Task 4), `receiptUploadTabs` / `receiptQRScanPage` / `receiptUploadPage` Alpine components (Task 5 + existing `upload.js`), `receipts:scan_qr` URL name (Task 4).

This task has no automated test (no JS test runner in this repo) — verification is a manual check in a real browser per Step 3.

- [ ] **Step 1: Update the template**

Replace the content of `hasta_la_vista_money/receipts/templates/receipts/upload_image.html` from the opening `<div class="receipts-card receipts-upload-card" ...>` (line 32) through its matching closing `</div>` (line 97) with:

```html
        <div class="receipts-card receipts-upload-card" x-data="receiptUploadTabs">
            <div class="receipts-mode-tabs" role="tablist">
                <button type="button"
                        class="receipts-mode-tab"
                        x-bind:class="{ 'is-active': activeTab === 'file' }"
                        x-on:click="selectFile()"
                        role="tab">
                    <i class="bi bi-cloud-upload"></i>
                    {% translate 'Файл' %}
                </button>
                <button type="button"
                        class="receipts-mode-tab"
                        x-bind:class="{ 'is-active': activeTab === 'scan' }"
                        x-on:click="selectScan()"
                        role="tab">
                    <i class="bi bi-qr-code-scan"></i>
                    {% translate 'Сканировать QR' %}
                </button>
            </div>

            <div x-show="activeTab === 'file'" x-data="receiptUploadPage">
                <form method="post" enctype="multipart/form-data" id="uploadForm" class="receipts-upload-form" novalidate>
                    {% csrf_token %}

                    <div class="receipts-section">
                        <h3>
                            <i class="bi bi-cloud-upload"></i>
                            {% translate 'Файл чека' %}
                        </h3>

                        <label id="upload-zone"
                               for="file-input"
                               class="receipts-dropzone"
                               x-bind:class="zoneClass"
                               x-on:dragenter="handleDragEnter"
                               x-on:dragover="handleDragOver"
                               x-on:dragleave="handleDragLeave"
                               x-on:drop="handleDrop">
                            <i class="bi bi-cloud-upload receipts-dropzone-icon"></i>
                            <div class="receipts-dropzone-text">
                                <strong>{% translate 'Перетащите изображение сюда или нажмите для выбора' %}</strong>
                                <span>{% translate 'JPG, JPEG или PNG, до 5 МБ' %}</span>
                                <span id="selected-file-name" class="receipts-dropzone-filename" x-show="hasFiles" x-cloak>
                                    <span x-text="selectedFileLabel"></span>
                                    <span class="receipts-dropzone-status">{% translate '(Файл добавлен. Отправке в обработку)' %}</span>
                                </span>
                            </div>
                        </label>

                        <input type="file"
                               name="file"
                               id="file-input"
                               class="hidden"
                               accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                               multiple
                               x-ref="fileInput"
                               x-on:change="handleInputChange">

                        <div id="upload-error" class="receipts-upload-error" x-show="errorMessage" x-text="errorMessage" x-cloak></div>
                    </div>

                    <div class="receipts-section">
                        <h3>
                            <i class="bi bi-wallet2"></i>
                            {{ upload_form.account.label }}
                        </h3>
                        {{ upload_form.account }}
                    </div>

                    <div class="receipts-card-ft">
                        <p class="hint">
                            <i class="bi bi-clock-history"></i>
                            {% translate 'Когда чек будет распознан, он появится в списке. Если что-то пошло не так — рядом будет показана причина.' %}
                        </p>
                        <div class="ft-actions">
                            <button type="submit"
                                    id="submitBtn"
                                    class="receipts-btn receipts-btn-primary"
                                    x-bind:disabled="!hasFiles">
                                <i class="bi bi-cloud-upload"></i>
                                <span>{% translate 'Поставить в обработку' %}</span>
                            </button>
                        </div>
                    </div>
                </form>
            </div>

            <div x-show="activeTab === 'scan'" x-cloak class="receipts-scan-panel" x-data="receiptQRScanPage">
                <form method="post" action="{% url 'receipts:scan_qr' %}" id="scanQrForm" x-ref="scanForm">
                    {% csrf_token %}
                    {{ scan_form.qr_raw }}

                    <div class="receipts-section">
                        <h3>
                            <i class="bi bi-wallet2"></i>
                            {{ scan_form.account.label }}
                        </h3>
                        {{ scan_form.account }}
                    </div>

                    <div class="receipts-scan-video-wrap">
                        <video x-ref="video" class="receipts-scan-video" autoplay playsinline muted></video>
                        <canvas x-ref="canvas" class="hidden"></canvas>
                    </div>

                    <div id="scan-error" class="receipts-upload-error" x-show="errorMessage" x-text="errorMessage" x-cloak></div>
                    <p class="hint" x-show="!errorMessage">
                        <i class="bi bi-qr-code-scan"></i>
                        {% translate 'Наведите камеру на QR-код чека' %}
                    </p>
                </form>
            </div>
        </div>
```

Then add the bundled scan script tag in `{% block extra_js %}`, right after the existing `upload.js` script tag:

```html
{% block extra_js %}
<script defer nonce="{{request.csp_nonce}}" src="{% static 'js/alpine.csp.min.js' %}"></script>
<script nonce="{{request.csp_nonce}}" src="{% static 'js/upload.js' %}"></script>
<script nonce="{{request.csp_nonce}}" src="{% static 'js/dist/pages/receipt-qr-scan.js' %}"></script>
{% endblock %}
```

- [ ] **Step 2: Add the tab and scan-panel CSS**

In `hasta_la_vista_money/receipts/static/receipts/css/receipts.css`, insert after the closing `}` of `.receipts-upload-error` (end of that rule, right before the `/* Review */` comment, ~line 1179):

```css
.receipts-mode-tabs {
  display: none;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

@media (max-width: 768px) {
  .receipts-mode-tabs {
    display: flex;
  }
}

.receipts-mode-tab {
  align-items: center;
  background: var(--receipts-surface-2);
  border: 1px solid var(--receipts-border);
  border-radius: 0.75rem;
  color: var(--receipts-muted);
  cursor: pointer;
  display: flex;
  font-size: 0.85rem;
  font-weight: 600;
  gap: 0.4rem;
  padding: 0.5rem 0.9rem;
}

.receipts-mode-tab.is-active {
  background: color-mix(in oklab, var(--receipts-accent) 12%, var(--receipts-surface));
  border-color: color-mix(in oklab, var(--receipts-accent) 45%, var(--receipts-border));
  color: var(--receipts-accent);
}

.receipts-scan-panel {
  display: grid;
  gap: 1rem;
}

.receipts-scan-video-wrap {
  background: #000;
  border-radius: 1.25rem;
  overflow: hidden;
}

.receipts-scan-video {
  display: block;
  width: 100%;
}
```

- [ ] **Step 3: Manual verification in a browser**

Run: `make start` (or your usual local server command) and `npm run watch:js` in a second terminal.

In Chrome DevTools, open the device toolbar (mobile emulation), pick a phone preset (e.g. "iPhone 12 Pro"), navigate to `/receipts/upload/`:
- Expected: the `.receipts-mode-tabs` bar is visible with "Файл" and "Сканировать QR" buttons.
- Click "Сканировать QR": expected — browser prompts for camera permission (DevTools may need a fake camera enabled via `chrome://settings/content/camera` or `--use-fake-device-for-media-stream` flag); on grant, the `<video>` shows a live feed.
- Deny camera permission (or test in an environment with no camera): expected — `errorMessage` text appears ("Нет доступа к камере...") and the user can click "Файл" to go back to the dropzone.

Resize the viewport above 768px (desktop width): expected — `.receipts-mode-tabs` is hidden (`display: none`), only the file dropzone is visible, matching current behavior exactly.

- [ ] **Step 4: Run the full backend test suite one more time**

Run: `uv run python manage.py test -v 2`
Expected: PASS (confirms the template/context changes across Tasks 4 and 6 didn't break `test_upload_image_view_get` or any other existing view test that renders this template)

- [ ] **Step 5: Commit**

```bash
git add hasta_la_vista_money/receipts/templates/receipts/upload_image.html hasta_la_vista_money/receipts/static/receipts/css/receipts.css
git commit -m "feat: add mobile camera QR scan tab to receipt upload page"
```

---

## Out of Scope (per spec)

- Desktop camera scanning / capability detection.
- Preview/confirmation step before submitting a decoded QR.
- Changes to the AI photo-inference pipeline (`analyze_image_with_ai`).
- Cross-dedup between a photo upload and a QR scan of the same physical receipt (each path dedups independently against its own hash space, as documented in the spec).
