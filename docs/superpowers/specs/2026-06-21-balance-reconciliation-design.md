# Balance Reconciliation Tool — Design Spec

**Date:** 2026-06-21  
**Status:** Approved

---

## Problem

Reconciling account balances against bank statements is painful even once a week. Bank statement formats are not standardised — writing a dedicated parser per bank is expensive to maintain. The existing `process_bank_statement()` pipeline already parses PDFs for Sberbank and Raiffeisen and creates transactions, but has three gaps:

1. `_get_or_create_category()` names categories after raw merchant descriptions (garbage like "SUPERMARKET SPAR NOVOSIBIRSK 1234").
2. Parsers do not extract the closing balance from the statement, so there is no way to compare "what the bank says" vs "what the app shows".
3. After import there is no reconciliation summary screen.

---

## Goals

- **Gap finding**: show what operations are in the statement but not yet in the app (skipped/imported counts).
- **Balance verification**: compare the statement's closing balance against `Account.balance` after import; surface any discrepancy.
- **Smart categorisation**: map raw merchant descriptions to meaningful user categories via LLM, without leaking personal data to the cloud.
- **Privacy-safe LLM**: support cloud providers (Claude, OpenAI) and local models (LM Studio, Ollama) via a single OpenAI-compatible abstraction.

---

## Architecture

### 1. LLM Abstraction (`CategoryClassifier`)

```
CategoryClassifier (Protocol)
├── OpenAICompatibleClassifier   — cloud or local via OpenAI-compatible API
└── NoopClassifier               — fallback when LLM is not configured
```

`OpenAICompatibleClassifier` takes three settings: `base_url`, `api_key`, `model`.

| Provider    | base_url                         | api_key      | model                   |
|-------------|----------------------------------|--------------|-------------------------|
| LM Studio   | `http://localhost:1234/v1`       | *(empty)*    | loaded model name       |
| Ollama      | `http://localhost:11434/v1`      | `ollama`     | e.g. `llama3`           |
| Claude      | `https://api.anthropic.com/v1`   | `sk-ant-…`   | `claude-haiku-4-5`      |
| OpenAI      | `https://api.openai.com/v1`      | `sk-…`       | `gpt-4o-mini`           |

Switching provider = changing three config values, no code changes.

**Prompt contract** — the only data sent to the LLM:

```json
{
  "description": "<cleaned merchant name>",
  "type": "income | expense",
  "existing_categories": ["Продукты", "Транспорт", ...]
}
```

No account numbers, names, dates, or reference codes leave the server.  
The LLM returns a single string: a category name (existing or new).

**PII stripping** (done locally before the LLM call):

- Card masks: `*1234`, `\*\d{4}`
- Authorisation / reference codes: standalone 5–7 digit numbers
- Date fragments embedded in descriptions
- Account number fragments

### 2. Pipeline Changes (`bank_statement.py`)

The existing `process_bank_statement()` gains one step between parsing and transaction creation:

```python
# Before:
category = _get_or_create_category(user, description, type_value)

# After:
clean_desc = _strip_pii(description)
category_name = classifier.classify(
    description=clean_desc,
    transaction_type=type_value,
    existing_categories=user_category_names,
)
category = _get_or_create_category(user, category_name, type_value)
```

`classifier` is injected via the DI container (`ApplicationContainer`) and defaults to `NoopClassifier` when no LLM is configured — existing behaviour preserved.

### 3. Closing Balance Extraction

`BaseBankStatementParser.parse()` return type expands from `list[dict]` to a named result:

```python
@dataclass
class StatementParseResult:
    transactions: list[dict[str, Any]]
    closing_balance: Decimal | None   # None if not found in PDF
    closing_balance_date: date | None
```

Each parser (`_SberbankParser`, `_RaiffeisenBankParser`, `_GenericBankParser`) gains a `_extract_closing_balance()` method. Extraction uses regex on the raw PDF text (via `pdfminer`) to find the final balance row.

### 4. `BankStatementUpload` Model — New Fields

```python
statement_closing_balance = DecimalField(null=True, blank=True)
account_balance_after     = DecimalField(null=True, blank=True)
balance_discrepancy       = DecimalField(null=True, blank=True)
```

`balance_discrepancy = statement_closing_balance - account_balance_after`.  
Populated at the end of the Celery task (`process_bank_statement_task`).

### 5. Reconciliation Summary UI

`BankStatementUploadStatusView` JSON response gains three fields:

```json
{
  "statement_closing_balance": "45230.00",
  "account_balance_after":     "45230.00",
  "balance_discrepancy":       "0.00"
}
```

The existing `bank_statement_upload.html` template shows a summary block after status = `completed`:

```
✓ Импортировано: 12 доходов, 34 расхода, 5 пропущено (дубли)

Остаток по выписке:     45 230,00 ₽
Остаток в приложении:   45 230,00 ₽
Расхождение:            0,00 ₽  ✓
```

If `balance_discrepancy != 0` the block is styled red and includes a link to the transaction list filtered by the statement's date range.

---

## Settings

```python
# config/settings.py (or env vars)
CATEGORY_CLASSIFIER_BASE_URL = "http://localhost:1234/v1"  # or cloud URL
CATEGORY_CLASSIFIER_API_KEY  = ""
CATEGORY_CLASSIFIER_MODEL    = "llama-3-8b-instruct"
```

If `CATEGORY_CLASSIFIER_BASE_URL` is empty or unset, `NoopClassifier` is used and categories fall back to the cleaned description (current behaviour).

---

## What Is Not Changing

- The PDF parsers themselves (camelot / pdfminer stack) — no new parser per bank.
- The deduplication logic (`source_ref` + legacy fallback).
- The `BalanceService.apply_balance_delta()` call.
- The Celery task structure.
- CSV/Excel support is out of scope for this iteration (PDF only).

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `hasta_la_vista_money/users/services/category_classifier.py` | New — `CategoryClassifier` protocol + two implementations |
| `hasta_la_vista_money/users/services/pii_stripper.py` | New — `_strip_pii()` |
| `hasta_la_vista_money/users/services/bank_statement.py` | Add `StatementParseResult`, closing balance extraction, classifier injection |
| `hasta_la_vista_money/users/models.py` | Add three fields to `BankStatementUpload` |
| `hasta_la_vista_money/users/migrations/` | Migration for new fields |
| `hasta_la_vista_money/users/tasks.py` | Populate reconciliation fields after processing |
| `hasta_la_vista_money/users/views/bank_statement.py` | Expose new fields in status JSON |
| `hasta_la_vista_money/users/templates/users/bank_statement_upload.html` | Reconciliation summary block |
| `config/settings.py` | `CATEGORY_CLASSIFIER_*` settings |
| `config/containers.py` | Wire `CategoryClassifier` into DI container |
