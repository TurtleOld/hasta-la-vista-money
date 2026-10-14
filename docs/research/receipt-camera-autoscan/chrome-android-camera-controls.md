# Управление камерой в Chrome Android: выбор модуля, зум, фокус, снимок

Исследование для тикета `.scratch/receipt-camera-autoscan/issues/02-chrome-android-camera-controls.md`.
Дата: 2026-10-14. Целевое устройство: Samsung Galaxy A55 (основная 50 МП с AF и OIS,
сверхширокая 12 МП, макро 5 МП; обе дополнительные — фиксированный фокус).

Главный источник — исходники Chromium на коммите `main`
[`1ada170a`](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235).
Ниже `C2` = `media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java`
(вся работа Chrome с камерой на Android идёт через Camera2 API), `IC` =
`third_party/blink/renderer/modules/imagecapture/image_capture.cc`. Номера строк — на этом коммите.
Спецификации: [Media Capture Image (ED)](https://w3c.github.io/mediacapture-image/),
документация Android Camera2.

## Коротко

- **Различить модули по API напрямую нельзя.** В label нет типа объектива: Chrome пишет
  `camera <N>, facing back` (`N` — индекс в `CameraManager.getCameraIdList()`), в старых
  версиях встречался префикс `camera2`. Строка на английском, не локализуется. Рабочие
  признаки основной камеры: (1) самый маленький индекс среди задних; (2) в `focusMode` есть
  `continuous` (у сверхширокой и макро фиксированный фокус, AF нет); (3) есть `torch`;
  (4) больший `zoom.max` / `imageWidth.max` (`getPhotoCapabilities`).
- **`facingMode: 'environment'` берёт первую заднюю камеру в порядке `getCameraIdList()`**,
  если по разрешению/fps камеры равны. Обычно это ID `0`, основная камера. Но запрос
  `width/height ideal` может склонить выбор к другой камере, у которой формат ближе к
  запрошенному. Поэтому лучше явно выбирать `deviceId`.
- **Зум на Chrome Android — только цифровой кроп сенсора (`SCALER_CROP_REGION`), от 1× до
  `SCALER_AVAILABLE_MAX_DIGITAL_ZOOM`.** На другой модуль он не переключает: ни на
  сверхширокую (<1×), ни на макро. Применяется «на лету» через `setRepeatingRequest`, поток не
  перезапускается. Разрешение PTZ на Android выдаётся автоматически, `zoom: true` в
  `getUserMedia` не нужен.
- **Кроп делается до масштабирования в ISP.** Поэтому 2× при видео 1080p даёт больше
  реальных деталей, чем 1×: читается центральная область сенсора, а не уменьшенный полный
  кадр. Это и есть основа приёма «зум ~2× и держать телефон дальше минимальной дистанции
  фокуса».
- **Фокус по умолчанию уже непрерывный** (`CONTROL_AF_MODE_CONTINUOUS_PICTURE`).
  `focusMode: 'single-shot'` на Android ничего не запускает: AF-trigger Chrome не отправляет.
  `pointsOfInterest` задаёт одну AF/AE/AWB-область 1/8 видимого кадра. Она сбрасывается при
  любом изменении `zoom`. `focusDistance` (метры) доступен только при поддержке ручного фокуса.
- **У нас баг: tap-to-focus никогда не срабатывает.** `pointsOfInterest` по спецификации
  отсутствует в `MediaTrackCapabilities`, а `focusAt()` проверяет
  `capabilities.pointsOfInterest` и сразу выходит. Проверять нужно
  `getSupportedConstraints().pointsOfInterest` или `'pointsOfInterest' in track.getSettings()`.
- **`ImageCapture.takePhoto()` поддерживается (Chrome 59+), но с оговорками.** Превью
  останавливается, открывается отдельная JPEG-сессия, после снимка превью пересоздаётся.
  Без `imageWidth` берётся первый размер из `getOutputSizes(JPEG)`, обычно максимальный.
  Для 50 МП сенсора это ожидаемо ~12,5 МП (бининг): режим `MAXIMUM_RESOLUTION` Chrome не
  использует. AF-trigger и AE-precapture перед снимком не запускаются. Текущие зум, фокус и
  область интереса копируются в снимок.

## 1. Как Chrome видит камеры Android

### 1.1 Список устройств и label

- Chrome перечисляет все ID из `CameraManager.getCameraIdList()` (`C2`
  [1507–1525](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#1507)).
  Android документирует, что этот список «doesn't contain physical cameras that can only be used
  as part of a logical multi-camera device»
  ([CameraManager#getCameraIdList](https://developer.android.com/reference/android/hardware/camera2/CameraManager#getCameraIdList())).
  Значит, браузер видит только то, что производитель открыл сторонним приложениям. Сколько
  задних ID отдаёт A55 (одну логическую камеру или отдельные 0/2/…), из исходников не узнать.
  Это вопрос диагностики (тикет 01).
- Label формируется в `getName()` (`C2`
  [1600–1630](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#1600)):
  `"camera " + index + ", facing " + {front|back|external} [+ ", infrared"]`. Строка собирается
  в Java и не локализуется. Фокусное расстояние, разрешение и тип объектива в неё не попадают.
  В обсуждении W3C встречается старый формат `camera2 0, facing back`
  ([w3c/mediacapture-extensions#20](https://github.com/w3c/mediacapture-extensions/issues/20)),
  поэтому парсить label надо терпимо: `/camera2? (\d+), facing back/`.
- Порядок в `enumerateDevices()`: фронтальные камеры переносятся в начало списка, задние идут в
  порядке `getCameraIdList()`
  ([video_capture_device_factory_android.cc 127–133](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/video_capture_device_factory_android.cc#127)).
  Для несъёмных камер ID — «integers starting at 0» (документация Android). То, что ID `0` —
  основная задняя камера, — устоявшаяся практика, а не гарантия.

### 1.2 Что выбирает `facingMode: 'environment'`

Алгоритм SelectSettings в Blink
([media_stream_constraints_util_video_device.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/mediastream/media_stream_constraints_util_video_device.cc#1020)):
сначала считается fitness distance по ограничениям (`facingMode`, `width`, `height`,
`frameRate` …). При равенстве работают tie-breaker'ы в таком порядке: (1) при PTZ-ограничениях
предпочитаются камеры с PTZ; (2) **«Favor IDs that appear first in the enumeration»**
(строки 1039–1045); (3) нативное разрешение, ближайшее к дефолтному; (4) fps.

Следствия:

- С одним `facingMode` выбирается первая задняя камера списка, обычно ID `0`.
- С `width: {ideal: 1920}, height: {ideal: 1080}` (как у нас) первым критерием становится
  fitness по разрешению. Если у основной камеры нет точного 1920×1080 в YUV, а у сверхширокой
  есть, победить может сверхширокая. Для A55 это не проверено. Отсюда решение из карты:
  выбирать `deviceId` явно и запоминать его.
- Похожий запрос в W3C, открытый с 2016 года:
  [«How to avoid wide-lens backfacing camera on new phones?»](https://github.com/w3c/mediacapture-extensions/issues/20).
  Ограничения для выбора объектива (focalLength / угол обзора) так и не стандартизированы.
  Практики из треда: брать камеру с `torch` (вспышка стоит у основной), брать «последнюю» камеру
  (ломается на iPhone 15 Pro), сортировать label. Scandit SDK считает основной заднюю камеру с
  лексикографически наименьшим label
  ([cameraAccess.ts, scandit-sdk 4.6.1](https://unpkg.com/scandit-sdk@4.6.1/src/lib/cameraAccess.ts),
  строки 129–136), то есть с наименьшим индексом.

### 1.3 Признаки модуля в `getCapabilities()` / `getPhotoCapabilities()`

Что Chrome заполняет из `CameraCharacteristics` (`C2` 440–600, 743):

| Возможность Web API | Источник в Camera2 | Основная (AF) | Сверхширокая/макро (фикс-фокус) |
|---|---|---|---|
| `focusMode` | `CONTROL_AF_AVAILABLE_MODES`: `OFF`→`manual`, `AUTO`/`MACRO`→`single-shot`, `CONTINUOUS_*`/`EDOF`→`continuous` | `['manual'?, 'single-shot', 'continuous']` | обычно только `['manual']` или пусто |
| `focusDistance` (м) | min = 1/`LENS_INFO_MINIMUM_FOCUS_DISTANCE`, max = 1/`HYPERFOCAL`; только если есть `AF_MODE_OFF` | диапазон, `min` ≈ минимальная дистанция фокуса | у фикс-фокуса `MINIMUM_FOCUS_DISTANCE = 0` → диапазона нет |
| `zoom` | `SCALER_AVAILABLE_MAX_DIGITAL_ZOOM`, min всегда 1, step 0,1 | например, 1–8/10 | своё значение, обычно меньше |
| `torch` | `FLASH_INFO_AVAILABLE` | `true` | обычно `false` |
| `imageWidth/Height` (photo) | `getOutputSizes(JPEG)` min/max | максимум сенсора в бининге | 12 МП / 5 МП |

Значения `focusDistance` заслуживают доверия только при `LENS_INFO_FOCUS_DISTANCE_CALIBRATION`
≠ `UNCALIBRATED`. Chrome эту калибровку не учитывает. Если она `UNCALIBRATED`, «метры»
условны. Для эвристики выбора камеры (есть AF или нет) это не важно.

**Рекомендуемая эвристика выбора основной камеры (для `receipt-qr-core.mjs`):** среди
`videoinput` с `facing back` (или `getSettings().facingMode === 'environment'`) оставить
камеры, у которых `focusMode` содержит `continuous`. Из них взять ту, у которой есть `torch`.
Если таких несколько — с наименьшим индексом в label. Для проверки возможностей каждую камеру
нужно открыть (`getUserMedia({video: {deviceId: {exact}}})`, затем `getCapabilities()`, затем
`stop()`): `enumerateDevices` возможностей не отдаёт. Поэтому результат стоит запомнить
(решение карты). Labels видны только после выдачи разрешения на камеру.

## 2. Зум

### 2.1 Реализация

- `zoom` → `SCALER_CROP_REGION`: центрированный прямоугольник размером `1/zoom` от
  `SENSOR_INFO_ACTIVE_ARRAY_SIZE`. Значение зажимается в `[1, mMaxZoom]` (`C2`
  [854–866](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#854)).
  Capability: min 1, max = `SCALER_AVAILABLE_MAX_DIGITAL_ZOOM`, step 0,1 (`C2` 471–488).
- Новый `CONTROL_ZOOM_RATIO` (API 30) Chrome не использует. По документации Android, именно
  `CONTROL_ZOOM_RATIO` умеет переключать линзы логической мультикамеры и делать zoom-out на
  сверхширокую, а `SCALER_CROP_REGION` — «doesn't [support zoom-out]»
  ([CaptureRequest#CONTROL_ZOOM_RATIO](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#CONTROL_ZOOM_RATIO)).
  Итог: **zoom в вебе на Android никогда не переключит модуль**, это чистый кроп текущей
  камеры.
- Кроп: «Output streams use this rectangle to produce their output … then scaling the sensor
  input to match the output's configured resolution»
  ([CaptureRequest#SCALER_CROP_REGION](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#SCALER_CROP_REGION)).
  Масштабирование делает ISP из полноразмерного (бинированного) кадра сенсора. Поэтому до
  кратности «ширина сенсора / ширина видео» (у A55 при 1080p это ~2×: 4080/1920) зум
  добавляет реальную детализацию, а не только растягивает пиксели. Ширину 4080 по аналогии с
  типичными 50 МП сенсорами в бининге 2×2 нужно подтвердить по `imageWidth.max`.

### 2.2 Нужен ли перезапуск потока

Нет. `applyConstraints` с image-capture-ограничениями уходит в `ImageCapture`
([media_stream_track_impl.cc 879–897](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/mediastream/media_stream_track_impl.cc#879)),
затем в `SetPhotoOptionsTask`. Тот обновляет `mPreviewRequestBuilder` и вызывает
`mPreviewSession.setRepeatingRequest(...)` на той же сессии (`C2` 960–981). Формат видео и
сессия не меняются, кадры идут без перерыва. На практике зум догоняет за несколько кадров.
Спецификация допускает, что zoom «might not be immediately applicable», поэтому после
`applyConstraints` нужно читать фактическое значение из `getSettings().zoom`.

### 2.3 Разрешение PTZ

- Спецификация: любой алгоритм с не-`false` `zoom` требует разрешения `panTiltZoom`, иначе zoom
  не экспонируется. При скрытой странице `applyConstraints` с `zoom` должен бросать
  `SecurityError` ([mediacapture-image](https://w3c.github.io/mediacapture-image/)).
- Chrome на десктопе так и делает: capability `zoom` показывается только при выданном PTZ
  (`IC`
  [2814–2827](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/imagecapture/image_capture.cc#2814)).
  Разрешение запрашивается, если в `getUserMedia` есть `pan/tilt/zoom` не-`false`
  ([web.dev: camera PTZ](https://web.dev/articles/camera-pan-tilt-zoom)).
- **На Android PTZ выдаётся всегда:**
  ```cpp
  #if BUILDFLAG(IS_ANDROID)
    // The PTZ permission is automatically granted on Android. This way, zoom is
    // not initially empty in ImageCapture. It is safe to do so because pan and
    // tilt are not supported on Android.
    return true;
  ```
  ([media_devices_permission_checker.cc 234–242](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/content/browser/media/media_devices_permission_checker.cc#234)).
  Обычного `getUserMedia({video: {facingMode}})` достаточно, чтобы `getCapabilities().zoom`
  был заполнен, если `MAX_DIGITAL_ZOOM > 1`. Добавлять `zoom: true` не нужно: это лишь
  включит PTZ-ветку запроса разрешения
  ([media_stream_devices_controller.cc 150–160](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/components/webrtc/media_stream_devices_controller.cc#150))
  и PTZ-tie-breaker без пользы.

### 2.4 Форма вызова `applyConstraints`: basic или advanced

Особенности Chromium (`IC` 425–509, 1746–1890; `media_stream_track_impl.cc` 879–897):

- **Нельзя смешивать** image-capture-ограничения (`zoom`, `focusMode`, `torch`,
  `pointsOfInterest` …) с обычными (`width`, `height`, `frameRate`, `deviceId`) в одном вызове:
  `OverconstrainedError("Mixing ImageCapture and non-ImageCapture constraints is not currently supported")`.
- **Первый `advanced`-набор обрабатывается не по спецификации** (TODO crbug.com/1408091):
  внутри него поддерживаются только «голые» значения (`{zoom: 2}`, а не `{zoom: {ideal: 2}}`),
  и неудовлетворимое значение отклоняет весь промис `OverconstrainedError`. По спецификации
  advanced-набор должен был бы просто отброситься. Значит, `advanced: [{zoom: 20}]` при
  `max = 8` → reject. **Зажимайте значение в `[min, max]` и округляйте до `step` сами.**
- Basic-набор: голое значение трактуется как `ideal` и подбирается в пределах capability,
  `{exact}` при невыполнимости отклоняется. Формы `{zoom: z}` и `{advanced: [{zoom: z}]}` с
  корректным z работают одинаково. В экосистеме устоялась `advanced`
  ([Chrome blog: ImageCapture](https://developer.chrome.com/blog/imagecapture),
  [Dynamsoft: camera zoom](https://dynamsoft.com/codepool/camera-zoom-control-on-web.html)).
- Пустой `applyConstraints({})` сбрасывает сохранённые image-capture-ограничения.

### 2.5 Когда доступны capabilities

Блог Chrome (2016) предупреждает, что capabilities появляются только после старта потока. В
текущем коде `ImageCapture` создаётся вместе с треком и асинхронно запрашивает `GetPhotoState`
(`IC` 2143–2170, `media_stream_track_impl.cc` 286–292). Колбэк инициализации передаётся при
создании трека, так что к резолву `getUserMedia` состояние обычно уже есть. Безопаснее всё же
перечитать `getCapabilities()` после `loadedmetadata` или первого кадра. Есть и
промис-вариант: `new ImageCapture(track).getPhotoCapabilities()`.

## 3. Фокус

- **По умолчанию `mFocusMode = CONTINUOUS`** (`C2` 1152), что даёт
  `CONTROL_AF_MODE_CONTINUOUS_PICTURE` + `AF_TRIGGER_IDLE` (`C2`
  [1306–1311](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#1306)).
  Наш `applyConstraints({advanced: [{focusMode: 'continuous'}]})` безвреден, но избыточен.
- **`single-shot` на Android ничего не делает.** В `configureCommonCaptureSettings` для
  `SINGLE_SHOT` стоит комментарий «dealt with independently since it needs to be triggered by a
  capture», но `CONTROL_AF_TRIGGER_START` в файле не встречается ни разу. Режим AF в
  repeating-запросе остаётся прежним (continuous). Программно «дёрнуть» AF нельзя.
- **`manual` + `focusDistance`** → `CONTROL_AF_MODE_OFF` + `LENS_FOCUS_DISTANCE = 1/метры`
  (`C2` 1312–1317). Capability `focusDistance` есть только при `AF_MODE_OFF` в доступных
  режимах. `focusDistance.min` — это 1/`LENS_INFO_MINIMUM_FOCUS_DISTANCE`, то есть минимальная
  дистанция фокуса в метрах (при калиброванном объективе). Ручной фокус для сканера рискован:
  пользователь двигает телефон, а калибровка у Samsung может быть `APPROXIMATE`/`UNCALIBRATED`.
  Годится как источник «насколько близко можно подносить», но не для управления.
- **`pointsOfInterest`** (`C2`
  [887–940](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#887)):
  поддерживается одна точка (x, y ∈ [0, 1] относительно видимого, уже обрезанного зумом кадра).
  Из неё строится `MeteringRectangle` размером 1/8 ширины × 1/8 высоты видимой области с
  максимальным весом, и он ставится одновременно в `CONTROL_AF_REGIONS`, `AE_REGIONS` и
  `AWB_REGIONS`. Условие — `CONTROL_MAX_REGIONS_AF|AE|AWB > 0`. Область **сбрасывается при
  любом новом `zoom`** и при `focusMode`/`exposureMode = none`. При continuous AF камера
  перефокусируется на эту область, явного триггера нет. Значит, при автозуме точку интереса
  нужно ставить заново после каждого изменения зума.
- **Как определять поддержку `pointsOfInterest`.** В `MediaTrackCapabilities` её нет ни по
  спецификации, ни в Chromium (`IC` 1776–1783: «There is no capability for `pointsOfInterest`
  in `MediaTrackCapabilities`»). Есть `getSupportedConstraints().pointsOfInterest` и поле
  `getSettings().pointsOfInterest`, которое на Android всегда присутствует, хотя бы пустым
  массивом (`IC` 2755–2764). **Текущий `focusAt()` в `receipt-qr-scan.js` проверяет
  `capabilities.pointsOfInterest` и поэтому всегда выходит до `applyConstraints`.**
- Отношение к ориентации: координаты задаются относительно кадра камеры, а не экрана. Chrome
  поворачивает видео, но в `SetPhotoOptionsTask` точка накладывается на `activeArray` без учёта
  поворота сенсора. В портретной ориентации x/y могут оказаться повёрнуты. Для центральной
  точки (0,5; 0,5), основного случая сканера, это не важно. Произвольный tap нужно проверить на
  устройстве.

## 4. `ImageCapture.takePhoto()` / `grabFrame()`

Поддержка: Chrome 59+ на Android и десктопе
([Chrome blog](https://developer.chrome.com/blog/imagecapture)). Реализация на Android (`C2`
[998–1086](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java#998),
`CrPhotoSessionListener` 286–330, `CrPhotoReaderListener` 333–385):

1. Размер: ближайший к `PhotoSettings.imageWidth/imageHeight` из
   `getOutputSizes(ImageFormat.JPEG)` (`findClosestSizeInArray`, 1456–1474). **Без явных
   размеров функция берёт первый элемент массива** (diff = 0 для всех). Порядок Android не
   гарантирует, но на практике первым обычно идёт максимальный размер. Надёжнее передавать
   `takePhoto({imageWidth: caps.imageWidth.max})` из `getPhotoCapabilities()`.
2. Максимум ограничен обычной `SCALER_STREAM_CONFIGURATION_MAP`. Полное разрешение
   ultra-high-resolution сенсоров (50 МП без бининга) доступно только через
   `SCALER_STREAM_CONFIGURATION_MAP_MAXIMUM_RESOLUTION` и `SENSOR_PIXEL_MODE_MAXIMUM_RESOLUTION`
   ([CameraCharacteristics](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#SCALER_STREAM_CONFIGURATION_MAP_MAXIMUM_RESOLUTION)).
   Chrome их не использует. Для A55 ожидаем ~4080×3060 (12,5 МП), подтвердить по
   `imageWidth.max`.
3. Создаётся **новая capture-сессия только с JPEG-поверхностью** (`TEMPLATE_STILL_CAPTURE`).
   Превью-сессия при этом закрывается, видеотрек замирает. После получения JPEG вызывается
   `createPreviewObjectsAndStartPreview…` (строка 383), и превью пересоздаётся с
   `TEMPLATE_PREVIEW`. Спецификация допускает это: «Devices MAY temporarily stop streaming data»
   с событиями mute/unmute. Длительность паузы зависит от устройства, её надо замерить.
4. В снимок копируются текущие настройки (`configureCommonCaptureSettings`): AF-режим
   (continuous), AF/AE-регионы, **кроп зума**, torch. **AF-trigger и ожидание сходимости AF/AE
   не делаются.** Precapture запускается только при `fillLightMode`. Снимок — один `capture()`
   в свежей сессии. Риск: смаз или недоэкспозиция. Положение линзы на практике обычно
   сохраняется, но на A55 это нужно проверить.
5. `grabFrame()` возвращает `ImageBitmap` в разрешении видео, без перерыва потока.

Вывод для запасного пути «Сделать фото» (тикет 06): `takePhoto()` даёт ~в 2,5 раза больше
линейного разрешения, чем 1080p-видео. Но это ценой паузы превью и без гарантии фокуса. Нужен
замер на A55: сравнить долю декодируемых `takePhoto` и лучшего по резкости кадра из видео.
`<input type="file" capture="environment">` открывает системную камеру с нормальным AF и
полным разрешением. Это ортогональный вариант, он уже покрыт вкладкой «Файл».

## 5. Практические приёмы для мелких кодов

- **Зум ~2× и держать телефон дальше.** Основная камера фокусируется не ближе ~7–10 см
  (точное значение — `focusDistance.min` или `LENS_INFO_MINIMUM_FOCUS_DISTANCE`). Пользователь,
  приближая мелкий QR, легко подносит телефон ближе этой дистанции, и кадр становится
  нерезким. При 2× тот же размер QR в кадре получается с вдвое большего расстояния. Оценка для
  горизонтального FOV основной камеры ~65–70°: кадр шириной ≈1,3·d. QR 25 мм при 1× на 15 см
  занимает ≈250 px из 1920; при 2× та же величина получается на ~25–30 см, далеко за минимальной
  дистанцией фокуса. Кроп до ~2× к тому же не теряет детализацию (п. 2.1).
- **Верхняя граница зума.** Выше `ширина сенсора / ширина видео` (~2× при 1080p) кроп только
  растягивает пиксели, и растёт смаз от дрожания (FOV меньше — дрожание заметнее). Для автозума
  разумный коридор 1,5–3×.
- **Не уходить на сверхширокую/макро.** Сверхширокая (фикс-фокус, низкое угловое разрешение)
  для мелкого QR хуже основной с зумом. Макро 5 МП с фиксированным фокусом на ~3–4 см попадает
  в фокус только на одном расстоянии и тоже уступает. Через `zoom` Chrome на них и не
  переключит.
- **Резолюция видео.** Запрашивать 1920×1080 (ideal) у **явно выбранной** основной камеры.
  STRICH по умолчанию берёт 720p и советует «full-hd for dense 2D or long 1D codes»
  ([STRICH docs](https://docs.strich.io/the-popup-scanner.html),
  [FrameSourceConfiguration](https://docs.strich.io/reference/interfaces/FrameSourceConfiguration.html)).
  Смена разрешения через `applyConstraints({width, height})` переконфигурирует источник, и её
  нельзя смешивать с `zoom` в одном вызове.
- **Точка интереса в центре.** После каждого изменения зума повторять
  `applyConstraints({advanced: [{pointsOfInterest: [{x: 0.5, y: 0.5}]}]})`, если поддерживается
  (п. 3), чтобы AF/AE мерили по центральной зоне с чеком, а не по фону.
- **Torch** доступен только у камеры со вспышкой. Это ещё и признак основной камеры.

## 6. Что подтвердить на A55 (вход для тикета 01)

Для каждой задней камеры из `enumerateDevices()` записать:

- `label`, `getSettings()` (`deviceId`, `facingMode`, `width`, `height`, `zoom`, `focusMode`,
  `pointsOfInterest`);
- `getCapabilities()` (`zoom`, `focusMode`, `focusDistance`, `torch`, `width`, `height`);
- `new ImageCapture(track).getPhotoCapabilities()` (`imageWidth`, `imageHeight`);
- какую камеру выбирает `facingMode: 'environment'` с `width/height ideal 1920×1080` и без них;
- время паузы превью при `takePhoto()`, фактический размер JPEG, резкость снимка;
- сходимость `getSettings().zoom` после `applyConstraints({advanced: [{zoom: 2}]})` и реакцию
  на `zoom > max`.

## Источники

- Chromium `1ada170a`:
  [VideoCaptureCamera2.java](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/java/src/org/chromium/media/VideoCaptureCamera2.java),
  [video_capture_device_factory_android.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/media/capture/video/android/video_capture_device_factory_android.cc),
  [image_capture.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/imagecapture/image_capture.cc),
  [media_stream_track_impl.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/mediastream/media_stream_track_impl.cc),
  [media_stream_constraints_util_video_device.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/third_party/blink/renderer/modules/mediastream/media_stream_constraints_util_video_device.cc),
  [media_devices_permission_checker.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/content/browser/media/media_devices_permission_checker.cc),
  [media_stream_devices_controller.cc](https://chromium.googlesource.com/chromium/src/+/1ada170acc1f5bc73b068c4f2cd075882dcd1235/components/webrtc/media_stream_devices_controller.cc).
- W3C: [MediaStream Image Capture (Editor's Draft)](https://w3c.github.io/mediacapture-image/),
  [w3c/mediacapture-extensions#20](https://github.com/w3c/mediacapture-extensions/issues/20).
- Android: [CameraManager](https://developer.android.com/reference/android/hardware/camera2/CameraManager),
  [CaptureRequest](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest),
  [CameraCharacteristics](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics).
- Chrome: [ImageCapture blog (2016)](https://developer.chrome.com/blog/imagecapture),
  [web.dev: camera pan/tilt/zoom](https://web.dev/articles/camera-pan-tilt-zoom).
- Практика: [Scandit SDK cameraAccess.ts](https://unpkg.com/scandit-sdk@4.6.1/src/lib/cameraAccess.ts),
  [STRICH docs](https://docs.strich.io/reference/interfaces/FrameSourceConfiguration.html),
  [Dynamsoft: camera zoom](https://dynamsoft.com/codepool/camera-zoom-control-on-web.html).
