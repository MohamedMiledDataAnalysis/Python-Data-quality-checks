# data_quality: standard data quality checks for pandas

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Licence](https://img.shields.io/badge/licence-MIT-green)

One Python module that checks the quality of any pandas DataFrame,
reports every problem, and separates valid rows from invalid ones.

```python
from data_quality import run_checks, split_valid_invalid, print_report

report = run_checks(df, rules)                    # one row per check
print_report(report)
valid, invalid = split_valid_invalid(df, rules)   # invalid rows + reasons
```

---

## Contents

1. [Installation](#installation)
2. [The two layers of checks](#the-two-layers-of-checks)
3. [Declaring rules](#declaring-rules)
4. [The outputs](#the-outputs)
5. [Demonstration](#demonstration)
6. [Python concepts used in the code](#python-concepts-used-in-the-code),
   including [What is @dataclass?](#what-is-dataclass)

---

## Installation

The module needs only pandas:

```bash
pip install -r requirements.txt
```

Copy `data_quality.py` next to your script, then import it.

---

## The two layers of checks

### Layer 1: automatic checks (WARNING)

They run on every DataFrame, without configuration. They describe the
data and flag what deserves a look; they never make a row invalid.

| Check | Catches | Example |
|---|---|---|
| `duplicate_rows` | rows identical in every column | the same loan entered twice |
| `missing_values` | None, NaN, NaT, per column | an empty borrower name |
| `blank_text` | text that is empty or only spaces | `""`, `"   "` |
| `stray_spaces` | spaces before or after the text | `"Jones "` |
| `mixed_types` | several Python types in one column | `0.048` and `"4.8%"` |
| `constant_column` | one single value in every row | a column always `"GBP"` |
| `extreme_outliers` | values beyond 3 interquartile ranges | a 9.9m loan among 200k ones |

`stray_spaces` matters more than it looks: `"Jones "` never equals
`"Jones"` in a filter, a group-by or a merge.

`extreme_outliers` uses the interquartile range (IQR), the distance
between the 25th and 75th percentiles. A value is extreme when it lies
more than 3 × IQR below the 25th percentile or above the 75th. The IQR
is not distorted by the outliers themselves, unlike the standard deviation.

### Layer 2: declared rules (ERROR)

You declare what valid data looks like. A row breaking a rule is
invalid. See [Declaring rules](#declaring-rules).

### Why two layers?

A warning can be genuine data: a 9.9m loan may exist. Rejecting it
automatically could lose real records. So the automatic checks only
flag; you decide what is invalid by declaring a rule, for example
`"ranges": {"amount": (0, 5_000_000)}`.

---

## Declaring rules

Rules are a dictionary. Every key is optional.

```python
rules = {
    "required_columns": ["loan_id", "amount", "currency"],
    "dtypes": {"loan_id": "integer", "amount": "numeric",
               "start_date": "date"},
    "unique": [["loan_id"], ["country", "year"]],
    "not_null": ["loan_id", "amount"],
    "ranges": {"amount": (0, None), "rate": (0, 0.25)},
    "allowed": {"status": ["open", "closed", "defaulted"]},
    "patterns": {"currency": r"[A-Z]{3}"},
    "date_range": {"start_date": ("2000-01-01", "today")},
}
```

| Rule | Checks | Notes |
|---|---|---|
| `required_columns` | the columns exist | a rule on a missing column is skipped, so this check reports it |
| `dtypes` | each value can be read as the type | types: `numeric`, `integer`, `date`, `string`, `bool` |
| `unique` | no key value appears twice | one list per key; `["country", "year"]` is a two-column key; every copy is flagged |
| `not_null` | no missing value | blank text `""` is not missing: see `blank_text` |
| `ranges` | numbers within `(min, max)` | `None` means no limit on that side |
| `allowed` | values in a fixed list | case-sensitive: `"Open"` is not `"open"` |
| `patterns` | text matches a regular expression | the **whole** value must match: `r"[A-Z]{3}"` rejects `"GBPX"` |
| `date_range` | dates within `(start, end)` | `"today"` is replaced by the current date |

Each rule checks one thing. A value that breaks several rules is
reported by each of them: `"4.8%"` in `rate` fails `dtypes`, not
`ranges`, because the range check only applies to values that are
numbers.

---

## The outputs

### `run_checks(df, rules)`: the report

A DataFrame with one row per check:

| Column | Content |
|---|---|
| `status` | `PASS`, `WARN` (automatic check failed) or `FAIL` (rule broken) |
| `check` | the check name, e.g. `not_null` |
| `column` | the column checked, or `(dataset)` |
| `dimension` | completeness, validity, uniqueness, consistency or accuracy |
| `failed` | the number of failing rows |
| `failed_pct` | the same, as a percentage of all rows |
| `examples` | up to 3 offending values |

The dimensions are the standard data quality framework:

| Dimension | Question |
|---|---|
| completeness | is everything there? |
| validity | does each value follow the rules? |
| uniqueness | is anything recorded twice? |
| consistency | is the same thing written the same way? |
| accuracy | are the values plausible? |

The report is a normal DataFrame, so it can be filtered, saved or loaded
into a database:

```python
report[report["status"] == "FAIL"]
report.to_csv("dq_report.csv", index=False)
```

### `print_report(report)`: the summary

Prints the counts, then the failed checks only.
`print_report(report, show_passed=True)` also shows the passed ones.

### `split_valid_invalid(df, rules)`: valid and invalid rows

Returns two DataFrames:

- `valid`: the rows that break no rule;
- `invalid`: the other rows, with a `dq_reasons` column listing every
  rule each row broke.

Warnings never make a row invalid.

---

## Demonstration

Run the module directly:

```bash
python data_quality.py
```

It checks a small loan book of 8 rows containing deliberate problems:

```
Data quality: 22 passed, 5 warnings, 8 errors
status  check             column      failed  examples
  FAIL  range [0, None]   amount           1  -5000
  FAIL  not_null          borrower         1
  FAIL  pattern [A-Z]{3}  currency         1  'gbp'
  FAIL  unique            loan_id          2  103
  FAIL  dtype_numeric     rate             1  '4.8%'
  FAIL  dtype_date        start_date       1  '2023-02-29'
  FAIL  date_range [...]  start_date       1  '2031-01-01'
  FAIL  allowed_values    status           1  'pending'
  WARN  extreme_outliers  amount           1  9900000
  WARN  missing_values    borrower         1
  WARN  blank_text        borrower         1  ''
  WARN  stray_spaces      borrower         1  'Jones '
  WARN  mixed_types       rate             2  float, str

3 valid rows, 5 invalid rows
```

(Some columns are shortened here to fit the page.)

`2023-02-29` fails `dtype_date` because 2023 is not a leap year: the
value has the right format but is not a real date.

---

## Python concepts used in the code

### What is @dataclass?

The module stores the outcome of each check in a `Result` object:

```python
from dataclasses import dataclass

@dataclass
class Result:
    check: str
    column: str
    dimension: str
    severity: str
    failed: int
    examples: str = ""
    mask: pd.Series | None = None
```

#### A decorator

A line starting with `@`, placed just above a class or a function, is a
**decorator**: it takes the class or function written below it and adds
features to it. `@dataclass` adds the features of a data container.

#### What it generates

From the list of fields, `@dataclass` writes three methods:

| Method | Role | Example |
|---|---|---|
| `__init__` | creates an object from values | `Result("not_null", "borrower", "completeness", "ERROR", 1)` |
| `__repr__` | displays it readably | `Result(check='not_null', column='borrower', ...)` |
| `__eq__` | compares two objects field by field | `r1 == r2` |

Without `@dataclass`, the same class needs all this code by hand:

```python
class Result:
    def __init__(self, check, column, dimension, severity,
                 failed, examples="", mask=None):
        self.check = check
        self.column = column
        self.dimension = dimension
        self.severity = severity
        self.failed = failed
        self.examples = examples
        self.mask = mask

    def __repr__(self):
        return (f"Result(check={self.check!r}, "
                f"column={self.column!r}, ...)")

    def __eq__(self, other):
        return (self.check, self.column, ...) == (
            other.check, other.column, ...)
```

Each field name appears three or four times, and adding a field means
editing every method. With `@dataclass`, each field is written once.

#### Declaring the fields

```python
    failed: int                    # name: type
    examples: str = ""             # name: type = default value
```

- `name: type` declares a field. The type documents what the field
  holds; Python does not enforce it.
- `= ""` gives a default value: the field may be left out when the
  object is created.
- Fields with a default must come **after** the fields without one.
  Otherwise Python cannot tell which value goes to which field.

#### Using a Result

```python
r = Result("not_null", "borrower", "completeness", "ERROR", 1)

r.check       # 'not_null'
r.failed      # 1
r.examples    # ''    (the default)
r.mask        # None  (the default)

r2 = Result(check="not_null", column="borrower",
            dimension="completeness", severity="ERROR", failed=1)
r == r2       # True: all the fields are equal
```

Fields can be given by position, as for `r`, or by name, as for `r2`.

#### Why not a dictionary?

```python
r = {"check": "not_null", "failed": 1}
r["faild"]     # KeyError, only when this line runs
```

| | Dictionary | Dataclass |
|---|---|---|
| Fields declared | no: any key can be added | yes, once, in the class |
| Missing field at creation | not detected | error immediately |
| Misspelt field | error only when that line runs | flagged by code editors as you type |
| Access | `r["failed"]` | `r.failed` |

#### Two common options

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Settings:
    max_rows: int = 1000
    mask: list = field(default=None, repr=False)
```

- `frozen=True` makes the objects read-only: `s.max_rows = 5` raises an
  error. Useful for settings that must not change during a run.
- `field(repr=False)` hides a field from the display. Useful for a
  large field, such as a mask of thousands of True/False values.

#### The R equivalent

The closest R structures are a named list with a fixed set of elements,
`list(check = "not_null", failed = 1)`, or a class defined with
`setClass()` or R6, which also declare their fields in advance.

### Type hints: `str | None`

```python
mask: pd.Series | None = None
def run_checks(df: pd.DataFrame, rules: dict | None = None) -> pd.DataFrame:
```

- `: type` after a name says what it should hold; `-> type` says what a
  function returns.
- `A | B` means "A or B". `pd.Series | None` means "a pandas Series, or
  nothing".
- Python does not check these types when the code runs. They document
  the code, and editors use them to catch mistakes as you type.

### Boolean masks

Most checks produce a **mask**: a Series of True/False, one value per
row, True where the row fails.

```python
mask = df["amount"] < 0          # True for negative amounts
mask.sum()                       # number of failing rows (True counts as 1)
df[mask]                         # the failing rows
df[~mask]                        # the other rows (~ means "not")
mask_a | mask_b                  # fails A or B
mask_a & mask_b                  # fails A and B
```

`split_valid_invalid()` combines the masks of every broken rule to
decide which rows are invalid.

---

## Project structure

```
data-quality/
├── data_quality.py     the module (run it for the demonstration)
├── requirements.txt    pandas
├── LICENSE
└── README.md
```

## Licence

MIT
