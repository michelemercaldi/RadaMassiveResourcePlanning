from dateutil.parser import parse
from datetime import datetime, timedelta
import math
from collections import defaultdict
from pmas_configuration import PmasConfiguration
from pmas_util import PmasLoggerSingleton, format_date, format_time
import sys
from collections import OrderedDict
from datetime import date
import calendar


conf: PmasConfiguration = None
glog: PmasLoggerSingleton = None


class PmasFactory:
    def __init__(self, pconf):
        global conf, glog
        glog = PmasLoggerSingleton.get_logger()
        conf = pconf

    def get_month_list(self, start_date, elapsed_days):
        """
        Returns a list of (year, month) tuples covering the period from start_date for elapsed_days.
        """
        months = []
        current = start_date.replace(day=1)
        end_date = start_date + timedelta(days=elapsed_days)
        while current < end_date:
            months.append((current.year, current.month))
            # Move to the first day of the next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return months


    def assign_monthly_workers(self, months, mbom_deadline, mbom_workers, production_workers):
        monthly_workers = {}
        for (year, month) in months:
            # first and last day of this month
            month_start = datetime(year, month, 1)
            if month == 12:
                next_month = datetime(year + 1, 1, 1)
            else:
                next_month = datetime(year, month + 1, 1)
            month_end = next_month - timedelta(days=1)

            if month_start <= mbom_deadline:
                monthly_workers[(year, month)] = int(math.ceil(mbom_workers))
            else:
                monthly_workers[(year, month)] = int(math.ceil(production_workers))
        return monthly_workers


    def assign_monthly_workers_from_pulp_months(self, months):
        monthly_workers = {}
        for m in sorted(months.keys()):
            monthly_workers[m] = months[m]['workers']
        return monthly_workers


    def generate_shifts(self, conf, start_date, days):
        shifts = []
        for day in range(days):
            day_base = start_date + timedelta(days=day)
            # exclude saturday and sunday
            if day_base.weekday() >= 5:
                continue
            for shift_num, shift_conf in conf.SHIFT_CONFIG.items():
                t = datetime.strptime(shift_conf["start"], "%H:%M")
                shift_start = day_base.replace(hour=t.hour, minute=t.minute)
                shift_end = shift_start + timedelta(hours=shift_conf["duration"])
                shifts.append({
                    "shift_num": shift_num,
                    "start": shift_start,
                    "end": shift_end,
                    "duration": shift_conf["duration"]
                })
        return shifts

    def log_shifts(self, shifts):
        if __debug__:
            glog.debug("\n🛠️ Shifts Generated:")
            for i, shift in enumerate(shifts):
                msg = f"  📆 {format_time(shift['start'])} - Shift {shift['shift_num']} (Duration: {shift['duration']}h)"
                if i < 3: glog.debug(msg)
                elif i == 3: 
                    #glog.debug("  📆  ...")
                    glog.debug(msg)
                elif i >= len(shifts) - 3: glog.debug(msg)
                else: glog.debug(msg)
        else:
            pass
                


    def aggregate_db_eboms_by_cassa(self, eboms):
        aggregated_eboms = []
        last_partnbr = 'dummy'
        last_ebom_added = None
        # we assume eboms ordered by partnbr !!!
        for ebom in eboms:
            partnbr = ebom['PARTNBR']
            production_date = conf.casse_production_dates[ebom['VEICOLOCASSA']]
            if partnbr == last_partnbr:
                # ebom added already, update the production date if needed
                if last_ebom_added['PRODUCTION_DATE'] < production_date:
                    last_ebom_added['PRODUCTION_DATE'] = production_date
            else:
                # new ebom
                ebom['PRODUCTION_DATE'] = production_date
                aggregated_eboms.append(ebom)
                last_partnbr = partnbr
                last_ebom_added = ebom
        return aggregated_eboms


        

    def generate_eboms(self, ebomsWithDates):
        """Generates EBOMs from input data with real part numbers and dates.    
        Args:
            ebomsWithDates: List of dicts with 'PARTNBR' and 'DATARILASCIO' strings
                Example: [{'IDANAGRAFICA': 12010, 'PARTNBR': 'DT00000915044', 'REV': 'A', 'DATARILASCIO': datetime.datetime(2019, 9, 2, 0, 0)}, ...]
        Returns:
            List of EBOM dicts with proper phase timelines
        """
        eboms = []

        for item in ebomsWithDates:
            eng_release_date = item['DATARILASCIO']
            if eng_release_date is None:
                glog.error(f"Missing 'DATARILASCIO' for PARTNBR {item.get('PARTNBR', 'UNKNOWN')}")
                sys.exit(1)
            production_date = item['PRODUCTION_DATE']
            if production_date is None:
                glog.error(f"Missing 'PRODUCTION_DATE' for PARTNBR {item.get('PARTNBR', 'UNKNOWN')}")
                sys.exit(1)

            for e in range(conf.multiplier_ebom_to_dtr):
                # Calculate phase deadlines
                mbom_deadline = eng_release_date + timedelta(days=conf.deadline_offset_mbom)
                wi_deadline = production_date + timedelta(days=conf.deadline_offset_workinstruction)  # negative deadline_offset_workinstruction
                routing_deadline = production_date + timedelta(days=conf.deadline_offset_routing)  # negative deadline_offset_routing

                eboms.append({
                    "id": item['PARTNBR'] + '__' + str(e+1),  # Use actual part number from input
                    "eng_release_date": eng_release_date,
                    "production_date": production_date,
                    "total_cost": conf.hourly_cost_mbom + conf.hourly_cost_workinstruction + conf.hourly_cost_routing,
                    "phases": [
                        {
                            "id": 0,
                            "name": "mbom",
                            "deadline": mbom_deadline,
                            "cost": conf.hourly_cost_mbom,
                            "remaining_cost": conf.hourly_cost_mbom,
                            "eng_release_date": eng_release_date,
                            "active_worker": None
                        },
                        {
                            "id": 1,
                            "name": "workinstruction",
                            "deadline": wi_deadline,
                            "cost": conf.hourly_cost_workinstruction,
                            "remaining_cost": conf.hourly_cost_workinstruction,
                            "eng_release_date": eng_release_date,
                            "active_worker": None
                        },
                        {
                            "id": 2,
                            "name": "routing",
                            "deadline": routing_deadline,
                            "cost": conf.hourly_cost_routing,
                            "remaining_cost": conf.hourly_cost_routing,
                            "eng_release_date": eng_release_date,
                            "active_worker": None
                        }
                    ]
                })
        conf.NUM_EBOMS = len(eboms)
        return eboms                


    def generate_eboms_fake(self, n):
        eboms = []
        sample_START_DATE = datetime(2024, 5, 1)
        costo_mbom_h = 1
        costo_workinstruction_h = 40
        costo_routing_h = 2
        offset_mbom_days = 10
        offset_workinstruction_days = 20
        offset_routing_days = 5
        for i in range(n):
            # base_start = sample_START_DATE + timedelta(days=random.randint(0, 3))
            base_start = sample_START_DATE + timedelta(days=(i % 4))
            # sample_elapsed_days = random.randint(365, 400)
            sample_elapsed_days = 365 + (i % (400 - 365 + 1))
            mbom_deadline = base_start + timedelta(days=(offset_mbom_days))
            wi_deadline = base_start + timedelta(sample_elapsed_days) - timedelta(days=(offset_workinstruction_days))
            routing_deadline = wi_deadline + timedelta(sample_elapsed_days) - timedelta(days=(offset_routing_days))
            eboms.append({
                "id": f"EBOM{i+1}",
                "eng_release_date": base_start,
                "phases": [
                    {
                        "id": 0,
                        "name": "mbom",
                        "deadline": mbom_deadline,
                        "cost": costo_mbom_h,
                        "remaining_cost": costo_mbom_h,
                        "eng_release_date": base_start,
                        "active_worker": None
                    },
                    {
                        "id": 1,
                        "name": "workinstruction",
                        "deadline": wi_deadline,
                        "cost": costo_workinstruction_h,
                        "remaining_cost": costo_workinstruction_h,
                        "eng_release_date": base_start,
                        "active_worker": None
                    },
                    {
                        "id": 2,
                        "name": "routing",
                        "deadline": routing_deadline,
                        "cost": costo_routing_h,
                        "remaining_cost": costo_routing_h,
                        "eng_release_date": base_start,
                        "active_worker": None
                    }
                ]
            })
        return eboms

    def log_eboms(self, eboms):
        if __debug__:
            glog.debug("\n📋 EBOMs Generated:")
            for ebom in eboms:
                glog.debug("  🏷️ %s  -  eng_release_date: %s - production_date: %s", ebom['id'], format_date(ebom['eng_release_date']), format_date(ebom['production_date']))
                for phase in ebom["phases"]:
                    glog.debug("    - %s (Deadline: %s), Cost: %sh", phase['name'], format_date(phase['deadline']), phase['cost'])
        else:
            pass

    def reset_eboms(self, eboms):
        for ebom in eboms:
            for phase in ebom["phases"]:
                phase["remaining_cost"] = phase["cost"]
                phase["eng_release_date"] = ebom["eng_release_date"]
                phase["active_worker"] = None
        return eboms


    def get_min_eng_release_date(self, eboms):
        """
        Returns the minimum eng_release_date among all EBOMs.
        """
        return min(ebom["eng_release_date"] for ebom in eboms)


    def get_min_cassa_production_date(self, casse_dates):
        # return min(datetime.strptime(date_str, "%Y-%m-%d") for date_str in casse_dates.values())
        return min(casse_dates.values())


    # Function to calculate the number of days in each month covered by shifts
    def calculate_shifts_per_month(self, shifts):
        month_days = {}
        last_month_shift = {}
        last_month = (1900, 1)        
        # we assume an ordered list of shifts
        for shift in shifts:
            start_date = shift["start"]
            month = (start_date.year, start_date.month)
            if last_month == month:
                last_month_shift['num_of_shifts'] += 1
                last_month_shift['available_hours'] += shift['duration']
            else:
                last_month_shift = {"num_of_shifts": 1, 'available_hours': shift['duration']}
                last_month = month
                month_days[month] = last_month_shift
        return month_days

    
    
    def assign_mean_working_days_per_ebom(self, eboms):
        for ebom in eboms:
            start_date = ebom['eng_release_date']
            end_date = ebom['production_date']
            day_diff = (end_date - start_date).days
            total_cost_in_hours = ebom['total_cost']
            ebom['daily_required_hours'] = total_cost_in_hours / day_diff

        
        
    # sum in every month the amount of hours needed by the eboms
    # we know which eboms are active based on eng_release_date and production_date
    # we know the average daily hours needed for every ebom
    def fill_total_working_hours_needed_by_eboms_per_month(self, eboms, months, shifts):
        if not shifts:
            return {}
        first_shift_date = shifts[0]['start']
        last_shift_date = shifts[-1]['end']
        glog.info("analyzing monthly hours needed by EBOMs from %s to %s", format_date(first_shift_date), format_date(last_shift_date))
        for month_key in months:
            months[month_key]['eboms_required_hours'] = 0
        current_date = first_shift_date.date()
        end_date = last_shift_date.date()
        while current_date <= end_date:
            month_key = (current_date.year, current_date.month)
            # _mme glog.info(month_key)
            for ebom in eboms:
                eng_release_date = ebom['eng_release_date'].date()
                production_date = ebom['production_date'].date()
                if current_date >= eng_release_date and current_date <= production_date:
                    months[month_key]['eboms_required_hours'] += ebom['daily_required_hours']
            current_date += timedelta(days=1)
    
    
    def aggregate_underutilized_months(self, months_dict):
        """
        Aggregates underutilized months by merging their eboms_required_hours into the next month.
        Only aggregates if eboms_required_hours < available_hours.
        Works on a dict with (year, month) keys.

        Parameters:
            months_dict (dict): {(year, month): {'num_of_shifts': int, 'available_hours': float, 'eboms_required_hours': float}}

        Returns:
            dict: Aggregated version of the input dict.
        """
        # Sort the months chronologically
        sorted_keys = sorted(months_dict.keys())
        result = OrderedDict()

        i = 0
        while i < len(sorted_keys):
            current_key = sorted_keys[i]
            current_data = months_dict[current_key]

            if current_data['eboms_required_hours'] < current_data['available_hours'] and i + 1 < len(sorted_keys):
                next_key = sorted_keys[i + 1]
                next_data = months_dict[next_key]

                # Merge current into next
                months_dict[next_key] = {
                    'num_of_shifts': max(current_data['num_of_shifts'], next_data['num_of_shifts']),
                    'available_hours': max(current_data['available_hours'], next_data['available_hours']),
                    'eboms_required_hours': current_data['eboms_required_hours'] + next_data['eboms_required_hours']
                }
                # Don't add current month to result
            else:
                result[current_key] = current_data

            i += 1

        # Handle last month if not underutilized
        last_key = sorted_keys[-1]
        if last_key not in result and months_dict[last_key]['eboms_required_hours'] >= months_dict[last_key]['available_hours']:
            result[last_key] = months_dict[last_key]

        return dict(result)


    def ensure_not_zero_workers(self, months):
        for m in months:
            if months[m]['workers'] == 0:
                months[m]['workers'] = 1
            # months[m]['workers'] *= 100   # _mme  fake  assignement

