# QR-сканирование чеков камерой в браузере

## Контекст

Сейчас на странице загрузки чека (`upload_image.html`) пользователь выбирает/перетаскивает изображение чека. Файл уходит на сервер, `PendingReceipt` создаётся в статусе `processing`, Celery-задача `process_pending_receipt` декодирует QR через `pyzbar` (`fns_qr.QRCodeExtractor`), берёт сырую строку QR, запрашивает данные чека у ФНС (`FNSClient`), маппит и валидирует их.

Цель: дать пользователю возможность отсканировать QR прямо камерой телефона, без фотографирования и загрузки файла — быстрее и без лишнего шага распознавания изображения на сервере.

## Область действия

Только мобильная версия страницы загрузки чека. Десктоп продолжает использовать только загрузку файла. Предпросмотр/инференс изображения (отдельный AI-пайплайн анализа фото) не затрагивается.

## Архитектура

```
Браузер (камера, facingMode: environment)
  │  video → canvas → jsQR раз в кадр
  │  успешный декод QR
  ▼
POST receipts:scan_qr  (qr_raw, account)
  │  parse_fns_qr(qr_raw) — валидация полей t,s,fn,i,fp,n
  │  sha256(qr_raw) → find_duplicate(image_hash=...)
  ▼
PendingReceipt(image_file=None, image_hash=sha256(qr_raw))
  │  process_pending_receipt_from_qr.delay(pending.pk, qr_raw)
  ▼
Celery: process_pending_receipt_from_qr
  │  FNSClient().fetch_receipt(qr_raw) → map_fns_receipt_to_receipt_data → validate
  ▼
PendingReceipt.status = ready / ready_with_warning / failed
```

### Фронтенд

- На `upload_image.html` рядом с существующим dropzone добавляется вторая вкладка «Сканировать QR», видимая только на мобильных (`md:hidden` на самой вкладке/переключателе — ширина экрана, без capability detection).
- Вкладка скана открывает `<video>` с камерой через `getUserMedia({ video: { facingMode: 'environment' } })`.
- Раз в кадр (`requestAnimationFrame`) текущий кадр видео рисуется на скрытый `<canvas>`, `ImageData` отдаётся в `jsQR`.
- При успешном декоде — сразу, без предпросмотра/подтверждения, отправляется `POST` (обычная форма с `qr_raw` + `account` + CSRF-токеном) на `receipts:scan_qr`. Это соответствует текущей асинхронной природе загрузки: чек ставится в очередь, готовность видна в списке.
- При ошибке доступа к камере (`NotAllowedError`, `NotFoundError` и т.п.) — текстовое сообщение об ошибке и кнопка возврата к вкладке загрузки файла. Камера всегда доступна как опция через сами вкладки — никогда не единственный путь.
- Библиотека: **jsQR** — добавляется как npm-зависимость (`package.json`), собирается отдельным esbuild entry point `static/js/pages/receipt-qr-scan.js` → `static/js/dist/pages/receipt-qr-scan.js` (по аналогии с другими `pages/*` точками входа в `esbuild.config.mjs`), подключается на `upload_image.html` через `<script src>` рядом с `upload.js`.
- Видеопоток останавливается (`track.stop()`) при уходе со вкладки скана, успешной отправке или закрытии страницы — не должен работать в фоне.

### Бэкенд

- Новый view `ScanQRReceiptView` (`hasta_la_vista_money/receipts/views/upload.py`, рядом с `UploadImageView`): `LoginRequiredMixin`, POST-only, по образцу `PendingReceiptRetryView` — обычный редирект на `receipts:list` с `django.contrib.messages`, без JSON-контракта.
  - Принимает `qr_raw` и `account` из POST.
  - Валидирует `qr_raw` через существующий `parse_fns_qr` (переиспользуется как есть, без изменений).
  - Считает `sha256(qr_raw)` и кладёт его в поле `PendingReceipt.image_hash` (поле уже используется чисто как ключ дедупликации, не привязано семантически к наличию файла) — это позволяет переиспользовать `PendingReceiptService.find_duplicate()` без изменений схемы и без новых полей.
  - При отсутствии дубликата создаёт `PendingReceipt` через новый метод `PendingReceiptService.create_processing_job_from_qr(user, account, image_hash)` (`image_file` остаётся `None` — поле уже nullable).
  - Запускает `process_pending_receipt_from_qr.delay(pending.pk, qr_raw)`, сохраняет `task_id` как и при обычной загрузке.
