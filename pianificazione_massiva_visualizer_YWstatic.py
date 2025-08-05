import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from datetime import datetime
from matplotlib.patches import Patch

def plot_gantt_grouped(csv_path):
    df = pd.read_csv(csv_path, delimiter=';')

    # Extract phase from task and base EBOM name
    df["phase"] = df["task"].apply(lambda x: x.split('.')[-1] if '.' in x else 'mbom')
    df["ebom"] = df["task"].apply(lambda x: x.split('.')[0])
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])

    # Sort for plotting order
    df.sort_values(by=["worker", "phase", "start"], inplace=True)

    # Setup canvas
    fig, ax = plt.subplots(figsize=(16, 10))

    workers = df["worker"].unique()
    cmap = plt.cm.get_cmap("tab20", len(workers))

    yticks = list(range(len(workers)))
    ylabels = workers
    worker_indices = {worker: i for i, worker in enumerate(workers)}

    # Phase colors (for legend)
    phase_colors = {
        "mbom": "grey",
        "workinstruction": "blue",
        "routing": "green"
    }

    for _, row in df.iterrows():
        worker = row["worker"]
        phase = row["phase"]
        ebom = row["ebom"]
        idx = worker_indices[worker]
        start = row["start"]
        end = row["end"]
        duration = end - start

        ax.barh(
            y=idx,
            left=start,
            width=duration,
            height=0.4,
            color=phase_colors.get(phase, "lightgrey"),
            edgecolor="black"
        )

        ax.text(
            start + duration / 2,
            idx,
            ebom,
            ha="center",
            va="center",
            fontsize=7,
            color="white"
        )

    # Phase color legend
    phase_legend = [Patch(facecolor=color, edgecolor='black', label=phase) for phase, color in phase_colors.items()]
    ax.legend(handles=phase_legend, loc='upper right', title='Phases')

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)

    # Horizontal lines to separate each worker
    for y in yticks:
        ax.axhline(y=y, color='lightgray', linestyle='--', linewidth=0.5, zorder=0)

    ax.set_xlabel("Date")
    ax.set_title("📋 Worker Gantt Chart (Grouped by Worker, Phases Colored)")
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.grid(True, axis="x", linestyle="--", alpha=0.5)

    # Vertical lines at noon of each day
    min_day = df["start"].min().normalize()
    max_day = df["end"].max().normalize()
    noon_ticks = pd.date_range(start=min_day, end=max_day, freq='D') + pd.Timedelta(hours=12)

    for tick in noon_ticks:
        ax.axvline(tick, color='lightgrey', linestyle=':', linewidth=0.5, zorder=0)

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    plot_gantt_grouped("logs/massive_planning_schedule_export.csv")
