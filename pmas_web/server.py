
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
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import asyncio, uuid

from pmas_configuration import PmasConfiguration
from pmas_sql import PmasSql
from pmas_strategy import PmasStrategy
from pmas_util import PmasLoggerSingleton, PmasLogBroker



app = FastAPI()

# _mme  uses QUEUES directly;
# _mme     QUEUES: dict[str, asyncio.Queue[str]] = {}

# Allow frontend on port 3000
origins = [
    "http://localhost:3000",
    # Add more allowed origins here (like production URL)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Code to run on application startup."""
    try:
        conf = PmasConfiguration()
        log_dir = os.path.join(os.path.dirname(__file__), '../logs')
        os.makedirs(log_dir, exist_ok=True)
        conf.log_file_path = os.path.join(log_dir, 'pmas_web.log')

        # Initialize and store logger, sql client, and config in app.state
        app.state.glog = PmasLoggerSingleton.get_logger(conf)
        app.state.log_broker = PmasLogBroker(maxsize=2000)
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

@app.get("/api/logs")
async def get_logs(request: Request):
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs', 'pmas_web.log')
    
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
    
    # _mme glog.info(f"Polling for task {task_id}, status is {simulation_state['status']}")
    return simulation_state

def run_simulation_logic_threaded(task_id: str, app_state, user_input_data: dict):
    """The actual simulation logic that runs in a background thread."""
    try:
        conf = PmasConfiguration() 
        strategy = PmasStrategy(conf) 
        
        app_state.glog.info(f"Starting background simulation for task: {task_id}")
        strategy.exec_simulation_logic(user_input_data)
        
        result = {"result": "Simulation executed successfully", "output": "fake_simulation_result"}
        app_state.simulations[task_id] = {"status": "completed", "result": result}
        app_state.glog.info(f"Simulation task {task_id} completed successfully.")

    except Exception as e:
        error_message = f"Simulation task {task_id} failed: {e}"
        app_state.glog.error(error_message)
        app_state.glog.error(traceback.format_exc())
        app_state.simulations[task_id] = {"status": "failed", "result": {"detail": error_message}}


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
        transformed['shift_config'][shift_num] = {
            'start': shift_data['start'].strftime('%H:%M'),
            'duration': shift_data['duration']
        }
    
    # Convert casse production dates
    for cassa, date_obj in web_input['casse_production_dates'].items():
        transformed['casse_production_dates'][cassa] = date_obj.strftime('%Y-%m-%d')
    
    return transformed



#  _mme ori with actual simulation run:
#@app.post("/api/run_simulation")
#def run_simulation(data: SimulationInput, request: Request):
#    """Runs the simulation with the provided input data."""
#    glog = request.app.state.glog
#    if not glog:
#        raise HTTPException(status_code=503, detail="Application is not initialized correctly. Check server logs.")
#
#    task_id = str(uuid.uuid4())
#    request.app.state.simulations[task_id] = {"status": "running", "result": None}
#    
#    web_user_input = data.dict()
#    user_input = transform_web_input_to_simulator_format(web_user_input)
#    
#    glog.info(f"Queuing simulation task {task_id} with input: {user_input}")
#
#    thread = threading.Thread(target=run_simulation_logic_threaded, args=(task_id, request.app.state, user_input))
#    thread.start()
#
#    return Response(status_code=202, content=f'{{"message": "Simulation started", "task_id": "{task_id}"}}', media_type="application/json")


# _mme  run_simulation test that uses QUEUES directly,
#    without the instance of the custom log broker
# with_QUEUES : @app.post("/api/run_simulation")
# with_QUEUES : async def run_simulation(payload: dict, background: BackgroundTasks):
# with_QUEUES :     job_id = uuid.uuid4().hex
# with_QUEUES :     QUEUES[job_id] = asyncio.Queue(maxsize=1000)
# with_QUEUES :     await app.state.log_broker.ensure(job_id)
# with_QUEUES :     background.add_task(simulation_task, job_id, payload)
# with_QUEUES :     return {"job_id": job_id}


@app.post("/api/run_simulation")
async def run_simulation(payload: dict, background: BackgroundTasks):
    job_id = uuid.uuid4().hex
    await app.state.log_broker.ensure(job_id)
    background.add_task(simulation_task, job_id, app.state.log_broker, payload)
    return {"job_id": job_id}


# _mme  simulation_task that uses QUEUES directly,
# with_QUEUES : async def simulation_task(job_id: str, payload: dict):
# with_QUEUES :     q = QUEUES[job_id]
# with_QUEUES :     try:
# with_QUEUES :         # emit logs while working
# with_QUEUES :         for i in range(100):
# with_QUEUES :             await q.put(f"[{i}] working with {payload.get('id_progetto')}")
# with_QUEUES :             await asyncio.sleep(0.5)
# with_QUEUES :         await q.put("__DONE__")
# with_QUEUES :     finally:
# with_QUEUES :         await asyncio.sleep(0)  # let last message flush


# test simulation_task,   just write some logs to for the client
async def simulation_task(job_id: str, broker: PmasLogBroker, payload: dict):
    try:
        # emit logs while working
        await broker.put(job_id, "starting…")
        for i in range(30):
            await broker.put(job_id, f"[{i}] working with {payload.get('id_progetto')}")
            app.state.glog.info(f"[{job_id}] working with {payload.get('id_progetto')}")
            await asyncio.sleep(0.5)
    finally:
        await broker.done(job_id)  # send the "__DONE__" sentinel


# _mme  stream_logs that uses QUEUES directly,
#      without the instance of the custom log broker
# with_QUEUES : @app.get("/api/run_simulation/{job_id}/logs")
# with_QUEUES : async def stream_logs(job_id: str):
# with_QUEUES :     q = QUEUES.get(job_id)
# with_QUEUES :     if not q:
# with_QUEUES :         async def _empty():
# with_QUEUES :             yield {"event":"error","data":"unknown job"}
# with_QUEUES :         return EventSourceResponse(_empty(), ping=15000)
# with_QUEUES : 
# with_QUEUES :     async def event_gen():
# with_QUEUES :         try:
# with_QUEUES :             while True:
# with_QUEUES :                 line = await q.get()
# with_QUEUES :                 if line == "__DONE__":
# with_QUEUES :                     yield {"event":"done", "data":"ok"}
# with_QUEUES :                     break
# with_QUEUES :                 yield {"event":"log", "data": line}
# with_QUEUES :         finally:
# with_QUEUES :             QUEUES.pop(job_id, None)
# with_QUEUES :     return EventSourceResponse(event_gen(), ping=15000)  # keep-alive pings


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


#Now from any module you can write logs:
#
## some_module.py
#async def step_x(job_id: str, broker: LogBroker):
#    await broker.put(job_id, "step X started")
#    # ...
#
#
#If you don’t have easy access to app.state in deep modules, expose a tiny accessor:
#
## appctx.py
#from typing import Optional
#from broker import LogBroker
#_broker: Optional[LogBroker] = None
#def set_broker(b: LogBroker):  # call this in lifespan
#    global _b; _b = b
#def get_broker() -> LogBroker:
#    assert _b is not None, "broker not initialized"
#    return _b
#
#Then anywhere: await get_broker().put(job_id, "msg").
#
# Tip: if you log from threads, use loop.call_soon_threadsafe(q.put_nowait, line); 
# or make your broker provide a put_threadsafe wrapper.








# To run the server with auto-reload, use the following command from the project root:
# poetry run uvicorn pmas_web.server:app --host 0.0.0.0 --port 8000 --reload