- Новый маршрут `path('scan-qr/', ScanQRReceiptView.as_view(), name='scan_qr')` в `receipts/urls.py`.
- В `tasks.py`:
  - `_run_fns_pipeline(pending)` разбивается на `_run_fns_pipeline_from_raw(pending, raw_qr)` (всё, что сейчас идёт после получения `qr_data.raw`: `FNSClient().fetch_receipt` → маппинг → категоризация → подстановка `retail_place` → валидация) и тонкую обёртку `_run_fns_pipeline(pending)`, которая сначала достаёт `raw_qr` через `QRCodeExtractor().extract(image_fp)`, затем вызывает общую функцию.
  - Новая задача `process_pending_receipt_from_qr(_self, pending_receipt_id, raw_qr)` — копия структуры `process_pending_receipt`, но без проверки `pending.image_file` (она ожидаемо пуста) и без чтения файла: сразу `_run_fns_pipeline_from_raw(pending, raw_qr)`. Та же логика классификации ошибок (`_classify_failure`, `_FAILURE_RULES`) переиспользуется без изменений — ошибки FNS/рейт-лимита/таймаута одинаковы для обоих путей.
- Существующий `process_pending_receipt` (путь с изображением) не меняется в поведении — он по-прежнему требует `image_file` и идёт через `pyzbar`.

### Дедупликация

Дубликаты по QR определяются тем же механизмом, что и дубликаты по фото — совпадением `image_hash` среди активных (`processing`/`ready`/`ready_with_warning`) `PendingReceipt` пользователя и среди `ReceiptImageHash` сохранённых чеков. Если один и тот же чек сначала отсканирован камерой, а затем по ошибке загружен фото (или наоборот), `image_hash` совпадёт только если это решит дедуп умышленно — на практике `sha256` файла и `sha256` строки QR будут разными, так что дедуп ловит лишь повторные сканы/загрузки одного и того же входа. Это ограничение принимается: полная кросс-дедупликация фото↔QR того же чека не входит в объём задачи.

### Безопасность и нагрузка

- `ScanQRReceiptView` защищён `LoginRequiredMixin` + CSRF, как остальные формы на странице — никакого нового открытого эндпоинта.
- Нагрузка на FNS API такая же, как при обычной загрузке (один вызов `FNSClient().fetch_receipt` на чек) — отдельного троттлинга не требуется, существующие правила (`_FAILURE_RULES`, retry/backoff) переиспользуются как есть.
- Получение видео с камеры выполняется только в браузере пользователя, на сервер уходит только декодированная строка QR — то же по объёму данных, что URL.

## Что не входит в объём

- Десктопная версия сканирования (camera capability detection, fallback на десктопе) — не делается.
- Предпросмотр/подтверждение распознанного QR перед отправкой — не делается, путь асинхронный, как при обычной загрузке.
- Изменение AI-пайплайна анализа фото (`analyze_image_with_ai`) — не затрагивается, это отдельная функциональность.
- Кросс-дедупликация одного и того же чека между фото- и QR-путями — не делается (см. раздел «Дедупликация»).

## Тестирование

- Unit-тесты на `_run_fns_pipeline_from_raw` (рефакторинг существующей функции — должен сохранить покрытие `_run_fns_pipeline`).
- Unit-тесты на `process_pending_receipt_from_qr` (успех, FNS-ошибки, дубликат по `image_hash`) — по аналогии с существующими тестами `process_pending_receipt`.
- Unit/view-тесты на `ScanQRReceiptView` (валидный QR, невалидный QR — `parse_fns_qr` бросает ошибку, дубликат, неавторизованный доступ).
- Frontend: ручная проверка на мобильном устройстве/эмуляторе Chrome DevTools (доступ к камере, decode, fallback при отказе в разрешении).
