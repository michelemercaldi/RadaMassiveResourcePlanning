import math
from typing import Dict, List, Tuple, NamedTuple
from dataclasses import dataclass

@dataclass
class WorkforceResult:
    """Result of workforce optimization calculation"""
    period: str
    assignable_eboms: int
    available_hours: float
    optimal_workers: int
    actual_saturation: float
    eboms_completed: int
    completion_rate: float
    total_worker_hours: float
    hours_per_worker: float
    efficiency_score: float
    is_feasible: bool
    overflow_eboms: int = 0

class OptimalEfficiencyAlgorithm:
    """
    Optimal Efficiency Algorithm for eBOM workforce allocation
    Target: 90% worker saturation for maximum sustainable productivity
    """
    
    def __init__(self, 
                 target_saturation: float = 0.90,
                 eboms_per_worker_per_hour: float = 2.5,
                 max_workers_per_shift: int = 15,
                 min_workers_per_shift: int = 3,
                 hours_per_shift: float = 7.5):
        """
        Initialize the optimization algorithm
        
        Args:
            target_saturation: Target worker utilization (0.0-1.0)
            eboms_per_worker_per_hour: Productivity rate
            max_workers_per_shift: Maximum workers allowed per shift
            min_workers_per_shift: Minimum workers required per shift
            hours_per_shift: Standard hours per shift
        """
        self.target_saturation = target_saturation
        self.productivity_rate = eboms_per_worker_per_hour
        self.max_workers = max_workers_per_shift
        self.min_workers = min_workers_per_shift
        self.hours_per_shift = hours_per_shift
    
    def calculate_optimal_workers(self, 
                                assignable_eboms: int, 
                                available_hours: float,
                                num_shifts: int) -> WorkforceResult:
        """
        Calculate optimal number of workers for 90% saturation
        
        Args:
            assignable_eboms: Number of eBOMs to process
            available_hours: Total available working hours
            num_shifts: Number of shifts in the period
            
        Returns:
            WorkforceResult with optimization details
        """
        # Calculate total hours needed to complete all eBOMs
        total_hours_needed = assignable_eboms / self.productivity_rate
        
        # Calculate optimal workers for target saturation
        # Formula: workers = total_hours_needed / (available_hours * target_saturation)
        optimal_workers_float = total_hours_needed / (available_hours * self.target_saturation)
        
        # Round to nearest integer and apply constraints
        optimal_workers = max(
            self.min_workers,
            min(self.max_workers, round(optimal_workers_float))
        )
        
        # Calculate actual performance with this workforce
        total_worker_hours = optimal_workers * available_hours
        actual_saturation = min(1.0, total_hours_needed / total_worker_hours)
        
        # Calculate eBOMs that can be completed
        max_eboms_possible = int(total_worker_hours * self.productivity_rate)
        eboms_completed = min(assignable_eboms, max_eboms_possible)
        
        # Calculate completion rate and efficiency metrics
        completion_rate = (eboms_completed / assignable_eboms) * 100
        hours_per_worker = available_hours
        efficiency_score = eboms_completed / total_worker_hours
        
        # Check if solution is feasible
        is_feasible = (optimal_workers >= self.min_workers and 
                      optimal_workers <= self.max_workers and
                      completion_rate >= 95.0)  # 95% completion threshold
        
        overflow_eboms = max(0, assignable_eboms - eboms_completed)
        
        return WorkforceResult(
            period=f"Period",
            assignable_eboms=assignable_eboms,
            available_hours=available_hours,
            optimal_workers=optimal_workers,
            actual_saturation=actual_saturation,
            eboms_completed=eboms_completed,
            completion_rate=completion_rate,
            total_worker_hours=total_worker_hours,
            hours_per_worker=hours_per_worker,
            efficiency_score=efficiency_score,
            is_feasible=is_feasible,
            overflow_eboms=overflow_eboms
        )
    
    def optimize_batch(self, data: Dict[Tuple[int, int], Dict]) -> List[WorkforceResult]:
        """
        Optimize workforce for multiple periods
        
        Args:
            data: Dictionary with (year, month) keys and workforce data
            
        Returns:
            List of WorkforceResult objects
        """
        results = []
        
        for (year, month), period_data in data.items():
            period_str = f"{year}-{month:02d}"
            
            result = self.calculate_optimal_workers(
                assignable_eboms=period_data['assignable_eboms'],
                available_hours=period_data['available_hours'],
                num_shifts=period_data['num_of_shifts']
            )
            result.period = period_str
            results.append(result)
        
        return results
    
    def print_optimization_summary(self, results: List[WorkforceResult]):
        """Print a formatted summary of optimization results"""
        print("="*80)
        print("OPTIMAL EFFICIENCY WORKFORCE OPTIMIZATION RESULTS")
        print(f"Target Saturation: {self.target_saturation*100:.1f}%")
        print(f"Productivity Rate: {self.productivity_rate} eBOMs/worker/hour")
        print("="*80)
        
        print(f"{'Period':<10} {'eBOMs':<8} {'Workers':<8} {'Saturation':<12} {'Completion':<12} {'Feasible':<10}")
        print("-"*70)
        
        for result in results:
            feasible_str = "✓" if result.is_feasible else "✗"
            print(f"{result.period:<10} {result.assignable_eboms:<8} {result.optimal_workers:<8} "
                  f"{result.actual_saturation*100:>8.1f}% {result.completion_rate:>8.1f}% {feasible_str:>8}")
    
    def adjust_for_infeasible_periods(self, results: List[WorkforceResult]) -> List[WorkforceResult]:
        """
        Adjust workforce allocation for periods that are not feasible
        Implements overflow handling strategies
        """
        adjusted_results = []
        
        for result in results:
            if not result.is_feasible and result.overflow_eboms > 0:
                # Strategy 1: Increase workers to maximum allowed
                if result.optimal_workers < self.max_workers:
                    max_workers_result = self.calculate_optimal_workers(
                        result.assignable_eboms,
                        result.available_hours,
                        0  # num_shifts not used in calculation
                    )
                    # Force maximum workers
                    max_workers_result.optimal_workers = self.max_workers
                    max_workers_result.total_worker_hours = self.max_workers * result.available_hours
                    max_workers_result.actual_saturation = min(1.0, 
                        (result.assignable_eboms / self.productivity_rate) / max_workers_result.total_worker_hours)
                    
                    max_eboms_possible = int(max_workers_result.total_worker_hours * self.productivity_rate)
                    max_workers_result.eboms_completed = min(result.assignable_eboms, max_eboms_possible)
                    max_workers_result.completion_rate = (max_workers_result.eboms_completed / result.assignable_eboms) * 100
                    max_workers_result.overflow_eboms = max(0, result.assignable_eboms - max_workers_result.eboms_completed)
                    max_workers_result.is_feasible = max_workers_result.completion_rate >= 95.0
                    
                    adjusted_results.append(max_workers_result)
                else:
                    adjusted_results.append(result)
            else:
                adjusted_results.append(result)
        
        return adjusted_results

