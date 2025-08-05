import datetime
import math
import calendar

class WorkerPlanner:
    def __init__(self, shifts, saturation_percentage=0.9):
        """
        Initializes the WorkerPlanner with shift configurations and saturation percentage.

        Args:
            shifts (list): A list of dictionaries, each representing a shift type with keys:
                           'shift_num', 'start' (datetime), 'end' (datetime), 'duration' (float).
                           Assumes all shifts have the same duration for a worker's daily capacity.
                           Weekends are assumed to be non-working days.
            saturation_percentage (float): The minimum percentage a worker must be saturated (e.g., 0.9 for 90%).
        """
        if not shifts:
            raise ValueError("No shifts provided. Cannot initialize WorkerPlanner.")
        
        self.shifts = shifts
        self.saturation_percentage = saturation_percentage
        
        # Calculate effective daily worker capacity once during initialization
        self.daily_worker_hours = self.shifts[0]['duration']
        self.effective_daily_worker_capacity = self.daily_worker_hours * self.saturation_percentage

    def plan_workers(self, eboms):
        """
        Calculates the minimal number of workers required for each month to complete
        all eboms within their specified date ranges, considering worker saturation.

        Args:
            eboms (list): A list of dictionaries, each representing an EBOM with keys:
                          'id', 'eng_release_date' (datetime), 'production_date' (datetime),
                          'total_cost' (int/float).

        Returns:
            dict: A dictionary where keys are (year, month) tuples and values are the
                  minimal number of workers required for that month.
        """

        if not eboms:
            return {}

        # 2. Determine Planning Horizon
        earliest_eng_release_date = min(ebom['eng_release_date'] for ebom in eboms).date()
        latest_production_date = max(ebom['production_date'] for ebom in eboms).date()

        # Initialize monthly workload
        monthly_workload = {}
        current_month_start = datetime.date(earliest_eng_release_date.year, earliest_eng_release_date.month, 1)
        
        # Iterate month by month to initialize the workload dictionary
        while current_month_start <= latest_production_date:
            monthly_workload[(current_month_start.year, current_month_start.month)] = 0.0
            # Move to the first day of the next month
            if current_month_start.month == 12:
                current_month_start = datetime.date(current_month_start.year + 1, 1, 1)
            else:
                current_month_start = datetime.date(current_month_start.year, current_month_start.month + 1, 1)

        # 3. Calculate and Distribute Ebom Workload
        for ebom in eboms:
            ebom_start_date = ebom['eng_release_date'].date()
            ebom_end_date = ebom['production_date'].date()
            total_cost = ebom['total_cost']

            # Calculate total available working days for this ebom's span (weekdays only)
            num_working_days_in_ebom_span = 0
            current_date_for_span = ebom_start_date
            while current_date_for_span <= ebom_end_date:
                if current_date_for_span.weekday() < 5:  # Monday (0) to Friday (4)
                    num_working_days_in_ebom_span += 1
                current_date_for_span += datetime.timedelta(days=1)

            if num_working_days_in_ebom_span == 0:
                print(f"Warning: Ebom {ebom['id']} has no working days in its span. Skipping.")
                continue

            daily_work_per_ebom = total_cost / num_working_days_in_ebom_span

            # Distribute the daily work across the months
            current_date_for_distribution = ebom_start_date
            while current_date_for_distribution <= ebom_end_date:
                if current_date_for_distribution.weekday() < 5:  # Only distribute on weekdays
                    month_key = (current_date_for_distribution.year, current_date_for_distribution.month)
                    if month_key in monthly_workload:
                        monthly_workload[month_key] += daily_work_per_ebom
                current_date_for_distribution += datetime.timedelta(days=1)

        # 4. Calculate Monthly Worker Requirements
        monthly_worker_requirements = {}
        for year, month in sorted(monthly_workload.keys()):
            # Calculate number of working days (weekdays) in this specific month
            num_days_in_month = calendar.monthrange(year, month)[1]
            working_days_in_month = 0
            for day in range(1, num_days_in_month + 1):
                date_obj = datetime.date(year, month, day)
                if date_obj.weekday() < 5:  # Monday (0) to Friday (4)
                    working_days_in_month += 1

            monthly_effective_worker_capacity_per_worker = working_days_in_month * self.effective_daily_worker_capacity

            if monthly_effective_worker_capacity_per_worker > 0:
                required_workers = math.ceil(monthly_workload[(year, month)] / monthly_effective_worker_capacity_per_worker)
            else:
                # If no capacity, and there's workload, it's impossible.
                # If no workload, then 0 workers.
                required_workers = 0 if monthly_workload[(year, month)] == 0 else float('inf')

            monthly_worker_requirements[(year, month)] = required_workers

        return monthly_worker_requirements

# # Example Usage (using your provided data structure)
# # Sample EBOMs
# sample_eboms = [
#     {
#         'id': 'DT00000740371__1',
#         'eng_release_date': datetime.datetime(2022, 4, 22, 0, 0),
#         'production_date': datetime.datetime(2025, 4, 23, 0, 0),
#         'total_cost': 43,
#         'phases': [] # Ignored for this problem
#     },
#     {
#         'id': 'DT00000740372__2',
#         'eng_release_date': datetime.datetime(2023, 1, 10, 0, 0),
#         'production_date': datetime.datetime(2024, 6, 15, 0, 0),
#         'total_cost': 120,
#         'phases': []
#     },
#     {
#         'id': 'DT00000740373__3',
#         'eng_release_date': datetime.datetime(2024, 5, 1, 0, 0),
#         'production_date': datetime.datetime(2024, 7, 31, 0, 0),
#         'total_cost': 80,
#         'phases': []
#     }
# ]

# # Sample Shifts
# sample_shifts = [
#     {'shift_num': 1, 'start': datetime.datetime(2019, 9, 2, 6, 0), 'end': datetime.datetime(2019, 9, 2, 13, 30), 'duration': 7.5}
# ]

# # Initialize the planner
# planner = WorkerPlanner(shifts=sample_shifts, saturation_percentage=0.9)

# # Calculate monthly worker requirements
# monthly_workers = planner.plan_workers(eboms=sample_eboms)

# # Print the results
# for (year, month), workers in monthly_workers.items():
#     print(f"Month: {year}-{month:02d}, Required Workers: {workers}")