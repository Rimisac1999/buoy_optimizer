"""
Buoy Optimization Script for ACT_160 Campaign
Optimizes buoy allocation with line-by-line collection and reuse
"""

import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
from typing import Dict, List, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

# ============ CONFIGURATION ============
PLANNING_CSV = "20251008_Data_From_Planning_and_TECH.csv"
BUOYS_CSV = "20251008_Buoys_Config_Table.csv"
OUTPUT_CSV = "buoy_optimization_plan_19lines.csv"

# Target down-thrust range (tonnes)
DOWN_THRUST_MIN = 1.5
DOWN_THRUST_MAX = 3.0

# Cost weights for optimization
COST_BUY_BUOY = 1000.0          # Cost per buoy to purchase (highest priority)
COST_SWITCH_TYPE = 50.0         # Cost to switch buoy type (e.g., Single Big to Tandem)
COST_RECONFIG = 10.0            # Base cost for any reconfiguration
COST_SHACKLE_CHANGE = 2.0       # Cost per shackle added/removed
COST_MODULE_CHANGE = 5.0        # Cost per module added/removed
COST_DIFF_FACTOR = 1.0          # Weight for difficulty factor

# Solver settings
MAX_SOLVE_TIME = 120.0          # seconds (increased for complex problems)
NUM_WORKERS = 8

# ============ DATA STRUCTURES ============

@dataclass
class Operation:
    """Represents a single installation operation"""
    order: int
    flowline: str
    tag: str
    type: str
    sub_w: float  # tonnes
    comp_d: float
    fam: str
    is_head: bool
    line_id: str  # Unique identifier for the flowline/line

@dataclass
class BuoyConfig:
    """Represents a buoy configuration"""
    index: int
    name: str
    config_code: str
    base_upthrust: float
    shackles: int
    modules: int
    final_upthrust: float
    diff_factor: int
    
    def get_type_family(self) -> str:
        """Extract buoy type family (e.g., 'Single Big', 'Tandem Small')"""
        return self.name

# ============ DATA LOADING ============

def load_planning_data(filepath: str) -> pd.DataFrame:
    """Load and parse planning data"""
    df = pd.read_csv(filepath)
    
    # Clean column names
    df.columns = df.columns.str.strip()
    
    # Ensure we have required columns
    required_cols = ['Order', 'Flowline', 'TAG', 'TYPE', 'Sub W', 'Line']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Sort by order
    df = df.sort_values('Order').reset_index(drop=True)
    
    # Identify heads (operations where Sub W is 0 or TYPE is "Head")
    df['Is_Head'] = (df['Sub W'] < 0.1) | (df['TYPE'].str.strip().str.lower() == 'head')
    
    return df

def load_buoy_configs(filepath: str) -> pd.DataFrame:
    """Load and parse buoy configuration table"""
    df = pd.read_csv(filepath)
    
    # Drop rows with missing critical data
    df = df.dropna(subset=['Name', 'BuoyConfig', 'FinalUpThrust'])
    
    # Clean and convert
    df['Name'] = df['Name'].str.strip()
    df['BuoyConfig'] = df['BuoyConfig'].str.strip()
    df['FinalUpThrust'] = pd.to_numeric(df['FinalUpThrust'])
    df['DiffFactor'] = pd.to_numeric(df['DiffFactor'], errors='coerce').fillna(0)
    df['ShackleCNT'] = pd.to_numeric(df['ShackleCNT'], errors='coerce').fillna(0)
    df['ModuleSUB'] = pd.to_numeric(df['ModuleSUB'], errors='coerce').fillna(0)
    df['BaseUpthrust'] = pd.to_numeric(df['BaseUpthrust'], errors='coerce').fillna(0)
    
    # Mark these as single buoy configs
    df['IsSeries'] = False
    df['Buoy1_Name'] = df['Name']
    df['Buoy1_Config'] = df['BuoyConfig']
    df['Buoy2_Name'] = None
    df['Buoy2_Config'] = None
    
    return df.reset_index(drop=True)

