# Kaggle Dataset

## Source

- Kaggle: `uciml/default-of-credit-card-clients-dataset`
- URL: https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset
- Local file: `kaggle_raw/extracted/UCI_Credit_Card.csv`

## Why This Fits

This is a classic regulated-credit dataset: payment history, credit limit, bill statements, prior payments, demographic segments, and next-month default. It is useful for model governance because the real problem is not only prediction. A middle/senior specialist must also handle calibration, population drift, policy thresholds, segment review, and audit language.

## Portfolio Use

Use it to produce a governance report from real credit-risk data:

```powershell
python govern.py kaggle_raw/extracted/UCI_Credit_Card.csv --adapter uci-default-credit --output model_governance_report.md
```

The adapter builds a transparent champion-style score from repayment behavior and utilization. This is deliberately auditable: it avoids pretending that a black-box model is always the best first answer in regulated banking.
