from datetime import datetime, timedelta
import sys
import time
from pmas_util import PmasLoggerSingleton, PhaseType, format_time, format_date, format_time_only
from pmas_configuration import PmasConfiguration

conf: PmasConfiguration = None
glog: PmasLoggerSingleton = None


class PmasSimulator:
    def __init__(self, pconf, eboms, shifts, monthly_workers):
        global conf, glog
        glog = PmasLoggerSingleton.get_logger()
        conf = pconf
        self.eboms = eboms
        self.shifts = shifts
        self.monthly_workers = monthly_workers  # (year, month) → num_of_workers
        self.current_time = None
        self.cts = None  # current time in string format
        self.htick = conf.TICK.total_seconds() / 3600  # Convert TICK to hours
        self.assign_current_time(conf.START_DATE)
        self.current_workers = {}
        self.current_day = self.current_time.date()
        self.schedule_log = []  # list of dicts for CSV/Gantt

        # list of ebom phases available, all the phases still not completed
        # as for every ebom the phases must be executed in sequence only one phase is available for every ebom
        self.available_phases = {ebom["id"]: ebom['phases'][0] for ebom in self.eboms}
        
        # metrics
        self.simulation_start_time = None
        self.simulation_end_time = None


    def assign_current_time(self, adate):
        self.current_time = adate
        self.cts = self.current_time.strftime('%Y-%m-%d %H:%M')  # current time in string format


    def run(self):
        self.simulation_start_time = time.time()
        end_time = conf.START_DATE + timedelta(days=conf.ELAPSED_DAYS)
        glog.info("%s - 🕒 Simulation starts: %s", self.cts, format_time(self.current_time))
        if __debug__: glog.info("%s - 🕒   expected end at: %s\n", self.cts, format_time(end_time))

        # Header for info output  (optional: only print once)
        glog.info("{:<20} {:<15} {:>12} {:>10} {:>25}".format("⏱ Timestamp", "📅 Period", "Uncompleted EBOMs", "Workers", "Total h worked / remaining"))
    
        is_working_time = False
        current_shift_num = -1
        simulation_failed = False

        # =======================================
        # =====          main loop          =====
        # =======================================
        while self.current_time <= end_time and not simulation_failed:
            if __debug__: glog.debug("\n%s - === ⏱️ Time Tick: %s ===", self.cts, format_time(self.current_time))
            self.current_day = self.current_time.date()
            # _mme remove if not needed  worker_ids_on_closed_phase_in_this_tick = []

            # Log at the beginning of the month
            #if __debug__:
            if self.current_time.day == 1 and self.current_time.hour == 0 and self.current_time.minute == 0:
                total_h_worked, total_h_remaining = self.get_total_h_worked_and_remaining()
                # _mme ori glog.info("%s - 📅 %s  ... working ...  uncompleted eboms: %s,  workers: %d, total_h worked/remaining: %.2f / %.2f", self.cts, self.current_time.strftime('%B %Y'), len(self.get_uncompleted_eboms()), self.monthly_workers[(self.current_time.year, self.current_time.month)], total_h_worked, total_h_remaining)
                glog.info("{:<20} {:<15} {:>12} {:>10} {:>12.2f} / {:<.2f}".format(
                    self.cts,
                    self.current_time.strftime('%B %Y'),
                    len(self.get_uncompleted_eboms()),
                    self.monthly_workers[(self.current_time.year, self.current_time.month)],
                    total_h_worked,
                    total_h_remaining
                ))

            is_shift_starting, shift_num, shift_idx = self.is_shift_start(self.current_time)
            if is_shift_starting:
                if __debug__: glog.debug("%s - %s", self.cts, "--------------------------------")
                if __debug__: glog.debug("%s - 🕒 %s - Shift %d start at %s", self.cts, format_date(self.current_time), shift_num, format_time_only(self.current_time))
                if self.reset_workers() == 0:
                    if __debug__: glog.info("%s - ❌ - empty list of workers, we cannot continue", self.cts)
                    simulation_failed = True
                    break
                is_working_time = True
                current_shift_num = shift_num
                if __debug__:
                    worker_ids_in_this_shift = [worker.id for worker in self.current_workers.values() if worker.shift_num_assigned == current_shift_num]
                    glog.debug("%s -    Workers in shift %d: %s", self.cts, current_shift_num, worker_ids_in_this_shift)

            if is_working_time:
                # decrease remaining cost for all active phases
                busy_workers = self.update_remaining_cost_for_active_phases()

                # check if we can close some phase
                self.check_phases_that_can_be_closed(busy_workers, current_shift_num)

                # assign phases to workers in this tick
                worker_id = self.get_first_available_worker_with_max_capacity(not_the_workers=busy_workers, current_shift_num=current_shift_num)
                ebomid, phase = self.get_next_available_phase()
                while worker_id is not None and phase is not None:
                    # assign this task to a worker
                    phase['remaining_cost'] -= self.htick
                    phase['active_worker'] = worker_id
                    worker_on_phase = self.current_workers[worker_id]
                    if not isinstance(worker_on_phase, Worker):
                        glog.error("%s - Error, %s  that can be assigned is not of class Workers", self.cts, worker_id)
                        sys.exit(2)
                    worker_on_phase.current_phase = f"{ebomid}.{phase['name']}"
                    worker_on_phase.current_phase_start = self.current_time
                    worker_on_phase.working_hours += self.htick
                    busy_workers.append(worker_id)
                    if __debug__: glog.debug("%s -    👷 task: %s.%s (remaining: %.2fh) assigned to %s (worked: %.2fh) at %s", self.cts, ebomid, phase['name'], phase['remaining_cost'], phase['active_worker'], worker_on_phase.working_hours, format_time(self.current_time))


                    # get next item
                    worker_id = self.get_first_available_worker_with_max_capacity(not_the_workers=busy_workers, current_shift_num=current_shift_num)
                    ebomid, phase = self.get_next_available_phase()



                # _mme loop_on_all_ebom  ##################################
                # _mme loop_on_all_ebom  for ebomid, phase in self.available_phases.items():
                # _mme loop_on_all_ebom      if phase is None or self.current_time < phase["eng_release_date"]:
                # _mme loop_on_all_ebom          continue
                # _mme loop_on_all_ebom      worker_on_phase = None
                # _mme loop_on_all_ebom      worker_id = phase['active_worker']
                # _mme loop_on_all_ebom      # check if this phase is currently in progress
                # _mme loop_on_all_ebom      if worker_id is not None:
                # _mme loop_on_all_ebom          worker_on_phase = self.current_workers[worker_id]
                # _mme loop_on_all_ebom          if not isinstance(worker_on_phase, Worker):
                # _mme loop_on_all_ebom              glog.error("%s - Error, %s is not of class Workers", self.cts, worker_id)
                # _mme loop_on_all_ebom              sys.exit(2)
                # _mme loop_on_all_ebom          if phase['remaining_cost'] > 0:
                # _mme loop_on_all_ebom              # decrease remaining cost for this phase
                # _mme loop_on_all_ebom              phase['remaining_cost'] -= self.htick
                # _mme loop_on_all_ebom              # increase working time for the worker
                # _mme loop_on_all_ebom              worker_on_phase.working_hours += self.htick
                # _mme loop_on_all_ebom          if __debug__: glog.debug("%s -    🐞 phase: %s.%s (remaining: %.2fh), active_worker:%s (worked: %.2fh), remaining_cost:%.1fs", self.cts, ebomid, phase['name'], phase['remaining_cost'], phase['active_worker'], (self.current_workers[worker_id]).working_hours, phase['remaining_cost'])

                # _mme loop_on_all_ebom      # check if we can close this task
                # _mme loop_on_all_ebom      if worker_id is not None and phase['remaining_cost'] <= 0:
                # _mme loop_on_all_ebom          if __debug__: glog.debug("%s -    🛬 task: %s.%s completed by %s at %s", self.cts, ebomid, phase['name'], worker_id, format_time(self.current_time + conf.TICK))
                # _mme loop_on_all_ebom          # finalize this task
                # _mme loop_on_all_ebom          self.schedule_log_append(ebomid, phase, current_shift_num,
                # _mme loop_on_all_ebom                  self.current_workers[worker_id].current_phase_start, 
                # _mme loop_on_all_ebom                  (self.current_time + timedelta(hours=self.htick)))
                # _mme loop_on_all_ebom          worker_ids_on_closed_phase_in_this_tick.append(worker_id)
                # _mme loop_on_all_ebom          worker_on_phase.current_phase = None
                # _mme loop_on_all_ebom          phase['active_worker'] = None
                # _mme loop_on_all_ebom          # todo: check if this token is closed before the deadline
                # _mme loop_on_all_ebom          # get next phase in this ebom
                # _mme loop_on_all_ebom          ebom = next(e for e in self.eboms if e["id"] == ebomid)
                # _mme loop_on_all_ebom          if len(ebom['phases']) > (phase['id'] + 1):
                # _mme loop_on_all_ebom              phase = ebom['phases'][phase['id'] + 1]
                # _mme loop_on_all_ebom          else:
                # _mme loop_on_all_ebom              phase = None
                # _mme loop_on_all_ebom          self.available_phases[ebomid] = phase  # update available phases

                # _mme loop_on_all_ebom          # _mme finetuning
                # _mme loop_on_all_ebom          # get phase with min id and min deadline
                # _mme loop_on_all_ebom          #    min id == prefer an mbom over workinstruction and a workinstruction over routing
                # _mme loop_on_all_ebom          for p, avphase in self.available_phases.items():
                # _mme loop_on_all_ebom              if avphase != None:
                # _mme loop_on_all_ebom                  if phase == None:
                # _mme loop_on_all_ebom                      phase = avphase
                # _mme loop_on_all_ebom                  else:
                # _mme loop_on_all_ebom                      #if avphase['id'] < phase['id'] and avphase['deadline'] < phase['deadline']:
                # _mme loop_on_all_ebom                      if avphase['deadline'] < phase['deadline']:
                # _mme loop_on_all_ebom                          phase = avphase

                # _mme loop_on_all_ebom      # check if we can assign the task to a worker
                # _mme loop_on_all_ebom      this_task_can_be_assigned = self.task_can_be_assigned(phase)
                # _mme loop_on_all_ebom      if this_task_can_be_assigned == 'ok':
                # _mme loop_on_all_ebom          worker_id = self.get_first_available_worker_with_max_capacity(not_the_workers=worker_ids_on_closed_phase_in_this_tick, current_shift_num=current_shift_num)
                # _mme loop_on_all_ebom          if worker_id is not None:
                # _mme loop_on_all_ebom              # assign this task to a worker
                # _mme loop_on_all_ebom              phase['remaining_cost'] -= self.htick
                # _mme loop_on_all_ebom              phase['active_worker'] = worker_id
                # _mme loop_on_all_ebom              worker_on_phase = self.current_workers[worker_id]
                # _mme loop_on_all_ebom              if not isinstance(worker_on_phase, Worker):
                # _mme loop_on_all_ebom                  glog.error("%s - Error, %s  that can be assigned is not of class Workers", self.cts, worker_id)
                # _mme loop_on_all_ebom                  sys.exit(2)
                # _mme loop_on_all_ebom              worker_on_phase.current_phase = f"{ebomid}.{phase['name']}"
                # _mme loop_on_all_ebom              worker_on_phase.current_phase_start = self.current_time
                # _mme loop_on_all_ebom              worker_on_phase.working_hours += self.htick
                # _mme loop_on_all_ebom              if __debug__: glog.debug("%s -    👷 task: %s.%s (remaining: %.2fh) assigned to %s (worked: %.2fh) at %s", self.cts, ebomid, phase['name'], phase['remaining_cost'], phase['active_worker'], worker_on_phase.working_hours, format_time(self.current_time))
                # _mme loop_on_all_ebom      else:
                # _mme loop_on_all_ebom          if ebomid is not None  and phase is not None:
                # _mme loop_on_all_ebom                  if __debug__: glog.debug("%s -    🐞 task: %s.%s cannot be assigned, reason: %s", self.cts, ebomid, phase['name'], this_task_can_be_assigned)
                # _mme loop_on_all_ebom  ##################################

            is_shift_ending, shift_num = self.is_shift_end(self.current_time)
            if is_shift_ending:
                if __debug__: glog.debug("%s - 🕒 %s - Shift %d end at  %s", self.cts, format_date(self.current_time), shift_num, format_time_only(self.current_time))
                # todo: check worker saturation
                # close shift, reset assignments
                # log all workers, they will be reassigned in the next shift
                for ebomid, phase in self.available_phases.items():
                    if phase is None or self.current_time < phase["eng_release_date"]:
                        continue
                    # check if we should close this task
                    #  todo: refactor with similar code above
                    worker_id = phase['active_worker']
                    if worker_id is not None:
                        self.schedule_log_append(ebomid, phase, current_shift_num,
                                self.current_workers[worker_id].current_phase_start, 
                                (self.current_time + timedelta(hours=self.htick)))
                        if phase['remaining_cost'] <= 0:
                            if __debug__: glog.debug("%s -    🛬 task: %s.%s (remaining: %.2fh) completed by %s at %s", self.cts, ebomid, phase['name'], phase['remaining_cost'], worker_id, format_time(self.current_time + conf.TICK))
                            # finalize this task
                            phase['active_worker'] = None
                            # todo: check if this token is closed before the deadline
                            # get next phase in this ebom
                            ebom = next(e for e in self.eboms if e["id"] == ebomid)
                            if len(ebom['phases']) > (phase['id'] + 1):
                                phase = ebom['phases'][phase['id'] + 1]
                            else:
                                phase = None
                            self.available_phases[ebomid] = phase  # update available phases
                    
                self.reset_eboms_assignement_to_workers()
                is_working_time = False
                current_shift_num = -1
                # # log current status of all eboms,  only for debug
                # if __debug__: 
                #     glog.debug("%s -    🐞 Current EBOMs status at end of shift %d:", self.cts, shift_num)
                #     for ebom in self.eboms:
                #         glog.debug("%s -      🐞 %s:", self.cts, ebom['id'])
                #         for phase in ebom["phases"]:
                #             glog.debug("%s -      🐞    %s: %.1fh remaining, deadline: %s", self.cts, phase['name'], phase['remaining_cost']:.1f, format_date(phase['deadline']))

            if not is_working_time:
                # simulation fail if we pass mbom deadlines without completing them
                if self.current_day > self.get_max_mbom_deadline().date():
                    if len(self.get_uncompleted_mboms()) > 0:
                        if __debug__: glog.info("%s - ❌ %s - Simulation failed: NOT all MBOMs were completed before max mbom deadline %s", self.cts, format_time(self.current_time), format_time(self.get_max_mbom_deadline()))
                        simulation_failed = True

                # we can check if all eboms are completed
                if len(self.get_uncompleted_eboms()) == 0:
                    if __debug__: glog.info("%s - ✅ %s - All EBOMs completed , simulation can end", self.cts, format_time(self.current_time))
                    self.assign_current_time(end_time)

            self.assign_current_time(self.current_time + conf.TICK)

        glog.info("%s - ✅ Simulation ended at %s\n", self.cts, format_time(self.current_time))
        self.simulation_end_time = time.time()
        elapsed_seconds = self.simulation_end_time - self.simulation_start_time
        glog.info("Simulation run time: %d min %d sec", int(elapsed_seconds // 60), int(elapsed_seconds % 60))


    def print_simulation_end(self, phaseType):
        if phaseType == PhaseType.ENGINEERING:
            uncompleted_mboms = self.get_uncompleted_mboms()
            if uncompleted_mboms:
                glog.info("%s - ⚠️ Uncompleted MBOMs: %d", self.cts, len(uncompleted_mboms))
            else:
                glog.info("%s - %s", self.cts, "📦 All MBOMs completed!")
        else:
            glog.info("%s - %s", self.cts, "=========================")
            uncompleted_eboms = self.get_uncompleted_eboms()
            if uncompleted_eboms:
                glog.error("%s - ❌ Simulation failed.", self.cts)
                glog.info("%s - ⚠️ Uncompleted EBOMs: %d", self.cts, len(uncompleted_eboms))
                self.print_remaining_tasks()
            else:
                glog.info("%s - ✅ Simulation completed.", self.cts)
                glog.info("%s - %s", self.cts, "📦 All EBOMs completed!")
            glog.info("%s - 👷 Workers Used: %s", self.cts, self.monthly_workers)
            glog.info("%s - %s", self.cts, "=========================\n")


    def task_can_be_assigned(self, phase):
        if phase is None:
            return "task_none"

        if self.current_time < phase["eng_release_date"]:
            return "ebom_not_released"

        # check if this phase is already assigned to a worker
        if phase['active_worker'] is not None:
            return "task_assigned"

        # check if this phase is already completed
        if phase['remaining_cost'] <= 0:
            return "task_completed"

        if self.current_day > phase["deadline"].date():
            return "task_overdue"

        return "ok"

    def get_max_mbom_deadline(self):
        max_deadline = datetime(1971, 1, 1)
        for ebom in self.eboms:
            if ebom["phases"][0]["deadline"] > max_deadline:
                max_deadline = ebom["phases"][0]["deadline"]
        return max_deadline

    def schedule_log_append(self, ebomid, phase, shift_num, start_time, end_time):
        # log for csv * gantt
        if phase['active_worker'] != None:
            self.schedule_log.append({
                "worker": phase['active_worker'],
                "task": f"{ebomid}.{phase['name']}",
                "shift": shift_num,
                "start": start_time,
                "end": end_time
            })

    def reset_workers(self):
        # get the number of workers for the current month
        shift_month = (self.current_time.year, self.current_time.month)
        num_workers = int(self.monthly_workers.get(shift_month, 1))
        if num_workers == len(self.current_workers):
            # reset current list, do not recreate, for performance reasons
            for wid, worker in enumerate(self.current_workers.values()):
                if isinstance(worker, Worker):
                    worker.current_phase = None
                    worker.current_phase_start = None
                    worker.working_hours = 0
                    #worker.shift_num_assigned = 0
                else:
                    glog.error("%s - worker id %s is not of class Worker", self.cts, wid)
                    sys.exit(2)
        else:
            # re-create the workers list
            shift_nums = list({shift["shift_num"] for shift in self.shifts})
            shifti = 0
            shiftlen = len(shift_nums)
            self.current_workers = {}
            for i in range(num_workers):
                self.current_workers[f"W{i+1}"] = Worker(i+1, shift_nums[shifti % shiftlen])
                shifti = shifti + 1
        return num_workers


    def reset_eboms_assignement_to_workers(self):
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                phase["active_worker"] = None


    def get_first_available_worker_with_max_capacity(self, not_the_workers=None, current_shift_num=-1):
        worker_id = None
        min_working_hours = sys.maxsize
        for wid, worker in self.current_workers.items():
            #if isinstance(worker, Worker):
            if worker.shift_num_assigned != current_shift_num:
                continue
            if worker.current_phase is not None:
                continue
            if worker.id in not_the_workers:
                continue
            if worker.working_hours < min_working_hours:
                worker_id = worker.id
                min_working_hours = worker.working_hours
            if min_working_hours == 0:
                break
        return worker_id



    def get_next_available_phase(self):
        best_ebomid = None
        best_phase = None
        # get phase with min id and min deadline
        for ebomid, phase in self.available_phases.items():
            if phase is None or self.current_time < phase["eng_release_date"]:
                continue
            this_task_can_be_assigned = self.task_can_be_assigned(phase)
            if this_task_can_be_assigned == 'ok':
                if best_ebomid == None:
                    best_ebomid = ebomid
                if best_phase == None:
                    best_phase = phase

                # _mme finetuning
                # get phase with min id and min deadline
                # we take min id because we prefer assigning mbom before workinstruction before routing also if they are available
                if phase['id'] < best_phase['id']:
                    # prefer min id
                    best_ebomid = ebomid
                    best_phase = phase
                elif phase['id'] == best_phase['id'] and phase['deadline'] < best_phase['deadline']:
                    # prefer min deadline
                    best_ebomid = ebomid
                    best_phase = phase
            else:
                if ebomid is not None  and phase is not None:
                        if __debug__: glog.debug("%s -    🐞 task: %s.%s cannot be assigned, reason: %s", self.cts, ebomid, phase['name'], this_task_can_be_assigned)
        return (best_ebomid, best_phase)



    def update_remaining_cost_for_active_phases(self):
        busy_workers = []
        for ebomid, phase in self.available_phases.items():
            if phase is None:
                continue
            worker_on_phase = None
            worker_id = phase['active_worker']
            # check if this phase is currently in progress
            if worker_id is not None:
                worker_on_phase = self.current_workers[worker_id]
                busy_workers.append(worker_id)
                #if not isinstance(worker_on_phase, Worker):
                #    glog.error("%s - Error, %s is not of class Workers", self.cts, worker_id)
                #    sys.exit(2)
                if phase['remaining_cost'] > 0:
                    # decrease remaining cost for this phase
                    phase['remaining_cost'] -= self.htick
                    # increase working time for the worker
                    worker_on_phase.working_hours += self.htick
                if __debug__: glog.debug("%s -    🐞 phase: %s.%s (remaining: %.2fh), active_worker:%s (worked: %.2fh), remaining_cost:%.1fs", self.cts, ebomid, phase['name'], phase['remaining_cost'], phase['active_worker'], (self.current_workers[worker_id]).working_hours, phase['remaining_cost'])
        return busy_workers


    def check_phases_that_can_be_closed(self, busy_workers, current_shift_num):
        for ebomid, phase in self.available_phases.items():
            if phase is None:
                continue
            # check if we can close this task
            worker_id = phase['active_worker']
            if worker_id is not None and phase['remaining_cost'] <= 0:
                if __debug__: glog.debug("%s -    🛬 task: %s.%s completed by %s at %s", self.cts, ebomid, phase['name'], worker_id, format_time(self.current_time + conf.TICK))
                # finalize this task
                self.schedule_log_append(ebomid, phase, current_shift_num,
                        self.current_workers[worker_id].current_phase_start, 
                        (self.current_time + timedelta(hours=self.htick)))
                busy_workers.append(worker_id)
                self.current_workers[worker_id].current_phase = None
                phase['active_worker'] = None
                # todo: check if this token is closed before the deadline
                # get next phase in this ebom
                ebom = next(e for e in self.eboms if e["id"] == ebomid)
                if len(ebom['phases']) > (phase['id'] + 1):
                    phase = ebom['phases'][phase['id'] + 1]
                else:
                    phase = None
                self.available_phases[ebomid] = phase  # update available phases



    def get_total_h_worked_and_remaining(self):
        total_h_worked = 0
        total_h_remaining = 0
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                total_h_remaining += phase["remaining_cost"]
                total_h_worked += (phase['cost'] - phase['remaining_cost'])
        return (total_h_worked, total_h_remaining)

    def get_uncompleted_eboms(self):
        unceboms = set()
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if phase["remaining_cost"] > 0:
                    unceboms.add(ebom["id"])
                    break
        return [ebom for ebom in self.eboms if ebom["id"] in unceboms]

    def get_uncompleted_mboms(self):
        uncmboms = set()
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if phase["name"] == "mbom" and phase["remaining_cost"] > 0:
                    uncmboms.add(ebom["id"])
                    break
        return [ebom for ebom in self.eboms if ebom["id"] in uncmboms]
    
    def get_uncompleted_wi_routing(self):
        uncompleted_wi_r = set()
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if (phase["name"] == "workinstruction" or phase["name"] == "routing") and phase["remaining_cost"] > 0:
                    uncompleted_wi_r.add(ebom["id"])
                    break
        return [ebom for ebom in self.eboms if ebom["id"] in uncompleted_wi_r]


    def is_shift_start(self, curtime):
        for idx, shift in enumerate(self.shifts):
            if shift["start"] == curtime:
                return True, shift["shift_num"], idx
        return False, -1, -1

    def is_shift_end(self, curtime):
        for shift in self.shifts:
            if shift["end"] == curtime:
                return True, shift["shift_num"]
        return False, -1

    def print_remaining_tasks(self):
        if __debug__: glog.debug("%s -     🐞 Remaining tasks:", self.cts)
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if phase["name"] == "mbom" and phase["remaining_cost"] > 0:
                    if __debug__: glog.debug("%s -     🐞    %s.%s : remaining cost: %.1f", self.cts, ebom['id'], phase['name'], phase['remaining_cost'])
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if phase["name"] == "workinstruction" and phase["remaining_cost"] > 0:
                    if __debug__: glog.debug("%s -     🐞    %s.%s : remaining cost: %.1f", self.cts, ebom['id'], phase['name'], phase['remaining_cost'])
        for ebom in self.eboms:
            for phase in ebom["phases"]:
                if phase["name"] == "routing" and phase["remaining_cost"] > 0:
                    if __debug__: glog.debug("%s -     🐞    %s.%s : remaining cost: %.1f", self.cts, ebom['id'], phase['name'], phase['remaining_cost'])





class Worker:
    def __init__(self, wid, shift_num_assigned):
        self.id = f"W{wid}"
        self.current_phase = None
        self.current_phase_start = None
        self.working_hours = 0
        self.shift_num_assigned = shift_num_assigned
