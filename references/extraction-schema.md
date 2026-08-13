# Entries schema — what Claude hands to `validate-extraction`

Claude reads the photographed timesheet. The script decides what that reading is
allowed to mean. The handover between the two is this JSON document, passed with
`--entries PATH` or on standard input with `--entries -`.

```json
{
  "schema_version": 1,
  "worker_id": "anna",
  "month": "2026-08",
  "observed_name": { "kind": "value", "value": "Anna Muster" },
  "entries": [
    { "date": "2026-08-03", "kind": "value", "value": "7.5", "confidence": "high" },
    { "date": "2026-08-04", "kind": "zero", "confidence": "high", "note": "krank" },
    { "date": "2026-08-05", "kind": "blank", "confidence": "high" },
    { "date": "2026-08-06", "kind": "unreadable", "confidence": "low", "note": "verwischt" }
  ]
}
```

## Top level

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | no (default `1`) | Version of this document format. |
| `worker_id` | no | If present it must equal the `--worker` argument. A mismatch is an error, never a silent switch. |
| `month` | no | If present it must equal the `--month` argument. |
| `observed_name` | no (defaults to `not_provided`) | The worker name as written on the sheet. |
| `entries` | yes | One object per transcribed day. |

Unknown fields are rejected, so a typo (`"cofidence"`) fails loudly instead of
being ignored. "Must be omitted" means omitted: an explicit `"value": null` is
refused rather than read as absent.

## `observed_name`

| `kind` | `value` | Meaning |
|---|---|---|
| `value` | required | The name was read; the script compares it with the registered name (ignoring case and extra spaces). |
| `unreadable` | must be omitted | A name is written but cannot be read. |
| `not_provided` | must be omitted | The sheet has no name line, or it is empty. |

The computed status is `matched`, `mismatch`, `unreadable` or `not_provided`.
`mismatch` and `unreadable` block confirmation until `confirm --accept-identity`
is passed. `not_provided` never blocks.

## Entries

| Field | Required | Meaning |
|---|---|---|
| `date` | yes | `YYYY-MM-DD`, a real date inside the requested month. |
| `kind` | yes | `value`, `zero`, `blank` or `unreadable`. |
| `value` | only when `kind` is `value` | Hours as text: `"7.5"` or `"7,5"`, at most 2 decimals. Must be omitted for the other kinds. |
| `confidence` | yes | `high` or `low` — how sure the reading is. |
| `note` | no | Short plain-text remark (max 200 characters). |

`kind` meanings: `value` = hours are written, `zero` = a written `0`, `blank` =
the field is empty, `unreadable` = something is written but it cannot be read.
A day that is not listed at all is treated as `blank`.

Hours count wherever they are written — a value on a non-working day is valid
and is included in the total (reality beats the schedule).

## Rejected outright (no confirmation can fix these)

* a date that does not exist (`2027-02-30`) or is outside the month;
* the same date listed twice;
* hours that are negative, use more than 2 decimals, or are written in
  exponent/`NaN`/`Infinity` form (the money grammar rejects them);
* more than 24 hours in one day;
* `value` missing when `kind` is `value`, or present when it is not;
* unknown fields, unknown `kind`/`confidence` values.

## Flagged, and blocking until a human decides

| Flag | Raised when | Cleared by |
|---|---|---|
| `unreadable` | `kind` is `unreadable` | `confirm --set DATE=HOURS` (use `0` for no hours) |
| `blank_on_working_day` | a scheduled working day is blank | `confirm --set DATE=HOURS` |
| `implausible` | more than 12 hours in one day | repeating the same value with `--set` (accept) or setting a corrected one |
| `low_confidence` | `confidence` is `low` | repeating the same value with `--set` (accept) or setting a corrected one |

Blank days that are *not* working days are fine and never block.

## Example fixtures

`tests/fixtures/` ships one document per case used by the test-suite:
`entries-clean.json`, `entries-flagged.json`, `entries-duplicate-date.json`,
`entries-impossible-hours.json`, `entries-name-mismatch.json`.
