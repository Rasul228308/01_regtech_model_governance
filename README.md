# Regtech Model Governance

Minimal batch governance tool for a regulated financial model.

It reads one prediction log, compares `baseline` vs `current`, and writes a model governance report with:

- schema checks
- classification performance
- calibration checks
- numeric and categorical drift
- segment monitoring
- business impact proxies
- risk verdict
- review actions for model risk / compliance

## Files

| File | Purpose |
| --- | --- |
| `govern.py` | Full runnable governance tool, including built-in self-tests. |
| `sample_predictions.csv` | Small example prediction log. |
| `model_governance_report.md` | Generated example report. Recreate it with the command below. |
| `appendix.md` | Background decisions, tests, metric choices, and model-risk reasoning. |
| `DATASET.md` | Real Kaggle dataset source and industry mapping. |

## Run

```powershell
python govern.py sample_predictions.csv
```

Run built-in tests:

```powershell
python govern.py --self-test
```

Use a different threshold:

```powershell
python govern.py sample_predictions.csv --threshold 0.40
```

Run the real Kaggle credit-default dataset:

```powershell
python govern.py kaggle_raw/extracted/UCI_Credit_Card.csv --adapter uci-default-credit --output model_governance_report.md
```

The Kaggle adapter builds an auditable champion score from repayment behavior and utilization, then monitors it like a regulated credit model.

Include a lightweight challenger benchmark:

```powershell
python govern.py kaggle_raw/extracted/UCI_Credit_Card.csv --adapter uci-default-credit --benchmark-challengers --output model_governance_report.md
```

The benchmark compares a logistic scorecard challenger with a LightGBM challenger. This keeps the main report simple while showing senior-level model selection discipline.

Make automation fail when the report status is `BREACH`:

```powershell
python govern.py sample_predictions.csv --fail-on-breach
```

## Required Input Columns

| Column | Meaning |
| --- | --- |
| `period` | Must contain `baseline` and `current`. |
| `entity_id` | Customer, account, application, or transaction identifier. |
| `score` | Predicted risk probability from 0 to 1. |
| `y_true` | Observed binary outcome: `0` or `1`. |

All other columns are treated as monitoring features. Numeric features get PSI and Wasserstein drift. Categorical features get proportion-shift and categorical PSI.

## Output Standard

The generated report answers five audit questions:

1. Is the model still performing acceptably?
2. Did the input distribution change?
3. Are probabilities calibrated enough for decision use?
4. Which monitored features explain the risk?
5. What should risk/compliance review next?

## Ethical Scope

This is a practice dry run for portfolio learning, model monitoring, and human review. Do not use it for automatic credit denial, pricing, collections, or adverse customer action. Segment monitoring is included to surface review questions, not to justify discriminatory optimization.
