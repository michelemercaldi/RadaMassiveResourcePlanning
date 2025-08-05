import math
from typing import List, Tuple, Set

def guess_parallel_workers(num_of_workers_and_simulation_result: List[Tuple[int, bool]], 
                          num_simulation_attempts: int,
                          parallel_capacity: int = 4) -> List[int]:
    """
    Algorithm to guess multiple worker counts for parallel simulation testing.
    
    Args:
        num_of_workers_and_simulation_result: List of tuples (int: num_workers, bool: failed)
        num_simulation_attempts: Maximum total attempts allowed (budget)
        parallel_capacity: Number of simulations to run in parallel
    
    Returns:
        List[int]: List of worker counts to test in parallel (length <= parallel_capacity)
    """
    attempts_used = len(num_of_workers_and_simulation_result)
    remaining_attempts = num_simulation_attempts - attempts_used
    
    # Don't exceed remaining budget or parallel capacity
    max_tests = min(parallel_capacity, remaining_attempts)
    
    if max_tests <= 0:
        return []
    
    # First batch - spread out exponentially to map the space
    if not num_of_workers_and_simulation_result:
        return generate_initial_parallel_batch(max_tests, num_simulation_attempts)
    
    # Analyze existing results
    results = num_of_workers_and_simulation_result
    tested_workers = set(r[0] for r in results)
    failed_workers = [w for w, failed in results if failed]
    successful_workers = [w for w, failed in results if not failed]
    
    # Generate candidates based on current knowledge
    candidates = []
    
    if successful_workers and failed_workers:
        # We have both - focus on optimization
        candidates = generate_optimization_batch(
            failed_workers, successful_workers, tested_workers, max_tests, remaining_attempts
        )
    elif successful_workers:
        # Only successes - search for minimum
        candidates = generate_minimization_batch(
            successful_workers, tested_workers, max_tests, remaining_attempts
        )
    else:
        # Only failures - search for working solution
        candidates = generate_exploration_batch(
            failed_workers, tested_workers, max_tests, remaining_attempts
        )
    
    # Remove already tested values and limit to max_tests
    candidates = [c for c in candidates if c not in tested_workers and c > 0]
    return candidates[:max_tests]


def generate_initial_parallel_batch(max_tests: int, total_budget: int) -> List[int]:
    """Generate initial batch using exponential spacing to map the solution space."""
    if max_tests == 1:
        return [4]  # Single safe guess
    
    # Strategy depends on total budget
    if total_budget <= 8:
        # Limited budget - be more aggressive
        base_values = [2, 8, 16, 32, 64]
    else:
        # Generous budget - more thorough exploration
        base_values = [1, 4, 12, 24, 48, 96]
    
    # Take first max_tests values
    return base_values[:max_tests]


def generate_optimization_batch(failed_workers: List[int], 
                              successful_workers: List[int],
                              tested_workers: Set[int],
                              max_tests: int,
                              remaining_attempts: int) -> List[int]:
    """Generate batch when we have both failures and successes - focus on finding optimum."""
    max_failure = max(failed_workers)
    min_success = min(successful_workers)
    
    candidates = []
    
    if max_failure < min_success:
        # Clear gap between failures and successes - search the gap
        gap_start = max_failure + 1
        gap_end = min_success - 1
        
        if gap_end >= gap_start:
            # Fill the gap intelligently
            if gap_end - gap_start + 1 <= max_tests:
                # Gap is small enough to test everything
                candidates = list(range(gap_start, gap_end + 1))
            else:
                # Gap is large - use strategic sampling
                candidates = sample_range_strategically(gap_start, gap_end, max_tests)
        else:
            # Adjacent values - we found the boundary, try to optimize around it
            candidates = generate_boundary_refinement(max_failure, min_success, max_tests)
    else:
        # Overlapping results - complex optimization needed
        candidates = generate_complex_optimization(
            failed_workers, successful_workers, max_tests
        )
    
    return candidates


