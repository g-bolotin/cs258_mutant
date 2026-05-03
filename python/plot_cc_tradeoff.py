#!/usr/bin/env python3
import argparse
import csv
import glob
import json
import os
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse


DISPLAY_NAME = {
    "cubic": "Cubic",
    "bbr": "BBR",
    "hybla": "Hybla",
    "westwood": "Westwood",
    "veno": "Veno",
    "vegas": "Vegas",
    "yeah": "YeAH",
    "bic": "Bic",
    "htcp": "HTCP",
    "illinois": "Illinois",
    "mutant": "Mutant",
}

MARKERS = {
    "cubic": "o",
    "bbr": "^",
    "hybla": "D",
    "westwood": "o",
    "veno": "s",
    "vegas": "s",
    "yeah": "^",
    "bic": "D",
    "htcp": "v",
    "illinois": "d",
    "mutant": "*",
}

COLORS = {
    "cubic": "#2f45e0",
    "bbr": "#ff3a3a",
    "hybla": "#39c1cb",
    "westwood": "#b4b93b",
    "veno": "#4fc5d4",
    "vegas": "#2c9e2e",
    "yeah": "#8c8c8c",
    "bic": "#3f7db6",
    "htcp": "#8f78b8",
    "illinois": "#c1bc35",
    "mutant": "#f0b12f",
}


@dataclass
class ProtocolStats:
    name: str
    path: str
    samples: int
    avg_owd_ms: float
    avg_tp_mbps: float
    std_owd_ms: float
    std_tp_mbps: float


def infer_protocol(path):
    base = os.path.basename(path)
    if base == "mutant_trace.csv":
        return "mutant"
    if base.startswith("fixed_") and base.endswith("_trace.csv"):
        return base[len("fixed_") : -len("_trace.csv")]
    return None


def read_trace_stats(path, baseline_oneway_ms, subtract_baseline):
    owd_vals = []
    tp_vals = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rtt_raw = row.get("rtt_ms")
            tp_raw = row.get("throughput_mbps")
            if rtt_raw in (None, "") or tp_raw in (None, ""):
                continue
            try:
                rtt = float(rtt_raw)
                tp = float(tp_raw)
            except ValueError:
                continue
            owd = 0.5 * rtt
            if subtract_baseline:
                owd = max(0.0, owd - baseline_oneway_ms)
            owd_vals.append(owd)
            tp_vals.append(tp)

    if not owd_vals:
        return None

    return {
        "samples": len(owd_vals),
        "avg_owd_ms": float(np.mean(owd_vals)),
        "avg_tp_mbps": float(np.mean(tp_vals)),
        "std_owd_ms": float(np.std(owd_vals)),
        "std_tp_mbps": float(np.std(tp_vals)),
    }


def pick_file(candidates, pick_mode):
    if not candidates:
        return None
    if pick_mode == "latest":
        return max(candidates, key=lambda x: os.path.getmtime(x))
    if pick_mode == "max_rows":
        def row_count(p):
            with open(p, "r", encoding="utf-8") as f:
                return max(0, sum(1 for _ in f) - 1)
        return max(candidates, key=row_count)
    return candidates[0]


def collect_stats(root_dir, trace_name, protocols, pick_mode, baseline_oneway_ms, subtract_baseline):
    pattern = os.path.join(root_dir, "cc_compare_sweep_*", trace_name, "*_trace.csv")
    all_files = glob.glob(pattern)

    by_protocol = {}
    for p in all_files:
        proto = infer_protocol(p)
        if not proto:
            continue
        if protocols and proto not in protocols:
            continue
        by_protocol.setdefault(proto, []).append(p)

    stats = []
    for proto, files in by_protocol.items():
        selected = pick_file(files, pick_mode)
        if not selected:
            continue
        s = read_trace_stats(selected, baseline_oneway_ms, subtract_baseline)
        if not s:
            continue
        stats.append(
            ProtocolStats(
                name=proto,
                path=selected,
                samples=s["samples"],
                avg_owd_ms=s["avg_owd_ms"],
                avg_tp_mbps=s["avg_tp_mbps"],
                std_owd_ms=s["std_owd_ms"],
                std_tp_mbps=s["std_tp_mbps"],
            )
        )
    return sorted(stats, key=lambda x: (x.name != "mutant", x.name))


