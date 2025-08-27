from pmas_simulator import PmasSimulator
from pmas_util import PmasLoggerSingleton, PmasLogBroker, PhaseType, format_time, format_date, format_time_only, job_id_var
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
        user_input['job_id'] = job_id_var.get()
        if user_input is None:
            glog.error(f"project {idprogetto} not configured for simulation")
            sys.exit(3)
        return user_input


    def exec_simulation_logic(self, user_input, weblog_broker: PmasLogBroker):
        job_id = user_input['job_id']
        def weblog(msg):
            if weblog_broker:
                weblog_broker.put_threadsafe(job_id, msg)

        # update configuration values based on user input
        conf.update_config_with_user_input(user_input)
        #glog.info(conf.to_dict())

        sql = PmasSql(conf)
        fac = PmasFactory(conf)
        
        if __debug__: glog.info("\n---------------------")
        glog.info("progetto %d", conf.ID_PROGETTO)
        weblog("getting list of eboms from database for project {}".format(conf.ID_PROGETTO))
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
            
            # retrieve list of casse for progetto
            #   es: ['4A1', '4A2', '4A3', '4A4']
            casse = sql.getCasse(conf.ID_PROGETTO)
            
            # retrieve all phases and costs 
            #   es: {'mbom': {'DESCRIZIONE': 'M-BOM', 'COSTOUNITARIOH': 1, 'OFFSET': 10}, 'workinstruction': {'DESCRIZIONE': 'WORK INSTRUCTION', 'COSTOUNITARIOH': 40, 'OFFSET': 20}, 'routing': {'DESCRIZIONE': 'ROUTING', 'COSTOUNITARIOH': 2, 'OFFSET': 5}}
            phasesOffsetAndCosts = sql.getPhasestOffsetAndCost()
            #sql.getMaxEbomReleaseDate(conf.ID_PROGETTO)
            
            ..........................................
            1) metti qualche commento da qui in poi
            2) correggere la FUNCTION GetEbomsNotAssignedToAP
                la selezione non va fatta solo sul progetto ma anche sul tipo attivita'
                l'assegnazione degli ebom deve essere unica per ogni tipo attivita' / progetto
            ..................................................

            ebomsPartnbr = sql.getAllEbomsLastRev(conf.ID_PROGETTO) # es: ['DT00000738735', 'DT00000740371', ... ] 
            ebomsWithDates = sql.getAllEbomsWithReleaseDates(conf.ID_PROGETTO)  # es: [{'IDANAGRAFICA': 12010, 'PARTNBR': 'DT00000915044', 'REV': 'A', 'DATARILASCIO': datetime.datetime(2019, 9, 2, 0, 0)}, ...]

            # aggregate eboms by cassa and assign production date
            ebomsWithDates = fac.aggregate_db_eboms_by_cassa(ebomsWithDates)
            if ebomsWithDates: glog.info("ebomsWithDates: [%s, ...] %d items", ebomsWithDates[0], len(ebomsWithDates))

            ebomsWithSkills = sql.getAllEbomsWithSkills(conf.ID_PROGETTO)  # es: [{'PARTNBR': 'DT00000738735', 'CODICE': 'SKILL 2', 'DESCRIZIONE': 'Meccanico'}, ...]
            if ebomsWithSkills: glog.info("ebomsWithSkills: [%s, ...] %d items", ebomsWithSkills[0], len(ebomsWithSkills))
            project_skills = {(item['CODICE'], item['DESCRIZIONE']) for item in ebomsWithSkills}
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
        weblog("\n---------------------")
        weblog("⚙️  Configuration:")
        weblog(f"⚙️    NUM_EBOMS = {conf.NUM_EBOMS} (= {len(ebomsWithDates)} eboms * {conf.multiplier_ebom_to_dtr} multiplier_factor)")
        weblog(f"⚙️    START_DATE   = {format_date(conf.START_DATE)}   (min engineering release date)")
        weblog(f"⚙️    END_DATE     = {format_date(conf.END_DATE)}   (min casse production dates)")
        weblog(f"⚙️    ELAPSED_DAYS = {str(conf.ELAPSED_DAYS).rjust(10)}   (END_DATE - START_DATE)")
        weblog("---------------------")
        
        # stop execution : glog.info(f"stop on {os.path.basename(__file__)}, line: {inspect.currentframe().f_lineno}"); return   # stop execution

        # Calculate the number of shifts and hours in each month
        #  sample output:   {(2022, 1): {'num_of_shifts': 36, 'available_hours': 270.0}, {...}, ... }
        months = fac.calculate_shifts_per_month(shifts)
        # glog.info("---------------------")

        # For each ebom, assign the average number of hours expected to be worked on a daily basis
        #  e.g.:  ebom: GL00002097306__3 release: 2023-11-17, production: 2025-03-25, cost:43, daily_required_hours:0.08704453441295547
        fac.assign_mean_working_days_per_ebom(eboms)
        # for ebom in eboms: glog.info(f"ebom: {ebom['id']} release: {format_date(ebom['eng_release_date'])}, production: {format_date(ebom['production_date'])}, cost:{ebom['total_cost']}, daily_required_hours:{ebom['daily_required_hours']}")
        # glog.info("---------------------")

        # Sum in every month the amount of hours needed by the eboms
        # based on elapsed from eng_release_date to production_date  and the average daily hours needed for every ebom
        #  sample:  (2024, 9): {'num_of_shifts': 42, 'available_hours': 315.0, 'eboms_required_hours': 1733.1249906270161}
        fac.fill_total_working_hours_needed_by_eboms_per_month(eboms, months, shifts)
        # for monthkey in sorted(months.keys()): glog.info(f"(a) {monthkey}: {months[monthkey]}")
        # glog.info("---------------------")

        # finetuning:  Aggregates underutilized months by merging their eboms_required_hours into the next month
        # months = fac.aggregate_underutilized_months(months)
        # for monthkey in sorted(months.keys()): glog.info(f"(b) {monthkey}: {months[monthkey]}")
        # glog.info("---------------------")


        #  ========================================
        #  Worker Planning
        #  ========================================
        # use MILP solver to calculate the number of workers needed for every month
        self.calculate_pulp_num_of_workers(months)
        fac.ensure_not_zero_workers(months)

        # log the final worker allocation in logger and to the client browser
        glog.info("---------------------\n\n")
        glog.info(" 📅 Months with Workers")
        # for monthkey in sorted(months.keys()): glog.info(f"  {monthkey}: {months[monthkey]}")
        glog.info("{:<12} {:>8} {:>8} {:>10} {:>12}".format("📅 Month", "Workers", "Shifts", "Hours", "Required (h)"))
        for monthkey in sorted(months.keys()): glog.info("{:<12} {:>8} {:>8} {:>10.0f} {:>12.0f}".format(
            f"{monthkey[0]}-{str(monthkey[1]).zfill(2)}",
            months[monthkey]['workers'],
            months[monthkey]['num_of_shifts'],
            months[monthkey]['available_hours'],
            months[monthkey]['eboms_required_hours']
        ))
        glog.info("---------------------")
        weblog("📅 Number of workers needed per month:")
        for monthkey in sorted(months.keys()): 
            weblog(f"{monthkey[0]} {datetime.date(monthkey[0], monthkey[1], 1).strftime('%b').upper()} : " +
                   f"  {months[monthkey]['workers']} workers  " +
                   f"  {months[monthkey]['num_of_shifts']} shifts"
            )
        weblog("---------------------")


        # run scheduling simulation 
        #   based on the results above we schedule every activity 
        #   assigning workers to every task
        glog.info("\n\n\n====================================================")
        monthly_workers = fac.assign_monthly_workers_from_pulp_months(months)
        fac.reset_eboms(eboms)
        sim = PmasSimulator(conf, eboms, shifts, monthly_workers, weblog)
        sim.run()
        sim.print_simulation_end(PhaseType.PRODUCTION)
        
        # export results    
        self.export_results(sim)

        # stop execution: glog.info(f"stop on {os.path.basename(__file__)}, line: {inspect.currentframe().f_lineno}");  return


    def export_results(self, sim):
        job_id = job_id_var.get()
        base, ext = os.path.splitext(conf.schedule_export_file_path)
        export_file = f"{base}.{job_id}{ext}"
        with open(export_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["worker", "task", "start", "end", "shift"], delimiter=';')
            writer.writeheader()
            for row in sim.schedule_log:
                writer.writerow({**row, "start": format_time(row["start"]), "end": format_time(row["end"])})
        glog.info("✅ CSV exported: %s", export_file)

        base, ext = os.path.splitext(conf.status_file_path)
        export_file = f"{base}.{job_id}{ext}"
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
 

    def check_casse_from_db_vs_casse_from_input(self, casse_from_db, casse_production_dates):
        # Check if list of casse from getCasse is equal to casse_production_dates list of keys
        casse_from_dbs = set(casse_from_db)
        casse_from_input = set(casse_production_dates.keys())
        if set(casse_from_dbs) != casse_from_input:
            glog.error("Mismatch between casse from DB (%s) and casse_production_dates keys (%s)", casse_from_dbs, casse_from_input)
            sys.exit(3)


    # considering that a worker can work on a single shift
    def calculate_pulp_num_of_workers(self, months):
        """
        Solve for the minimal number of workers per month using MILP with PuLP,
        subject to shift capacity, saturation constraints, and workload shifting.

        Assumes each worker can only perform one shift per day.
        Each day has 2 shifts → a worker can work up to half the number of shifts in the month.

        Parameters:
            months (dict): {
                'Jan': {'num_of_shifts': 42, 'eboms_required_hours': 800 ...},
                ...
            }
        sample data:
        {
            (2022, 1): {'num_of_shifts': 36, 'available_hours': 270.0, 'eboms_required_hours': 35.29617692701845}, 
            (2022, 2): {'num_of_shifts': 40, 'available_hours': 300.0, 'eboms_required_hours': 119.30932850424772}, 
            .....
            (2024, 12): {'num_of_shifts': 44, 'available_hours': 330.0, 'eboms_required_hours': 2146.209947173681}, 
            (2025, 1): {'num_of_shifts': 32, 'available_hours': 240.0, 'eboms_required_hours': 1523.1167367038938}
        }
        """
        
        saturation = conf.worker_saturation_per_shift   # e.g., 0.9 means workers must be utilized at least 90% of the time during their shifts

        shifts_per_day = len(conf.SHIFT_CONFIG)

        # average duration of the shifts
        shift_hours = (sum(s.get('duration', 0) for s in conf.SHIFT_CONFIG.values()) / shifts_per_day) if shifts_per_day else 0

        # Effective shift hours (considering saturation)
        effective_shift_hours = shift_hours * saturation

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
            num_of_worker = int(w[m].varValue) # here we can hack the number of workers
            print(f"{m}: Workers = {num_of_worker:.0f}, Shifted Hours = {x[m].varValue:.2f}")
            months[m]['workers'] = num_of_worker

