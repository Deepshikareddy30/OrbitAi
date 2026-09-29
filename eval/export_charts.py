"""Reads eval/results.json and writes PNG charts for the slides (SPEC S10.3/S10.5).
Nothing is computed here - every number comes straight from results.json.

Usage: python -m eval.export_charts [--in eval/results.json] [--out eval/charts]
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from generator import REPO_ROOT

BASELINE_COLOR = "#94a3b8"   # slate - "no memory"
TRUSTLENS_COLOR = "#2563eb"  # blue - "with Hindsight memory"
ACCENT_COLOR = "#dc2626"     # red - conflict / regret


def _label_note(results: dict) -> str:
    store = results["meta"].get("memory_store", "?")
    return f"Simulated replay evaluation - {results['meta']['n_held_out']} held-out incidents - memory: {store}"


def chart_cumulative_p_success(results: dict, out: Path):
    agg = results["aggregates"]["cumulative_p_success"]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(agg["baseline"], color=BASELINE_COLOR, label="Baseline (no memory)", linewidth=2)
    ax.plot(agg["trustlens"], color=TRUSTLENS_COLOR, label="OrbitAI (Hindsight memory)", linewidth=2)
    ax.set_xlabel("Held-out incident # (time order)")
    ax.set_ylabel("Cumulative mean p(success)")
    ax.set_title("Cumulative recommendation quality on held-out incidents")
    ax.legend()
    ax.set_ylim(0, 1)
    fig.text(0.01, 0.01, _label_note(results), fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out / "cumulative_p_success.png", dpi=150)
    plt.close(fig)


def chart_best_fix_and_regret(results: dict, out: Path):
    bf = results["aggregates"]["best_fix_rate"]
    rg = results["aggregates"]["mean_regret"]
    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    for ax, data, title, ylabel in [
        (axes[0], bf, "Best-fix rate", "Fraction choosing the best fix"),
        (axes[1], rg, "Mean regret", "best p(success) - chosen p(success)"),
    ]:
        bars = ax.bar(["Baseline", "OrbitAI"], [data["baseline"], data["trustlens"]],
                      color=[BASELINE_COLOR, TRUSTLENS_COLOR])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.margins(y=0.15)  # headroom so a bar-top label never touches the title
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{b.get_height():.2f}",
                   ha="center", va="bottom", fontsize=9)
    fig.text(0.01, 0.01, _label_note(results), fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out / "best_fix_and_regret.png", dpi=150)
    plt.close(fig)


def chart_lookalike_subset(results: dict, out: Path):
    la = results["aggregates"].get("lookalike_subset", {})
    if not la or la.get("n", 0) == 0:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(["Baseline", "OrbitAI"],
                  [la["baseline_best_fix_rate"], la["trustlens_best_fix_rate"]],
                  color=[BASELINE_COLOR, TRUSTLENS_COLOR])
    ax.set_title(f"Look-alike trap subset (n={la['n']})\nOrbitAI flags conflict "
                f"{la['trustlens_conflict_rate']:.0%} of the time")
    ax.set_ylabel("Best-fix rate")
    ax.set_ylim(0, 1.12)  # headroom so a 1.00 label never touches the title
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{b.get_height():.2f}",
               ha="center", va="bottom", fontsize=9)
    fig.text(0.01, 0.01, _label_note(results), fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out / "lookalike_subset.png", dpi=150)
    plt.close(fig)


def chart_learning_curve(results: dict, out: Path):
    curve = results["aggregates"].get("learning_curve", [])
    if not curve:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot([c["n_train"] for c in curve], [c["mean_p_success"] for c in curve],
           marker="o", color=TRUSTLENS_COLOR, linewidth=2)
    ax.set_xlabel("Training incidents available")
    ax.set_ylabel("Mean p(success) of top recommendation")
    ax.set_title("Learning curve: does more memory help?")
    ax.set_ylim(0, 1)
    fig.text(0.01, 0.01, _label_note(results), fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out / "learning_curve.png", dpi=150)
    plt.close(fig)


def chart_calibration(results: dict, out: Path):
    cal = results["aggregates"].get("calibration", [])
    if not cal:
        return
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", linewidth=1, label="Perfect calibration")
    ax.plot([c["mean_predicted"] for c in cal], [c["actual_rate"] for c in cal],
           marker="o", color=TRUSTLENS_COLOR, label="OrbitAI trust score T")
    ax.set_xlabel("Mean predicted trust (T)")
    ax.set_ylabel("Actual verified-resolved rate")
    brier = results["aggregates"].get("brier")
    auc = results["aggregates"].get("auc")
    ax.set_title(f"Trust score calibration (Brier={brier}, AUC={auc})")
    ax.legend()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.text(0.01, 0.01, _label_note(results), fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out / "calibration.png", dpi=150)
    plt.close(fig)


def export_all(results: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    chart_cumulative_p_success(results, out_dir)
    chart_best_fix_and_regret(results, out_dir)
    chart_lookalike_subset(results, out_dir)
    chart_learning_curve(results, out_dir)
    chart_calibration(results, out_dir)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", default=str(REPO_ROOT / "eval" / "results.json"))
    ap.add_argument("--out", dest="out_dir", default=str(REPO_ROOT / "eval" / "charts"))
    args = ap.parse_args()
    results = json.loads(Path(args.in_path).read_text(encoding="utf-8"))
    export_all(results, Path(args.out_dir))
    print(f"Wrote charts to {args.out_dir}")


if __name__ == "__main__":
    main()
