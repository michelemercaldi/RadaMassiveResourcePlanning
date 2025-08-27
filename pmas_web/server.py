
import sys
import os
import traceback, threading, uuid
from datetime import datetime, time
from typing import Dict

# Add parent directory to path to allow imports of pmas modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request, Response, Response, BackgroundTasks
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse

from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import anyio, asyncio, uuid
import pandas as pd
import plotly.express as px

from pmas_configuration import PmasConfiguration
from pmas_sql import PmasSql
from pmas_strategy import PmasStrategy
from pmas_util import PmasLoggerSingleton, PmasLogBroker, job_id_var


app = FastAPI()


# Allow frontend on port 3000
origins = [
    "http://localhost:3000",
    # Add more allowed origins here (like production URL)
]
#origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.on_event("startup")
async def startup_event():
    """Code to run on application startup."""
    try:
        conf = PmasConfiguration()
        app.state.log_file_path = os.path.join(conf.base_dir, conf.log_file_path)
        app.state.schedule_export_file_path = os.path.join(conf.base_dir, conf.schedule_export_file_path)
        app.state.status_file_path = os.path.join(conf.base_dir, conf.status_file_path)

        # Initialize and store logger, sql client, and config in app.state
        app.state.glog = PmasLoggerSingleton.get_logger(conf)
        app.state.log_broker = PmasLogBroker(maxsize=2000)
        app.state.log_broker.bind_loop(asyncio.get_running_loop())
        app.state.sql = PmasSql(conf)
        app.state.conf = conf
        app.state.simulations = {}
        
        app.state.sql.start()
        app.state.glog.info("Application startup complete. Logger and DB connection ready.")
    except Exception as e:
        print("!!! FAILED TO INITIALIZE APPLICATION ON STARTUP !!!")
        print(f"Error: {e}")
        traceback.print_exc()
        # Set state to None on failure to prevent further errors
        app.state.glog = None
        app.state.sql = None
        app.state.conf = None
        app.state.log_broker = None

@app.on_event("shutdown")
async def shutdown_event():
    """Code to run on application shutdown."""
    if getattr(app.state, 'sql', None):
        app.state.sql.end()
        if getattr(app.state, 'glog', None):
            app.state.glog.info("Application shutdown complete. DB connection closed.")


# Add a safe-join helper (prevents .. path tricks)
def _safe_join(base_dir: str, *parts: str) -> str:
    base = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(base, *parts))
    if os.path.commonpath([base, path]) != base:
        raise HTTPException(status_code=400, detail="Invalid path.")
    return path


@app.get("/api/logs")
async def get_logs(request: Request):
    log_file_path = app.state.log_file_path
    
    # Support range requests for tailing
    range_header = request.headers.get('Range')
    if range_header:
        try:
            # Parse range header: "bytes=0-1024"
            unit, range_spec = range_header.split('=')
            start, end = range_spec.split('-')
            start = int(start)
            end = int(end) if end else None
            
            with open(log_file_path, 'r', encoding='utf-8') as f:
                f.seek(start)
                content = f.read(end - start if end else -1)
                
            filesize = os.path.getsize(log_file_path)
            headers = {
                'Content-Range': f'bytes {start}-{start + len(content) - 1}/{filesize}',
                'Accept-Ranges': 'bytes'
            }
            return Response(content, status_code=206, headers=headers)
            
        except Exception as e:
            app.state.glog.error(f"Range request error: {e}")
    
    # Full file request
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r', encoding='utf-8') as f:
            return PlainTextResponse(f.read())
    return PlainTextResponse("")

@app.get("/")
def read_root():
    """Serves the main index.html file."""
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))

class Shift(BaseModel):
    start: time
    duration: float

