import logging
from datetime import datetime, timedelta



class PmasConfiguration:

    # --------- CONSTANTS --------- #
    # run python with  -O  to remove logging,  see usage of  "if __debug__":
    log_setup_level = logging.DEBUG    # Capture all logs at DEBUG level and above
    log_console_level = logging.INFO
    log_file_level = logging.DEBUG
    log_file_path = 'logs\massive_planning.log'

    max_simulation_attempts = 6  # Maximum number of simulation attempts to find a working configuration    _mme review

    ## ora11
    #sql_connection_params = {
    #    "host": "200.1.1.19",
    #    "port": 1521,
    #    "service_name": "ora11",
    #    "username": "",
    #    "password": ""
    #}
    
    # ora19
    sql_connection_params = {
        "host": "200.1.1.29",
        "port": 1521,
        "service_name": "orcl",
        "username": "",
        "password": ""
    }

    TICK = timedelta(minutes=30)
    # --------- CONSTANTS end --------- #


    def __init__(self):
        try:
            # Load database credentials from 'secret' file
            with open("secret", "r") as f:
                lines = f.readlines()
                if len(lines) < 2:
                    raise ValueError("The 'secret' file must contain at least two lines (username and password).")
                username = lines[0].strip()
                password = lines[1].strip()
                self.sql_connection_params["username"] = username
                self.sql_connection_params["password"] = password
        except Exception as e:
            logging.error(f"Failed to load database credentials from 'secret': {e}")
            raise



    # --------- USER INPUT --------- #
    # default values:
    ID_PROGETTO = 71

    SHIFT_CONFIG = {
        1: {"start": "06:00", "duration": 7.5},
        2: {"start": "14:00", "duration": 7.5},
        #3: {"start": "22:00", "duration": 7.0},
    }
    
    target_worker_saturation = 0.9

    # data inizio produzione per ogni cassa
    #  list of casse from database
    casse_production_dates = {}
    # sample:
    #casse_production_dates = {
    #    '4A1': '2025-09-23',
    #    '4A2': '2025-10-23',
    #    '4A3': '2025-11-23',
    #    '4A4': '2025-12-23'
    #}

    multiplier_ebom_to_dtr = 3  # ---- this is the conversion factor from EBOM to DRT, default = 3
 
    # ---- hourly unit cost and offset for MBOM, WORK INSTRUCTION, ROUTING
    #  default values from database, but can be modified
    hourly_cost_mbom = 1                   # M-BOM cost
    hourly_cost_workinstruction = 40       # WORK INSTRUCTION cost
    hourly_cost_routing = 2                # ROUTING cost
    deadline_offset_mbom = 10              # M-BOM deadline offset in days
    deadline_offset_workinstruction = -20  # WORK INSTRUCTION deadline offset in days
    deadline_offset_routing = -5           # ROUTING deadline offset in days
    # --------- USER INPUT end --------- #



    # --------- FROM DATABASE --------- #
    NUM_EBOMS = 715
    #  ... get all eboms
    # --------- FROM DATABASE end --------- #



    # --------- DERIVED_VALUES --------- #
    START_DATE = None     # min engineering release date among all eboms
    END_DATE = None       # min production among all casse production dates
    ELAPSED_DAYS = None   # (END_DATE - START_DATE)
    # --------- DERIVED_VALUES end --------- #



    # --------- only for debug --------- #
    debug__execute_a_single_simulation = False
    debug__force_mbom_workers_on_single_simulation = 5
    debug__force_production_workers_on_single_simulation = 11
    # --------- only for debug - end --------- #


    def update_config_with_user_input(self, user_input):
        # Update project ID if provided
        if 'id_progetto' in user_input:
            self.ID_PROGETTO = user_input['id_progetto']
        
        # Update shift configuration if provided
        if 'shift_config' in user_input:
            self.SHIFT_CONFIG = {
                int(k): v for k, v in user_input['shift_config'].items()
            }
        
        # Update casse production dates if provided
        if 'casse_production_dates' in user_input:
            validated_dates = {}
            for k, v in user_input['casse_production_dates'].items():
                if v is None:
                    raise ValueError(f"Production date for '{k}' is None")
                if isinstance(v, str):
                    try:
                        # Validate and parse the date string
                        dt = datetime.strptime(v, '%Y-%m-%d')
                        validated_dates[k] = dt  # dt.strftime('%Y-%m-%d')
                    except ValueError:
                        raise ValueError(f"Invalid date format for '{k}': '{v}'. Expected 'yyyy-mm-dd'.")
                elif isinstance(v, datetime):
                    validated_dates[k] = v  # v.strftime('%Y-%m-%d')
                else:
                    raise ValueError(f"Invalid type for production date of '{k}': {type(v)}")
            self.casse_production_dates = validated_dates

        # Update multiplier if provided
        if 'multiplier_ebom_to_dtr' in user_input:
            self.multiplier_ebom_to_dtr = user_input['multiplier_ebom_to_dtr']

        # Update cost parameters if provided
        if 'hourly_cost_mbom' in user_input:
            self.hourly_cost_mbom = user_input['hourly_cost_mbom']
        if 'hourly_cost_workinstruction' in user_input:
            self.hourly_cost_workinstruction = user_input['hourly_cost_workinstruction']
        if 'hourly_cost_routing' in user_input:
            self.hourly_cost_routing = user_input['hourly_cost_routing']
        
        # Update deadline offsets if provided
        if 'offset_mbom' in user_input:
            self.deadline_offset_mbom = user_input['offset_mbom']
        if 'offset_workinstruction' in user_input:
            self.deadline_offset_workinstruction = user_input['offset_workinstruction']
        if 'offset_routing' in user_input:
            self.deadline_offset_routing = user_input['offset_routing']


    def to_dict(self):
        """Convert the configuration object to a dictionary representation.
        
        Returns:
            dict: A dictionary containing all configuration values
        """
        config_dict = {
            # Constants
            'log_setup_level': self.log_setup_level,
            'log_console_level': self.log_console_level,
            'log_file_level': self.log_file_level,
            'log_file_path': self.log_file_path,
            'max_simulation_attempts': self.max_simulation_attempts,
            'sql_connection_params': self.sql_connection_params,
            'TICK': str(self.TICK),  # Convert timedelta to string
            
            # User Input
            'ID_PROGETTO': self.ID_PROGETTO,
            'SHIFT_CONFIG': self.SHIFT_CONFIG,
            'casse_production_dates': {k: v.strftime('%Y-%m-%d') if hasattr(v, 'strftime') else v 
                                    for k, v in self.casse_production_dates.items()},
            'multiplier_ebom_to_dtr': self.multiplier_ebom_to_dtr,
            'hourly_cost_mbom': self.hourly_cost_mbom,
            'hourly_cost_workinstruction': self.hourly_cost_workinstruction,
            'hourly_cost_routing': self.hourly_cost_routing,
            'deadline_offset_mbom': self.deadline_offset_mbom,
            'deadline_offset_workinstruction': self.deadline_offset_workinstruction,
            'deadline_offset_routing': self.deadline_offset_routing,
            
            # From Database
            'NUM_EBOMS': self.NUM_EBOMS,
            
            # Derived Values
            'START_DATE': self.START_DATE.strftime('%Y-%m-%d') if self.START_DATE else None,
            'END_DATE': self.END_DATE.strftime('%Y-%m-%d') if self.END_DATE else None,
            'ELAPSED_DAYS': self.ELAPSED_DAYS,
            
            # Debug
            'debug__execute_a_single_simulation': self.debug__execute_a_single_simulation,
            'debug__force_mbom_workers_on_single_simulation': self.debug__force_mbom_workers_on_single_simulation,
            'debug__force_production_workers_on_single_simulation': self.debug__force_production_workers_on_single_simulation
        }
        
        return config_dict        
        

    def simulate_user_input_for_progetto(self, idprogetto):
        # Returns a dictionary simulating user input for debugging purposes
        if idprogetto == 71:
            return {
                'id_progetto': 71,
                'shift_config': {
                    1: {"start": "06:00", "duration": 7.5},
                    2: {"start": "14:00", "duration": 7.5},
                    # 3: {"start": "22:00", "duration": 7.0},
                },
                'casse_production_dates': {
                    '4A1': '2025-01-23',
                    '4A2': '2025-02-23',
                    '4A3': '2025-03-25',
                    '4A4': '2025-04-23'
                },
                'multiplier_ebom_to_dtr': 3,
                "project_skills": [
                    ('SKILL 1', 'Elettrico'), 
                    ('SKILL 2', 'Meccanico'), 
                    ('SKILL 4', 'Arredatore'), 
                    ('SKILL 8', 'Ritoccatore'), 
                    ('SKILL 5', 'Generico'), 
                    ('SKILL 3', 'Tubista'), 
                    ('SKILL 100', 'Verniciatore')
                ],
                "hourly_costs" :[
                    {
                        "skill": "default",
                        "hourly_cost_mbom": 1,
                        "hourly_cost_workinstruction": 40,
                        "hourly_cost_routing": 2
                    },
                    {
                        "skill": "SKILL 1",
                        "hourly_cost_mbom": 3,
                        "hourly_cost_workinstruction": 45,
                        "hourly_cost_routing": 5
                    },
                    {
                        "skill": "SKILL 2",
                        "hourly_cost_mbom": 5,
                        "hourly_cost_workinstruction": 50,
                        "hourly_cost_routing": 6
                    }
                ],
                'offset_mbom': 10,
                'offset_workinstruction': -20,
                'offset_routing': -5
            }

        elif idprogetto == 83:
            return {
                'id_progetto': 83,
                'shift_config': {
                    1: {"start": "06:00", "duration": 7.5},
                    2: {"start": "14:00", "duration": 7.5},
                    # 3: {"start": "22:00", "duration": 7.0},
                },
                'casse_production_dates': {
                    'DC1': '2025-01-23',
                    'DC2': '2025-02-23',
                    'EC1': '2025-03-25',
                    'EC2': '2025-04-23',
                    'IC1': '2025-05-23',
                    'IC2': '2025-06-23'
                },
                'multiplier_ebom_to_dtr': 3,
                'hourly_cost_mbom': 1,
                'hourly_cost_workinstruction': 40,
                'hourly_cost_routing': 2,
                'offset_mbom': 10,
                'offset_workinstruction': -20,
                'offset_routing': -5
            }
        else:
            return None

