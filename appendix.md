# Appendix: Governance Decisions

This appendix keeps the background work out of the main product. The main user only needs `README.md`, `govern.py`, `sample_predictions.csv`, and the generated report.

## Product Decision

The project is a batch governance report, not a full MLOps platform.

Reason:

- Model risk teams usually need a clear monthly/weekly review artifact before they need a complex service.
- The fastest useful product is a repeatable report that validates data, checks performance, checks calibration, checks drift, and recommends review actions.
- APIs, dashboards, MLflow, cloud, and CI are later layers. They are not needed to prove the governance logic.

The project now supports a real Kaggle credit-risk dataset through `--adapter uci-default-credit`. The adapter converts the UCI default-credit file into the governance log shape required by the report.

## Chosen Minimal Structure

| File | Decision |
| --- | --- |
| `govern.py` | One readable script instead of many tiny modules. Faster to review. |
| `sample_predictions.csv` | Small but complete example with baseline and current periods. |
| `model_governance_report.md` | Generated audit artifact. |
| `appendix.md` | Background reasoning that would normally live across tickets, experiment notes, and design docs. |
| `DATASET.md` | Kaggle source mapping and industry framing. |

Removed from the first version:

- empty `src/`, `tests/`, `api/`, `dashboards/`, `infra/`, and notebook folders
- external dependencies
- model training pipeline
- cloud deployment
- database migrations

This is still "simple", but no longer "easy": the surface is small while the methodology includes challenger modeling, calibration review, drift policy, cost impact, and segment governance.

## Input Contract

Required fields:

- `period`: `baseline` or `current`
- `entity_id`: business identifier
- `score`: predicted probability, 0 to 1
- `y_true`: observed outcome, 0 or 1

Every other column is treated as a monitored feature.

This design is intentionally flexible. It can govern credit risk, fraud, AML, churn, or collections models if the score and label definitions are clear.

## Metrics Chosen

| Area | Metric | Why it is included |
| --- | --- | --- |
| Ranking | ROC-AUC | Measures whether positives rank above negatives. Stable general diagnostic. |
| Rare events | PR-AUC | Better signal when positives are scarce. |
| Operating point | Precision, recall, F1, confusion matrix | Shows analyst workload and missed-risk tradeoff. |
| Probability quality | Log loss, Brier score, calibration error | Governance needs probability quality, not only class labels. |
| Numeric drift | PSI, Wasserstein distance, median shift | PSI is common in banking; Wasserstein gives intuitive magnitude. |
| Categorical drift | Categorical PSI, total variation | Captures product/region/segment mix changes. |
| Decision impact | Decision rate shift | Shows whether the model suddenly sends more cases to review. |

## Policy Thresholds

| Check | Watch | Breach |
| --- | ---: | ---: |
| PSI | `>= 0.10` | `>= 0.25` |
| ROC-AUC drop | `>= 0.04` | `>= 0.08` |
| Calibration error | `>= 0.08` | `>= 0.12` |
| Decision-rate shift | `>= 0.15` | manual review |

These are review triggers, not universal regulatory law. A real bank would tune them by model criticality, sample size, label delay, and policy risk.

## Champion / Challenger Model Decision

This project monitors a champion score. It does not train the model.

For the Kaggle UCI adapter, the champion is a transparent repayment/utilization score. That is deliberate. In regulated credit work, an auditable score with monotonic business logic can be a stronger portfolio artifact than a black-box model with slightly better AUC and weak governance.

The adapter uses:

- repayment delay history
- number of delinquent months
- credit utilization
- payment shortfall
- no recent payment flag
- bill growth relative to credit limit
- credit limit band as a monitored segment

The adapter does not use `SEX`, `EDUCATION`, or `MARRIAGE` in scoring. Those fields are monitored as segments because they are governance and fairness review concerns, not variables to casually optimize on.

`govern.py` also supports `--benchmark-challengers`. That trains two deliberately different challengers on the baseline period and evaluates them on the current period:

- Logistic scorecard challenger: interpretable, coefficient-based, stable governance baseline.
- LightGBM challenger: histogram-based gradient boosting for tabular data, good with sparse one-hot features, fast iteration, and often simpler deployment/latency tradeoffs than heavier XGBoost setups.

The reason to prefer LightGBM over XGBoost for this specific specialist demo is not fashion. The credit-risk adapter creates mixed numeric and sparse categorical monitoring variables. LightGBM is efficient on this type of tabular feature matrix, has good regularization knobs (`num_leaves`, `min_child_samples`, subsampling), and is fast enough to support repeated challenger tests inside model-risk review. XGBoost remains valid, but it is not automatically the superior choice.

For the portfolio story, the model selection record should look like this once training work exists:

| Candidate | Expected Strength | Governance Risk | Decision |
| --- | --- | --- | --- |
| Logistic regression / scorecard | Transparent coefficients, easy reason codes, simple calibration | May miss nonlinear effects | Strong baseline and likely regulated champion. |
| Random forest | Captures nonlinear effects, robust baseline | Harder reason codes, weaker calibration without extra work | Good challenger. |
| LightGBM gradient boosting | Strong tabular ranking, fast histogram training, good sparse-feature behavior | Explanation, calibration, and drift governance still required | Preferred challenger for this project. |
| XGBoost gradient boosting | Strong, widely used, robust | Often heavier for quick governance iteration here | Keep as alternative, not default. |
| Neural network | Flexible | Hard to justify for tabular regulated risk unless clear uplift | Not first choice. |

Senior-level decision: for regulated banking, the "best" model is not automatically the highest AUC model. It is the model with the best risk-adjusted combination of performance, calibration, stability, explainability, monitoring cost, and audit defensibility.

## Methodology Depth

The report intentionally touches several concerns that mid/senior model-risk and credit-risk specialists are expected to understand:

- Time or vintage split: baseline vs current is treated as monitoring over time, not random cross-validation.
- Leakage discipline: target is next-period default; monitored demographic fields are not fed into the champion score.
- Ranking vs probability quality: ROC-AUC and PR-AUC answer ranking; log loss, Brier score, and calibration error answer probability usefulness.
- Threshold economics: false positives consume analyst/review capacity; false negatives proxy missed credit loss.
- Drift: PSI is familiar in banking; Wasserstein distance gives numeric magnitude; categorical total variation catches portfolio-mix changes.
- Segment monitoring: differences by sex, education, marriage, and limit band are review triggers, not final legal conclusions.
- Calibration: a high AUC model can still be bad for expected-loss decisions if probabilities are miscalibrated.
- Champion/challenger governance: uplift must be material after accounting for documentation, explainability, monitoring, and operational cost.

## Skills Reflected From The Skill List

| Skill Area | Where It Appears |
| --- | --- |
| Logistic regression / scorecard thinking | transparent champion and logistic challenger |
| LightGBM / gradient boosting | optional challenger benchmark |
| ROC-AUC, PR-AUC, F1, confusion matrix | performance monitoring |
| Log loss, Brier score, calibration | probability governance |
| PSI, Wasserstein distance | drift monitoring |
| Categorical proportion shift | segment and portfolio-mix drift |
| Robust business metric mapping | FP review cost and FN loss proxy |
| Fairness / protected-feature caution | monitored segments excluded from scoring |
| Model risk management | model card, intended/forbidden use, audit notes |
| Data leakage awareness | time split and excluded fields |
| MLOps awareness | report is batch-first but CI-friendly through `--fail-on-breach` |
| Explainability discipline | reasoned champion score before black-box deployment |
| Threshold tuning | decision-rate monitoring and threshold argument |

## Tests Performed

Built into `govern.py --self-test`:

- ROC-AUC returns `1.0` for perfect ranking.
- PR-AUC returns `1.0` for perfect ranking.
- Brier score is low for confident correct probabilities.
- Numeric PSI is `0.0` for identical distributions.
- Categorical total variation detects distribution change.
- Report generation contains the required sections.
- Optional challenger benchmark can compare logistic scorecard vs LightGBM when dependencies are present.

Manual review checklist:

- Required columns are enforced.
- Score must be in `[0, 1]`.
- Label must be binary.
- Both `baseline` and `current` periods must exist.
- Current drift rows are sorted by highest PSI first.
- The report includes model card, validation, performance, drift, calibration, review actions, and audit notes.

## Known Limits

- Small sample data is only a demonstration.
- This is a narrow practice dry run, not a production credit-risk system.
- No confidence intervals yet.
- Segment monitoring is included, but full fairness/adverse-impact review still requires legal and policy context.
- No delayed-label handling beyond audit notes.
- No SHAP/LIME reason codes yet.
- No database-backed audit log yet.
- No PDF export yet.
- By default, a `BREACH` report is still a successful command because the tool did its job. Use `--fail-on-breach` for CI enforcement.

## Ethical Considerations

Recommended use:

- model monitoring practice
- governance report practice
- calibration/drift/threshold learning
- human model-risk review simulation

Not recommended:

- automatic credit denial
- automated pricing or limit reduction
- collections targeting
- punitive customer action
- optimizing on protected/proxy-sensitive demographic segments

Even if a model improves AUC, that does not make it ethical or compliant. In credit, the correct standard is not "can the model predict?" but "can the institution justify the data, decision policy, customer impact, monitoring controls, and appeal/review path?"

## Next Extensions

Add only after the minimal product is accepted:

1. Confidence intervals via bootstrap.
2. Segment-level monitoring by region, product, and customer segment.
3. Fairness / adverse-impact checks where legally and ethically appropriate.
4. Model-card export as JSON plus Markdown.
5. FastAPI endpoint for report status.
6. CI job that runs `python govern.py --self-test`.