class SimulationInput(BaseModel):
    id_progetto: int
    shifts: Dict[int, Shift]
    casse_production_dates: Dict[str, datetime]
    multiplier_ebom_to_dtr: int
    family_skill: str
    hourly_cost_mbom: int
    hourly_cost_workinstruction: int
    hourly_cost_routing: int
    offset_mbom: int
    offset_workinstruction: int
    offset_routing: int

@app.get("/api/casse/{id_progetto}")
def get_casse(id_progetto: int, request: Request):
    """Gets the list of 'casse' for a given project ID."""
    glog = request.app.state.glog
    sql = request.app.state.sql
    if not glog or not sql:
        raise HTTPException(status_code=503, detail="Application is not initialized correctly. Check server logs.")
    
    conf = request.app.state.conf
    glog.info(f"Received request for casse with id_progetto: {id_progetto}")
    try:
        conf.ID_PROGETTO = id_progetto
        casse = sql.getCasse(id_progetto)
        glog.info(f"Casse for progetto {conf.ID_PROGETTO}: {casse}")
        return {"casse": casse}
    except Exception as e:
        glog.error(f"Error in get_casse: {e}")
        glog.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/get_default_costs")
def get_default_costs(request: Request):
    """Retrieves default hourly costs from the database."""
    glog = request.app.state.glog
    sql = request.app.state.sql
    if not glog or not sql:
        raise HTTPException(status_code=503, detail="Application is not initialized correctly. Check server logs.")
    
    try:
        costs = sql.getPhasestOffsetAndCost()
        glog.info(f"Retrieved default costs: {costs}")
        return costs
    except Exception as e:
        glog.error(f"Error retrieving default costs: {e}")
        glog.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/review_inputs")
def review_inputs(data: SimulationInput):
    """Takes the simulation input data and returns it for user review."""
    return data.dict()

@app.get("/api/simulation_status/{task_id}")
def get_simulation_status(task_id: str, request: Request):
    """Gets the status of a simulation task."""
    glog = request.app.state.glog
    if not glog:
        raise HTTPException(status_code=503, detail="Application is not initialized correctly.")
    
    simulation_state = request.app.state.simulations.get(task_id)
    if not simulation_state:
        raise HTTPException(status_code=404, detail="Simulation task not found.")
    
    # "trace debug" :  glog.info(f"Polling for task {task_id}, status is {simulation_state['status']}")
    return simulation_state

def transform_web_input_to_simulator_format(web_input):
    transformed = {
        'id_progetto': web_input['id_progetto'],
        'shift_config': {},
        'casse_production_dates': {},
        'multiplier_ebom_to_dtr': web_input['multiplier_ebom_to_dtr'],
        'family_skill': web_input['family_skill'],
        'hourly_cost_mbom': web_input['hourly_cost_mbom'],
        'hourly_cost_workinstruction': web_input['hourly_cost_workinstruction'],
        'hourly_cost_routing': web_input['hourly_cost_routing'],
        'offset_mbom': web_input['offset_mbom'],
        'offset_workinstruction': web_input['offset_workinstruction'],
        'offset_routing': web_input['offset_routing']
    }
    
    # Convert shifts
    for shift_num, shift_data in web_input['shifts'].items():
        start = shift_data['start']
        if isinstance(start, str):
            start = datetime.strptime(start, '%H:%M')  # it should be already in "%H:%M" format
        start_str = start.strftime('%H:%M')
        transformed['shift_config'][shift_num] = {
            'start': start_str,
            'duration': shift_data['duration']
        }
    # Convert casse production dates
    for cassa, date_obj in web_input['casse_production_dates'].items():
        if isinstance(date_obj, str):
            date_obj = datetime.strptime(date_obj, '%Y-%m-%dT%H:%M:%S.%fZ')  # expected iso format
        transformed['casse_production_dates'][cassa] = date_obj.strftime('%Y-%m-%d')
    
    return transformed