def generate_minimization_batch(successful_workers: List[int],
                               tested_workers: Set[int],
                               max_tests: int,
                               remaining_attempts: int) -> List[int]:
    """Generate batch when we only have successes - search for minimum."""
    min_success = min(successful_workers)
    candidates = []
    
    # Binary search approach downward
    if remaining_attempts >= 6:
        # Enough budget for thorough search
        search_points = [
            max(1, min_success // 2),
            max(1, min_success // 4),
            max(1, min_success - 1),
            max(1, min_success - 2)
        ]
    else:
        # Limited budget - be more focused
        search_points = [
            max(1, min_success // 2),
            max(1, min_success - 1)
        ]
    
    candidates = list(dict.fromkeys(search_points))  # Remove duplicates while preserving order
    return candidates


def generate_exploration_batch(failed_workers: List[int],
                             tested_workers: Set[int],
                             max_tests: int,
                             remaining_attempts: int) -> List[int]:
    """Generate batch when we only have failures - search for working solution."""
    max_failure = max(failed_workers)
    
    if remaining_attempts <= 4:
        # Very limited budget - make aggressive jumps
        multipliers = [3, 5, 8]
    else:
        # More budget available - systematic exploration
        multipliers = [1.5, 2, 3, 4]
    
    candidates = [int(max_failure * m) for m in multipliers]
    return candidates


def sample_range_strategically(start: int, end: int, max_samples: int) -> List[int]:
    """Sample a range strategically for parallel testing."""
    if max_samples >= end - start + 1:
        return list(range(start, end + 1))
    
    if max_samples == 1:
        return [(start + end) // 2]
    
    if max_samples == 2:
        return [start + (end - start) // 3, start + 2 * (end - start) // 3]
    
    # For more samples, use even distribution
    step = (end - start) / (max_samples - 1)
    return [int(start + i * step) for i in range(max_samples)]


def generate_boundary_refinement(max_failure: int, min_success: int, max_tests: int) -> List[int]:
    """Generate candidates when we're at the boundary between failure and success."""
    candidates = []
    
    # Try values just below the minimum success
    for i in range(1, max_tests + 1):
        candidate = max(1, min_success - i)
        if candidate > max_failure:  # Don't go below known failures
            candidates.append(candidate)
    
    return candidates


def generate_complex_optimization(failed_workers: List[int],
                                successful_workers: List[int],
                                max_tests: int) -> List[int]:
    """Handle complex cases where failures and successes overlap."""
    min_success = min(successful_workers)
    candidates = []
    
    # Focus around the minimum successful value
    for offset in range(1, max_tests + 1):
        candidate = max(1, min_success - offset)
        candidates.append(candidate)
    
    return candidates


# Enhanced version with adaptive parallel strategies
def guess_parallel_workers_adaptive(num_of_workers_and_simulation_result: List[Tuple[int, bool]], 
                                   num_simulation_attempts: int,
                                   parallel_capacity: int = 4) -> List[int]:
    """
    Adaptive parallel algorithm that adjusts strategy based on progress and budget.
    """
    attempts_used = len(num_of_workers_and_simulation_result)
    remaining_attempts = num_simulation_attempts - attempts_used
    budget_ratio = remaining_attempts / num_simulation_attempts
    
    max_tests = min(parallel_capacity, remaining_attempts)
    
    if max_tests <= 0:
        return []
    
    # Adjust parallel capacity based on budget
    if budget_ratio < 0.3:
        # Low budget - reduce parallelism to focus efforts
        max_tests = min(max_tests, 2)
    elif budget_ratio < 0.6:
        # Medium budget - moderate parallelism
        max_tests = min(max_tests, 3)
    
    # Use the main algorithm
    return guess_parallel_workers(
        num_of_workers_and_simulation_result, 
        num_simulation_attempts, 
        max_tests
    )


# Utility function for analyzing parallel results
def analyze_parallel_results(results: List[Tuple[int, bool]]) -> dict:
    """Analyze results to provide insights about the search progress."""
    if not results:
        return {"status": "No results yet"}
    
    failed_workers = [w for w, failed in results if failed]
    successful_workers = [w for w, failed in results if not failed]
    
    analysis = {
        "total_tests": len(results),
        "failures": len(failed_workers),
        "successes": len(successful_workers),
    }
    
    if successful_workers:
        analysis["min_successful"] = min(successful_workers)
        analysis["best_solution"] = min(successful_workers)
        
        if failed_workers:
            max_failure = max(failed_workers)
            min_success = min(successful_workers)
            
            if max_failure < min_success:
                gap = min_success - max_failure - 1
                analysis["gap_size"] = gap
                analysis["status"] = f"Found boundary with {gap} untested values"
                analysis["confidence"] = "High" if gap <= 2 else "Medium"
            else:
                analysis["status"] = "Complex boundary - overlapping results"
                analysis["confidence"] = "Low"
        else:
            analysis["status"] = "Only successes found - searching for minimum"
            analysis["confidence"] = "Medium"
    else:
        analysis["max_failure"] = max(failed_workers)
        analysis["status"] = "No successful configuration found yet"
        analysis["confidence"] = "Low"
    
    return analysis


# Example usage and testing
if __name__ == "__main__":
    def simulate_parallel_testing():
        """Simulate parallel testing process"""
        actual_minimum = 12
        total_budget = 15
        parallel_capacity = 3
        
        results = []
        round_num = 0
        
        print("Parallel Simulation Testing Process:")
        print(f"Actual minimum: {actual_minimum} workers")
        print(f"Total budget: {total_budget} attempts")
        print(f"Parallel capacity: {parallel_capacity}")
        print("=" * 60)
        
        while len(results) < total_budget:
            round_num += 1
            remaining = total_budget - len(results)
            
            # Get next batch to test
            next_batch = guess_parallel_workers(results, total_budget, parallel_capacity)
            
            if not next_batch:
                break
                
            print(f"\nRound {round_num} - Testing: {next_batch}")
            print(f"Budget remaining: {remaining}")
            
            # Simulate parallel execution
            round_results = []
            for workers in next_batch:
                failed = workers < actual_minimum
                status = "FAIL" if failed else "PASS"
                round_results.append((workers, failed))
                print(f"  {workers} workers -> {status}")
            
            results.extend(round_results)
            
            # Analyze progress
            analysis = analyze_parallel_results(results)
            print(f"Progress: {analysis['status']}")
            
            # Check if we found a good solution
            if 'best_solution' in analysis:
                efficiency = (actual_minimum / analysis['best_solution']) * 100
                print(f"Current best: {analysis['best_solution']} workers ({efficiency:.1f}% efficient)")
                
                if analysis.get('confidence') == 'High':
                    print("High confidence in result - could stop here")
        
        print(f"\n{'='*60}")
        print("FINAL RESULTS:")
        final_analysis = analyze_parallel_results(results)
        print(f"Total attempts used: {len(results)}/{total_budget}")
        
        if 'best_solution' in final_analysis:
            best = final_analysis['best_solution']
            efficiency = (actual_minimum / best) * 100
            print(f"Best solution: {best} workers")
            print(f"Efficiency: {efficiency:.1f}%")
            print(f"Confidence: {final_analysis.get('confidence', 'Unknown')}")
        else:
            print("No successful solution found")
    
    simulate_parallel_testing()
    