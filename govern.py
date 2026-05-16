#!/usr/bin/env python3
"""Minimal model governance report generator.

The tool intentionally uses only the Python standard library. That keeps the
project easy to run in interviews, audits, and restricted corporate machines.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REQUIRED_COLUMNS = {"period", "entity_id", "score", "y_true"}
EXCLUDED_FEATURE_COLUMNS = REQUIRED_COLUMNS | {"decision", "prediction", "label"}

MODEL_CARD = {
    "model_name": "Consumer Credit Early-Risk Score",
    "model_version": "v0.1-governance-demo",
    "owner": "Risk Analytics / Model Risk",
    "intended_use": "Prioritize accounts for manual risk review and monitoring.",
    "forbidden_use": "Automatic adverse action without human review and policy approval.",
    "label_definition": "1 means observed risk event in the monitoring window.",
}


@dataclass
class Performance:
    n: int
    positives: int
    event_rate: float
    decision_rate: float
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    specificity: float
    f1: float
    accuracy: float
    roc_auc: float | None
    pr_auc: float | None
    log_loss: float
    brier: float
    ece: float


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], ["CSV has no header row."]

        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            errors.append(f"Missing required columns: {', '.join(sorted(missing))}.")

        rows = [dict(row) for row in reader]

    if not rows:
        errors.append("CSV contains no data rows.")

    for row_number, row in enumerate(rows, start=2):
        period = row.get("period", "").strip()
        if period not in {"baseline", "current"}:
            errors.append(f"Row {row_number}: period must be baseline or current.")
        score = parse_float(row.get("score", ""), "score", row_number, errors)
        if score is not None and not 0 <= score <= 1:
            errors.append(f"Row {row_number}: score must be between 0 and 1.")
        label = row.get("y_true", "").strip()
        if label not in {"0", "1"}:
            errors.append(f"Row {row_number}: y_true must be 0 or 1.")

    periods = Counter(row.get("period", "").strip() for row in rows)
    if periods["baseline"] == 0:
        errors.append("No baseline rows found.")
    if periods["current"] == 0:
        errors.append("No current rows found.")

    return rows, errors


def read_input(
    path: Path,
    adapter: str,
    baseline_ratio: float,
    max_rows: int | None,
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    if adapter == "governance-log":
        rows, errors = read_rows(path)
        return rows, errors, []
    if adapter == "uci-default-credit":
        rows, errors = read_uci_default_credit(path, baseline_ratio, max_rows)
        notes = [
            "Kaggle UCI default-credit adapter used.",
            "A transparent repayment/utilization score is used as the champion score for governance.",
            "SEX, EDUCATION, and MARRIAGE are monitored as portfolio segments, not used in the score.",
            "Row order is used as a vintage proxy because the Kaggle file has statement months but no application timestamp.",
        ]
        return rows, errors, notes
    return [], [f"Unknown adapter: {adapter}."], []


def read_uci_default_credit(
    path: Path,
    baseline_ratio: float,
    max_rows: int | None,
) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    required = {
        "ID",
        "LIMIT_BAL",
        "SEX",
        "EDUCATION",
        "MARRIAGE",
        "AGE",
        "PAY_0",
        "PAY_2",
        "PAY_3",
        "PAY_4",
        "PAY_5",
        "PAY_6",
        "BILL_AMT1",
        "BILL_AMT2",
        "BILL_AMT3",
        "BILL_AMT4",
        "BILL_AMT5",
        "BILL_AMT6",
        "PAY_AMT1",
        "PAY_AMT2",
        "PAY_AMT3",
        "PAY_AMT4",
        "PAY_AMT5",
        "PAY_AMT6",
        "default.payment.next.month",
    }

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], ["CSV has no header row."]
        missing = required - set(reader.fieldnames)
        if missing:
            return [], [f"Missing UCI default-credit columns: {', '.join(sorted(missing))}."]

        raw_rows = []
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            raw_rows.append(row)

    if not raw_rows:
        return [], ["CSV contains no UCI default-credit rows."]

    split_index = max(1, min(len(raw_rows) - 1, int(len(raw_rows) * baseline_ratio)))
    normalized: list[dict[str, str]] = []
    for index, row in enumerate(raw_rows):
        try:
            normalized.append(uci_credit_to_governance_row(row, "baseline" if index < split_index else "current"))
        except ValueError as exc:
            errors.append(f"Row {index + 2}: {exc}")

    return normalized, errors


def uci_credit_to_governance_row(row: dict[str, str], period: str) -> dict[str, str]:
    limit = float(row["LIMIT_BAL"])
    if limit <= 0:
        raise ValueError("LIMIT_BAL must be positive.")

    pay_status = [float(row[column]) for column in ["PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"]]
    bills = [max(0.0, float(row[column])) for column in [f"BILL_AMT{i}" for i in range(1, 7)]]
    payments = [max(0.0, float(row[column])) for column in [f"PAY_AMT{i}" for i in range(1, 7)]]

    max_delay = max(0.0, max(pay_status))
    recent_delay = max(0.0, pay_status[0])
    delinquency_months = sum(1 for value in pay_status if value > 0)
    utilization = min(3.0, safe_div(statistics.mean(bills), limit))
    payment_ratio = min(3.0, safe_div(sum(payments), sum(bills)))
    payment_shortfall = max(0.0, 0.08 - safe_div(payments[0], bills[0])) if bills[0] else 0.0
    bill_growth = safe_div(bills[0] - bills[-1], limit)
    no_recent_payment = 1 if bills[0] > 0 and payments[0] == 0 else 0

    logit = (
        -2.35
        + 0.48 * max_delay
        + 0.34 * recent_delay
        + 0.26 * delinquency_months
        + 1.10 * utilization
        + 1.75 * payment_shortfall
        + 0.35 * max(0.0, bill_growth)
        + 0.30 * no_recent_payment
        - 0.35 * min(payment_ratio, 1.0)
        - 0.0000015 * limit
    )
    score = 1 / (1 + math.exp(-logit))

    return {
        "period": period,
        "entity_id": row["ID"],
        "score": f"{score:.6f}",
        "y_true": row["default.payment.next.month"],
        "limit_balance": f"{limit:.2f}",
        "age": row["AGE"],
        "pay_0": row["PAY_0"],
        "max_pay_delay": f"{max_delay:.2f}",
        "delinquency_months": str(delinquency_months),
        "utilization": f"{utilization:.6f}",
        "payment_ratio": f"{payment_ratio:.6f}",
        "payment_shortfall": f"{payment_shortfall:.6f}",
        "bill_growth_to_limit": f"{bill_growth:.6f}",
        "no_recent_payment": str(no_recent_payment),
        "sex_segment": map_uci_sex(row["SEX"]),
        "education_segment": map_uci_education(row["EDUCATION"]),
        "marriage_segment": map_uci_marriage(row["MARRIAGE"]),
        "limit_band": limit_band(limit),
    }


def map_uci_sex(value: str) -> str:
    return {"1": "male", "2": "female"}.get(value.strip(), "unknown")


def map_uci_education(value: str) -> str:
    return {
        "1": "graduate_school",
        "2": "university",
        "3": "high_school",
        "4": "other",
        "5": "unknown",
        "6": "unknown",
    }.get(value.strip(), "unknown")


def map_uci_marriage(value: str) -> str:
    return {"1": "married", "2": "single", "3": "other"}.get(value.strip(), "unknown")


def limit_band(limit: float) -> str:
    if limit < 50000:
        return "low_limit"
    if limit < 200000:
        return "mid_limit"
    if limit < 500000:
        return "high_limit"
    return "very_high_limit"


def parse_float(value: str, column: str, row_number: int, errors: list[str]) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            errors.append(f"Row {row_number}: {column} is missing.")
            return None
        return float(value)
    except ValueError:
        errors.append(f"Row {row_number}: {column} is not numeric.")
        return None


def period_rows(rows: list[dict[str, str]], period: str) -> list[dict[str, str]]:
    return [row for row in rows if row.get("period", "").strip() == period]


def infer_features(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        column
        for column in rows[0]
        if column not in EXCLUDED_FEATURE_COLUMNS and any(row.get(column, "").strip() for row in rows)
    ]


def labels_and_scores(rows: list[dict[str, str]]) -> tuple[list[int], list[float]]:
    labels = [int(row["y_true"]) for row in rows]
    scores = [float(row["score"]) for row in rows]
    return labels, scores


def performance(rows: list[dict[str, str]], threshold: float) -> Performance:
    labels, scores = labels_and_scores(rows)
    predictions = [1 if score >= threshold else 0 for score in scores]

    tp = sum(1 for y, yhat in zip(labels, predictions) if y == 1 and yhat == 1)
    fp = sum(1 for y, yhat in zip(labels, predictions) if y == 0 and yhat == 1)
    tn = sum(1 for y, yhat in zip(labels, predictions) if y == 0 and yhat == 0)
    fn = sum(1 for y, yhat in zip(labels, predictions) if y == 1 and yhat == 0)

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    f1 = safe_div(2 * precision * recall, precision + recall)
    accuracy = safe_div(tp + tn, len(labels))
    positives = sum(labels)

    return Performance(
        n=len(labels),
        positives=positives,
        event_rate=safe_div(positives, len(labels)),
        decision_rate=safe_div(sum(predictions), len(predictions)),
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1=f1,
        accuracy=accuracy,
        roc_auc=roc_auc(labels, scores),
        pr_auc=average_precision(labels, scores),
        log_loss=log_loss(labels, scores),
        brier=brier_score(labels, scores),
        ece=expected_calibration_error(labels, scores),
    )


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def roc_auc(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None

    sorted_pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    ranks: list[float] = [0.0] * len(sorted_pairs)
    i = 0
    while i < len(sorted_pairs):
        j = i
        while j + 1 < len(sorted_pairs) and sorted_pairs[j + 1][0] == sorted_pairs[i][0]:
            j += 1
        average_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[k] = average_rank
        i = j + 1

    positive_rank_sum = sum(rank for rank, (_, label) in zip(ranks, sorted_pairs) if label == 1)
    return (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def average_precision(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(labels)
    if positives == 0:
        return None

    tp = 0
    fp = 0
    previous_recall = 0.0
    area = 0.0

    for score, label in sorted(zip(scores, labels), key=lambda item: item[0], reverse=True):
        _ = score
        if label == 1:
            tp += 1
            recall = tp / positives
            precision = tp / (tp + fp)
            area += precision * (recall - previous_recall)
            previous_recall = recall
        else:
            fp += 1

    return area


def log_loss(labels: list[int], scores: list[float]) -> float:
    eps = 1e-15
    total = 0.0
    for label, score in zip(labels, scores):
        p = min(max(score, eps), 1 - eps)
        total += -(label * math.log(p) + (1 - label) * math.log(1 - p))
    return total / len(labels)


def brier_score(labels: list[int], scores: list[float]) -> float:
    return sum((score - label) ** 2 for label, score in zip(labels, scores)) / len(labels)


def expected_calibration_error(labels: list[int], scores: list[float], bins: int = 5) -> float:
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(bins)]
    for label, score in zip(labels, scores):
        index = min(int(score * bins), bins - 1)
        buckets[index].append((label, score))

    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        observed = statistics.mean(label for label, _ in bucket)
        predicted = statistics.mean(score for _, score in bucket)
        ece += len(bucket) / len(labels) * abs(observed - predicted)
    return ece


def calibration_table(rows: list[dict[str, str]], bins: int = 5) -> list[dict[str, float]]:
    labels, scores = labels_and_scores(rows)
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(bins)]
    for label, score in zip(labels, scores):
        index = min(int(score * bins), bins - 1)
        buckets[index].append((label, score))

    table = []
    for index, bucket in enumerate(buckets, start=1):
        if not bucket:
            continue
        observed = statistics.mean(label for label, _ in bucket)
        predicted = statistics.mean(score for _, score in bucket)
        table.append(
            {
                "bin": index,
                "n": len(bucket),
                "mean_score": predicted,
                "observed_rate": observed,
                "gap": observed - predicted,
            }
        )
    return table


def feature_drift(
    baseline: list[dict[str, str]], current: list[dict[str, str]], features: list[str]
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for feature in features:
        baseline_values = [row.get(feature, "").strip() for row in baseline if row.get(feature, "").strip()]
        current_values = [row.get(feature, "").strip() for row in current if row.get(feature, "").strip()]
        if not baseline_values or not current_values:
            continue

        if all_numeric(baseline_values + current_values):
            baseline_numeric = [float(value) for value in baseline_values]
            current_numeric = [float(value) for value in current_values]
            psi_value = numeric_psi(baseline_numeric, current_numeric)
            wasserstein = wasserstein_distance(baseline_numeric, current_numeric)
            median_shift = statistics.median(current_numeric) - statistics.median(baseline_numeric)
            results.append(
                {
                    "feature": feature,
                    "type": "numeric",
                    "psi": psi_value,
                    "distance": wasserstein,
                    "shift": median_shift,
                    "status": drift_status(psi_value),
                }
            )
        else:
            psi_value = categorical_psi(baseline_values, current_values)
            total_variation = categorical_total_variation(baseline_values, current_values)
            top_current = Counter(current_values).most_common(1)[0][0]
            results.append(
                {
                    "feature": feature,
                    "type": "categorical",
                    "psi": psi_value,
                    "distance": total_variation,
                    "shift": top_current,
                    "status": drift_status(psi_value),
                }
            )

    return sorted(results, key=lambda row: float(row["psi"]), reverse=True)


def all_numeric(values: Iterable[str]) -> bool:
    try:
        for value in values:
            float(value)
        return True
    except ValueError:
        return False


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("quantile needs at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def numeric_psi(baseline: list[float], current: list[float], bins: int = 5) -> float:
    raw_edges = [quantile(baseline, i / bins) for i in range(bins + 1)]
    edges = sorted(set(raw_edges))
    if len(edges) < 2:
        return 0.0

    baseline_counts = count_bins(baseline, edges)
    current_counts = count_bins(current, edges)
    return psi_from_counts(baseline_counts, current_counts)


def count_bins(values: list[float], edges: list[float]) -> list[int]:
    counts = [0 for _ in range(len(edges) - 1)]
    for value in values:
        if value <= edges[0]:
            counts[0] += 1
            continue
        if value > edges[-1]:
            counts[-1] += 1
            continue
        for index in range(1, len(edges)):
            if value <= edges[index]:
                counts[index - 1] += 1
                break
    return counts


def categorical_psi(baseline: list[str], current: list[str]) -> float:
    baseline_counter = Counter(baseline)
    current_counter = Counter(current)
    categories = sorted(set(baseline_counter) | set(current_counter))
    baseline_counts = [baseline_counter[category] for category in categories]
    current_counts = [current_counter[category] for category in categories]
    return psi_from_counts(baseline_counts, current_counts)


def psi_from_counts(baseline_counts: list[int], current_counts: list[int]) -> float:
    eps = 1e-6
    baseline_total = sum(baseline_counts)
    current_total = sum(current_counts)
    total = 0.0
    for base_count, current_count in zip(baseline_counts, current_counts):
        base_pct = max(base_count / baseline_total, eps)
        current_pct = max(current_count / current_total, eps)
        total += (current_pct - base_pct) * math.log(current_pct / base_pct)
    return total


def categorical_total_variation(baseline: list[str], current: list[str]) -> float:
    baseline_counter = Counter(baseline)
    current_counter = Counter(current)
    categories = sorted(set(baseline_counter) | set(current_counter))
    return 0.5 * sum(
        abs(baseline_counter[category] / len(baseline) - current_counter[category] / len(current))
        for category in categories
    )


def wasserstein_distance(baseline: list[float], current: list[float]) -> float:
    grid = [i / 100 for i in range(101)]
    return statistics.mean(abs(quantile(baseline, q) - quantile(current, q)) for q in grid)


def drift_status(psi_value: float) -> str:
    if psi_value >= 0.25:
        return "BREACH"
    if psi_value >= 0.10:
        return "WATCH"
    return "PASS"


def verdict(
    baseline_perf: Performance, current_perf: Performance, drift_rows: list[dict[str, object]], errors: list[str]
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "PASS"

    if errors:
        return "BREACH", ["Input validation failed."]

    breach_drift = [row for row in drift_rows if row["status"] == "BREACH"]
    watch_drift = [row for row in drift_rows if row["status"] == "WATCH"]
    if breach_drift:
        status = "BREACH"
        reasons.append(f"{len(breach_drift)} monitored feature(s) breached drift policy.")
    elif watch_drift:
        status = "WATCH"
        reasons.append(f"{len(watch_drift)} monitored feature(s) entered drift watch.")

    if baseline_perf.roc_auc is not None and current_perf.roc_auc is not None:
        auc_drop = baseline_perf.roc_auc - current_perf.roc_auc
        if auc_drop >= 0.08:
            status = "BREACH"
            reasons.append(f"ROC-AUC dropped by {auc_drop:.3f}.")
        elif auc_drop >= 0.04 and status == "PASS":
            status = "WATCH"
            reasons.append(f"ROC-AUC dropped by {auc_drop:.3f}.")

    if current_perf.ece >= 0.12:
        status = "BREACH"
        reasons.append(f"Current calibration error is high ({current_perf.ece:.3f}).")
    elif current_perf.ece >= 0.08 and status == "PASS":
        status = "WATCH"
        reasons.append(f"Current calibration error needs review ({current_perf.ece:.3f}).")

    decision_shift = abs(current_perf.decision_rate - baseline_perf.decision_rate)
    if decision_shift >= 0.15:
        status = "BREACH" if status == "BREACH" else "WATCH"
        reasons.append(f"Decision rate shifted by {decision_shift:.1%}.")

    if not reasons:
        reasons.append("No policy threshold was breached.")

    return status, reasons


def fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def performance_table(baseline_perf: Performance, current_perf: Performance) -> list[str]:
    rows = [
        ("Rows", str(baseline_perf.n), str(current_perf.n)),
        ("Event rate", pct(baseline_perf.event_rate), pct(current_perf.event_rate)),
        ("Decision rate", pct(baseline_perf.decision_rate), pct(current_perf.decision_rate)),
        ("Precision", fmt(baseline_perf.precision), fmt(current_perf.precision)),
        ("Recall", fmt(baseline_perf.recall), fmt(current_perf.recall)),
        ("F1", fmt(baseline_perf.f1), fmt(current_perf.f1)),
        ("ROC-AUC", fmt(baseline_perf.roc_auc), fmt(current_perf.roc_auc)),
        ("PR-AUC", fmt(baseline_perf.pr_auc), fmt(current_perf.pr_auc)),
        ("Log loss", fmt(baseline_perf.log_loss), fmt(current_perf.log_loss)),
        ("Brier score", fmt(baseline_perf.brier), fmt(current_perf.brier)),
        ("Calibration error", fmt(baseline_perf.ece), fmt(current_perf.ece)),
    ]
    lines = ["| Metric | Baseline | Current |", "| --- | ---: | ---: |"]
    lines.extend(f"| {metric} | {baseline} | {current} |" for metric, baseline, current in rows)
    return lines


def business_impact_lines(current_perf: Performance, fp_cost: float, fn_cost: float) -> list[str]:
    review_count = current_perf.tp + current_perf.fp
    analyst_cost = review_count * fp_cost
    missed_loss_proxy = current_perf.fn * fn_cost
    false_positive_cost = current_perf.fp * fp_cost
    lines = ["| Item | Value |", "| --- | ---: |"]
    lines.append(f"| Accounts sent to review | {review_count} |")
    lines.append(f"| False-positive review cost proxy | {false_positive_cost:,.2f} |")
    lines.append(f"| Total analyst review cost proxy | {analyst_cost:,.2f} |")
    lines.append(f"| Missed-default exposure proxy | {missed_loss_proxy:,.2f} |")
    lines.append(f"| Cost assumptions | FP/review={fp_cost:,.2f}; FN/default={fn_cost:,.2f} |")
    return lines


def segment_monitoring_lines(rows: list[dict[str, str]], threshold: float) -> list[str]:
    if not rows:
        return ["- No current rows available for segment monitoring."]

    candidate_columns = [
        "sex_segment",
        "education_segment",
        "marriage_segment",
        "limit_band",
        "segment",
        "region",
        "product",
    ]
    segment_columns = [column for column in candidate_columns if column in rows[0]]
    if not segment_columns:
        return ["- No recognized segment columns were available."]

    lines = ["| Segment | Group | Rows | Event Rate | Decision Rate | Precision | Recall |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for column in segment_columns:
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(column, "unknown") or "unknown", []).append(row)
        for group, group_rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:8]:
            perf = performance(group_rows, threshold)
            lines.append(
                f"| {column} | {group} | {perf.n} | {pct(perf.event_rate)} | "
                f"{pct(perf.decision_rate)} | {fmt(perf.precision)} | {fmt(perf.recall)} |"
            )

    lines.append("")
    lines.append("- Segment rows are monitoring evidence, not automatic proof of discrimination.")
    lines.append("- A real approval workflow would add legal review, adverse-action policy, and sample-size checks.")
    return lines


def challenger_benchmark_lines(rows: list[dict[str, str]], features: list[str]) -> list[str]:
    if not rows:
        return ["- Benchmark skipped: no rows available."]

    try:
        import pandas as pd
        from lightgbm import LGBMClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import average_precision_score, brier_score_loss, log_loss as sk_log_loss, roc_auc_score
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        return [f"- Benchmark skipped: optional modeling dependency is missing ({exc.name})."]

    baseline = [row for row in rows if row["period"] == "baseline"]
    current = [row for row in rows if row["period"] == "current"]
    if not baseline or not current:
        return ["- Benchmark skipped: both baseline and current periods are required."]

    benchmark_features = [
        feature
        for feature in features
        if feature not in {"sex_segment", "education_segment", "marriage_segment"}
    ]
    if not benchmark_features:
        return ["- Benchmark skipped: no eligible model features."]

    train_frame = pd.DataFrame(baseline)
    test_frame = pd.DataFrame(current)
    y_train = train_frame["y_true"].astype(int)
    y_test = test_frame["y_true"].astype(int)
    x_train_raw = train_frame[benchmark_features].copy()
    x_test_raw = test_frame[benchmark_features].copy()

    x_all = pd.concat([x_train_raw, x_test_raw], axis=0)
    for column in benchmark_features:
        numeric = pd.to_numeric(x_all[column], errors="coerce")
        if numeric.notna().mean() >= 0.95:
            x_all[column] = numeric.fillna(numeric.median())
        else:
            x_all[column] = x_all[column].fillna("missing").astype(str)

    x_all = pd.get_dummies(x_all, drop_first=False)
    x_train = x_all.iloc[: len(x_train_raw)]
    x_test = x_all.iloc[len(x_train_raw) :]

    models = [
        (
            "Logistic scorecard challenger",
            make_pipeline(
                StandardScaler(with_mean=False),
                LogisticRegression(max_iter=1000, class_weight="balanced", solver="liblinear"),
            ),
            "Transparent coefficient baseline; good governance reference.",
        ),
        (
            "LightGBM challenger",
            LGBMClassifier(
                n_estimators=160,
                learning_rate=0.035,
                num_leaves=15,
                min_child_samples=120,
                subsample=0.85,
                colsample_bytree=0.85,
                class_weight="balanced",
                random_state=42,
                verbose=-1,
            ),
            "Histogram GBDT; preferred over XGBoost here for fast tabular iteration and stable handling of sparse one-hot features.",
        ),
    ]

    lines = [
        "| Model | ROC-AUC | PR-AUC | Log Loss | Brier | Governance Read |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, model, note in models:
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_test)[:, 1]
        probabilities = [min(max(float(value), 1e-6), 1 - 1e-6) for value in probabilities]
        lines.append(
            f"| {name} | {roc_auc_score(y_test, probabilities):.3f} | "
            f"{average_precision_score(y_test, probabilities):.3f} | "
            f"{sk_log_loss(y_test, probabilities):.3f} | "
            f"{brier_score_loss(y_test, probabilities):.3f} | {note} |"
        )

    lines.append("")
    lines.append("- Protected/proxy governance fields are excluded from challenger training and monitored separately.")
    lines.append("- Challenger metrics are not automatic approval; calibration, drift, fairness, and operating-cost review still decide deployment.")
    return lines


def build_report(
    rows: list[dict[str, str]],
    errors: list[str],
    threshold: float,
    features: list[str],
    notes: list[str] | None = None,
    fp_cost: float = 35.0,
    fn_cost: float = 2500.0,
    benchmark_challengers: bool = False,
) -> str:
    baseline = period_rows(rows, "baseline")
    current = period_rows(rows, "current")
    baseline_perf = performance(baseline, threshold) if baseline else empty_performance()
    current_perf = performance(current, threshold) if current else empty_performance()
    drift_rows = feature_drift(baseline, current, features) if baseline and current else []
    report_status, reasons = verdict(baseline_perf, current_perf, drift_rows, errors)

    lines: list[str] = []
    lines.append("# Model Governance Report")
    lines.append("")
    lines.append("## Executive Verdict")
    lines.append("")
    lines.append(f"**Status:** {report_status}")
    lines.append("")
    for reason in reasons:
        lines.append(f"- {reason}")

    lines.append("")
    lines.append("## Model Card")
    lines.append("")
    for key, value in MODEL_CARD.items():
        label = key.replace("_", " ").title()
        lines.append(f"- **{label}:** {value}")
    lines.append(f"- **Decision threshold:** {threshold:.2f}")

    lines.append("")
    lines.append("## Input Validation")
    lines.append("")
    if errors:
        for error in errors:
            lines.append(f"- BREACH: {error}")
    else:
        lines.append("- PASS: required schema and label/score ranges are valid.")
        lines.append(f"- PASS: monitoring features inferred: {', '.join(features)}.")
        for note in notes or []:
            lines.append(f"- NOTE: {note}")

    lines.append("")
    lines.append("## Performance Monitoring")
    lines.append("")
    lines.extend(performance_table(baseline_perf, current_perf))

    lines.append("")
    lines.append("## Confusion Matrix")
    lines.append("")
    lines.append("| Period | TP | FP | TN | FN |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    lines.append(
        f"| Baseline | {baseline_perf.tp} | {baseline_perf.fp} | {baseline_perf.tn} | {baseline_perf.fn} |"
    )
    lines.append(f"| Current | {current_perf.tp} | {current_perf.fp} | {current_perf.tn} | {current_perf.fn} |")

    lines.append("")
    lines.append("## Business Impact")
    lines.append("")
    lines.extend(business_impact_lines(current_perf, fp_cost, fn_cost))

    lines.append("")
    lines.append("## Drift Monitoring")
    lines.append("")
    if drift_rows:
        lines.append("| Feature | Type | PSI | Distance | Shift / Top Current | Status |")
        lines.append("| --- | --- | ---: | ---: | --- | --- |")
        for row in drift_rows:
            shift = row["shift"]
            if isinstance(shift, float):
                shift_text = fmt(shift)
            else:
                shift_text = str(shift)
            lines.append(
                "| {feature} | {type} | {psi} | {distance} | {shift} | {status} |".format(
                    feature=row["feature"],
                    type=row["type"],
                    psi=fmt(float(row["psi"])),
                    distance=fmt(float(row["distance"])),
                    shift=shift_text,
                    status=row["status"],
                )
            )
    else:
        lines.append("- No drift checks were run.")

    lines.append("")
    lines.append("## Current Calibration")
    lines.append("")
    lines.append("| Score Bin | Rows | Mean Score | Observed Rate | Gap |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for row in calibration_table(current) if current else []:
        lines.append(
            f"| {int(row['bin'])} | {int(row['n'])} | {fmt(row['mean_score'])} | "
            f"{fmt(row['observed_rate'])} | {fmt(row['gap'])} |"
        )

    lines.append("")
    lines.append("## Segment Monitoring")
    lines.append("")
    lines.extend(segment_monitoring_lines(current, threshold))

    if benchmark_challengers and not errors:
        lines.append("")
        lines.append("## Challenger Benchmark")
        lines.append("")
        lines.extend(challenger_benchmark_lines(rows, features))

    lines.append("")
    lines.append("## Review Actions")
    lines.append("")
    lines.extend(review_actions(report_status, current_perf, drift_rows))

    lines.append("")
    lines.append("## Audit Notes")
    lines.append("")
    lines.append("- Scope: this is a narrow practice dry run for portfolio learning, not a production credit-decision system.")
    lines.append("- Ethical use: use for model monitoring, QA, and human risk review only.")
    lines.append("- Do not use this script for automatic credit denial, pricing, collections action, or customer adverse action.")
    lines.append("- Do not use protected or proxy-sensitive segments to optimize punitive decisions.")
    lines.append("- This report monitors an existing champion score; it does not train a new model.")
    lines.append("- Delayed labels must be backfilled before final performance sign-off.")
    lines.append("- Drift is a trigger for investigation, not proof that the model is wrong.")
    lines.append("- Any adverse customer action requires policy review outside this script.")
    lines.append("")

    return "\n".join(lines)


def empty_performance() -> Performance:
    return Performance(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None, 0, 0, 0)


def review_actions(status: str, current_perf: Performance, drift_rows: list[dict[str, object]]) -> list[str]:
    actions: list[str] = []
    high_drift = [row for row in drift_rows if row["status"] in {"WATCH", "BREACH"}]
    if status == "PASS":
        actions.append("- Continue standard monthly monitoring.")
    else:
        actions.append("- Open a model-risk review ticket before the next production release.")

    if high_drift:
        features = ", ".join(str(row["feature"]) for row in high_drift[:5])
        actions.append(f"- Investigate feature drift first: {features}.")
    if current_perf.ece >= 0.08:
        actions.append("- Recheck probability calibration and consider threshold recalibration.")
    if current_perf.fp > current_perf.tp:
        actions.append("- Review false-positive workload and analyst capacity before expanding usage.")
    if current_perf.fn > 0:
        actions.append("- Sample false negatives to check missing features, label delay, or policy leakage.")

    actions.append("- Keep challenger-model work in appendix until it beats the champion on risk-adjusted metrics.")
    return actions


def run(
    input_path: Path,
    output_path: Path,
    threshold: float,
    fail_on_breach: bool,
    adapter: str,
    baseline_ratio: float,
    max_rows: int | None,
    fp_cost: float,
    fn_cost: float,
    benchmark_challengers: bool,
) -> int:
    rows, errors, notes = read_input(input_path, adapter, baseline_ratio, max_rows)
    features = infer_features(rows)
    report = build_report(
        rows,
        errors,
        threshold,
        features,
        notes=notes,
        fp_cost=fp_cost,
        fn_cost=fn_cost,
        benchmark_challengers=benchmark_challengers,
    )
    output_path.write_text(report, encoding="utf-8")

    baseline = period_rows(rows, "baseline")
    current = period_rows(rows, "current")
    baseline_perf = performance(baseline, threshold) if baseline else empty_performance()
    current_perf = performance(current, threshold) if current else empty_performance()
    drift_rows = feature_drift(baseline, current, features) if baseline and current else []
    status, reasons = verdict(baseline_perf, current_perf, drift_rows, errors)

    print(f"Wrote {output_path}")
    print(f"Status: {status}")
    print(f"Reason: {reasons[0]}")
    return 1 if fail_on_breach and status == "BREACH" else 0


def self_test() -> int:
    labels = [0, 0, 1, 1]
    scores = [0.05, 0.20, 0.80, 0.95]
    assert roc_auc(labels, scores) == 1.0
    assert round(average_precision(labels, scores) or 0, 6) == 1.0
    assert brier_score(labels, scores) < 0.05
    assert numeric_psi([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 0.0
    assert categorical_total_variation(["a", "a", "b"], ["a", "b", "b"]) > 0

    fake_rows = [
        {"period": "baseline", "entity_id": "b1", "score": "0.1", "y_true": "0", "income": "50", "segment": "a"},
        {"period": "baseline", "entity_id": "b2", "score": "0.9", "y_true": "1", "income": "90", "segment": "b"},
        {"period": "current", "entity_id": "c1", "score": "0.2", "y_true": "0", "income": "55", "segment": "a"},
        {"period": "current", "entity_id": "c2", "score": "0.8", "y_true": "1", "income": "95", "segment": "b"},
    ]
    report = build_report(fake_rows, [], 0.5, infer_features(fake_rows))
    assert "Executive Verdict" in report
    assert "Performance Monitoring" in report
    assert "Drift Monitoring" in report
    assert "Business Impact" in report
    assert "Segment Monitoring" in report

    print("Self-tests passed.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a minimal model governance report.")
    parser.add_argument("input", nargs="?", type=Path, default=Path("sample_predictions.csv"))
    parser.add_argument("--output", type=Path, default=Path("model_governance_report.md"))
    parser.add_argument("--adapter", choices=["governance-log", "uci-default-credit"], default="governance-log")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--baseline-ratio", type=float, default=0.60)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--fp-cost", type=float, default=35.0)
    parser.add_argument("--fn-cost", type=float, default=2500.0)
    parser.add_argument("--benchmark-challengers", action="store_true")
    parser.add_argument("--fail-on-breach", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        return self_test()
    if not 0 <= args.threshold <= 1:
        print("--threshold must be between 0 and 1", file=sys.stderr)
        return 2
    if not 0 < args.baseline_ratio < 1:
        print("--baseline-ratio must be between 0 and 1", file=sys.stderr)
        return 2
    return run(
        args.input,
        args.output,
        args.threshold,
        args.fail_on_breach,
        args.adapter,
        args.baseline_ratio,
        args.max_rows,
        args.fp_cost,
        args.fn_cost,
        args.benchmark_challengers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
