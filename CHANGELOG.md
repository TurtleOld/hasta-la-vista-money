# История изменений

## [2.9.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.8.1...v2.9.0) (2026-07-12)


### Features

* **finance_account:** remember accounts from last transfer ([#889](https://github.com/TurtleOld/hasta-la-vista-money/issues/889)) ([474362c](https://github.com/TurtleOld/hasta-la-vista-money/commit/474362cd588d321f820848f69ed024622d7783c9))
* **receipts:** improve paper qr scanning with zxing wasm ([#890](https://github.com/TurtleOld/hasta-la-vista-money/issues/890)) ([acb669b](https://github.com/TurtleOld/hasta-la-vista-money/commit/acb669b398bf14cee8119f56bf5ca9ed61de4a89))


### Bug Fixes

* **transactions:** use current date when copying operations ([#887](https://github.com/TurtleOld/hasta-la-vista-money/issues/887)) ([53ef821](https://github.com/TurtleOld/hasta-la-vista-money/commit/53ef82181a3d0c2e2b6b624a8f452821c9fce661))

## [2.8.1](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.8.0...v2.8.1) (2026-07-11)


### Bug Fixes

* **finance_account:** make balance updates atomic ([#885](https://github.com/TurtleOld/hasta-la-vista-money/issues/885)) ([02f7c78](https://github.com/TurtleOld/hasta-la-vista-money/commit/02f7c78e57233d121e924bc67557e19e1925f16f))

## [2.8.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.7.2...v2.8.0) (2026-07-04)


### Features

* **finance_account:** add category search with autocomplete in operation form ([#876](https://github.com/TurtleOld/hasta-la-vista-money/issues/876)) ([842d822](https://github.com/TurtleOld/hasta-la-vista-money/commit/842d8228fefd96d4f0b04b85dd3c5b3c45c982be))


### Bug Fixes

* **theme:** hide dismissed message toast so it stops blocking clicks ([#877](https://github.com/TurtleOld/hasta-la-vista-money/issues/877)) ([b8ba2c9](https://github.com/TurtleOld/hasta-la-vista-money/commit/b8ba2c909e79742e882048098e4d3b70b86eb115))
* **transactions:** auto-advance to minutes after typing hours in datetime picker ([#879](https://github.com/TurtleOld/hasta-la-vista-money/issues/879)) ([599d426](https://github.com/TurtleOld/hasta-la-vista-money/commit/599d426c8d4c377f314d250e304159b333b9bb93))

## [2.7.2](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.7.1...v2.7.2) (2026-07-04)


### Bug Fixes

* **receipts:** set standard 1x camera zoom for QR scanning ([#874](https://github.com/TurtleOld/hasta-la-vista-money/issues/874)) ([0e8a0db](https://github.com/TurtleOld/hasta-la-vista-money/commit/0e8a0dbe289b2fc0b7fce82bd818f1beea0cd259))

## [2.7.1](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.7.0...v2.7.1) (2026-07-02)


### Bug Fixes

* **receipts:** improve camera autofocus for QR scanning on paper receipts ([#872](https://github.com/TurtleOld/hasta-la-vista-money/issues/872)) ([fa3b70e](https://github.com/TurtleOld/hasta-la-vista-money/commit/fa3b70e385ade5c74c890b37792d27fe47acdaa6))

## [2.7.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.6.0...v2.7.0) (2026-07-01)


### Features

* **finance_account:** floating preview sidebar, previous month filter, camera error fix ([#870](https://github.com/TurtleOld/hasta-la-vista-money/issues/870)) ([b36e02d](https://github.com/TurtleOld/hasta-la-vista-money/commit/b36e02dfeb178d767b050c0c4a786a482526ea57))

## [2.6.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.5.0...v2.6.0) (2026-07-01)


### Features

* **receipts:** add mobile camera QR scanning for receipt upload ([#868](https://github.com/TurtleOld/hasta-la-vista-money/issues/868)) ([45c06ab](https://github.com/TurtleOld/hasta-la-vista-money/commit/45c06ab16d5242ef2a1d322df8300a585b66ad40))

## [2.5.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.4.1...v2.5.0) (2026-06-21)


### Features

* **users:** balance reconciliation — LLM categorization and statement verification ([#861](https://github.com/TurtleOld/hasta-la-vista-money/issues/861)) ([41d591c](https://github.com/TurtleOld/hasta-la-vista-money/commit/41d591c43bc362665958b64a2653d5267d855e79))


### Bug Fixes

* env vars, copy redirect, datetime defaults, mobile receipt preview ([#863](https://github.com/TurtleOld/hasta-la-vista-money/issues/863)) ([81c3742](https://github.com/TurtleOld/hasta-la-vista-money/commit/81c3742177009b8f0f7ade08ca98662b1040f278))

## [2.4.1](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.4.0...v2.4.1) (2026-06-08)


### Bug Fixes

* **finance_account:** lock transfer row on delete ([#855](https://github.com/TurtleOld/hasta-la-vista-money/issues/855)) ([5311ae9](https://github.com/TurtleOld/hasta-la-vista-money/commit/5311ae9fb24e1b5bf377218c91f874588443d03d))

## [2.4.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.3.1...v2.4.0) (2026-06-08)


### Features

* **finance_account:** show and delete transfers ([#853](https://github.com/TurtleOld/hasta-la-vista-money/issues/853)) ([6b03451](https://github.com/TurtleOld/hasta-la-vista-money/commit/6b03451415822b34d0ef4f8940b24a54934c5009))


### Bug Fixes

* **deps:** update dependency django to v6.0.6 ([#852](https://github.com/TurtleOld/hasta-la-vista-money/issues/852)) ([cf71dd8](https://github.com/TurtleOld/hasta-la-vista-money/commit/cf71dd8eee6c0bf80eb67f3391d272601c3a5959))

## [2.3.1](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.3.0...v2.3.1) (2026-06-04)


### Bug Fixes

* correct transactions static mobile layout ([#847](https://github.com/TurtleOld/hasta-la-vista-money/issues/847)) ([5fd05ef](https://github.com/TurtleOld/hasta-la-vista-money/commit/5fd05efa42b08df19b1eaecabef6e55e7844a7c8))

## [2.3.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.2.0...v2.3.0) (2026-06-03)


### Features

* **users:** add expires_at to FamilyInvite model ([#843](https://github.com/TurtleOld/hasta-la-vista-money/issues/843)) ([0ab004a](https://github.com/TurtleOld/hasta-la-vista-money/commit/0ab004a4bb5efd24d9d7c3926018ad49aa69f689))


### Documentation

* **readme:** refresh project overview and documentation links ([83640d2](https://github.com/TurtleOld/hasta-la-vista-money/commit/83640d29e496562ab06a8ed4c82bc7b8be781af4))
* **readme:** refresh project overview and documentation links ([6706f8f](https://github.com/TurtleOld/hasta-la-vista-money/commit/6706f8fc41fedc60ac88897386d03f95b520bd30))

## [2.2.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.1.1...v2.2.0) (2026-06-02)


### Features

* **system:** enrich audit log with object names and human-readable field labels ([4c8a5ba](https://github.com/TurtleOld/hasta-la-vista-money/commit/4c8a5bacd5946dca7ec0da1764b900f79120c797))


### Bug Fixes

* **receipts:** apply refund to balance for return receipt operation types ([30a4e6a](https://github.com/TurtleOld/hasta-la-vista-money/commit/30a4e6add610a69c2a7bf8af70fd491c9b82ed01))


### Documentation

* **agents:** update AGENTS.md ([29ccdc4](https://github.com/TurtleOld/hasta-la-vista-money/commit/29ccdc4b37d7efcce502ada442fe16b067bef570))

## [2.1.1](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.1.0...v2.1.1) (2026-06-02)


### Bug Fixes

* **finances:** fix E501 line too long in _pre_period_debt_for_card docstring ([ae9488f](https://github.com/TurtleOld/hasta-la-vista-money/commit/ae9488fcdd3d72cefcae113d45964def894deb83))
* **finances:** include income repayments and pre-period debt in credit card payment schedule ([b11dd2c](https://github.com/TurtleOld/hasta-la-vista-money/commit/b11dd2c9e615d425e3a198fd9e3ed247bdbc6b41))
* **finances:** include income repayments and pre-period debt in credit card payment schedule ([f3534cc](https://github.com/TurtleOld/hasta-la-vista-money/commit/f3534cc2075a2ac48606851cbbf5ce64113ce4a0))

## [2.1.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v2.0.0...v2.1.0) (2026-06-01)


### Features

* **api:** integrate login rate throttling into token obtain view ([8894a57](https://github.com/TurtleOld/hasta-la-vista-money/commit/8894a57f5e2a9df72e1b7fd034b2edd695afd708))
* **api:** integrate login rate throttling into token obtain view ([d88894a](https://github.com/TurtleOld/hasta-la-vista-money/commit/d88894a69783bcd86233e29a3f8415932d485c4a))
* **receipts:** improve pending receipt validation ([e1f0e4a](https://github.com/TurtleOld/hasta-la-vista-money/commit/e1f0e4a2d66669512dc14ce523b6229b8537525b))
* **receipts:** show pending receipt warnings ([f91b1a0](https://github.com/TurtleOld/hasta-la-vista-money/commit/f91b1a088e17a06941914b3c98ccfc2a23765424))


### Bug Fixes

* **sberbank:** correct grace period debt calculation ([2c3a63a](https://github.com/TurtleOld/hasta-la-vista-money/commit/2c3a63aaca2f89a7d0f89f63c9c199f0ccdf0a09))
* **sberbank:** correct grace period debt calculation ([70d05a9](https://github.com/TurtleOld/hasta-la-vista-money/commit/70d05a9d7377fa64d20089a96148b7ee29111289))

## [2.0.0](https://github.com/TurtleOld/hasta-la-vista-money/compare/v1.10.0...v2.0.0) (2026-05-31)


### ⚠ BREAKING CHANGES

* **users:** default group filter semantics changed to 'my' (only own accounts) which may affect URLs, saved filters, or dashboard defaults.
* **receipt-inference:** The receipt-llm service and all LLAMA-related environment variables are removed. Applications must configure RECEIPT_INFERENCE_BACKEND to 'paddleocr_vl' and adjust accordingly.
* **inference:** Updated prompt expectations may require adjustments in LLM response handling.

### Features

* **accounts:** redesign accounts dashboard with hero, swipe cards & quick add ([cd1071d](https://github.com/TurtleOld/hasta-la-vista-money/commit/cd1071ddafc335f7a2972b18b950f7cf14c32da7))
* **accounts:** show credit debt in account hero ([dcbd25f](https://github.com/TurtleOld/hasta-la-vista-money/commit/dcbd25f3a4f03e3c4147a48a8a7b33aee6aec927))
* **accounts:** show credit debt in account hero ([2e6eff9](https://github.com/TurtleOld/hasta-la-vista-money/commit/2e6eff9e65b3749a9b3feef35a0c7e8de50128a3))
* add health checks and audit log ([8eea671](https://github.com/TurtleOld/hasta-la-vista-money/commit/8eea6711a866725bb3ae7c04e4ac3cc1af828a73))
* add health checks and audit log ([d404741](https://github.com/TurtleOld/hasta-la-vista-money/commit/d40474190c070e097eec7b816f70ed7812eed110))
* **api:** report runtime dependency status in readiness checks ([1275154](https://github.com/TurtleOld/hasta-la-vista-money/commit/1275154193f6cf33188a78e99eddb3be5c8ee571))
* **auth:** redesign login & registration with design tokens ([b057676](https://github.com/TurtleOld/hasta-la-vista-money/commit/b057676dfad2c8618300c7c166186f94aff8dd7a))
* **auth:** redesign login & registration with design tokens ([8c1f100](https://github.com/TurtleOld/hasta-la-vista-money/commit/8c1f1002354c5dc4ce0c62b1bdeced2b0b7a953f))
* **budget:** add family budget scope ([8a63a67](https://github.com/TurtleOld/hasta-la-vista-money/commit/8a63a677a5633135865539dbc4ad0d258b546a32))
* **budget:** add limits and htmx planning tables ([f70a70a](https://github.com/TurtleOld/hasta-la-vista-money/commit/f70a70a0826cb64da73c6796c0d3cdc813912750))
* **budget:** add limits and htmx planning tables ([9299ea0](https://github.com/TurtleOld/hasta-la-vista-money/commit/9299ea0255ed7b0e40dc3aa774b6d9850a7f9d4f))
* **config:** add environment variables for receipt inference settings ([7f7ecb3](https://github.com/TurtleOld/hasta-la-vista-money/commit/7f7ecb301bbcf7ea6e120e255a29645799c64738))
* **config:** add environment variables for receipt inference settings ([12d04c7](https://github.com/TurtleOld/hasta-la-vista-money/commit/12d04c7646f279b2a50ed4feb0ebdbc753ce41c8))
* **config:** add LLAMA_READINESS_REQUIRED toggle for flexible LLM deployment ([6aefba6](https://github.com/TurtleOld/hasta-la-vista-money/commit/6aefba6afbcf26546b5d6771495c21fc0e0e09e5))
* **config:** add OCR readiness toggle for flexible deployment ([e1e9a18](https://github.com/TurtleOld/hasta-la-vista-money/commit/e1e9a181e9a900e11c8a7e4a242c261868322ae4))
* **date-picker:** integrate Flatpickr for date and datetime inputs ([130ce08](https://github.com/TurtleOld/hasta-la-vista-money/commit/130ce08d11301d9768fd5b0fdecaf6d8bd59d81b))
* **finances:** add combined category management ([e113267](https://github.com/TurtleOld/hasta-la-vista-money/commit/e113267184aa9f817c16a7d435d72320b8093f1f))
* **finances:** add combined finances page with composer form ([c29197b](https://github.com/TurtleOld/hasta-la-vista-money/commit/c29197b535ca6e0d743141260e48ed6ee9b63bb8))
* **finances:** add inline category editing in tree ([c143e58](https://github.com/TurtleOld/hasta-la-vista-money/commit/c143e58caba192b56616a443fec3684c83539c84))
* **finances:** add inline category editing in tree ([bce72f1](https://github.com/TurtleOld/hasta-la-vista-money/commit/bce72f11fe3360774d7b78885b9b4e2b4df11bee))
* **finances:** add save and add another composer action ([5b989df](https://github.com/TurtleOld/hasta-la-vista-money/commit/5b989df0d3face43564e3e56697a8faa2b3a33f0))
* **finances:** add Категории link to operations toolbar ([ec2f1c3](https://github.com/TurtleOld/hasta-la-vista-money/commit/ec2f1c389a6a5029c148c172f48c641352967204))
* **finances:** add Категории link to operations toolbar ([89b28d2](https://github.com/TurtleOld/hasta-la-vista-money/commit/89b28d2c72d1878082739779ee98f13c2f8e2676))
* **finances:** migrate heavy list interactions to HTMX ([9d3cd92](https://github.com/TurtleOld/hasta-la-vista-money/commit/9d3cd92584795ac3c776018e91e73a1fe6be2dee))
* **finances:** migrate heavy list interactions to HTMX ([fff3d54](https://github.com/TurtleOld/hasta-la-vista-money/commit/fff3d54abafa92612ac96f098b6d67277ad124ed))
* **forms:** add default transfer account selection ([62c1af2](https://github.com/TurtleOld/hasta-la-vista-money/commit/62c1af25bb45a81e8f9276f7df2d72e466deba56))
* **forms:** improve transfer account selectors ([88dc96f](https://github.com/TurtleOld/hasta-la-vista-money/commit/88dc96fcf36bb1aca4d6d5302c0bfbc25426105c))
* **inference:** enhance JSON extraction from LLM responses ([1a86ce5](https://github.com/TurtleOld/hasta-la-vista-money/commit/1a86ce5dba1a7eeca2ee9b3db879ecf9cc88fdd8))
* **inference:** enhance JSON extraction from LLM responses ([b4763b3](https://github.com/TurtleOld/hasta-la-vista-money/commit/b4763b34e19df273d1a3e0b656d3831a7ce70e9f))
* **js:** replace vanilla JS UI patterns with Alpine.js ([0c4404e](https://github.com/TurtleOld/hasta-la-vista-money/commit/0c4404e1711b3a342c311e47b28cac8dc4b96750))
* **js:** replace vanilla JS UI patterns with Alpine.js ([887c178](https://github.com/TurtleOld/hasta-la-vista-money/commit/887c178afd40b5cd3a49558b5a71e8cdfb50fda9))
* **js:** split page-specific scripts into esbuild entry points ([2f8eb36](https://github.com/TurtleOld/hasta-la-vista-money/commit/2f8eb361d275f5a2ecc2107f95cf0d7bc3e96355))
* **loan:** align styling with app tokens ([b8f4237](https://github.com/TurtleOld/hasta-la-vista-money/commit/b8f42376a8236a17a9a51878bc03a73a70b0756d))
* **loan:** align styling with app tokens ([2e8c3a3](https://github.com/TurtleOld/hasta-la-vista-money/commit/2e8c3a380beec5df6a060c227403fd2afe20b3da))
* **normalizer:** add marketplace seller name corrections ([88ca1fb](https://github.com/TurtleOld/hasta-la-vista-money/commit/88ca1fbe13251b81f8a497d01bd575c25225fb63))
* **pwa:** add offline support and swipe actions ([50e2554](https://github.com/TurtleOld/hasta-la-vista-money/commit/50e2554c026bbcae68d8b385e2a1342ddcc8c292))
* **pwa:** add offline support and swipe actions ([1f426f4](https://github.com/TurtleOld/hasta-la-vista-money/commit/1f426f453a05c22cd5ff1e12d768eb7b8b548e33))
* **receipt-inference:** add configurable PaddleOCR runtime support ([050b7be](https://github.com/TurtleOld/hasta-la-vista-money/commit/050b7be2cd6e1a11fc00133622f8eabf1695bc2e))
* **receipt-inference:** enable configurable model alias for llama server and improve error handling ([184c4f1](https://github.com/TurtleOld/hasta-la-vista-money/commit/184c4f1e5888434fd543808ef92e5d87fa21afb7))
* **receipt-inference:** enable configurable model alias for llama server and improve error handling ([7806974](https://github.com/TurtleOld/hasta-la-vista-money/commit/7806974786a110e8b3af8c71bffb1fd50b56f83e))
* **receipt-inference:** implement receipt parsing pipeline with OCR override ([63ca311](https://github.com/TurtleOld/hasta-la-vista-money/commit/63ca311de579dfbb46c74812bc4a1356bb4abad9))
* **receipt-inference:** introduce PaddleOCR-VL backend and remove Llama dependency ([8d17047](https://github.com/TurtleOld/hasta-la-vista-money/commit/8d17047bd8f9aac24075e8520bb8a61232195bef))
* **receipt-inference:** introduce PaddleOCR-VL backend and remove Llama dependency ([402498a](https://github.com/TurtleOld/hasta-la-vista-money/commit/402498aee3abeeab15532b91506e9586e79f4ace))
* **receipt:** handle uploaded receipt parse requests ([fad528a](https://github.com/TurtleOld/hasta-la-vista-money/commit/fad528a2b325e9a0ee9a3b2ddb45278b905d1a37))
* **receipts:** add pending receipt background lifecycle ([ca00f8c](https://github.com/TurtleOld/hasta-la-vista-money/commit/ca00f8c6ca3ac8297a3c5d4f9c888a9d858c4183))
* **receipts:** add receipt deletion service with account refund ([4de54cf](https://github.com/TurtleOld/hasta-la-vista-money/commit/4de54cfa92ae9e001240db6ed6c9f2ee6b9b7dac))
* **receipts:** add receipt deletion service with account refund ([fc87e21](https://github.com/TurtleOld/hasta-la-vista-money/commit/fc87e21e813081e65cfdb39299ebc3ca72a954ab))
* **receipts:** add receipt-inference client fallback ([47f068a](https://github.com/TurtleOld/hasta-la-vista-money/commit/47f068a2ed104e381a9d34a08d1e171f4c5cb7e4))
* **receipts:** add retail place field and display seller retail chip ([b863ed0](https://github.com/TurtleOld/hasta-la-vista-money/commit/b863ed0ade37ced5775cae8f3e7b02430d5f7f6b))
* **receipts:** add seller INN and simplify receipt inference ([19f10e9](https://github.com/TurtleOld/hasta-la-vista-money/commit/19f10e9b5a5f77a113096a3172c5c9f38584d521))
* **receipts:** add seller INN and simplify receipt inference ([c4f3eaa](https://github.com/TurtleOld/hasta-la-vista-money/commit/c4f3eaaa52821699bf946dd90ae6ba5abbb71b51))
* **receipts:** integrate FNS QR processing ([2a1b110](https://github.com/TurtleOld/hasta-la-vista-money/commit/2a1b11076fa53faafe8755a04ec16fcee458b961))
* **receipts:** merge text items and add placeholders in PaddleOCR ([a854049](https://github.com/TurtleOld/hasta-la-vista-money/commit/a854049618e2bd5dd7de01cff25538d006bc6c16))
* **receipts:** merge text items and add placeholders in PaddleOCR ([10ea799](https://github.com/TurtleOld/hasta-la-vista-money/commit/10ea7996272b555e2a2887f920c66f3e2f369d85))
* **receipts:** replace group dropdown with chips and add avg receipt stat ([1a96776](https://github.com/TurtleOld/hasta-la-vista-money/commit/1a96776af79107b32b1ddc135dd7ec8bd0a9e225))
* **receipts:** show pending image processing states ([c415efa](https://github.com/TurtleOld/hasta-la-vista-money/commit/c415efaa515a125e30ec03f062a59d9fc1d69834))
* **receipts:** validate parsed receipt payloads ([eadfa74](https://github.com/TurtleOld/hasta-la-vista-money/commit/eadfa748be6f9af78fea3c4fdc368ca9d73000c2))
* **receipts:** validate parsed receipt payloads ([a4609d9](https://github.com/TurtleOld/hasta-la-vista-money/commit/a4609d90cf0537a60097979453e9a86847036fe3))
* **reports:** improve dashboard analytics ([5cec927](https://github.com/TurtleOld/hasta-la-vista-money/commit/5cec9274729fed6f1fa558281c8b652869484833))
* **reports:** improve dashboard analytics ([e7b4b1f](https://github.com/TurtleOld/hasta-la-vista-money/commit/e7b4b1f7c4bd30d435bebd11bd4084ea4bbbb1f3))
* **security:** enhance content security policy by adding style-src URLs ([4424e4f](https://github.com/TurtleOld/hasta-la-vista-money/commit/4424e4f0e78bc0102ab2a6ad768a75c91e8a2bab))
* **security:** enhance content security policy by adding style-src URLs ([325e75d](https://github.com/TurtleOld/hasta-la-vista-money/commit/325e75dbd76da458d17e6785186ac8a2ed3b238c))
* **swipe-list:** enhance swipe functionality and update styles ([30c074a](https://github.com/TurtleOld/hasta-la-vista-money/commit/30c074add37b21c84b6ef44516fae6c0fa414662))
* **tests:** enhance service worker tests and update app bundle registration ([77dabe6](https://github.com/TurtleOld/hasta-la-vista-money/commit/77dabe6aa917ac975c8a168bdf9760f310f60c30))
* **theme:** add automatic theme mode ([b109ac6](https://github.com/TurtleOld/hasta-la-vista-money/commit/b109ac6c901c66f4fcd8cd7fa73841bb5f03e19a))
* **transactions:** add REST API endpoints ([3867640](https://github.com/TurtleOld/hasta-la-vista-money/commit/38676409808a05ba5d78733e0b49e81fe83dd3d1))
* **transactions:** add services, repositories, forms, DI container ([712b20a](https://github.com/TurtleOld/hasta-la-vista-money/commit/712b20a5ea0b0c8923c059589bbbe1d672f962da))
* **transactions:** add unified Transaction and Category models ([cb0f7f6](https://github.com/TurtleOld/hasta-la-vista-money/commit/cb0f7f65bc12c495bf7af24caec9b9b7d8113ce2))
* **transactions:** add unified Transaction and Category models ([170e1ba](https://github.com/TurtleOld/hasta-la-vista-money/commit/170e1ba0dc3b5474461fc7b6dbc465fc406c20cd))
* **transactions:** wire TransactionContainer into ApplicationContainer ([77ed4de](https://github.com/TurtleOld/hasta-la-vista-money/commit/77ed4de21e3cd210d401f606aec48baab7dc0add))
* **ui:** restyle profilepage ([641a25e](https://github.com/TurtleOld/hasta-la-vista-money/commit/641a25e024d1806c50a1fec69c03c6fbef97f01f))
* **users:** add family access workflow ([1e59244](https://github.com/TurtleOld/hasta-la-vista-money/commit/1e5924474f258f53728783d5aecc16d512226bd8))
* **users:** add statistics filters ([d51e918](https://github.com/TurtleOld/hasta-la-vista-money/commit/d51e9184efae6f8ac87b8b8044700a62421474b8))
* **users:** extend detailed statistics analytics ([abb09f4](https://github.com/TurtleOld/hasta-la-vista-money/commit/abb09f455a17f453495beeaec017615536d4ba88))
* **users:** restyle profile page ([4c24b1d](https://github.com/TurtleOld/hasta-la-vista-money/commit/4c24b1d7d1d7dea3ed963dead649321ed8c7b0ba))
* **users:** use family membership roles and member-based statistics ([27073c5](https://github.com/TurtleOld/hasta-la-vista-money/commit/27073c5aeb000705f7ac8af8ab3014cb1f433953))


### Bug Fixes

* **accounts:** make quick-add drawer actually open under CSP ([2d43ad0](https://github.com/TurtleOld/hasta-la-vista-money/commit/2d43ad0f8551b0f6c3188f1436f63a97490c3bbc))
* **accounts:** move quickAdd and toast state into Alpine.store ([a0413da](https://github.com/TurtleOld/hasta-la-vista-money/commit/a0413da2d8513482f1acb2ef14d960f9926bedf5))
* **accounts:** restore date picker for payment due date ([518d928](https://github.com/TurtleOld/hasta-la-vista-money/commit/518d9288a9dcbf5355474867581651488003d0ee))
* **accounts:** use inline expressions instead of getters in Alpine CSP templates ([949a4ca](https://github.com/TurtleOld/hasta-la-vista-money/commit/949a4ca3dd83177b0a566bc318d9bfc9a4969956))
* **balance-trend:** emit valid JSON for widget data attribute ([505e309](https://github.com/TurtleOld/hasta-la-vista-money/commit/505e309e1ad6cb8fc3f3934447d6b14d4c491506))
* **bank-statement:** correctly import all rows and dedupe on re-upload ([54e6f24](https://github.com/TurtleOld/hasta-la-vista-money/commit/54e6f24c5d6edd60228dd621f05019b3ed4fe5e1))
* **bank-statement:** correctly import all rows and dedupe on re-upload ([104ed49](https://github.com/TurtleOld/hasta-la-vista-money/commit/104ed49c1b1142eb72da39a4c73d0c7b9c90c5e0))
* **budget:** align budget migration index names ([b57b078](https://github.com/TurtleOld/hasta-la-vista-money/commit/b57b0789b1b909a19000da0700eb4d3d8f5a96ac))
* **budget:** include full month in limit progress ([70394a7](https://github.com/TurtleOld/hasta-la-vista-money/commit/70394a7d64babe7bf106e20d46e317bc4590d7df))
* **budget:** render month ranges via htmx ([f95910b](https://github.com/TurtleOld/hasta-la-vista-money/commit/f95910b87fdd90a98d7df2c5950a468c19518609))
* **ci:** configure redis access in money workflow ([ba517d1](https://github.com/TurtleOld/hasta-la-vista-money/commit/ba517d12e78f61f898e1e4c0cecd57dd1e043310))
* **ci:** harden production validation ([e2d66c7](https://github.com/TurtleOld/hasta-la-vista-money/commit/e2d66c73a8c2f8f01a8ff012354aeec097a90be0))
* **ci:** harden production validation ([eb3ba5c](https://github.com/TurtleOld/hasta-la-vista-money/commit/eb3ba5ce9dcbc77f778121cebb86005612a78691))
* **ci:** remove subprocess from migration rollback check ([d151ffc](https://github.com/TurtleOld/hasta-la-vista-money/commit/d151ffc9edf2c760731e08128e31ad8b5f5ce910))
* **ci:** swap connection settings for rollback checks ([63523ed](https://github.com/TurtleOld/hasta-la-vista-money/commit/63523edf9ee73f38f651e01a8946b8b7cb2f300d))
* **ci:** use isolated db wrapper for rollback checks ([9923dac](https://github.com/TurtleOld/hasta-la-vista-money/commit/9923dac0b723834e88b12355b9ab8b5a849dfbfa))
* **ci:** validate changed migrations in isolation ([bac6406](https://github.com/TurtleOld/hasta-la-vista-money/commit/bac6406690bcad75dad028d1a2451b64b7e7433a))
* **config:** pass django settings module to production services ([5e6659e](https://github.com/TurtleOld/hasta-la-vista-money/commit/5e6659e9a1b58bc7cfe74690881f94cdf9c75f91))
* **config:** unify host parsing and enable production csrf hsts ([1c3a03b](https://github.com/TurtleOld/hasta-la-vista-money/commit/1c3a03b8c0652c702f6580d0cd6949d39791ed58))
* **constants:** update date constants to use timezone-aware datetime ([034e519](https://github.com/TurtleOld/hasta-la-vista-money/commit/034e51999abddafa5db6618177a9ed76df9a0126))
* **core:** load site tour globally ([6a94c64](https://github.com/TurtleOld/hasta-la-vista-money/commit/6a94c64be0a803318c5be56db9f8f91fc7c0dad0))
* **dashboard:** adjust widget button text color ([80aa9f1](https://github.com/TurtleOld/hasta-la-vista-money/commit/80aa9f1bb2356cb0ac4851021c034ff2dff0a1c7))
* **dashboard:** adjust widget button text color ([7c75a40](https://github.com/TurtleOld/hasta-la-vista-money/commit/7c75a40df706dddaef158db0ce7a8f605c9938e8))
* **dashboard:** gate widget editing mode ([757cd48](https://github.com/TurtleOld/hasta-la-vista-money/commit/757cd4819fb5225be86f44397a5882c216a42346))
* **deps:** suppress Bandit test password findings ([7da342f](https://github.com/TurtleOld/hasta-la-vista-money/commit/7da342f4310079bde6629879ff3c86e43ec3023b))
* **deps:** suppress Bandit test password findings ([15c6914](https://github.com/TurtleOld/hasta-la-vista-money/commit/15c6914f4dd16b6a0a665b3310e76ad7b6c26657))
* **deps:** update dependency django to v6.0.4 ([#700](https://github.com/TurtleOld/hasta-la-vista-money/issues/700)) ([f2f9f09](https://github.com/TurtleOld/hasta-la-vista-money/commit/f2f9f09d0698efee085cf36b1f0ce7c206552677))
* **deps:** update dependency django to v6.0.5 ([1684871](https://github.com/TurtleOld/hasta-la-vista-money/commit/168487165adf966934a9fb44566e25c487e1e661))
* **deps:** update dependency django to v6.0.5 ([d0d3f84](https://github.com/TurtleOld/hasta-la-vista-money/commit/d0d3f842c98289b9568cee3900403a2048d385fb))
* **deps:** update dependency pygments to &gt;=2.20,&lt;2.21 ([99dc5e5](https://github.com/TurtleOld/hasta-la-vista-money/commit/99dc5e5ba127e737f4090f1f973279cb09a19e6a))
* **deps:** update dependency pygments to &gt;=2.20,&lt;2.21 ([6bd67a6](https://github.com/TurtleOld/hasta-la-vista-money/commit/6bd67a64aa3a379a175f7933ecdbf21aa09a6fc9))
* **finance_account:** return None for invalid filter dates ([76617e1](https://github.com/TurtleOld/hasta-la-vista-money/commit/76617e1b9be732a04b5b7b6ed1cb08102958b655))
* **finances:** apply pagination to day and category views ([18c0a10](https://github.com/TurtleOld/hasta-la-vista-money/commit/18c0a10f872f5e442c0e7c1a2472b85339eaa39c))
* **finances:** correct composer routing and category tree serialization ([cf026dc](https://github.com/TurtleOld/hasta-la-vista-money/commit/cf026dcd445716e978d9ad8533c6b42a1492552e))
* **finances:** standardize date inputs and remove extra focus chrome ([90fa8c3](https://github.com/TurtleOld/hasta-la-vista-money/commit/90fa8c3236d3e81c19b3520457f114970e99afb9))
* **finances:** standardize date inputs and remove extra focus chrome ([3741bc5](https://github.com/TurtleOld/hasta-la-vista-money/commit/3741bc5cca82bd3f377316720a71b4ea56a3d16a))
* **forms:** set default source account before selecting destination ([cabb2c2](https://github.com/TurtleOld/hasta-la-vista-money/commit/cabb2c23bbd1cec7011ee9b6adad51e04f01676a))
* **frontend:** sync tailwind forms lockfile ([ca3cdfe](https://github.com/TurtleOld/hasta-la-vista-money/commit/ca3cdfeed489ccd3c9df64a07f101d510d12d99c))
* keep receipts when seller is deleted ([f1db884](https://github.com/TurtleOld/hasta-la-vista-money/commit/f1db8840ac5eb4ebb5f1f760744b12092baf948d))
* keep receipts when seller is deleted ([f77fa88](https://github.com/TurtleOld/hasta-la-vista-money/commit/f77fa88e2b41f523fd028c94a7f100ad167de067))
* **lint:** resolve ruff violations in statistics ([b6c85a0](https://github.com/TurtleOld/hasta-la-vista-money/commit/b6c85a01f0dc79c8591efd9a75f5b2140aba727a))
* make receipt ai rate limit atomic ([9acc3d2](https://github.com/TurtleOld/hasta-la-vista-money/commit/9acc3d2924575f59d09e317ad4a440aafb0aeb0b))
* make receipt ai rate limit atomic ([23308a9](https://github.com/TurtleOld/hasta-la-vista-money/commit/23308a984694d07bc1ae4903d9028fdc6df5b178))
* **ocr:** set paddleocr device to cpu ([dfc5c6d](https://github.com/TurtleOld/hasta-la-vista-money/commit/dfc5c6d5f59417dfeb8c0bca26c4983aab03e01d))
* **ocr:** set paddleocr device to cpu ([6c114b1](https://github.com/TurtleOld/hasta-la-vista-money/commit/6c114b1420d778be0d996fdfc4d07986b221cee9))
* **receipts:** handle review balance validation ([b257e2e](https://github.com/TurtleOld/hasta-la-vista-money/commit/b257e2e5666fb21e4a6a47014b1f9ce38cd53af1))
* **receipts:** improve upload processing and finances integration ([215b086](https://github.com/TurtleOld/hasta-la-vista-money/commit/215b086af3932c653d984224545d47b7109882c5))
* **receipts:** improve upload processing and finances integration ([496e0ed](https://github.com/TurtleOld/hasta-la-vista-money/commit/496e0ed6d75c1e0a731ac8ec5d3f7258f5031cd2))
* **receipts:** increase inference timeout and provide actionable error messages ([cc83864](https://github.com/TurtleOld/hasta-la-vista-money/commit/cc83864a9f8022a70f4335d3e551a08b32d09e42))
* **receipts:** increase inference timeout and provide actionable error messages ([9100180](https://github.com/TurtleOld/hasta-la-vista-money/commit/9100180970b11e858c13b6cfa7d4ee968dded419))
* **receipts:** preserve product categories ([68f4033](https://github.com/TurtleOld/hasta-la-vista-money/commit/68f403323cbe077e52b05807f969ab48017949e6))
* **receipts:** prevent leaking internal exception details ([e7d9834](https://github.com/TurtleOld/hasta-la-vista-money/commit/e7d983442bf58438d3665f0d749f3090c6bc15d7))
* **receipts:** recover dropped first item in PaddleOCR-VL parsing ([8b0236d](https://github.com/TurtleOld/hasta-la-vista-money/commit/8b0236d5771baaef739dfcca0e34daaf3ef3639a))
* **receipts:** recover dropped first item in PaddleOCR-VL parsing ([8ab0ead](https://github.com/TurtleOld/hasta-la-vista-money/commit/8ab0ead289c38e2f499762d1ea344462f33e847f))
* **ui:** render chart only when data is present ([d1bb5b8](https://github.com/TurtleOld/hasta-la-vista-money/commit/d1bb5b8b57632b59e91fded1329c513a01e99bd8))


### Performance Improvements

* **backend:** configure paddleocr with mobile detection model and cpu optimizations ([f00b68b](https://github.com/TurtleOld/hasta-la-vista-money/commit/f00b68bdfd49329021e4b3a41191e97d729e36b4))
* **dashboard:** cache expensive analytics endpoints ([6c5d5c2](https://github.com/TurtleOld/hasta-la-vista-money/commit/6c5d5c292c05c026313ca66683dcfbd1da24b69d))
* **docker:** reduce default granian blocking threads ([43634b2](https://github.com/TurtleOld/hasta-la-vista-money/commit/43634b2274ea27e11f14e4600a954f9b627e63b6))
* **inference:** optimize resource usage and performance ([ff98963](https://github.com/TurtleOld/hasta-la-vista-money/commit/ff9896327d29d634f30081ae27eae9b4ec24933f))
* **infra:** extend timeouts and allocate more resources for receipt inference ([a27bf09](https://github.com/TurtleOld/hasta-la-vista-money/commit/a27bf098f0be9d32b1858dc4eae126eb1f62d480))
* **ocr:** optimize image preprocessing and enable configurable OCR models ([5eccc0e](https://github.com/TurtleOld/hasta-la-vista-money/commit/5eccc0e3ef6b1ec4379ebf5c52541737278ffbc2))
* **ocr:** optimize image preprocessing and enable configurable OCR models ([696a1da](https://github.com/TurtleOld/hasta-la-vista-money/commit/696a1da3c2ed3129a924604e8df82894047407cb))
* **receipt-inference:** enhance service reliability with healthchecks and connection retries ([c7d155f](https://github.com/TurtleOld/hasta-la-vista-money/commit/c7d155f22989c84fd6ffefeeab54f94249b5bb69))
* **receipt-inference:** optimize inference with increased threads, resources, and warmup ([09d47dc](https://github.com/TurtleOld/hasta-la-vista-money/commit/09d47dc21156608967e4f55237d75398beadd509))
* **receipt-inference:** optimize inference with increased threads, resources, and warmup ([b08f99c](https://github.com/TurtleOld/hasta-la-vista-money/commit/b08f99c712f8a6606511dd29e5aacdfc19b84b0f))


### Documentation

* clarify self-hosted production setup ([7acdc60](https://github.com/TurtleOld/hasta-la-vista-money/commit/7acdc600a9bf7def5796773a4b0b4e22804e095c))
* clarify self-hosted production setup ([778d213](https://github.com/TurtleOld/hasta-la-vista-money/commit/778d213e23434a2891a72d8f48cda349804a997c))
* document django testcase workflow ([5831381](https://github.com/TurtleOld/hasta-la-vista-money/commit/5831381cda4031502b9f4359afead060676bbe98))
* document JS build workflow and add make targets ([6555d32](https://github.com/TurtleOld/hasta-la-vista-money/commit/6555d32826711a01fe34afe28ceb55eb05f7f119))
* **readme:** add DeepWiki badge ([bbe16b8](https://github.com/TurtleOld/hasta-la-vista-money/commit/bbe16b8d53f8f0fcc4ec217cd69167f202232f00))
* **readme:** add DeepWiki badge and fix workflow file extension ([eca7c3c](https://github.com/TurtleOld/hasta-la-vista-money/commit/eca7c3c6dbc59870cab272bed06f632dc3894a5d))

## [1.9.0] - 2025-12-18

### 🎨 Миграция UI фреймворка

#### Tailwind CSS
- Полная миграция с Bootstrap на Tailwind CSS
- Обновлены все шаблоны модулей income и expense
- Переведены базовые шаблоны (base.html, header.html) на Tailwind CSS
- Интеграция crispy-tailwind для работы с формами
- Мобильное меню переведено на Tailwind без использования JavaScript (checkbox + peer)
- Обновлены страницы ошибок (404, 500) с улучшенным UI/UX
- Улучшены страницы входа и регистрации с использованием Tailwind CSS
- Удалены устаревшие SCSS селекторы после миграции

#### Улучшения UI/UX
- Улучшены toast сообщения с автоматическим скрытием
- Оптимизирована работа мобильного меню
- Улучшена адаптивность интерфейса
- Обновлен дизайн форм и кнопок

### 🔒 Улучшения безопасности

#### XSS защита
- Заменен `innerHTML` на безопасные DOM методы в `expense_table.js` и `income_table.js`
- Добавлен модуль `HTMLSanitizer` в `receipt_group_filter.js` для безопасной обработки HTML
- Улучшена безопасность загрузки внешних скриптов
- Улучшена валидация размера загрузок
- Исправлены предупреждения Codacy:
  - Variable Assigned to Object Injection Sink
  - Generic Object Injection Sink
- Предотвращены XSS уязвимости в рендеринге групп счетов

#### Безопасность JavaScript
- Улучшена безопасность работы с DOM элементами
- Добавлена валидация HTML перед парсингом
- Реализована изоляция HTML парсинга через Range API

### 🐛 Исправления ошибок

- Исправлен `cancel_url` в `IncomeCreateView` контексте
- Исправлена валидация окружения для локальной разработки с `DEBUG=False`
- Исправлены ошибки типизации (mypy)
- Исправлен тип возврата в `get_is_foreign` для устранения ошибок mypy

### 🔧 Улучшения

#### Производительность
- Оптимизация JavaScript: добавлен debounce для touch events
- Реализован lazy loading для скриптов
- Улучшена производительность загрузки страниц

#### Рефакторинг
- Обновлены формы и стили для Tailwind CSS
- Удалены неиспользуемые SCSS файлы
- Улучшена структура шаблонов
- Оптимизирована работа с мобильными карточками

### 📦 Обновления зависимостей

- Обновлены GitHub Actions workflows
- Обновления зависимостей через Renovate
- Обновлены версии инструментов в CI/CD

---

## [1.8.0] - 2025-01-27

### 🎉 Новые возможности

#### Дашборд и аналитика
- Добавлен интерактивный дашборд с настраиваемыми виджетами
- Реализована аналитика динамики и сравнение периодов
- Добавлена функция детального анализа (drill-down)
- Интеграция с ECharts для визуализации данных
- API endpoints для работы с виджетами дашборда

#### Мобильный интерфейс
- Добавлена нижняя навигационная панель для мобильных устройств
- Улучшена поддержка HTMX для динамических обновлений
- Добавлены частичные шаблоны для форм (partial templates)
- Реализован HTMXMixin для обработки HTMX запросов
- Улучшена адаптивность интерфейса

#### Обработка чеков
- Добавлена возможность обновления чеков с отслеживанием баланса
- Улучшена валидация API для работы с чеками
- Расширена функциональность импорта чеков

#### Кеширование и производительность
- Внедрено Redis кеширование для production окружения
- Оптимизированы запросы к базе данных (исправлены N+1 queries)
- Добавлено логирование медленных запросов
- Улучшена производительность входа в систему

#### API и документация
- Интеграция drf-spectacular для автоматической генерации OpenAPI документации
- Добавлена конфигурация API throttling
- Улучшена структура API endpoints
- Добавлена документация API в MkDocs

### 🔧 Улучшения

#### Архитектура
- Внедрена система Dependency Injection (dependency-injector)
- Добавлен слой репозиториев для абстракции доступа к данным
- Рефакторинг сервисов с использованием протоколов
- Улучшена модульность и тестируемость кода
- Централизована логика фильтрации по группам в AccountService

#### Безопасность
- Исправлены уязвимости XSS атак
- Добавлена защита от SSRF (безопасный метод _safeFetch)
- Исправлены проблемы с injection
- Улучшена JWT аутентификация для мобильных приложений
- Добавлен django-compressor для оптимизации статических файлов
- Интеграция security audit (pysentry-rs) в CI/CD
- Улучшена обработка HTML атрибутов в CompressorNonceMiddleware

#### База данных
- Добавлено поле `updated_at` в модель TimeStampedModel
- Добавлено поле `bank` в модель Account
- Добавлена миграция для DashboardWidget
- Улучшена работа с timezone в Django проекте
- Оптимизированы запросы с использованием select_related и prefetch_related

#### Типизация
- Включен strict mode для mypy
- Улучшена типизация во всех модулях
- Добавлены протоколы для сервисов с @runtime_checkable
- Исправлены циклические импорты
- Заменено использование .id на .pk для Django моделей

#### Тестирование
- Значительно расширено покрытие тестами
- Добавлены тесты для dashboard analytics
- Улучшены тесты аутентификации
- Добавлены тесты для middleware
- Стабилизированы тесты throttling
- Обновлены тесты для работы с DI

#### Docker и инфраструктура
- Добавлена поддержка non-privileged пользователя в Docker контейнерах
- Исправлены проблемы с правами доступа в production Dockerfile
- Улучшена конфигурация nginx
- Добавлены заголовки безопасности в nginx config
- Оптимизирована сборка Docker образов

#### Конфигурация
- Добавлена валидация переменных окружения
- Улучшена документация .env.example
- Добавлена поддержка timezone в настройках
- Улучшена конфигурация CORS
- Оптимизирована конфигурация сессий

### 🐛 Исправления ошибок

- Исправлена логика расчета балансов в дашборде
- Исправлена фильтрация по периоду в IncomeQuerySet
- Исправлено сохранение account при обновлении расхода
- Исправлена логика get_accounts_for_user_or_group
- Исправлена валидация AddAccountForm
- Исправлена ошибка сериализации генераторов в Redis
- Исправлены проблемы с timezone в Django проекте
- Исправлена обработка CheckableLazyObject в CompressorNonceMiddleware
- Исправлено экранирование специальных символов в base64 кодировании изображений
- Исправлены проблемы со статическими файлами в production

### 📦 Обновления зависимостей

- Django: 5.2.5 → 5.2.8
- dependency-injector: добавлен в зависимости
- django-redis: добавлен для кеширования
- django-compressor: добавлен для оптимизации статики
- drf-spectacular: добавлен для документации API
- Множество обновлений других пакетов через Renovate

### 🔄 Рефакторинг

- Рефакторинг всех сервисов для использования DI
- Вынесение магических чисел в константы
- Улучшение структуры кода и обработки ошибок
- Удаление дублирования кода (DRY принцип)
- Улучшение форматирования и организации импортов
- Рефакторинг форм через миксины для income/expense

### 📚 Документация

- Добавлена документация для users app
- Улучшена структура README
- Добавлена документация по кешированию
- Интеграция API документации в MkDocs
- Улучшена документация в коде (docstrings)

### ⚙️ Инфраструктура CI/CD

- Обновлены GitHub Actions workflows
- Добавлена проверка миграций в CI
- Интеграция security scanning
- Улучшена конфигурация pre-commit hooks
- Обновлены версии инструментов в CI

---

## [1.7.0] - Предыдущая версия

[Unreleased]: https://github.com/TurtleOld/hasta-la-vista-money/compare/v1.9.0...HEAD
[1.9.0]: https://github.com/TurtleOld/hasta-la-vista-money/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/TurtleOld/hasta-la-vista-money/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/TurtleOld/hasta-la-vista-money/releases/tag/v1.7.0
