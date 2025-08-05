import pandas as pd
import plotly.express as px
from datetime import datetime

def plot_gantt_grouped(csv_path):
    df = pd.read_csv(csv_path, delimiter=';')

    # Extract phase from task and base EBOM name
    df["phase"] = df["task"].apply(lambda x: x.split('.')[-1] if '.' in x else 'mbom')
    df["ebom"] = df["task"].apply(lambda x: x.split('.')[0])
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])

    # Sort for plotting order
    df.sort_values(by=["worker", "phase", "start"], inplace=True)

    # Create colors for different phases
    phase_colors = {
        "mbom": "blue",
        "workinstruction": "orange",
        "routing": "green"
    }
    df['color'] = df['phase'].map(phase_colors)

    # Create the Gantt chart using Plotly Express
    fig = px.timeline(
        df,
        x_start="start",
        x_end="end",
        y="worker",
        color="phase",
        hover_data=["ebom", "phase"],
        title="Resource Scheduling Gantt Chart"
    )

    fig.update_yaxes(categoryorder="total ascending")
    fig.show()

if __name__ == "__main__":
    plot_gantt_grouped("logs/massive_planning_schedule_export.csv")
