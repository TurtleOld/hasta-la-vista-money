# Сигналы декодера zxing-wasm для автозума и подсказок

Исследование для тикета `.scratch/receipt-camera-autoscan/issues/03-zxing-wasm-detection-signals.md`.
Дата: 2026-10-14. Версии: `zxing-wasm` 3.1.3 (установлена в `node_modules`),
вшитый `zxing-cpp` на коммите
[`a17fd9dc`](https://github.com/zxing-cpp/zxing-cpp/tree/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f)
(сабмодуль тега `v3.1.3` в Sec-ant/zxing-wasm).

## Коротко

- **Да, позицию нераспознанного QR получить можно, но не всегда.** С `returnErrors: true`
  `readBarcodes` возвращает результат с `isValid: false`, непустым `error`
  (`"ChecksumError @ ..."` / `"FormatError ..."`) и **полной `position`**, если детектор
  нашёл три finder-паттерна и смог выбрать сетку модулей, а упал уже декодер
  (Reed-Solomon, format info). Если finder-паттерны не найдены (сильный расфокус,
  код слишком мелкий), результата нет вообще, даже с `returnErrors`.
- **У результата есть всё нужное для автозума:** `position` (4 угла в пикселях
  переданного кадра), `orientation` (градусы), `isMirrored`, `isInverted`, `format`,
  `error`, `symbol` (сэмплированная сетка модулей), `extra` (JSON с `Version`,
  `ECLevel`, `DataMask`, `UEC`). По `position` и `Version` считается размер модуля в
  пикселях.
- **`tryHarder` и `tryDenoise` дорогие только на кадрах без результата.** Замер на
  десктопе (Ryzen 7 9700X, Node 26, та же wasm-сборка): полный кадр 1920x1080 без
  успеха — около 13 мс с текущими опциями, около 7 мс без `tryDenoise`, около 4–5 мс в
  минимальном режиме. Центральный кроп 777x777 — около 2 мс. На телефоне ожидаемо в
  3–6 раз медленнее (это оценка, на устройстве не мерили).
- **Оценка резкости и яркости дешёвая:** дисперсия Лапласиана + средняя яркость +
  доля пересвеченных пикселей на прореженной в 4 раза сетке (480x270 из 1080p)
  стоит около 0,4 мс на десктопе. В бюджет цикла 120 мс укладывается с запасом.
- **Ловушка:** у нас стоит `maxNumberOfSymbols: 1`. С `returnErrors: true` первый же
  результат с ошибкой засчитывается в лимит и останавливает перебор слоёв
  пирамиды, инверсии и denoise. На синтетике это успех не ухудшило, но риск реальный
  (см. раздел 2.3).

## 1. Поля `ReadResult`

Источник: `node_modules/zxing-wasm/dist/es/bindings/readResult.d.ts`, `position.d.ts`,
`barcodeSymbol.d.ts` (v3.1.3). Заполняются в
[`ZXingWasm.cpp` (v3.1.3)](https://github.com/Sec-ant/zxing-wasm/blob/v3.1.3/src/cpp/ZXingWasm.cpp),
функция `readBarcodes`: каждое поле копируется из `ZXing::Barcode`.

| Поле | Что это | Полезно для |
|---|---|---|
| `isValid` | Декодирован без ошибок | Отличить «найден, но не прочитан» |
| `error` | `""` или `ToString(Error)`: `"FormatError"`, `"ChecksumError"`, `"Unsupported"` + `(msg)` + `@ file:line` ([Error.cpp](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/Error.cpp)) | Причина неудачи |
| `format`, `symbology` | `"QRCode"` и т.п. | — |
| `text`, `bytes`, `bytesECI`, `hasECI`, `contentType` | Содержимое | Чтение чека |
| `position` | `{topLeft, topRight, bottomRight, bottomLeft}`, точки `{x, y}` в пикселях **переданного кадра** | Автозум, рамка-подсказка |
| `orientation` | Поворот в градусах (int) | Подсказка «поверните» (не обязательно) |
| `isMirrored` | Зеркальный символ (только QR и DataMatrix) | — |
| `isInverted` | Найден в инвертированном изображении | — |
| `symbol` | `{data: Uint8ClampedArray, width, height}`, сетка модулей 1 px = 1 модуль (experimental) | Отладка |
| `extra` | Строка JSON: `DataMask`, `ECLevel`, `Version`, `UEC` (запас коррекции ошибок в `[0, 1]`) и др. (experimental) | Размер модуля, «насколько близко к отказу» |
| `version`, `ecLevel`, `readerInit` | Deprecated, дублируют `extra` | — |
| `symbologyIdentifier`, `sequence*`, `lineCount` | Для нас бесполезны | — |

Важные детали:

- **Координаты в системе переданного кадра.** Для найденных на уменьшенных слоях
  пирамиды `zxing-cpp` масштабирует `position` обратно
  ([ReadBarcode.cpp L293-294](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/ReadBarcode.cpp#L293-L294)).
  Мы передаём центральный кроп, поэтому к координатам надо прибавить `region.x/y` из
  `calculateCenteredScanRegion`.
- **Размер модуля** = длина стороны (`|topRight - topLeft|`) / (17 + 4·`Version`).
  `Version` есть в `extra` и у результатов с ошибкой. Проверено: для синтетического QR
  версии 4 с модулем 4 px позиция дала сторону 132 px = 33 модуля × 4 px.
- **`UEC`** для успешного чтения: `1.0` — запас полный, меньше — кадр деградирует.
  У результатов с ошибкой `0.0`.
- Если C++ бросил исключение, `readBarcodes` возвращает один «результат» только с
  `error = e.what()` (ZXingWasm.cpp, ветка `catch`). Такой результат нужно
  отфильтровать по `format === 'None'` или по отсутствию `position`.

## 2. `returnErrors`: что именно возвращается

### 2.1. Логика в zxing-cpp

[`QRReader.cpp` L61-147](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/qrcode/QRReader.cpp#L61-L147):

1. `FindFinderPatterns(binImg, tryHarder)` ищет концентрические finder-паттерны.
2. `GenerateFinderPatternSets` → для каждой тройки `SampleQR(...)` строит сетку модулей.
3. `Decode(detectorResult.bits())`, и если `decoderResult.isValid(_opts.returnErrors())`,
   результат кладётся в ответ вместе с `detectorResult`, то есть с позицией.

`DecoderResult::isValid(includeErrors)` возвращает `true` для результатов с ошибкой,
если `includeErrors`
([DecoderResult.h L48-51](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/DecoderResult.h#L48-L51)).
`MultiFormatReader::read` выкидывает невалидные результаты, только если
`returnErrors` выключен
([MultiFormatReader.cpp](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/MultiFormatReader.cpp)).

Позиции **не будет**, если:

- не нашлись три finder-паттерна (размытие сильнее модуля, код слишком мелкий);
- `SampleQR` сделал `co_return`: не оценилась размерность или у версии ≥ 7 мусорные
  version bits ([QRDetector.cpp L460+](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/qrcode/QRDetector.cpp#L460)).
  Для QR ФНС (около 70–100 символов, версия 4–6) проверка version bits не
  срабатывает, она только для версий ≥ 7.

Отдельного API «кандидат в QR без сетки» (одиночные finder-паттерны, примерная рамка)
в zxing-cpp/zxing-wasm 3.1.x **нет**.

### 2.2. Постобработка в `ReadBarcodes`

[`ReadBarcode.cpp` L308-316](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/ReadBarcode.cpp#L308-L316):
при `returnErrors`, если результат с ошибкой пересекается по bounding box с
результатом без неё, ошибочный удаляется. Два ошибочных результата с разными позициями
не дедуплицируются: на замере с `maxNumberOfSymbols: 2` пришли два `ChecksumError` с
чуть разными углами и разным `orientation` (0 и 1). Дедупликацию по IoU нужно делать на
стороне JS.

### 2.3. Взаимодействие с `maxNumberOfSymbols: 1`

Цикл в `ReadBarcodes`
([L277-306](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/ReadBarcode.cpp#L277-L306))
делает `--maxSymbols` на любой новый результат, включая ошибочный, и при
`maxSymbols <= 0` сразу возвращается. Значит, с `maxNumberOfSymbols: 1` +
`returnErrors: true` ошибка на полноразмерном слое **останавливает** попытки на
уменьшенных слоях, с инверсией и с denoise, которые иначе могли бы код прочитать.
Это видно по времени: размытый кадр с текущими опциями — 13,2 мс (перебор всех
проходов), с `returnErrors` — 5,5 мс (выход после первого прохода).

Варианты:

- `maxNumberOfSymbols: 2` + `returnErrors: true`: перебор продолжается после ошибки,
  а ошибочный дубль удаляется пост-фильтром, если найден валидный. Цена — при
  успехе на первом слое сканирование продолжается в поисках второго символа
  (замер: 13 мс вместо 5,5 мс на успешном 1080p, 4 мс вместо 1,6 мс на кропе).
- Основной проход без `returnErrors`, а при неудаче отдельный дешёвый проход с
  `returnErrors` на том же кадре (например, на кропе или раз в N кадров).

Синтетический прогон (60 комбинаций: модуль 2–8 px, blur 0–2, шум, блик 20 %)
разницы в числе успехов не показал: 22/60 у всех вариантов. При этом
`returnErrors` дал позицию ещё в 26 случаях, где декодирование не удалось.
Синтетика без перспективы и текстуры, так что на реальных кадрах ловушку
нужно проверить.

## 3. Стоимость `tryHarder` / `tryDenoise` / прочих опций

### 3.1. Что делает каждая опция для QR (по исходникам)

- **`tryHarder`**: шаг строк при поиске finder-паттернов. Без него
  `skip = 3·height / (4·97)` (≈ 8 для высоты 1080, ≈ 6 для 777), с ним — всегда 3
  ([QRDetector.cpp L52-70](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/qrcode/QRDetector.cpp#L52-L70)).
  На уменьшенных слоях (высота ≤ 388) шаг и так 3, разницы нет. Ещё он влияет на
  порядок 1D-ридеров, но для `formats: ['QRCode']` их нет.
- **`tryRotate`**: в `QRReader.cpp` не используется. QR-детектор инвариантен к
  повороту, опция нужна только 1D-кодам. Для нас это no-op.
- **`tryDownscale`**: пирамида с порогом `downscaleThreshold = 500` и
  `downscaleFactor = 3`
  ([ReadBarcode.cpp L150-200](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/ReadBarcode.cpp#L150-L200)):
  1920x1080 → 640x360 → 213x120 (3 слоя), 777x777 → 259x259 (2 слоя).
- **`tryInvert`**: +1 проход на каждый слой.
- **`tryDenoise`** (experimental, в сборке zxing-wasm включён:
  `ZXING_EXPERIMENTAL_API ON` в
  [CMakeLists.txt](https://github.com/Sec-ant/zxing-wasm/blob/v3.1.3/src/cpp/CMakeLists.txt)):
  +1 проход на каждый слой с морфологическим закрытием битовой матрицы
  ([ReadBarcode.cpp L264-291](https://github.com/zxing-cpp/zxing-cpp/blob/a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f/core/src/ReadBarcode.cpp#L264-L291)).

Итого на кадре без результата при текущих опциях: 3 слоя × (обычный + инверсия +
closing) = **9 чтений** для 1080p и 6 для кропа. С `maxNumberOfSymbols: 1` при
успехе перебор обрывается на первом удачном проходе.

Сборка однопоточная, без SIMD-флагов (CMakeLists v3.1.3). Конвертация RGBA → Lum
делается в JS внутри `readBarcodes` (`share.js`, цикл
`306·R + 601·G + 117·B >> 10`) и входит в замеры ниже.

### 3.2. Замер

Скрипт на Node 26.8.1, `zxing-wasm/full` 3.1.3 (тот же C++-ридер, что и в
`zxing-wasm/reader`), AMD Ryzen 7 9700X. Синтетический QR ФНС (версия 4, ECL M) на
сером шумном фоне, медиана из 7 запусков. Опции «current» — как в
`static/js/pages/receipt-qr-worker.js`.

| Кадр | current | без denoise | без tryHarder | без harder+denoise | minimal¹ |
|---|---|---|---|---|---|
| 1920x1080, пусто | 7,6 | 6,0 | 7,5 | 5,9 | 3,9 |
| 777x777 кроп, пусто | 1,9 | 1,6 | 1,9 | 1,5 | 0,9 |
| 1920x1080, QR 4 px/модуль (успех) | 5,7 | 5,5 | 5,0 | 5,0 | 4,6 |
| 1920x1080, QR 4 px, blur (неудача, но паттерны видны) | 13,2 | 7,1 | 11,9 | 6,3 | 4,7 |
| 1920x1080, QR 6 px, блик (неудача) | 14,0 | 7,6 | 12,6 | 6,7 | 4,7 |
| 777x777, QR 4 px (успех) | 1,7 | 1,6 | 1,5 | 1,5 | 1,4 |

¹ minimal = `tryHarder`, `tryDenoise`, `tryInvert`, `tryDownscale` выключены. Время в мс.

Выводы:

- Самые дорогие кадры — «код в кадре, но не читается»: denoise почти удваивает их
  стоимость (+6–7 мс на десктопе). `tryHarder` добавляет около 1 мс.
- На синтетике ни `tryDenoise`, ни `tryHarder` не дали ни одного дополнительного
  успеха (sweep 60 кадров). Реальные камерные кадры (шум сенсора, JPEG-артефакты,
  перспектива) — как раз тот случай, ради которого они существуют, поэтому решение
  выключать их стоит принимать по замеру на устройстве.
- **Перенос на телефон — оценка, не измерение:** wasm на мобильном ARM среднего
  класса обычно в 3–6 раз медленнее десктопного x86. Ожидаемо 1080p-кадр без успеха
  стоит 25–80 мс, кроп 777 — 5–12 мс. Цикл 120 мс укладывается, но полный кадр с
  denoise может съедать заметную долю бюджета. Рекомендация: мерить в воркере
  `performance.now()` вокруг `readBarcodes` и возвращать `decodeMs` в `scan-result`
  для диагностики (пересекается с тикетом 01).

## 4. Дешёвая оценка резкости и яркости в воркере

Метрика: дисперсия Лапласиана (variance of Laplacian, классический фокус-критерий,
Pech-Pacheco et al., ICPR 2000) по 4-соседнему ядру `[0 1 0; 1 -4 1; 0 1 0]` на
яркости, взятой с шагом `step` по исходному RGBA (без отдельного ресайза). Вместе с ней
в том же проходе считаются средняя яркость и доля пикселей с `Y ≥ 250` (блики).

```js
function frameQuality({ data, width: W, height: H }, step = 4) {
  const w = Math.floor(W / step), h = Math.floor(H / step);
  const g = new Uint8Array(w * h);
  let sum = 0, clipped = 0;
  for (let y = 0; y < h; y++) {
    const row = y * step * W;
    for (let x = 0; x < w; x++) {
      const i = (row + x * step) << 2;
      const v = (306 * data[i] + 601 * data[i + 1] + 117 * data[i + 2] + 512) >> 10;
      g[y * w + x] = v; sum += v; if (v >= 250) clipped++;
    }
  }
  let s = 0, s2 = 0, n = 0;
  for (let y = 1; y < h - 1; y++)
    for (let x = 1; x < w - 1; x++) {
      const k = y * w + x;
      const lap = g[k - 1] + g[k + 1] + g[k - w] + g[k + w] - 4 * g[k];
      s += lap; s2 += lap * lap; n++;
    }
  const m = s / n;
  return { mean: sum / (w * h), lapVar: s2 / n - m * m, clippedPct: (100 * clipped) / (w * h) };
}
```

Замер (тот же десктоп, 1920x1080):

| step | сетка | время |
|---|---|---|
| 4 | 480x270 | 0,41 мс |
| 2 | 960x540 | 1,7 мс |
| 1 | 1920x1080 | 9,6 мс |

Значения `lapVar` на синтетике: резкий QR — 2507, blur r=2 — 137, blur r=3 — 32.
Метрика различает расфокус на порядки.

Рекомендации:

- `step = 4` на кропе или полном кадре: на телефоне ожидаемо 1–3 мс. Считать на том
  же `ImageData`, который уже пришёл в воркер, до или после `readBarcodes`.
- Абсолютные пороги ненадёжны: шум сенсора и текстура фона завышают `lapVar`, а
  прореживание (aliasing) делает метрику чувствительной к мелкому шуму. Лучше
  сравнивать с собственным скользящим максимумом за сессию («резкость упала в N
  раз») и/или считать метрику внутри `position`, если есть результат с ошибкой.
- Для мелкого QR (модуль 2–3 px) прореживание в 4 раза теряет модульную структуру.
  Тогда резкость кода лучше оценивать по ROI вокруг `position` с `step = 1`. ROI
  маленький, это дёшево.
- Яркость: `mean` < ~50 → «мало света», `clippedPct` в ROI кода > нескольких
  процентов → «блик». Пороги подбираются эмпирически на устройстве.
- Подсказку можно строить на сочетании сигналов: нет результата + низкий `lapVar` →
  «не в фокусе / слишком близко»; `ChecksumError` с позицией + высокий `clippedPct` в
  ROI → «блик, наклоните»; позиция есть и модуль < ~3 px → «ближе / зум»; ничего нет
  при нормальной резкости → «наведите на QR».

## 5. Что это значит для автозума и подсказок

1. Включить `returnErrors` и учесть раздел 2.3: либо `maxNumberOfSymbols: 2` с
   дедупликацией в JS, либо отдельный проход.
2. Из `position` + `extra.Version` считать размер модуля в пикселях (в координатах
   видео, с поправкой на offset кропа). Это основной вход для автозума.
3. Когда кода нет совсем (finder-паттерны не найдены), zxing сигнала не даст. Здесь
   работают только `lapVar` / `mean` / `clippedPct` всего кадра.
4. `tryRotate` для QR бесполезен, его можно выключить без потерь. `tryDenoise` —
   главный кандидат на выключение или прореживание (например, только на кропе или
   раз в N кадров), если замер на A55 покажет, что он съедает бюджет.

## Воспроизведение замеров

Скрипт генерирует QR через `writeBarcode` из `zxing-wasm/full`, рисует его в
синтетическом кадре (шум, box-blur, «блик» — белый круг поверх данных) и прогоняет
`readBarcodes` с вариантами опций. Скрипт в репозиторий не добавлен. Ключевые
моменты: `prepareZXingModule({ overrides: { wasmBinary: readFileSync('.../zxing_full.wasm') } })`
и передача `{ data, width, height }` как ImageData.
