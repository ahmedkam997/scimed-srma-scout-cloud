"""Audit ASReview 3.0.8 closed-corpus simulations at matching analysis units."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def summarize(labels, ordered_ids):
    positives = sum(labels.values())
    if not positives or not ordered_ids or len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("Expected positive reference labels and unique screening decisions")
    budgets = {str(percent): math.ceil(len(labels) * percent / 100) for percent in (10, 25, 50)}
    prefix_positives = [0]
    at95 = None
    target = math.ceil(0.95 * positives)
    for screened, record_id in enumerate(ordered_ids, 1):
        prefix_positives.append(prefix_positives[-1] + labels[record_id])
        if at95 is None and prefix_positives[-1] >= target:
            at95 = screened
    found = prefix_positives[-1]
    return {
        "total": len(labels),
        "reference_positive": positives,
        "screened": len(ordered_ids),
        "found_positive": found,
        "reference_recall": found / positives,
        "recall_at_budget_percent": {
            percent: (
                prefix_positives[min(budget, len(ordered_ids))] / positives
                if budget <= len(ordered_ids) or found == positives
                else None
            )
            for percent, budget in budgets.items()
        },
        "screened_at_95": at95,
        "random_expected_screened_at_95": target * (len(labels) + 1) / (positives + 1),
        "wss95": None if at95 is None else 0.95 - at95 / len(labels),
    }


def audit(labels, members, representatives, expanded, *, grouped=True):
    if set(members) != set(labels):
        raise ValueError("ASReview input IDs do not cover the reference corpus")
    group_labels = {}
    conflicts = set()
    for record_id, group_id in members.items():
        label = labels[record_id]
        if label not in (0, 1):
            raise ValueError("Non-binary reference label")
        if group_labels.setdefault(group_id, label) != label:
            conflicts.add(group_id)
    if grouped and conflicts:
        raise ValueError("conflicting reference label in a duplicate group")
    for record_id, label in expanded + representatives:
        if labels[record_id] != label:
            raise ValueError("ASReview result label disagrees with the reference CSV")
    group_ids = [record_id for record_id, _ in representatives]
    expanded_ids = [record_id for record_id, _ in expanded]
    if len(set(expanded_ids)) != len(expanded_ids):
        raise ValueError("Expanded results contain repeated record IDs")
    if group_ids != [record for record in expanded_ids if members[record] == record]:
        raise ValueError("Representative export does not match the expanded record order")
    group_sizes = Counter(members.values())
    duplicate_summary = {
        "duplicate_groups": sum(size > 1 for size in group_sizes.values()),
        "duplicate_rows": len(labels) - len(group_labels),
        "conflicting_label_groups": len(conflicts),
        "exported_representative_rows": len(group_ids),
        "exported_representative_positives": sum(int(label) for _, label in representatives),
    }
    if not grouped:
        return {**duplicate_summary, "record_decisions": summarize(labels, expanded_ids)}

    if any(members[group] != group for group in group_ids):
        raise ValueError("Representative is not the base record of its group")
    if list(dict.fromkeys(members[record] for record in expanded_ids)) != group_ids:
        raise ValueError("Expanded and representative exports disagree on screening order")
    if Counter(members[record] for record in expanded_ids) != {
        group: group_sizes[group] for group in group_ids
    }:
        raise ValueError("Expanded results do not cover all members of screened groups")

    return {
        **duplicate_summary,
        "group_decisions": summarize(group_labels, group_ids),
        # Expanded rows measure coverage. Their within-group order is arbitrary
        # and does not represent separate screening decisions.
        "expanded_rows": {
            "total": len(labels),
            "reference_positive": sum(labels.values()),
            "labeled": len(expanded_ids),
            "found_positive": sum(int(label) for _, label in expanded),
            "reference_recall": sum(int(label) for _, label in expanded) / sum(labels.values()),
        },
    }


def main():
    from asreview import Project, open_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("project", type=Path)
    parser.add_argument("--grouped", action="store_true", help="Simulation used --group-similar-records")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset_sha256 = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    with args.dataset.open(newline="", encoding="utf-8-sig") as source:
        labels = {
            index: int(row["label_included"])
            for index, row in enumerate(csv.DictReader(source))
        }
    with TemporaryDirectory() as directory:
        project = Project.load(args.project, directory)
        if project.config.get("mode") != "simulate" or (project.review or {}).get("status") != "finished":
            raise ValueError("Expected a finished ASReview simulation")
        inputs = [path for path in project.data_dir.iterdir() if path.is_file()]
        if len(inputs) != 1 or hashlib.sha256(inputs[0].read_bytes()).hexdigest() != dataset_sha256:
            raise ValueError("Reference CSV does not match the simulation input bytes")
        with open_db(project.db_path, read_only=True) as state:
            stored_labels = dict(
                state.input.get_df()[["record_id", "included"]].itertuples(index=False, name=None)
            )
            if stored_labels != labels:
                raise ValueError("ASReview stored input labels differ from the reference CSV")
            members = {record: group for group, record in state.input.get_groups()}
            columns = ["record_id", "label"]
            representative_rows = state.get_results_table(columns=columns)
            expanded_rows = state.get_results_table(columns=columns, groups=True)
            report = audit(
                labels, members,
                list(representative_rows.itertuples(index=False, name=None)),
                list(expanded_rows.itertuples(index=False, name=None)),
                grouped=args.grouped,
            )
    report.update(
        asreview_version=version("asreview"),
        seed=args.seed,
        grouped_simulation=args.grouped,
        dataset_sha256=dataset_sha256,
        oracle_assisted=True,
        qualification_granted=False,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