"""
Concurrency: the code handles multiple simultaneous requests by spawning a new thread for each simulation.
Thread Safety: we use put_threadsafe and done_threadsafe to avoid race conditions.
Scalability: Works well for moderate load, but may need a task queue for high scalability.

Each call to run_simulation_logic_threaded spawns a new thread for _simulation_blocking_worker.
Multiple requests result in multiple threads running concurrently.
The number of concurrent threads is limited by the thread pool (managed by anyio/ASGI server).

    summary table:
"Component",                      "Runs In",        "Concurrency Model",   "Blocking?",    "Notes"
"run_simulation (endpoint)",      "Event loop",     "Async",                 "No",         "Schedules background task."
"run_simulation_logic_threaded",  "Event loop",     "Async",                 "No",         "Offloads work to thread."
"_simulation_blocking_worker",    "OS Thread",      "Thread pool",           "Yes",        "CPU-bound/blocking work happens here."
"app.state.simulations",          "Event loop",     "Async",                 "No",         "Shared state, updated safely."
"""
@app.post("/api/run_simulation")
async def run_simulation(payload: dict, background: BackgroundTasks, request: Request):
    glog = request.app.state.glog
    if not glog:
        raise HTTPException(status_code=503, detail="Application is not initialized correctly. Check server logs.")
    #glog.info(f"Received simulation request with payload: {payload}")
    user_input = transform_web_input_to_simulator_format(payload)
    glog.info(f"run_simulation received user input: {user_input}")
    
    job_id = uuid.uuid4().hex
    # Set context so any logs *before* scheduling also include the job_id
    job_id_var.set(job_id)
    
    request.app.state.simulations[job_id] = {"status": "running", "result": None}
    glog.info(f"run_simulation queuing simulation task {job_id} with input: {user_input}")
    
    await app.state.log_broker.ensure(job_id)
    #background.add_task(run_simulation_logic_test_just_write_logs, job_id, user_input)
    background.add_task(run_simulation_logic_threaded, job_id, user_input)
    return {"job_id": job_id}


def _simulation_blocking_worker(job_id: str, app_state, user_input_data: dict):
    """
    Runs in a real OS thread (not the event loop). NO awaits here.
    Performs CPU-bound/blocking work (e.g., strategy.exec_simulation_logic).
    Use log_broker.put_threadsafe(...) / done_threadsafe(...) to stream logs.
    """
    job_id_var.set(job_id)
    log_broker: PmasLogBroker = app_state.log_broker
    try:
        log_broker.put_threadsafe(job_id, "starting…")
        app_state.glog.info("job %s: starting…", job_id)

        # --- blocking / CPU-bound work below ---
        conf = PmasConfiguration()
        strategy = PmasStrategy(conf)
        app_state.glog.info("job %s: executing simulation", job_id)

        user_input_data['job_id'] = job_id
        strategy.exec_simulation_logic(user_input_data, log_broker)  # BLOCKING call
        result = {"result": "Simulation executed successfully", "output": "fake_simulation_result"}

        log_broker.put_threadsafe(job_id, "finished work")
        app_state.glog.info("job %s: finished work", job_id)

        # return outcome for the async wrapper to persist
        return ("completed", result)

    except Exception as e:
        msg = f"ERROR: {type(e).__name__}: {e}"
        log_broker.put_threadsafe(job_id, msg)
        app_state.glog.exception("job %s failed", job_id)
        app_state.glog.error(msg)
        app_state.glog.error(traceback.format_exc())
        app_state.simulations[job_id] = {"status": "failed", "result": {"detail": msg}}
        return ("failed", {"detail": str(e)})
    finally:
        # Always close the SSE stream
        log_broker.done_threadsafe(job_id)


async def run_simulation_logic_threaded(job_id: str, user_input_data: dict):
    """
    Async wrapper: offloads the blocking worker to a thread, then persists status.
    This function runs in the event loop (non-blocking).
    It immediately offloads the blocking work to a thread using anyio.to_thread.run_sync(...)
    """
    job_id_var.set(job_id)
    # anyio.to_thread.run_sync schedules _simulation_blocking_worker to run in a separate OS thread
    status, result = await anyio.to_thread.run_sync(
        _simulation_blocking_worker, job_id, app.state, user_input_data
    )
    # Persist status/result back on the event loop thread
    app.state.simulations[job_id] = {"status": status, "result": result}


