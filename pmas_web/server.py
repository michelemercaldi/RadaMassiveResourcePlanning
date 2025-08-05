
import sys
import os
import traceback, threading, uuid
from datetime import datetime, time
from typing import Dict

# Add parent directory to path to allow imports of pmas modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request, Response, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from pmas_configuration import PmasConfiguration
from pmas_sql import PmasSql
from pmas_strategy import PmasStrategy
from pmas_util import PmasLoggerSingleton



app = FastAPI()

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

@app.post("/api/run_simulation")
def run_simulation(data: SimulationInput, request: Request):
    """Runs the simulation with the provided input data."""
    glog = request.app.state.glog
    if not glog:
        raise HTTPException(status_code=503, detail="Application is not initialized correctly. Check server logs.")

    task_id = str(uuid.uuid4())
    request.app.state.simulations[task_id] = {"status": "running", "result": None}
    
    web_user_input = data.dict()
    user_input = transform_web_input_to_simulator_format(web_user_input)
    
    glog.info(f"Queuing simulation task {task_id} with input: {user_input}")

    thread = threading.Thread(target=run_simulation_logic_threaded, args=(task_id, request.app.state, user_input))
    thread.start()

    return Response(status_code=202, content=f'{{"message": "Simulation started", "task_id": "{task_id}"}}', media_type="application/json")


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


# To run the server with auto-reload, use the following command from the project root:
# poetry run uvicorn pmas_web.server:app --host 0.0.0.0 --port 8000 --reload