def generate_series_combinations(single_buoys_df: pd.DataFrame, ops_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Generate 2-buoy series combinations for high upthrust requirements.
    Series means 2 buoys working together (combined upthrust).
    """
    series_configs = []
    
    # Generate all reasonable pairs (including same buoy twice)
    # Note: We keep this simple to avoid missing feasible configurations
    for i, buoy1 in single_buoys_df.iterrows():
        for j, buoy2 in single_buoys_df.iterrows():
            combined_upthrust = buoy1['FinalUpThrust'] + buoy2['FinalUpThrust']
            
            # Skip if combined upthrust is too high (unrealistic)
            if combined_upthrust > 150:
                continue
            
            # Create series config name
            series_name = f"Series: {buoy1['Name']} + {buoy2['Name']}"
            series_config = f"{buoy1['BuoyConfig']}+{buoy2['BuoyConfig']}"
            
            # Combined properties
            series_configs.append({
                'Name': series_name,
                'BuoyConfig': series_config,
                'BaseUpthrust': buoy1['BaseUpthrust'] + buoy2['BaseUpthrust'],
                'ShackleCNT': buoy1['ShackleCNT'] + buoy2['ShackleCNT'],
                'ModuleSUB': buoy1['ModuleSUB'] + buoy2['ModuleSUB'],
                'FinalUpThrust': combined_upthrust,  # FIXED: Capital T
                'DiffFactor': buoy1['DiffFactor'] + buoy2['DiffFactor'] + 2,  # +2 for series complexity
                'IsSeries': True,
                'Buoy1_Name': buoy1['Name'],
                'Buoy1_Config': buoy1['BuoyConfig'],
                'Buoy2_Name': buoy2['Name'],
                'Buoy2_Config': buoy2['BuoyConfig']
            })
    
    series_df = pd.DataFrame(series_configs)
    
    # Combine with original single buoys
    combined_df = pd.concat([single_buoys_df, series_df], ignore_index=True)
    
    return combined_df

# ============ LINE IDENTIFICATION ============

def identify_lines(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[int]]]:
    """
    Identify lines using the 'Line' column from the data.
    Buoys are collected at the end of each line (last operation or Head).
    """
    df = df.copy()
    
    # Check if Line column exists
    if 'Line' not in df.columns:
        raise ValueError("'Line' column not found in data. Please ensure the CSV has a 'Line' column.")
    
    df['LineID'] = df['Line'].apply(lambda x: f"Line_{int(x):02d}" if pd.notna(x) and x != 0 else "Unknown")
    df['CanCollectBuoys'] = False
    
    lines = {}
    
    # Group by Line number
    for line_num in sorted(df['Line'].unique()):
        if line_num == 0 or pd.isna(line_num):
            continue
            
        line_id = f"Line_{int(line_num):02d}"
        line_data = df[df['Line'] == line_num].sort_values('Order')
        
        # Store indices of operations in this line
        lines[line_id] = line_data.index.tolist()
        
        # Mark the last operation of the line as collection point
        last_idx = line_data.index[-1]
        df.at[last_idx, 'CanCollectBuoys'] = True
    
    return df, lines

# ============ FEASIBILITY CHECK ============

def get_feasible_configs(sub_w: float, buoy_df: pd.DataFrame) -> List[int]:
    """
    Get list of feasible buoy configurations for given submerged weight.
    Feasible if: DOWN_THRUST_MIN <= (Sub W - Final Upthrust) <= DOWN_THRUST_MAX
    """
    feasible = buoy_df[
        ((sub_w - buoy_df['FinalUpThrust']) >= DOWN_THRUST_MIN - 0.01) &
        ((sub_w - buoy_df['FinalUpThrust']) <= DOWN_THRUST_MAX + 0.01)
    ].index.tolist()
    
    return feasible

# ============ COST CALCULATIONS ============

def reconfig_cost(buoy_a: pd.Series, buoy_b: pd.Series) -> float:
    """Calculate cost to reconfigure from buoy A to buoy B"""
    cost = 0.0
    
    # Base reconfiguration cost
    cost += COST_RECONFIG
    
    # Type change (different buoy families)
    if buoy_a['Name'] != buoy_b['Name']:
        cost += COST_SWITCH_TYPE
    
    # Shackle changes
    shackle_diff = abs(buoy_a['ShackleCNT'] - buoy_b['ShackleCNT'])
    cost += COST_SHACKLE_CHANGE * shackle_diff
    
    # Module changes
    module_diff = abs(buoy_a['ModuleSUB'] - buoy_b['ModuleSUB'])
    cost += COST_MODULE_CHANGE * module_diff
    
    # Difficulty factor
    cost += COST_DIFF_FACTOR * (buoy_a['DiffFactor'] + buoy_b['DiffFactor'])
    
    return cost

# ============ OPTIMIZATION ============

def optimize_buoy_allocation(ops_df: pd.DataFrame, buoy_df: pd.DataFrame, 
                             lines: Dict[str, List[int]]) -> pd.DataFrame:
    """
    Optimize buoy allocation using CP-SAT with line-based collection.
    Key insight: buoys are released after each line is complete.
    """
    
    print("\n=== Starting Optimization ===")
    print(f"Operations to allocate: {len(ops_df)}")
    print(f"Available buoy configs: {len(buoy_df)}")
    print(f"  - Single configs: {len(buoy_df[~buoy_df['IsSeries']])}")
    print(f"  - Series configs: {len(buoy_df[buoy_df['IsSeries']])}")
    print(f"Number of lines: {len(lines)}")
    
    # Calculate search space size
    total_feasible = 0
    for i in range(len(ops_df[~ops_df['Is_Head']])):
        sub_w = ops_df[~ops_df['Is_Head']].iloc[i]['Sub W']
        feas_count = len(get_feasible_configs(sub_w, buoy_df))
        total_feasible += feas_count
    print(f"Search space: ~{total_feasible} feasible config assignments")
    
    # Filter out head operations (they don't need buoys) but keep track of original Order
    ops_df_full = ops_df.copy()  # Keep full dataframe for reference
    ops_df = ops_df[~ops_df['Is_Head']].copy().reset_index(drop=True)
    ops_df['OriginalIndex'] = ops_df.index  # Track new index
    
    model = cp_model.CpModel()
    
    N = len(ops_df)  # Number of operations
    M = len(buoy_df)  # Number of buoy configs
    
    # Check feasibility for each operation
    feasible = {}
    for i in range(N):
        sub_w = ops_df.at[i, 'Sub W']
        feasible[i] = get_feasible_configs(sub_w, buoy_df)
        
        if not feasible[i]:
            print(f"\nERROR: No feasible buoy config for operation {i}")
            print(f"  Order: {ops_df.at[i, 'Order']}")
            print(f"  TAG: {ops_df.at[i, 'TAG']}")
            print(f"  TYPE: {ops_df.at[i, 'TYPE']}")
            print(f"  Sub W: {sub_w:.2f} tonnes")
            print(f"  Required upthrust range: {sub_w - DOWN_THRUST_MAX:.2f} to {sub_w - DOWN_THRUST_MIN:.2f}")
            
            # Show closest options (including series)
            buoy_df['UpThrustDiff'] = abs(buoy_df['FinalUpThrust'] - (sub_w - 2.25))
            closest = buoy_df.nsmallest(10, 'UpThrustDiff')[['Name', 'BuoyConfig', 'FinalUpThrust', 'IsSeries']]
            print(f"\n  Closest configs by upthrust:\n{closest.to_string(index=False)}")
            
            # Check how many configs are in the required range
            required_min = sub_w - DOWN_THRUST_MAX
            required_max = sub_w - DOWN_THRUST_MIN
            in_range = buoy_df[
                (buoy_df['FinalUpThrust'] >= required_min - 0.01) &
                (buoy_df['FinalUpThrust'] <= required_max + 0.01)
            ]
            print(f"\n  Configs in required upthrust range ({required_min:.2f}-{required_max:.2f} t): {len(in_range)}")
            if len(in_range) > 0:
                print(f"  These configs ARE in range:\n{in_range[['Name', 'BuoyConfig', 'FinalUpThrust', 'IsSeries']].head(10).to_string(index=False)}")
            
            # Also show how many series configs we have in total
            series_count = buoy_df[buoy_df['IsSeries']].shape[0]
            print(f"\n  Total series configurations available: {series_count}")
            
            # Show upthrust range in buoy database
            print(f"  Buoy upthrust range in database: {buoy_df['FinalUpThrust'].min():.2f} to {buoy_df['FinalUpThrust'].max():.2f} tonnes")
            
            raise ValueError(f"No feasible configuration for operation {i}")
    
    # Decision variables: x[i, c] = 1 if operation i uses config c
    x = {}
    for i in range(N):
        for c in feasible[i]:
            x[(i, c)] = model.NewBoolVar(f'x_{i}_{c}')
    
    # Constraint: Each operation must use exactly one config
    for i in range(N):
        model.Add(sum(x[(i, c)] for c in feasible[i]) == 1)
    
    # Track which buoy types (Name) are purchased
    # Get unique single buoy names (not series combinations)
    single_buoy_names = sorted(buoy_df[~buoy_df['IsSeries']]['Name'].unique())
    y_name = {}
    for name in single_buoy_names:
        y_name[name] = model.NewBoolVar(f'y_name_{name}')
        
        # This name is used if:
        # 1. Any single config with this name is used, OR
        # 2. Any series config that includes this name is used
        uses = []
        for i in range(N):
            for c in feasible[i]:
                buoy_config = buoy_df.loc[c]
                if (not buoy_config['IsSeries'] and buoy_config['Name'] == name) or \
                   (buoy_config['IsSeries'] and (buoy_config['Buoy1_Name'] == name or buoy_config['Buoy2_Name'] == name)):
                    uses.append(x[(i, c)])
        
        if uses:
            model.AddMaxEquality(y_name[name], uses)
        else:
            model.Add(y_name[name] == 0)
    
    # Calculate maximum simultaneous buoys needed
    # For each line, count how many physical buoys are in use
    # Note: A series config counts as 2 physical buoys
    line_ids = sorted(lines.keys())
    max_buoys = {}
    
    for line_id in line_ids:
        line_ops_indices = lines[line_id]
        # Get orders from the original full dataframe for this line
        line_orders = [ops_df_full.at[orig_i, 'Order'] for orig_i in line_ops_indices if orig_i in ops_df_full.index]
        # Map to filtered dataframe indices (exclude head operations)
        line_ops = [i for i in range(N) if ops_df.at[i, 'Order'] in line_orders]
        
        if not line_ops:
            continue
        
        # Count physical buoys needed for this line
        # For each single buoy type, track max count needed simultaneously
        line_name_counts = {}
        for name in single_buoy_names:
            # This is the count of this buoy type needed in the line
            count_var = model.NewIntVar(0, 2 * len(line_ops), f'line_{line_id}_count_{name}')
            
            # Sum up contributions from each operation in this line
            count_terms = []
            for i in line_ops:
                for c in feasible[i]:
                    buoy_config = buoy_df.loc[c]
                    contribution = 0
                    if not buoy_config['IsSeries'] and buoy_config['Name'] == name:
                        contribution = 1  # Single buoy of this type
                    elif buoy_config['IsSeries']:
                        # Count how many of this type are in the series
                        if buoy_config['Buoy1_Name'] == name:
                            contribution += 1
                        if buoy_config['Buoy2_Name'] == name:
                            contribution += 1
                    
                    if contribution > 0:
                        count_terms.append(contribution * x[(i, c)])
            
            if count_terms:
                model.Add(count_var == sum(count_terms))
            else:
                model.Add(count_var == 0)
            
            line_name_counts[name] = count_var
        
        # Total physical buoys for this line
        total_line_buoys = sum(line_name_counts.values())
        max_buoys[line_id] = total_line_buoys
    
    # The total buoys to purchase is the maximum across all lines
    # (since buoys are collected and reused between lines)
    max_simultaneous = model.NewIntVar(0, 2 * N, 'max_simultaneous')
    if max_buoys:
        model.AddMaxEquality(max_simultaneous, list(max_buoys.values()))
    
    # Transition costs (within lines only)
    transition_cost_terms = []
    
    for i in range(N - 1):
        # Check if i and i+1 are in the same line
        line_i = ops_df.at[i, 'LineID']
        line_i_plus_1 = ops_df.at[i + 1, 'LineID']
        
        if line_i == line_i_plus_1:
            # They're in the same line, so reconfiguration matters
            for c1 in feasible[i]:
                for c2 in feasible[i + 1]:
                    # Indicator variable for this transition
                    z = model.NewBoolVar(f'z_{i}_{c1}_{c2}')
                    model.Add(z <= x[(i, c1)])
                    model.Add(z <= x[(i + 1, c2)])
                    
                    # Add transition cost
                    cost = reconfig_cost(buoy_df.loc[c1], buoy_df.loc[c2])
                    if cost > 0:
                        transition_cost_terms.append(int(cost * 100) * z)
    
    # Objective: Minimize (purchase cost + reconfiguration cost)
    purchase_cost = int(COST_BUY_BUOY * 100) * max_simultaneous
    total_transition_cost = sum(transition_cost_terms) if transition_cost_terms else 0
    
    model.Minimize(purchase_cost + total_transition_cost)
    
    # Solve
    print("\n=== Solving ===")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVE_TIME
    solver.parameters.num_search_workers = NUM_WORKERS
    solver.parameters.log_search_progress = True
    
    status = solver.Solve(model)
    
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Solver failed with status: {solver.StatusName(status)}")
    
    print(f"\n=== Solution Found: {solver.StatusName(status)} ===")
    print(f"Objective value: {solver.ObjectiveValue() / 100:.2f}")
    print(f"Solve time: {solver.WallTime():.2f}s")
    print(f"Branches explored: {solver.NumBranches()}")
    print(f"Conflicts: {solver.NumConflicts()}")
    
    # Extract solution
    results = []
    for i in range(N):
        chosen_config = None
        for c in feasible[i]:
            if solver.Value(x[(i, c)]) == 1:
                chosen_config = c
                break
        
        if chosen_config is None:
            raise RuntimeError(f"No config chosen for operation {i}")
        
        sub_w = ops_df.at[i, 'Sub W']
        buoy = buoy_df.loc[chosen_config]
        down_thrust = sub_w - buoy['FinalUpThrust']
        
        results.append({
            'Order': int(ops_df.at[i, 'Order']),
            'LineID': ops_df.at[i, 'LineID'],
            'Flowline': ops_df.at[i, 'Flowline'],
            'TAG': ops_df.at[i, 'TAG'],
            'TYPE': ops_df.at[i, 'TYPE'],
            'SubW_tonnes': round(sub_w, 2),
            'BuoyName': buoy['Name'],
            'BuoyConfig': buoy['BuoyConfig'],
            'IsSeries': buoy['IsSeries'],
            'Buoy1_Name': buoy['Buoy1_Name'],
            'Buoy1_Config': buoy['Buoy1_Config'],
            'Buoy2_Name': buoy['Buoy2_Name'] if buoy['IsSeries'] else None,
            'Buoy2_Config': buoy['Buoy2_Config'] if buoy['IsSeries'] else None,
            'Shackles': int(buoy['ShackleCNT']),
            'Modules': int(buoy['ModuleSUB']),
            'Upthrust_tonnes': round(buoy['FinalUpThrust'], 2),
            'DownThrust_tonnes': round(down_thrust, 2),
            'CanCollectBuoys': ops_df.at[i, 'CanCollectBuoys']
        })
    
    # Calculate statistics
    max_buoys_needed = solver.Value(max_simultaneous)
    names_used = [name for name in single_buoy_names if solver.Value(y_name[name]) == 1]
    
    # VALIDATION: Verify all down-thrusts are in acceptable range
    results_df = pd.DataFrame(results)
    validation_errors = []
    
    for _, row in results_df.iterrows():
        if row['DownThrust_tonnes'] < DOWN_THRUST_MIN - 0.01:
            validation_errors.append(f"Order {row['Order']}: Down-thrust {row['DownThrust_tonnes']:.2f}t < minimum {DOWN_THRUST_MIN}t")
        if row['DownThrust_tonnes'] > DOWN_THRUST_MAX + 0.01:
            validation_errors.append(f"Order {row['Order']}: Down-thrust {row['DownThrust_tonnes']:.2f}t > maximum {DOWN_THRUST_MAX}t")
    
    if validation_errors:
        print("\n⚠️  VALIDATION WARNINGS:")
        for error in validation_errors:
            print(f"  {error}")
    else:
        print("\n✓ VALIDATION PASSED: All down-thrusts within range")
    
    print(f"\n=== OPTIMIZATION RESULTS ===")
    print(f"Maximum buoys needed simultaneously: {max_buoys_needed}")
    print(f"Unique buoy types used: {len(names_used)}")
    print(f"Buoy types: {names_used}")
    
    return results_df, max_buoys_needed, names_used

# ============ MAIN ============

def main():
    print("=" * 60)
    print("BUOY OPTIMIZATION FOR ACT_160 CAMPAIGN")
    print("=" * 60)
    
    # Load data
    print("\n[1/5] Loading planning data...")
    ops_df = load_planning_data(PLANNING_CSV)
    print(f"  Loaded {len(ops_df)} operations")
    
    print("\n[2/5] Loading buoy configurations...")
    buoy_df = load_buoy_configs(BUOYS_CSV)
    print(f"  Loaded {len(buoy_df)} single buoy configurations")
    
    print("\n[2b/5] Generating 2-buoy series combinations...")
    buoy_df = generate_series_combinations(buoy_df, ops_df)
    single_count = buoy_df[~buoy_df['IsSeries']].shape[0]
    series_count = buoy_df[buoy_df['IsSeries']].shape[0]
    print(f"  Generated {series_count} optimized series combinations")
    print(f"  Total configurations: {len(buoy_df)} (single + series)")
    
    print("\n[3/5] Identifying flowlines and collection points...")
    ops_df, lines = identify_lines(ops_df)
    print(f"  Identified {len(lines)} lines")
    for line_id, ops_indices in lines.items():
        print(f"    {line_id}: {len(ops_indices)} operations")
    
    print("\n[4/5] Running optimization...")
    results_df, max_buoys, names_used = optimize_buoy_allocation(ops_df, buoy_df, lines)
    
    print("\n[5/5] Saving results...")
    results_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Results saved to: {OUTPUT_CSV}")
    
    # Display summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total physical buoys to purchase: {max_buoys}")
    print(f"Buoy types needed: {len(names_used)}")
    
    # Count physical buoys by type across all lines
    buoy_type_counts = {}
    for name in names_used:
        # Count in single configs
        single_count = results_df[(~results_df['IsSeries']) & (results_df['BuoyName'] == name)].shape[0]
        # Count in series configs (both buoy 1 and buoy 2)
        series_as_buoy1 = results_df[(results_df['IsSeries']) & (results_df['Buoy1_Name'] == name)].shape[0]
        series_as_buoy2 = results_df[(results_df['IsSeries']) & (results_df['Buoy2_Name'] == name)].shape[0]
        
        total_uses = single_count + series_as_buoy1 + series_as_buoy2
        if total_uses > 0:
            buoy_type_counts[name] = total_uses
            print(f"  - {name}: used {total_uses} times")
    
    # Count series uses
    series_count = results_df[results_df['IsSeries']].shape[0]
    if series_count > 0:
        print(f"\nNote: {series_count} operations use 2-buoy series configurations")
    
    # Show line-by-line summary
    print("\n" + "=" * 60)
    print("LINE-BY-LINE ALLOCATION")
    print("=" * 60)
    for line_id in sorted(results_df['LineID'].unique()):
        line_data = results_df[results_df['LineID'] == line_id]
        print(f"\n{line_id}:")
        print(f"  Operations: {len(line_data)}")
        print(f"  Buoys in use: {line_data['BuoyName'].nunique()}")
        for _, row in line_data.iterrows():
            collect_marker = " [COLLECT]" if row['CanCollectBuoys'] else ""
            series_marker = " [2 BUOYS]" if row['IsSeries'] else ""
            buoy_display = f"{row['BuoyConfig']:15s}" if not row['IsSeries'] else f"{row['Buoy1_Config']}+{row['Buoy2_Config']}"
            print(f"    Order {row['Order']:2d} | {row['TYPE']:12s} | "
                  f"SubW: {row['SubW_tonnes']:6.2f}t | Up: {row['Upthrust_tonnes']:6.2f}t | "
                  f"Down: {row['DownThrust_tonnes']:4.2f}t | "
                  f"{buoy_display}{series_marker}{collect_marker}")
    
    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