def plot_stats(stats, out_png, title, invert_x, ellipse_scale):
    if not stats:
        raise SystemExit("No trace stats found for plotting.")

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(8.2, 6.6))

    for s in stats:
        color = COLORS.get(s.name, "#333333")
        marker = MARKERS.get(s.name, "o")
        label = DISPLAY_NAME.get(s.name, s.name)

        if s.std_owd_ms > 0 or s.std_tp_mbps > 0:
            e = Ellipse(
                (s.avg_owd_ms, s.avg_tp_mbps),
                width=max(0.2, ellipse_scale * s.std_owd_ms),
                height=max(0.05, ellipse_scale * s.std_tp_mbps),
                facecolor=color,
                edgecolor="none",
                alpha=0.25,
                zorder=1,
            )
            ax.add_patch(e)

        size = 220 if s.name == "mutant" else 110
        edge = "black" if s.name == "mutant" else "none"
        ax.scatter(
            s.avg_owd_ms,
            s.avg_tp_mbps,
            marker=marker,
            s=size,
            color=color,
            edgecolors=edge,
            linewidths=0.9 if edge != "none" else 0,
            zorder=3,
            label=label,
        )

    ax.set_xlabel("Avg. One-way Delay (ms)", fontsize=18)
    ax.set_ylabel("Avg. Throughput (Mbps)", fontsize=18)
    ax.tick_params(axis="both", labelsize=14)
    ax.set_title(title, fontsize=20, pad=14)
    if invert_x:
        ax.invert_xaxis()

    handles, labels = ax.get_legend_handles_labels()
    unique = {}
    for h, l in zip(handles, labels):
        unique[l] = h
    ax.legend(
        unique.values(),
        unique.keys(),
        loc="lower right",
        fontsize=11,
        ncol=3,
        frameon=True,
        fancybox=True,
        framealpha=0.85,
    )

    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    print(f"Saved plot: {out_png}")

    print("\nSelected protocol traces:")
    for s in stats:
        print(
            f"- {s.name:9s} owd={s.avg_owd_ms:7.3f}ms tp={s.avg_tp_mbps:7.3f}Mbps "
            f"samples={s.samples:6d} file={s.path}"
        )


def write_intermediate_json(
    stats,
    out_json,
    args,
):
    payload = {
        "config": {
            "root_dir": os.path.abspath(args.root_dir),
            "trace_name": args.trace_name,
            "protocols_filter": args.protocols,
            "pick_mode": args.pick_mode,
            "baseline_oneway_ms": args.baseline_oneway_ms,
            "subtract_baseline": args.subtract_baseline,
            "ellipse_scale": args.ellipse_scale,
            "invert_x": args.invert_x,
            "title": args.title,
            "out_png": os.path.abspath(args.out_png),
        },
        "points": [
            {
                "protocol": s.name,
                "display_name": DISPLAY_NAME.get(s.name, s.name),
                "source_trace_csv": s.path,
                "samples": s.samples,
                "avg_oneway_ms": s.avg_owd_ms,
                "avg_throughput_mbps": s.avg_tp_mbps,
                "std_oneway_ms": s.std_owd_ms,
                "std_throughput_mbps": s.std_tp_mbps,
                "marker": MARKERS.get(s.name, "o"),
                "color": COLORS.get(s.name, "#333333"),
            }
            for s in stats
        ],
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved graph data JSON: {out_json}")


def parse_protocols(raw):
    if not raw:
        return []
    out = []
    for token in raw.split(","):
        p = token.strip().lower()
        if p:
            out.append(p)
    return out


def build_parser():
    p = argparse.ArgumentParser(description="Plot throughput vs one-way delay from Mutant trace CSV files.")
    p.add_argument("--root-dir", default="../trcgen", help="Directory containing cc_compare_sweep_* outputs.")
    p.add_argument("--trace-name", default="ATT_LTE_driving", help="Trace subdirectory name to plot.")
    p.add_argument(
        "--protocols",
        default="",
        help="Comma-separated protocol filter (e.g. cubic,bbr,mutant). Empty means all discovered.",
    )
    p.add_argument(
        "--pick-mode",
        choices=["latest", "max_rows"],
        default="max_rows",
        help="How to choose one file per protocol when multiple exist.",
    )
    p.add_argument(
        "--baseline-oneway-ms",
        type=float,
        default=0.0,
        help="Baseline one-way delay used if subtracting baseline.",
    )
    p.add_argument(
        "--subtract-baseline",
        action="store_true",
        help="Plot excess one-way delay: max(0, RTT/2 - baseline).",
    )
    p.add_argument("--ellipse-scale", type=float, default=1.8, help="Scale factor for uncertainty ellipse size.")
    p.add_argument("--invert-x", action="store_true", default=True, help="Invert x-axis (higher delay to the left).")
    p.add_argument("--title", default="Cellular Link (ATT LTE)", help="Plot title.")
    p.add_argument("--out-png", default="../trcgen/att_tradeoff.png", help="Output image file path.")
    p.add_argument(
        "--out-json",
        default="",
        help="Optional output JSON path for intermediate graph data. Default: <out-png>.json",
    )
    return p


def main():
    args = build_parser().parse_args()
    root_dir = os.path.abspath(args.root_dir)
    out_png = os.path.abspath(args.out_png)
    out_json = os.path.abspath(args.out_json) if args.out_json else (out_png + ".json")
    protocols = parse_protocols(args.protocols)

    stats = collect_stats(
        root_dir=root_dir,
        trace_name=args.trace_name,
        protocols=protocols,
        pick_mode=args.pick_mode,
        baseline_oneway_ms=args.baseline_oneway_ms,
        subtract_baseline=args.subtract_baseline,
    )
    plot_stats(
        stats=stats,
        out_png=out_png,
        title=args.title,
        invert_x=args.invert_x,
        ellipse_scale=args.ellipse_scale,
    )
    write_intermediate_json(stats=stats, out_json=out_json, args=args)


if __name__ == "__main__":
    main()