# Example usage and testing
if __name__ == "__main__":
    # Sample data from your dataset
    sample_data = {
        (2019, 9): {'num_of_shifts': 42, 'available_hours': 315.0, 'assignable_eboms': 87},
        (2019, 10): {'num_of_shifts': 46, 'available_hours': 345.0, 'assignable_eboms': 93},
        (2021, 12): {'num_of_shifts': 46, 'available_hours': 345.0, 'assignable_eboms': 522},
        (2022, 1): {'num_of_shifts': 42, 'available_hours': 315.0, 'assignable_eboms': 1575},
        (2022, 6): {'num_of_shifts': 44, 'available_hours': 330.0, 'assignable_eboms': 18843},
        (2023, 12): {'num_of_shifts': 42, 'available_hours': 315.0, 'assignable_eboms': 38502},
        (2024, 12): {'num_of_shifts': 44, 'available_hours': 330.0, 'assignable_eboms': 38688},
    }
    
    # Initialize algorithm
    optimizer = OptimalEfficiencyAlgorithm(
        target_saturation=0.90,
        eboms_per_worker_per_hour=2.5,
        max_workers_per_shift=15,
        min_workers_per_shift=3
    )
    
    # Run optimization
    results = optimizer.optimize_batch(sample_data)
    
    # Print results
    optimizer.print_optimization_summary(results)
    
    # Detailed analysis for high-volume periods
    print("\n" + "="*50)
    print("DETAILED ANALYSIS FOR HIGH-VOLUME PERIODS")
    print("="*50)
    
    for result in results:
        if result.assignable_eboms > 10000:  # High-volume periods
            print(f"\nPeriod: {result.period}")
            print(f"  eBOMs to Process: {result.assignable_eboms:,}")
            print(f"  Optimal Workers: {result.optimal_workers}")
            print(f"  Worker Saturation: {result.actual_saturation*100:.1f}%")
            print(f"  eBOMs Completed: {result.eboms_completed:,}")
            print(f"  Completion Rate: {result.completion_rate:.1f}%")
            print(f"  Total Worker Hours: {result.total_worker_hours:.0f}")
            print(f"  Efficiency: {result.efficiency_score:.2f} eBOMs/hour")
            print(f"  Feasible: {'Yes' if result.is_feasible else 'No'}")
            if result.overflow_eboms > 0:
                print(f"  Overflow eBOMs: {result.overflow_eboms:,}")
    
    # Test adjustment for infeasible periods
    adjusted_results = optimizer.adjust_for_infeasible_periods(results)
    
    print("\n" + "="*50)
    print("ADJUSTED RESULTS FOR INFEASIBLE PERIODS")
    print("="*50)
    
    for original, adjusted in zip(results, adjusted_results):
        if original.optimal_workers != adjusted.optimal_workers:
            print(f"\nPeriod: {original.period}")
            print(f"  Original Workers: {original.optimal_workers} -> Adjusted Workers: {adjusted.optimal_workers}")
            print(f"  Original Completion: {original.completion_rate:.1f}% -> Adjusted: {adjusted.completion_rate:.1f}%")
            print(f"  Original Saturation: {original.actual_saturation*100:.1f}% -> Adjusted: {adjusted.actual_saturation*100:.1f}%")