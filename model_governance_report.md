# Model Governance Report

## Executive Verdict

**Status:** PASS

- No policy threshold was breached.

## Model Card

- **Model Name:** Consumer Credit Early-Risk Score
- **Model Version:** v0.1-governance-demo
- **Owner:** Risk Analytics / Model Risk
- **Intended Use:** Prioritize accounts for manual risk review and monitoring.
- **Forbidden Use:** Automatic adverse action without human review and policy approval.
- **Label Definition:** 1 means observed risk event in the monitoring window.
- **Decision threshold:** 0.35

## Input Validation

- PASS: required schema and label/score ranges are valid.
- PASS: monitoring features inferred: limit_balance, age, pay_0, max_pay_delay, delinquency_months, utilization, payment_ratio, payment_shortfall, bill_growth_to_limit, no_recent_payment, sex_segment, education_segment, marriage_segment, limit_band.
- NOTE: Kaggle UCI default-credit adapter used.
- NOTE: A transparent repayment/utilization score is used as the champion score for governance.
- NOTE: SEX, EDUCATION, and MARRIAGE are monitored as portfolio segments, not used in the score.
- NOTE: Row order is used as a vintage proxy because the Kaggle file has statement months but no application timestamp.

## Performance Monitoring

| Metric | Baseline | Current |
| --- | ---: | ---: |
| Rows | 18000 | 12000 |
| Event rate | 23.1% | 20.7% |
| Decision rate | 22.8% | 19.8% |
| Precision | 0.515 | 0.538 |
| Recall | 0.510 | 0.513 |
| F1 | 0.513 | 0.525 |
| ROC-AUC | 0.723 | 0.752 |
| PR-AUC | 0.484 | 0.502 |
| Log loss | 0.497 | 0.442 |
| Brier score | 0.155 | 0.135 |
| Calibration error | 0.056 | 0.029 |

## Confusion Matrix

| Period | TP | FP | TN | FN |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 2117 | 1994 | 11856 | 2033 |
| Current | 1276 | 1097 | 8417 | 1210 |

## Business Impact

| Item | Value |
| --- | ---: |
| Accounts sent to review | 2373 |
| False-positive review cost proxy | 38,395.00 |
| Total analyst review cost proxy | 83,055.00 |
| Missed-default exposure proxy | 3,025,000.00 |
| Cost assumptions | FP/review=35.00; FN/default=2,500.00 |

## Drift Monitoring

| Feature | Type | PSI | Distance | Shift / Top Current | Status |
| --- | --- | ---: | ---: | --- | --- |
| limit_balance | numeric | 0.013 | 13283.168 | 20000.000 | PASS |
| limit_band | categorical | 0.010 | 0.041 | mid_limit | PASS |
| education_segment | categorical | 0.008 | 0.017 | university | PASS |
| sex_segment | categorical | 0.007 | 0.040 | female | PASS |
| pay_0 | numeric | 0.007 | 0.119 | 0.000 | PASS |
| payment_ratio | numeric | 0.005 | 0.030 | 0.016 | PASS |
| utilization | numeric | 0.005 | 0.011 | -0.034 | PASS |
| delinquency_months | numeric | 0.004 | 0.129 | 0.000 | PASS |
| marriage_segment | categorical | 0.002 | 0.015 | single | PASS |
| age | numeric | 0.002 | 0.168 | 0.000 | PASS |
| max_pay_delay | numeric | 0.001 | 0.089 | 0.000 | PASS |
| bill_growth_to_limit | numeric | 0.001 | 0.024 | -0.001 | PASS |
| payment_shortfall | numeric | 0.000 | 0.001 | -0.003 | PASS |
| no_recent_payment | numeric | 0.000 | 0.010 | 0.000 | PASS |

## Current Calibration

| Score Bin | Rows | Mean Score | Observed Rate | Gap |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 8348 | 0.100 | 0.110 | 0.009 |
| 2 | 1451 | 0.259 | 0.244 | -0.015 |
| 3 | 768 | 0.492 | 0.395 | -0.098 |
| 4 | 919 | 0.695 | 0.610 | -0.085 |
| 5 | 514 | 0.880 | 0.687 | -0.194 |

## Segment Monitoring

| Segment | Group | Rows | Event Rate | Decision Rate | Precision | Recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| sex_segment | female | 7536 | 19.0% | 17.6% | 0.530 | 0.492 |
| sex_segment | male | 4464 | 23.6% | 23.4% | 0.547 | 0.542 |
| education_segment | university | 5563 | 23.0% | 22.7% | 0.554 | 0.547 |
| education_segment | graduate_school | 4162 | 16.9% | 14.1% | 0.547 | 0.457 |
| education_segment | high_school | 2011 | 23.9% | 24.8% | 0.502 | 0.520 |
| education_segment | unknown | 184 | 9.2% | 11.4% | 0.238 | 0.294 |
| education_segment | other | 80 | 6.2% | 3.8% | 0.000 | 0.000 |
| marriage_segment | single | 6307 | 19.5% | 20.2% | 0.524 | 0.540 |
| marriage_segment | married | 5565 | 21.9% | 19.3% | 0.559 | 0.492 |
| marriage_segment | other | 102 | 27.5% | 20.6% | 0.381 | 0.286 |
| marriage_segment | unknown | 26 | 15.4% | 15.4% | 0.250 | 0.250 |
| limit_band | mid_limit | 5704 | 22.7% | 23.2% | 0.524 | 0.536 |
| limit_band | high_limit | 4377 | 13.8% | 7.3% | 0.591 | 0.313 |
| limit_band | low_limit | 1539 | 35.9% | 46.5% | 0.536 | 0.696 |
| limit_band | very_high_limit | 380 | 9.2% | 3.4% | 0.692 | 0.257 |

- Segment rows are monitoring evidence, not automatic proof of discrimination.
- A real approval workflow would add legal review, adverse-action policy, and sample-size checks.

## Challenger Benchmark

| Model | ROC-AUC | PR-AUC | Log Loss | Brier | Governance Read |
| --- | ---: | ---: | ---: | ---: | --- |
| Logistic scorecard challenger | 0.749 | 0.512 | 0.557 | 0.183 | Transparent coefficient baseline; good governance reference. |
| LightGBM challenger | 0.797 | 0.573 | 0.520 | 0.169 | Histogram GBDT; preferred over XGBoost here for fast tabular iteration and stable handling of sparse one-hot features. |

- Protected/proxy governance fields are excluded from challenger training and monitored separately.
- Challenger metrics are not automatic approval; calibration, drift, fairness, and operating-cost review still decide deployment.

## Review Actions

- Continue standard monthly monitoring.
- Sample false negatives to check missing features, label delay, or policy leakage.
- Keep challenger-model work in appendix until it beats the champion on risk-adjusted metrics.

## Audit Notes

- Scope: this is a narrow practice dry run for portfolio learning, not a production credit-decision system.
- Ethical use: use for model monitoring, QA, and human risk review only.
- Do not use this script for automatic credit denial, pricing, collections action, or customer adverse action.
- Do not use protected or proxy-sensitive segments to optimize punitive decisions.
- This report monitors an existing champion score; it does not train a new model.
- Delayed labels must be backfilled before final performance sign-off.
- Drift is a trigger for investigation, not proof that the model is wrong.
- Any adverse customer action requires policy review outside this script.
