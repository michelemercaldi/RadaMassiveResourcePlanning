from pmas_simulator import PmasSimulator
from pmas_util import PmasLoggerSingleton, PhaseType, format_time, format_date, format_time_only
from pmas_configuration import PmasConfiguration
from pmas_sql import PmasSql
from pmas_factory import PmasFactory
import traceback
import sys
import os
import inspect
import math
from datetime import timedelta
import csv
import datetime
from collections import defaultdict
from pmas_x_wl_gem import WorkerPlanner
import pulp


conf: PmasConfiguration = None
glog: PmasLoggerSingleton = None



class PmasStrategy:

    def __init__(self, pconf):
        global conf, glog
        glog = PmasLoggerSingleton.get_logger()
        conf = pconf


    def simulate_user_input(self):
        # set here id progetto if you are debugging from cli
        idprogetto = 71
        user_input = conf.simulate_user_input_for_progetto(idprogetto)
        if user_input is None:
            glog.error(f"project {idprogetto} not configured for simulation")
            sys.exit(3)
        return user_input


    def exec_simulation_logic(self, user_input):
        # update configuration values based on user input
        conf.update_config_with_user_input(user_input)
        #glog.info(conf.to_dict())

        sql = PmasSql(conf)
        fac = PmasFactory(conf)
        
        if __debug__: glog.info("\n---------------------")
        glog.info("progetto %d", conf.ID_PROGETTO)
        try:
            sql.start()
            casse = sql.getCasse(conf.ID_PROGETTO)              # es: ['4A1', '4A2', '4A3', '4A4']
        except Exception as e:
            glog.error("Exception retrieving data from database: %s", e)
            glog.error(traceback.format_exc())
            sys.exit(3)
        finally:
            if sql: sql.end()

        # get data from database
        try:
            sql.start()
            #sql.get_all_data_from_database()
            casse = sql.getCasse(conf.ID_PROGETTO)              # es: ['4A1', '4A2', '4A3', '4A4']
            phasesOffsetAndCosts = sql.getPhasestOffsetAndCost() # es: {'mbom': {'DESCRIZIONE': 'M-BOM', 'COSTOUNITARIOH': 1, 'OFFSET': 10}, 'workinstruction': {'DESCRIZIONE': 'WORK INSTRUCTION', 'COSTOUNITARIOH': 40, 'OFFSET': 20}, 'routing': {'DESCRIZIONE': 'ROUTING', 'COSTOUNITARIOH': 2, 'OFFSET': 5}}
            #sql.getMaxEbomReleaseDate(conf.ID_PROGETTO)
            ebomsPartnbr = sql.getAllEbomsLastRev(conf.ID_PROGETTO) # es: ['DT00000738735', 'DT00000740371', ... ] 
            ebomsWithDates = sql.getAllEbomsWithReleaseDates(conf.ID_PROGETTO)  # es: [{'IDANAGRAFICA': 12010, 'PARTNBR': 'DT00000915044', 'REV': 'A', 'DATARILASCIO': datetime.datetime(2019, 9, 2, 0, 0)}, ...]
            # aggregate eboms by cassa and assign production date
            ebomsWithDates = fac.aggregate_db_eboms_by_cassa(ebomsWithDates)
            ebomsWithSkills = sql.getAllEbomsWithSkills(conf.ID_PROGETTO)  # es: [{'IDANAGRAFICA': 12010, 'PARTNBR': 'DT00000915044', 'REV': 'A', 'SKILLS': ['skill1', 'skill2']}, ...]
            project_skills = {(item['CODICE'], item['DESCRIZIONE']) for item in ebomsWithSkills}
            glog.info("skills : %s", ebomsWithSkills)
            glog.info("skills for progetto %d: %s", conf.ID_PROGETTO, project_skills)
        except Exception as e:
            glog.error("Exception retrieving data from database: %s", e)
            glog.error(traceback.format_exc())
            sys.exit(3)
        finally:
            if sql: sql.end()
        glog.info("casse for progetto %d : %s", conf.ID_PROGETTO, casse)
        glog.info("costi: %s", {key: val['COSTOUNITARIOH'] for key, val in phasesOffsetAndCosts.items()})
        glog.info("offset: %s", {key: val['OFFSET'] for key, val in phasesOffsetAndCosts.items()})
        glog.info("%d eboms (last rev)", len(ebomsPartnbr))
        glog.info("%d eboms con release dates", len(ebomsWithDates))
        if len(ebomsPartnbr) != len(ebomsWithDates): glog.info("  ⚠️  WARNING: different length of eboms")
        if __debug__: glog.info("---------------------\n")

        self.check_casse_from_db_vs_casse_from_input(casse, conf.casse_production_dates)

        # Generate EBOMs
        eboms = fac.generate_eboms(ebomsWithDates)
        #eboms = fac.generate_eboms_fake(conf.NUM_EBOMS)
        if __debug__: fac.log_eboms(eboms)

        # set other configuration data
        conf.START_DATE = fac.get_min_eng_release_date(eboms)
        conf.END_DATE = fac.get_min_cassa_production_date(conf.casse_production_dates)
        conf.ELAPSED_DAYS = (conf.END_DATE - conf.START_DATE).days
        months = fac.get_month_list(conf.START_DATE, conf.ELAPSED_DAYS)

        # Generate Shifts
        shifts = fac.generate_shifts(conf, conf.START_DATE, conf.ELAPSED_DAYS)
        if __debug__: fac.log_shifts(shifts)


        glog.info("\n---------------------")
        glog.info("⚙️  Configuration:")
        glog.info("⚙️    NUM_EBOMS = %d (= %d eboms * %d multiplier_factor)", conf.NUM_EBOMS, len(ebomsWithDates), conf.multiplier_ebom_to_dtr)
        glog.info("⚙️    SHIFT_CONFIG = %s", conf.SHIFT_CONFIG)
        glog.info("⚙️    TICK = %s", conf.TICK)
        glog.info("⚙️    START_DATE   = %s   (%s)", format_date(conf.START_DATE), "min engineering release date")
        glog.info("⚙️    END_DATE     = %s   (%s)", format_date(conf.END_DATE), "min casse production dates")
        glog.info("⚙️    ELAPSED_DAYS = %10s   (%s)", str(conf.ELAPSED_DAYS).rjust(10), "END_DATE - START_DATE")
        glog.info("⚙️    MONTHS = %s", months)
        glog.info("---------------------")
        
        glog.info(f"stop on {os.path.basename(__file__)}, line: {inspect.currentframe().f_lineno}"); sys.exit(2) # _mme





        glog.info("---------------------")
        #glog.info("---------------------")
        #glog.info(f"_mme first eboms[0]: {eboms[0]}")
        #glog.info("---------------------")
        # Calculate the number of shifts and hours in each month
        months = fac.calculate_shifts_per_month(shifts)
        #glog.info(f"_mme months: {months}")
        #glog.info("---------------------")
        fac.assign_mean_working_days_per_ebom(eboms)
        #for ebom in eboms: glog.info(f"_mme ebom: {ebom['id']} release: {format_date(ebom['eng_release_date'])}, production: {format_date(ebom['production_date'])}, cost:{ebom['total_cost']}, daily_required_hours:{ebom['daily_required_hours']}")
        glog.info("---------------------")
        fac.fill_total_working_hours_needed_by_eboms_per_month(eboms, months, shifts)
        #for monthkey in sorted(months.keys()): glog.info(f"_mme a {monthkey}: {months[monthkey]}")
        glog.info("---------------------")
        # _mme rivedi se usare o no 'sta aggregazione o togliere il vincolo sulla mbom date deadline    months = fac.aggregate_underutilized_months(months)
        #for monthkey in sorted(months.keys()): glog.info(f"_mme b {monthkey}: {months[monthkey]}")
        #glog.info("---------------------")
        self.calculate_pulp_num_of_workers(months)
        glog.info("---------------------")
        fac.ensure_not_zero_workers(months)
        #glog.info(f"_mme months inited: {months}")
        glog.info(" 📅 Months with Workers")
        # _ mme ori for monthkey in sorted(months.keys()): glog.info(f"  {monthkey}: {months[monthkey]}")
        glog.info("{:<12} {:>8} {:>8} {:>10} {:>12}".format("📅 Month", "Workers", "Shifts", "Hours", "Required (h)"))
        for monthkey in sorted(months.keys()): glog.info("{:<12} {:>8} {:>8} {:>10.1f} {:>12.2f}".format(
            f"{monthkey[0]}-{str(monthkey[1]).zfill(2)}",
            months[monthkey]['workers'],
            months[monthkey]['num_of_shifts'],
            months[monthkey]['available_hours'],
            months[monthkey]['eboms_required_hours']
        ))
        glog.info("---------------------")
        
        # Initialize the planner  #  _mme remove
        #planner = WorkerPlanner(shifts=shifts, saturation_percentage=0.9)
        ## Calculate monthly worker requirements
        #monthly_workers = planner.plan_workers(eboms=eboms)
        ## Print the results
        #for (year, month), workers in monthly_workers.items():
        #    print(f"Month: {year}-{month:02d}, Required Workers: {workers}")
        #glog.info("---------------------")

        
        # run simulation with the best number of workers
        glog.info("\n\n\n====================================================")
        monthly_workers = fac.assign_monthly_workers_from_pulp_months(months)
        fac.reset_eboms(eboms)
        sim = PmasSimulator(conf, eboms, shifts, monthly_workers)
        sim.run()
        sim.print_simulation_end(PhaseType.PRODUCTION)
        
        # export results    
        self.export_results(sim)


        glog.info(f"_mme stop on {os.path.basename(__file__)}, line: {inspect.currentframe().f_lineno}");  sys.exit(2)









        ##################  simulation start
        # Create a dictionary mapping (year, month) → num_of_worker,  initialized with fixed num of workers
        # Assign monthly workers: from START_DATE to max_mbom_deadline use min_num_workers_needed_for_mbom,
        # then from (max_mbom_deadline + 1) to max_production_deadline use min_num_workers_needed_for_production
        # create a list of tuple (num_of_worker, simulation_failed) to keep track of the list of simulation attempts

        # tuple (num_of_worker, simulation_failed)
        mbom_workers_num_and_results = []
        production_workers_num_and_results = []

        
        if conf.debug__execute_a_single_simulation:
            mbom_workers = conf.debug__force_mbom_workers_on_single_simulation
            production_workers = conf.debug__force_production_workers_on_single_simulation

        else:
            # optimize engineering
            lnc.optimize_num_of_workers_running_simulations(
                conf,
                PhaseType.ENGINEERING,   # first round of simulations only for engineering phases
                months,
                eboms,
                shifts,
                conf.max_simulation_attempts,
                max_mbom_deadline,
                min_num_workers_needed_for_mbom,
                min_num_workers_needed_for_production,
                mbom_workers_num_and_results,
                production_workers_num_and_results
            )

            glog.info("\n\n\n====================")
            glog.info("Engineering simulation attempts (num of workers, sim failed): %s", mbom_workers_num_and_results)
            glog.info("Production simulation attempts (num of workers, sim failed): %s", production_workers_num_and_results)
            glog.info("====================")

            # optimize production
            lnc.optimize_num_of_workers_running_simulations(
                conf,
                PhaseType.PRODUCTION,  # second round for all engineering and production phases
                months,
                eboms,
                shifts,
                conf.max_simulation_attempts,
                max_mbom_deadline,
                min_num_workers_needed_for_mbom,
                min_num_workers_needed_for_production,
                mbom_workers_num_and_results,
                production_workers_num_and_results
            )
            
            glog.info("\n\n\n====================")
            glog.info("Engineering simulation attempts (num of workers, sim failed): %s", mbom_workers_num_and_results)
            glog.info("Production simulation attempts (num of workers, sim failed): %s", production_workers_num_and_results)
            glog.info("====================")

            # get min number of workers with simulation_failed == False
            mbom_workers = min(worker for worker, failed in mbom_workers_num_and_results if not failed)
            production_workers = min(worker for worker, failed in production_workers_num_and_results if not failed)

        # run last simulation with the best number of workers
        glog.info("\n\n\n====================================================")
        glog.info("Final Engineering workers: %d (theoretical min needed: %d)", mbom_workers, min_num_workers_needed_for_mbom)
        glog.info("Final  Production workers: %d (theoretical min needed: %d)", production_workers, min_num_workers_needed_for_production)
        monthly_workers = fac.assign_monthly_workers(months, max_mbom_deadline, mbom_workers, production_workers)
        fac.reset_eboms(eboms)
        sim = PmasSimulator(conf, eboms, shifts, monthly_workers)
        sim.run()
        sim.print_simulation_end(PhaseType.ENGINEERING)
        
        # export results    
        self.export_results(sim)




    def export_results(self, sim):
        export_file = "logs\massive_planning_schedule_export.csv"
        with open(export_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["worker", "task", "start", "end", "shift"], delimiter=';')
            writer.writeheader()
            for row in sim.schedule_log:
                writer.writerow({**row, "start": format_time(row["start"]), "end": format_time(row["end"])})
        glog.info("✅ CSV exported: %s", export_file)

        export_file = "logs\massive_planning_status.txt"
        with open(export_file, "w") as f:
            f.write(f"\nSTART_DATE: {conf.START_DATE}\n")
            f.write(f"ELAPSED_DAYS: {conf.ELAPSED_DAYS} days\n")
            f.write("\n")
            for ebom in sim.eboms:
                uncompleted_ebom = "UNCOMPLETED" if self.is_uncompleted_ebom(ebom) else ""
                f.write(f"{ebom['id']}  {uncompleted_ebom}\n")  
                f.write(f"eng_release_date: {format_date(ebom['eng_release_date'])} - production_date: {format_date(ebom['production_date'])}\n")
                for phase in ebom["phases"]:
                    remaining_cost = round(phase["remaining_cost"], 2) if phase["remaining_cost"] > 0 else 0
                    f.write(f"  - { phase['name']}: {remaining_cost}h remaining, deadline: {format_date(phase['deadline'])}, worker: {phase['active_worker']}\n")
                f.write("\n")
        glog.info("✅ Status exported: %s", export_file)
        glog.info("log in: %s", conf.log_file_path)

    def is_uncompleted_ebom(self, ebom):
        for phase in ebom["phases"]:
            if phase["remaining_cost"] > 0:
                return True
        return False
 
        
        
    def guess_optimal_number_of_workers(self, num_of_workers_and_simulation_result, num_simulation_attempts):
        """
        this function is invoked if previous attempt failed or on first run
        a list of num of workers used till now in the various attempt is passed as argument

        the num of workers is a tuple (numofworker, simulation_failed)
        based on this list I want to guess the next number using an algorithm like this:
        if last_simulation failed, I want to increase number by 10 or more
        if last simulation was ok I want to decrease the number by the half of the distance from the previous number
        """
        # Example: workers_history = [(20, True), (30, False), (25, True)]
        default_incr = num_simulation_attempts * 2 - 2
        if not num_of_workers_and_simulation_result or len(num_of_workers_and_simulation_result) == 0:
            return 0  # no history

        last_num_of_workers, last_failed = num_of_workers_and_simulation_result[-1]

        if len(num_of_workers_and_simulation_result) == 1:
            # Only one attempt so far, just increase if failed, or decrease a bit if succeeded
            if last_failed:
                return last_num_of_workers + default_incr
            else:
                return max(1, last_num_of_workers - default_incr // 2)

        # get min and max number of workers
        min_ok = min((worker for worker, failed in num_of_workers_and_simulation_result if not failed), default=-1)
        max_ok = max((worker for worker, failed in num_of_workers_and_simulation_result if not failed), default=-1)
        min_ko = min((worker for worker, failed in num_of_workers_and_simulation_result if failed), default=-1)
        max_ko = max((worker for worker, failed in num_of_workers_and_simulation_result if failed), default=-1)
        
        next_guess = 0
        if min_ok == -1 and max_ok == -1:  # All simulations failed
            next_guess = max_ko + default_incr
        elif min_ko == -1 and max_ko == -1:  # All simulations succeeded
            next_guess = max_ok + default_incr
        else:
            next_guess =    (max_ko + min_ok) // 2
        if __debug__: glog.debug("            guess_optimal_number_of_workers : min_ok: %d, max_ok: %d, min_ko: %d, max_ko: %d, next_guess: %d", min_ok, max_ok, min_ko, max_ko, next_guess)
        return next_guess


    def optimize_num_of_workers_running_simulations(self,
                conf,
                phaseType,
                months,
                eboms,
                shifts,
                max_simulation_attempts,
                max_mbom_deadline,
                mbom_min_num_workers,
                production_min_num_workers,
                mbom_workers_num_and_results,
                production_workers_num_and_results 
            ):
        fac = PmasFactory(conf)

        for attempt in range(1, max_simulation_attempts + 1):
            glog.info("\n\n\n====================================================")
            glog.info("%s - Attempt %d/%d", phaseType.name, attempt, max_simulation_attempts)
            if phaseType == PhaseType.ENGINEERING:
                mbom_workers = self.guess_optimal_number_of_workers(mbom_workers_num_and_results, max_simulation_attempts)
                if mbom_workers == 0 : mbom_workers = mbom_min_num_workers
                production_workers = 0
            else:
                # get min mbom number of workers with simulation_failed == False
                mbom_workers = min(worker for worker, failed in mbom_workers_num_and_results if not failed)
                production_workers = self.guess_optimal_number_of_workers(production_workers_num_and_results, max_simulation_attempts)
                if production_workers == 0: production_workers = production_min_num_workers

            glog.info("    👷    %d  engineering workers    -    %d  production workers", mbom_workers, production_workers)
            monthly_workers = fac.assign_monthly_workers(months, max_mbom_deadline, mbom_workers, production_workers)
            glog.info("Monthly Workers Configuration: %s", monthly_workers)
            fac.reset_eboms(eboms)

            sim = PmasSimulator(conf, eboms, shifts, monthly_workers)
            sim.run()
            sim.print_simulation_end(phaseType)
            
            if phaseType == PhaseType.ENGINEERING:
                mbom_workers_num_and_results.append((mbom_workers, len(sim.get_uncompleted_mboms()) > 0))
            else:
                production_workers_num_and_results.append((production_workers, len(sim.get_uncompleted_eboms()) > 0))
            glog.info("MBOM Workers used: %d, uncompleted MBOMs: %d", mbom_workers, len(sim.get_uncompleted_mboms()))
            glog.info("Production Workers used: %d, uncompleted EBOMs: %d", production_workers, len(sim.get_uncompleted_eboms()))

    
    def check_casse_from_db_vs_casse_from_input(self, casse_from_db, casse_production_dates):
        # Check if list of casse from getCasse is equal to casse_production_dates list of keys
        casse_from_dbs = set(casse_from_db)
        casse_from_input = set(casse_production_dates.keys())
        if set(casse_from_dbs) != casse_from_input:
            glog.error("Mismatch between casse from DB (%s) and casse_production_dates keys (%s)", casse_from_dbs, casse_from_input)
            sys.exit(3)






    def allocate_workers(tasks):  # _mme rivedi se serve questa o no
        # Initialize a dictionary to hold monthly workloads
        monthly_workload = defaultdict(float)
        start_date = min(task['start_date'] for task in tasks)
        end_date = max(task['deadline'] for task in tasks)

        # Iterate over each month in the date range
        current_date = start_date
        while current_date <= end_date:
            year_month = (current_date.year, current_date.month)
            monthly_workload[year_month] = 0
            # Move to the next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        # Distribute task hours across months
        for task in tasks:
            task_start = task['start_date']
            task_deadline = task['deadline']
            task_hours = task['cost_in_hours']

            # Calculate the number of months the task spans
            months = []
            current_month_start = task_start.replace(day=1)
            while current_month_start <= task_deadline:
                year_month = (current_month_start.year, current_month_start.month)
                months.append(year_month)
                if current_month_start.month == 12:
                    current_month_start = current_month_start.replace(year=current_month_start.year + 1, month=1)
                else:
                    current_month_start = current_month_start.replace(month=current_month_start.month + 1)

            # Distribute task hours evenly across the months
            hours_per_month = task_hours / len(months)
            for year_month in months:
                monthly_workload[year_month] += hours_per_month

        # Calculate the number of workers needed each month
        monthly_worker_allocation = {}
        for year_month, total_hours in monthly_workload.items():
            year, month = year_month
            # Assuming an average of 22 working days per month
            working_hours_per_month = 8 * 22
            workers_needed = total_hours / working_hours_per_month
            monthly_worker_allocation[year_month] = workers_needed

        return monthly_worker_allocation

    ## Example usage
    #tasks = [
    #    {'start_date': datetime.date(2023, 1, 1), 'deadline': datetime.date(2023, 3, 31), 'cost_in_hours': 400},
    #    {'start_date': datetime.date(2023, 2, 1), 'deadline': datetime.date(2023, 4, 30), 'cost_in_hours': 360},
    #    # Add more tasks as needed
    #]
    # monthly_worker_allocation = allocate_workers(tasks)
    # print(monthly_worker_allocation)



    def calculate_pulp_num_of_workers_v2(self, months):
        """
        Solve for the minimal number of workers per month using MILP with PuLP,
        subject to shift capacity, saturation constraints, and workload shifting.

        Parameters:
            months (dict): {
                (year, month): {'num_of_shifts': int, 'eboms_required_hours': float},
                ...
            }
        """
        shift_hours = 7.5
        saturation = 0.9
        effective_shift_hours = shift_hours * saturation

        # Define the MILP problem
        prob = pulp.LpProblem("WorkerLoadBalancer", pulp.LpMinimize)

        # Variables
        w = {m: pulp.LpVariable(f"workers_{m}", lowBound=0, cat='Integer') for m in months}
        x = {m: pulp.LpVariable(f"shifted_hours_{m}", lowBound=0, cat='Continuous') for m in months}

        # Objective: minimize total number of workers
        prob += pulp.lpSum(w[m] for m in months)

        # Sort the months in chronological order
        month_list = sorted(months.keys())

        # Ensure each month covers its required hours (including any previously shifted hours)
        for m in month_list:
            shifts = months[m]['num_of_shifts']
            required = months[m]['eboms_required_hours']
            available = w[m] * shifts * effective_shift_hours
            prob += available + x[m] >= required, f"coverage_{m}"

        # Allow forward shifting of workload to the next month
        for i in range(len(month_list) - 1):
            m, next_m = month_list[i], month_list[i + 1]
            required = months[m]['eboms_required_hours']
            prob += (
                x[next_m] >= x[m] + required - (w[m] * months[m]['num_of_shifts'] * effective_shift_hours),
                f"shift_{m}_to_{next_m}"
            )

        # Ensure all workload is completed by the last month
        last_month = month_list[-1]
        prob += x[last_month] == 0, "no_work_left_after_final_month"

        # Solve the problem
        prob.solve()

        # Print results
        print("\nResult -", pulp.LpStatus[prob.status])
        print(f"Objective value (total workers): {pulp.value(prob.objective):.2f}\n")

        for m in month_list:
            print(f"{m}: Workers = {w[m].varValue:.0f}, Shifted Hours = {x[m].varValue:.2f}")
            months[m]['workers'] = int(w[m].varValue)



    # review the penalty in this function
    def calculate_pulp_num_of_workers_v1(self, months):
        """
        Solve for the minimal number of workers per month using MILP with PuLP,
        subject to shift capacity, saturation constraints, and optional inter-month load balancing.
        
        Parameters:
            months (dict): {
                'Jan': {'num_of_shifts': 42, 'eboms_required_hours': 800},
                'Feb': {'num_of_shifts': 44, 'eboms_required_hours': 1200},
                ...
            }
        """
        
        """
        Variables
            w_m: Integer variable = number of workers in month m
            x_m: Real variable = number of hours shifted into month m from previous months

        Constants
            H_m: Required hours in month m (from eboms_required_hours)
            A_m: Available hours in month m = w_m × shifts × hours/shift × saturation

        Objective: minimize total workers
            min(summation_m(w_m))
        """
        
        shift_hours = 7.5
        saturation = 0.9
        effective_shift_hours = shift_hours * saturation

        # Problem definition
        prob = pulp.LpProblem("WorkerLoadBalancer", pulp.LpMinimize)

        # Variables
        w = {m: pulp.LpVariable(f"workers_{m}", lowBound=0, cat='Integer') for m in months}
        x = {m: pulp.LpVariable(f"shifted_hours_{m}", lowBound=0, cat='Continuous') for m in months}

        # Objective: minimize total workers
        # Optional: penalize excessive shifting (uncomment if desired)
        penalty_weight = 0.1 # 0.01
        prob += pulp.lpSum(w[m] for m in months) + penalty_weight * pulp.lpSum(x[m] for m in months)

        # Sort months in logical order
        month_list = sorted(months.keys())

        # Task coverage constraint
        for m in month_list:
            shifts = months[m]['num_of_shifts']
            required = months[m]['eboms_required_hours']
            available = w[m] * shifts * effective_shift_hours
            prob += available + x[m] >= required, f"coverage_{m}"

        # Allow workload shift from m to m+1
        for i in range(len(month_list) - 1):
            m, next_m = month_list[i], month_list[i + 1]
            required = months[m]['eboms_required_hours']
            prob += (
                x[next_m] >= x[m] + required - (w[m] * months[m]['num_of_shifts'] * effective_shift_hours),
                f"shift_{m}_to_{next_m}"
            )

        # Enforce that no workload is left over in the last month
        last_month = month_list[-1]
        prob += x[last_month] == 0, "final_month_must_clear_all_shifted_work"

        # Solve the problem
        prob.solve()

        # Output results
        print("\nResult -", pulp.LpStatus[prob.status])
        print(f"Objective value (total workers + penalty): {pulp.value(prob.objective):.2f}\n")

        for m in month_list:
            print(f"{m}: Workers = {w[m].varValue:.0f}, Shifted Hours = {x[m].varValue:.2f}")
            months[m]['workers'] = int(w[m].varValue)



    # considering that a worker can work on a single shift
    def calculate_pulp_num_of_workers(self, months):
        """
        Solve for the minimal number of workers per month using MILP with PuLP,
        subject to shift capacity, saturation constraints, and workload shifting.

        Assumes each worker can only perform one shift per day.
        Each day has 2 shifts → a worker can work up to half the number of shifts in the month.

        Parameters:
            months (dict): {
                'Jan': {'num_of_shifts': 42, 'eboms_required_hours': 800},
                ...
            }
        """
        # _mme  ........... questi qua sotto devono essere parametri
        shift_hours = 7.5   # _mme get as param
        saturation = 0.9   # _mme get as param
        shifts_per_day = 2  # now explicitly considered   # _mme get as param
        effective_shift_hours = shift_hours * saturation   # _mme get as param ?

        # Define MILP problem
        prob = pulp.LpProblem("WorkerLoadBalancer", pulp.LpMinimize)

        # Variables
        w = {m: pulp.LpVariable(f"workers_{m}", lowBound=0, cat='Integer') for m in months}
        x = {m: pulp.LpVariable(f"shifted_hours_{m}", lowBound=0, cat='Continuous') for m in months}

        # Objective: minimize total workers + penalty for shifting
        penalty_weight = 0.1
        prob += pulp.lpSum(w[m] for m in months) + penalty_weight * pulp.lpSum(x[m] for m in months)

        # Sort months chronologically
        month_list = sorted(months.keys())

        for m in month_list:
            total_shifts = months[m]['num_of_shifts']
            required_hours = months[m]['eboms_required_hours']

            # Compute max number of shifts each worker can do: 1 shift/day → shifts/2 days per month
            workdays = total_shifts / shifts_per_day
            max_worker_hours = workdays * effective_shift_hours

            # Total available = number of workers * max hours per worker
            available = w[m] * max_worker_hours

            # Task coverage constraint (includes shifted hours from previous month)
            prob += available + x[m] >= required_hours, f"coverage_{m}"

        # Allow workload to shift forward month-to-month
        for i in range(len(month_list) - 1):
            m, next_m = month_list[i], month_list[i + 1]
            total_shifts = months[m]['num_of_shifts']
            workdays = total_shifts / shifts_per_day
            max_worker_hours = workdays * effective_shift_hours
            required_hours = months[m]['eboms_required_hours']

            prob += (
                x[next_m] >= x[m] + required_hours - (w[m] * max_worker_hours),
                f"shift_{m}_to_{next_m}"
            )

        # No workload should remain after the final month
        last_month = month_list[-1]
        prob += x[last_month] == 0, "final_month_must_clear_all_shifted_work"

        # Solve
        prob.solve()

        # Output results
        print("\nResult -", pulp.LpStatus[prob.status])
        print(f"Objective value (total workers + penalty): {pulp.value(prob.objective):.2f}\n")

        for m in month_list:
            num_of_worker = int(w[m].varValue)  # _mme finetuning _pulp_ adjustment  review this adjustment
            print(f"{m}: Workers = {num_of_worker:.0f}, Shifted Hours = {x[m].varValue:.2f}")
            months[m]['workers'] = num_of_worker