# test simulation task,   just write some logs to the client
async def run_simulation_logic_test_just_write_logs(job_id: str, payload: dict):
    try:
        # emit logs while working
        log_broker : PmasLogBroker = app.state.log_broker
        await log_broker.put(job_id, "starting…")
        for i in range(30):
            await log_broker.put(job_id, f"[{i}] working with {payload.get('id_progetto')}")
            #app.state.glog.info(f"[{job_id}] working with {payload.get('id_progetto')}")
            await asyncio.sleep(0.5)
        await log_broker.put(job_id, "finished work")
    except Exception as e:
        try:
            await log_broker.put(job_id, f"ERROR: {type(e).__name__}: {e}")
        finally:
            log_broker.exception("job %s failed", job_id)
    finally:
        await log_broker.done(job_id)  # send the "__DONE__" sentinel



@app.get("/api/run_simulation/{job_id}/logs")
async def stream_logs(job_id: str):
    q = app.state.log_broker.get(job_id)
    if not q:
        async def _empty():
            yield {"event":"error","data":"unknown job"}
        return EventSourceResponse(_empty(), ping=15000)

    async def event_gen():
        try:
            while True:
                line = await q.get()
                if line == "__DONE__":
                    yield {"event":"done","data":"ok"}
                    break
                yield {"event":"log","data": line}
        finally:
            # delete only when you're SURE job is done
            app.state.log_broker.pop(job_id)
    return EventSourceResponse(event_gen(), ping=15000)


@app.get("/api/download/log")
def download_log(request: Request):
    log_path = request.app.state.conf.log_file_path
    if not log_path or not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found.")
    filename = os.path.basename(log_path)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return FileResponse(
        log_path,
        media_type="text/plain",
        filename=filename,
        headers=headers
    )


@app.get("/api/download/{job_id}/simresult")
def download_simresult(job_id: str, request: Request):
    base, ext = os.path.splitext(request.app.state.conf.schedule_export_file_path)
    simresult_path = f"{base}.{job_id}{ext}"
    if not simresult_path or not os.path.exists(simresult_path):
        raise HTTPException(status_code=404, detail="Log file not found.")
    filename = os.path.basename(simresult_path)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return FileResponse(
        simresult_path,
        media_type="text/plain",
        filename=filename,
        headers=headers
    )



# server gantt visualization
def generate_gantt_chart(csv_path):
    df = pd.read_csv(csv_path, delimiter=';')
    df["phase"] = df["task"].apply(lambda x: x.split('.')[-1] if '.' in x else 'mbom')
    df["ebom"] = df["task"].apply(lambda x: x.split('.')[0])
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df.sort_values(by=["worker", "phase", "start"], inplace=True)
    phase_colors = {
        "mbom": "blue",
        "workinstruction": "orange",
        "routing": "green"
    }
    df['color'] = df['phase'].map(phase_colors)
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
    return fig.to_html(include_plotlyjs='cdn')


@app.get("/api/{job_id}/gantt", response_class=HTMLResponse)
async def get_gantt_chart(job_id: str, request: Request):
    base, ext = os.path.splitext(request.app.state.conf.schedule_export_file_path)
    csv_path = f"{base}.{job_id}{ext}"
    if not os.path.exists(csv_path):
        return {"error": "CSV file not found"}, 404
    gantt_html = generate_gantt_chart(csv_path)
    return HTMLResponse(content=gantt_html, status_code=200)



# To run the server with auto-reload, use the following command from the project root:
# poetry run uvicorn pmas_web.server:app --host 0.0.0.0 --port 8000 --reload
