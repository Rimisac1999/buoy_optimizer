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
FINANCIAL_PARAMS_CSV = "financial_parameters.csv"
OUTPUT_CSV = "buoy_optimization_plan_19lines.csv"

# Target down-thrust range (tonnes) - will be loaded from financial params
DOWN_THRUST_MIN = 1.5
DOWN_THRUST_MAX = 3.0

# Financial parameters - will be loaded from CSV
COST_PER_TONNE_BUOYANCY = 11000.0   # USD per tonne
COST_LARGE_BUOY_MOLD = 250000.0     # One-time mold cost for large buoys
LARGE_BUOY_THRESHOLD = 70.0         # Buoys >= this size (tonnes) need special mold
COST_PER_HOUR = 10000.0             # Reconfiguration hourly rate
TIME_MODULE_CHANGE = 3.0            # Hours per module
TIME_SHACKLE_CHANGE = 1.0           # Hours per shackle
TIME_STRING_CHANGE = 5.0            # Hours for full string change

# Global variable to store buoy metadata (loaded from CSV)
BUOY_METADATA = {}

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

# ============ FINANCIAL PARAMETERS ============

def load_financial_parameters(filepath: str = FINANCIAL_PARAMS_CSV) -> Dict:
    """Load financial and operational parameters from CSV"""
    global COST_PER_TONNE_BUOYANCY, COST_LARGE_BUOY_MOLD, LARGE_BUOY_THRESHOLD, COST_PER_HOUR
    global TIME_MODULE_CHANGE, TIME_SHACKLE_CHANGE, TIME_STRING_CHANGE
    global DOWN_THRUST_MIN, DOWN_THRUST_MAX
    
    try:
        df = pd.read_csv(filepath)
        params = {}
        for _, row in df.iterrows():
            param_name = row['Parameter']
            value = float(row['Value'])
            params[param_name] = value
        
        # Update global parameters
        COST_PER_TONNE_BUOYANCY = params.get('COST_PER_TONNE_BUOYANCY', COST_PER_TONNE_BUOYANCY)
        COST_LARGE_BUOY_MOLD = params.get('COST_86T_MOLD', COST_LARGE_BUOY_MOLD)  # Keep old name for compatibility
        LARGE_BUOY_THRESHOLD = params.get('LARGE_BUOY_THRESHOLD', LARGE_BUOY_THRESHOLD)
        COST_PER_HOUR = params.get('COST_PER_HOUR', COST_PER_HOUR)
        TIME_MODULE_CHANGE = params.get('TIME_MODULE_CHANGE', TIME_MODULE_CHANGE)
        TIME_SHACKLE_CHANGE = params.get('TIME_SHACKLE_CHANGE', TIME_SHACKLE_CHANGE)
        TIME_STRING_CHANGE = params.get('TIME_STRING_CHANGE', TIME_STRING_CHANGE)
        DOWN_THRUST_MIN = params.get('DOWN_THRUST_MIN', DOWN_THRUST_MIN)
        DOWN_THRUST_MAX = params.get('DOWN_THRUST_MAX', DOWN_THRUST_MAX)
        
        print(f"  Loaded financial parameters from {filepath}")
        print(f"    Cost per tonne: ${COST_PER_TONNE_BUOYANCY:,.0f}")
        print(f"    Large buoy mold cost: ${COST_LARGE_BUOY_MOLD:,.0f}")
        print(f"    Large buoy threshold: {LARGE_BUOY_THRESHOLD:.1f} tonnes")
        print(f"    Reconfiguration: ${COST_PER_HOUR:,.0f}/hour")
        
        return params
    except FileNotFoundError:
        print(f"  WARNING: {filepath} not found. Using default values.")
        return {}

def extract_buoy_metadata(buoy_df: pd.DataFrame) -> Dict:
    """
    Extract buoy metadata from the configuration CSV.
    This makes the system fully dynamic - no hardcoding needed!
    
    Returns dict mapping base_code -> {name, base_buoyancy, needs_mold}
    """
    global BUOY_METADATA
    BUOY_METADATA = {}
    
    # Get unique base codes and their properties
    for _, row in buoy_df[~buoy_df['IsSeries']].iterrows():
        config_code = row['BuoyConfig']
        if pd.isna(config_code) or len(config_code) < 2:
            continue
            
        base_code = config_code[:2]
        
        if base_code not in BUOY_METADATA:
            base_buoyancy = float(row['BaseUpthrust'])
            needs_mold = base_buoyancy >= LARGE_BUOY_THRESHOLD
            
            BUOY_METADATA[base_code] = {
                'name': row['Name'],
                'base_buoyancy': base_buoyancy,
                'needs_mold': needs_mold
            }
    
    print(f"\n  Detected {len(BUOY_METADATA)} buoy families from CSV:")
    for base_code, info in sorted(BUOY_METADATA.items()):
        mold_marker = " [MOLD COST]" if info['needs_mold'] else ""
        cost = info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
        print(f"    {base_code} ({info['name']}): {info['base_buoyancy']:.1f}t @ ${cost:,.0f}{mold_marker}")
    
    return BUOY_METADATA

def calculate_physical_buoy_cost(physical_id: str, count_large_buoys: int) -> float:
    """
    Calculate the actual USD cost of a physical buoy DYNAMICALLY from metadata.
    
    Args:
        physical_id: e.g., 'BA0', 'BC2', 'BE1', 'BF0' (any base code from CSV)
        count_large_buoys: Total count of large buoys (for mold cost amortization)
    
    Returns:
        Cost in USD
    """
    base_code = physical_id[:2]
    
    if base_code not in BUOY_METADATA:
        return 0.0
    
    family_info = BUOY_METADATA[base_code]
    buoyancy_cost = family_info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
    
    # Add amortized mold cost for large buoys
    if family_info['needs_mold'] and count_large_buoys > 0:
        mold_cost_per_buoy = COST_LARGE_BUOY_MOLD / count_large_buoys
        return buoyancy_cost + mold_cost_per_buoy
    
    return buoyancy_cost

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
    """
    Calculate REAL DOLLAR cost to reconfigure from buoy A to buoy B.
    Based on actual time and hourly rates.
    """
    if buoy_a['BuoyConfig'] == buoy_b['BuoyConfig']:
        return 0.0
    
    # Different buoy family = full string change
    if buoy_a['Name'] != buoy_b['Name']:
        time_hours = TIME_STRING_CHANGE
    else:
        # Same family - add time for module and shackle changes
        time_hours = 0.0
        module_diff = abs(buoy_a['ModuleSUB'] - buoy_b['ModuleSUB'])
        shackle_diff = abs(buoy_a['ShackleCNT'] - buoy_b['ShackleCNT'])
        time_hours += module_diff * TIME_MODULE_CHANGE
        time_hours += shackle_diff * TIME_SHACKLE_CHANGE
    
    return time_hours * COST_PER_HOUR

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
    infeasible_ops = []  # Track operations with no feasible configs
    
    for i in range(N):
        sub_w = ops_df.at[i, 'Sub W']
        feasible[i] = get_feasible_configs(sub_w, buoy_df)
        
        if not feasible[i]:
            # Store infeasible operation info
            required_min = sub_w - DOWN_THRUST_MAX
            required_max = sub_w - DOWN_THRUST_MIN
            
            infeasible_ops.append({
                'index': i,
                'order': ops_df.at[i, 'Order'],
                'tag': ops_df.at[i, 'TAG'],
                'type': ops_df.at[i, 'TYPE'],
                'sub_w': sub_w,
                'required_min': required_min,
                'required_max': required_max,
                'line_id': ops_df.at[i, 'LineID']
            })
    
    # Report infeasible operations
    if infeasible_ops:
        print("\n" + "=" * 80)
        print("WARNING: OPERATIONS WITH INSUFFICIENT BUOY CAPACITY")
        print("=" * 80)
        print(f"\nFound {len(infeasible_ops)} operation(s) that cannot be satisfied with current buoy inventory:\n")
        
        for op in infeasible_ops:
            print(f"  Order {op['order']:2d} | {op['type']:12s} | {op['tag']}")
            print(f"    Sub W: {op['sub_w']:6.2f}t | Required upthrust: {op['required_min']:.2f}-{op['required_max']:.2f}t")
            print(f"    Line: {op['line_id']}")
            
            # Show closest available
            buoy_df['UpThrustDiff'] = abs(buoy_df['FinalUpThrust'] - (op['sub_w'] - 2.25))
            closest = buoy_df.nsmallest(3, 'UpThrustDiff')[['Name', 'FinalUpThrust']]
            max_available = buoy_df['FinalUpThrust'].max()
            print(f"    Max available upthrust: {max_available:.2f}t (need {op['required_min']:.2f}t minimum)")
            print(f"    Shortfall: {op['required_min'] - max_available:.2f}t\n")
        
        print("=" * 80)
        print("RECOMMENDATION: Add larger buoys or 3-buoy series configurations")
        print("=" * 80)
        
        # Remove infeasible operations from optimization
        print(f"\nContinuing optimization with remaining {N - len(infeasible_ops)} operations...")
        
        # Filter out infeasible operations
        infeasible_indices = [op['index'] for op in infeasible_ops]
        ops_df_filtered = ops_df.drop(infeasible_indices).reset_index(drop=True)
        
        # Update N and feasible dict
        N_original = N
        N = len(ops_df_filtered)
        
        # Rebuild feasible dict with new indices
        feasible_new = {}
        old_to_new = {}
        new_idx = 0
        for old_idx in range(N_original):
            if old_idx not in infeasible_indices:
                feasible_new[new_idx] = feasible[old_idx]
                old_to_new[old_idx] = new_idx
                new_idx += 1
        
        feasible = feasible_new
        ops_df = ops_df_filtered
        
        print(f"Optimizing {N} feasible operations...\n")
    
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
    
    # Calculate maximum simultaneous buoys needed WITH MSV COLLECTION
    # CRITICAL FIX: Track physical buoys by (base_code + module_count)
    # This properly accounts for MSV collection/reuse and reconfiguration limits:
    # - Shackles can be easily reconfigured (BC0.1 -> BC0.2 is the SAME physical buoy)
    # - Modules define different physical buoys (BC0 vs BC1 are DIFFERENT buoys)
    
    line_ids = sorted(lines.keys())
    
    # Build a mapping of all unique physical buoy IDs (base_code + module_count)
    physical_buoy_ids = set()
    for c in range(M):
        config_code = buoy_df.at[c, 'BuoyConfig']
        if not pd.isna(config_code):
            # Extract base code (first 2 chars) and module count
            base_code = config_code[:2] if len(config_code) >= 2 else config_code
            module_count = int(buoy_df.at[c, 'ModuleSUB'])
            physical_id = f"{base_code}{module_count}"
            physical_buoy_ids.add(physical_id)
        
        # For series configs, also add both buoys
        if buoy_df.at[c, 'IsSeries']:
            buoy1_config = buoy_df.at[c, 'Buoy1_Config']
            buoy2_config = buoy_df.at[c, 'Buoy2_Config']
            
            if not pd.isna(buoy1_config):
                base1 = buoy1_config[:2] if len(buoy1_config) >= 2 else buoy1_config
                # Find the module count for this buoy1 config in the original df
                buoy1_rows = buoy_df[buoy_df['BuoyConfig'] == buoy1_config]
                if len(buoy1_rows) > 0:
                    module1 = int(buoy1_rows.iloc[0]['ModuleSUB'])
                    physical_buoy_ids.add(f"{base1}{module1}")
            
            if not pd.isna(buoy2_config):
                base2 = buoy2_config[:2] if len(buoy2_config) >= 2 else buoy2_config
                # Find the module count for this buoy2 config in the original df
                buoy2_rows = buoy_df[buoy_df['BuoyConfig'] == buoy2_config]
                if len(buoy2_rows) > 0:
                    module2 = int(buoy2_rows.iloc[0]['ModuleSUB'])
                    physical_buoy_ids.add(f"{base2}{module2}")
    
    physical_buoy_ids = sorted(physical_buoy_ids)
    
    # For each physical buoy ID, track max count needed across all lines
    max_physical_counts = {}
    
    for physical_id in physical_buoy_ids:
        # For this physical buoy, find the max count needed in any single line
        physical_line_max_counts = []
        
        for line_id in line_ids:
            line_ops_indices = lines[line_id]
            # Get orders from the original full dataframe for this line
            line_orders = [ops_df_full.at[orig_i, 'Order'] for orig_i in line_ops_indices if orig_i in ops_df_full.index]
            # Map to filtered dataframe indices (exclude head operations)
            line_ops = [i for i in range(N) if ops_df.at[i, 'Order'] in line_orders]
            
            if not line_ops:
                continue
            
            # For this line, find the MAX count of this physical buoy needed in ANY SINGLE operation
            # (operations within a line are sequential, so we only need the peak)
            operation_counts = []
            
            for i in line_ops:
                # Count this physical buoy in operation i
                op_count_terms = []
                for c in feasible[i]:
                    buoy_config = buoy_df.loc[c]
                    contribution = 0
                    
                    if not buoy_config['IsSeries']:
                        # Single buoy
                        config_code = buoy_config['BuoyConfig']
                        if not pd.isna(config_code):
                            base = config_code[:2] if len(config_code) >= 2 else config_code
                            modules = int(buoy_config['ModuleSUB'])
                            if f"{base}{modules}" == physical_id:
                                contribution = 1
                    else:
                        # Series - check both buoys
                        buoy1_config = buoy_config['Buoy1_Config']
                        buoy2_config = buoy_config['Buoy2_Config']
                        
                        # Check buoy1
                        if not pd.isna(buoy1_config):
                            base1 = buoy1_config[:2] if len(buoy1_config) >= 2 else buoy1_config
                            buoy1_rows = buoy_df[buoy_df['BuoyConfig'] == buoy1_config]
                            if len(buoy1_rows) > 0:
                                module1 = int(buoy1_rows.iloc[0]['ModuleSUB'])
                                if f"{base1}{module1}" == physical_id:
                                    contribution += 1
                        
                        # Check buoy2
                        if not pd.isna(buoy2_config):
                            base2 = buoy2_config[:2] if len(buoy2_config) >= 2 else buoy2_config
                            buoy2_rows = buoy_df[buoy_df['BuoyConfig'] == buoy2_config]
                            if len(buoy2_rows) > 0:
                                module2 = int(buoy2_rows.iloc[0]['ModuleSUB'])
                                if f"{base2}{module2}" == physical_id:
                                    contribution += 1
                    
                    if contribution > 0:
                        op_count_terms.append(contribution * x[(i, c)])
                
                if op_count_terms:
                    # Create a variable for this operation's count
                    op_count_var = model.NewIntVar(0, 10, f'line_{line_id}_op_{i}_phys_{physical_id}')
                    model.Add(op_count_var == sum(op_count_terms))
                    operation_counts.append(op_count_var)
            
            # Max count for this physical buoy in this line (across all operations in line)
            if operation_counts:
                line_max_var = model.NewIntVar(0, 10, f'line_{line_id}_max_phys_{physical_id}')
                model.AddMaxEquality(line_max_var, operation_counts)
                physical_line_max_counts.append(line_max_var)
        
        # Max count for this physical buoy across all lines
        if physical_line_max_counts:
            max_count_var = model.NewIntVar(0, 10, f'max_phys_{physical_id}')
            model.AddMaxEquality(max_count_var, physical_line_max_counts)
            max_physical_counts[physical_id] = max_count_var
    
    # The total PHYSICAL buoys to purchase is the SUM of max counts per physical ID
    # This correctly accounts for MSV collection and reconfiguration capabilities
    max_simultaneous = sum(max_physical_counts.values()) if max_physical_counts else 0
    
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
    
    # ============ OBJECTIVE: MINIMIZE REAL DOLLAR COST ============
    # 
    # Calculate ACTUAL purchase costs for each physical buoy type
    # This allows the optimizer to intelligently trade off:
    #   - One expensive 86T buoy + mold cost
    #   - vs Two cheaper smaller buoys
    #
    
    # Collect all large buoy count variables (dynamically detected from CSV)
    buoys_large_vars = []
    for physical_id, count_var in max_physical_counts.items():
        base_code = physical_id[:2]
        if base_code in BUOY_METADATA and BUOY_METADATA[base_code]['needs_mold']:
            buoys_large_vars.append(count_var)
    
    # Create a binary variable: uses_large = 1 if any large buoys purchased
    uses_large = model.NewBoolVar('uses_large_buoy')
    
    if buoys_large_vars:
        # Total large buoys = sum of all large variants
        total_large_buoys = sum(buoys_large_vars)
        
        # Link uses_large to whether any large buoys are purchased
        # uses_large = 1 if total_large_buoys >= 1
        # uses_large = 0 if total_large_buoys == 0
        model.Add(total_large_buoys >= 1).OnlyEnforceIf(uses_large)
        model.Add(total_large_buoys == 0).OnlyEnforceIf(uses_large.Not())
    else:
        # No large buoys in the problem
        model.Add(uses_large == 0)
    
    # Calculate purchase costs with REAL DOLLAR values (DYNAMIC from CSV)
    purchase_cost_terms = []
    
    for physical_id, count_var in max_physical_counts.items():
        base_code = physical_id[:2]
        if base_code in BUOY_METADATA:
            family_info = BUOY_METADATA[base_code]
            
            # Base buoyancy cost (calculated from CSV data)
            buoyancy_cost = family_info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
            
            # Convert to integer for solver (no cents, just dollars)
            cost_per_buoy = int(buoyancy_cost)
            purchase_cost_terms.append(cost_per_buoy * count_var)
    
    # Add large buoy mold cost (one-time, only if any large buoys purchased)
    mold_cost = int(COST_LARGE_BUOY_MOLD)
    mold_cost_term = mold_cost * uses_large
    
    total_purchase_cost = sum(purchase_cost_terms) + mold_cost_term if purchase_cost_terms else mold_cost_term
    total_transition_cost = sum(transition_cost_terms) if transition_cost_terms else 0
    
    # OBJECTIVE: Minimize total real dollar cost
    model.Minimize(total_purchase_cost + total_transition_cost)
    
    print(f"\n=== Cost-Based Optimization ===")
    print(f"Using REAL DOLLAR COSTS (dynamically loaded from CSV):")
    for base_code, info in sorted(BUOY_METADATA.items()):
        cost = info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
        mold_marker = " + mold" if info['needs_mold'] else ""
        print(f"  {base_code} - {info['name']:30s} ${cost:>10,.0f}/buoy{mold_marker}")
    print(f"  {'Large buoy mold (one-time)':37s} ${COST_LARGE_BUOY_MOLD:>10,.0f}")
    print(f"\nOptimizer will intelligently choose between:")
    print(f"  - Buying fewer expensive buoys")
    print(f"  - Buying more cheaper buoys")
    print(f"  - Trading off mold cost vs multiple buoys")
    print(f"  - Works with ANY buoy types from CSV (BA, BB, BC, BD, BE, BF, ...)")
    
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
    
    # Get physical buoy breakdown
    physical_breakdown = {}
    for physical_id in physical_buoy_ids:
        if physical_id in max_physical_counts:
            count = solver.Value(max_physical_counts[physical_id])
            if count > 0:
                physical_breakdown[physical_id] = count
    
    # VALIDATION: Verify all down-thrusts are in acceptable range
    results_df = pd.DataFrame(results)
    validation_errors = []
    
    for _, row in results_df.iterrows():
        if row['DownThrust_tonnes'] < DOWN_THRUST_MIN - 0.01:
            validation_errors.append(f"Order {row['Order']}: Down-thrust {row['DownThrust_tonnes']:.2f}t < minimum {DOWN_THRUST_MIN}t")
        if row['DownThrust_tonnes'] > DOWN_THRUST_MAX + 0.01:
            validation_errors.append(f"Order {row['Order']}: Down-thrust {row['DownThrust_tonnes']:.2f}t > maximum {DOWN_THRUST_MAX}t")
    
    if validation_errors:
        print("\nVALIDATION WARNINGS:")
        for error in validation_errors:
            print(f"  {error}")
    else:
        print("\n[OK] VALIDATION PASSED: All down-thrusts within range")
    
    print(f"\n=== OPTIMIZATION RESULTS ===")
    print(f"TOTAL PHYSICAL BUOYS TO PURCHASE: {max_buoys_needed}")
    print(f"\nPhysical buoy breakdown (base_code + module_count):")
    for physical_id, count in sorted(physical_breakdown.items()):
        base_code = physical_id[:2]
        module_count = physical_id[2:]
        print(f"  {physical_id} ({base_code} with {module_count} module(s)): {count} buoy(s)")
    
    print(f"\nUnique buoy families used: {len(names_used)}")
    print(f"Families: {names_used}")
    
    return results_df, max_buoys_needed, names_used, infeasible_ops if infeasible_ops else [], physical_breakdown

# ============ MAIN ============

def main():
    print("=" * 60)
    print("BUOY OPTIMIZATION FOR ACT_160 CAMPAIGN")
    print("COST-BASED OPTIMIZER (Real Dollar Costs)")
    print("=" * 60)
    
    # Load financial parameters first
    print("\n[1/6] Loading financial parameters...")
    load_financial_parameters()
    
    # Load data
    print("\n[2/6] Loading planning data...")
    ops_df = load_planning_data(PLANNING_CSV)
    print(f"  Loaded {len(ops_df)} operations")
    
    print("\n[3/6] Loading buoy configurations...")
    buoy_df = load_buoy_configs(BUOYS_CSV)
    print(f"  Loaded {len(buoy_df)} single buoy configurations")
    
    # Extract buoy metadata DYNAMICALLY from CSV
    extract_buoy_metadata(buoy_df)
    
    print("\n[4/6] Generating 2-buoy series combinations...")
    buoy_df = generate_series_combinations(buoy_df, ops_df)
    single_count = buoy_df[~buoy_df['IsSeries']].shape[0]
    series_count = buoy_df[buoy_df['IsSeries']].shape[0]
    print(f"  Generated {series_count} optimized series combinations")
    print(f"  Total configurations: {len(buoy_df)} (single + series)")
    
    print("\n[5/6] Identifying flowlines and collection points...")
    ops_df, lines = identify_lines(ops_df)
    print(f"  Identified {len(lines)} lines")
    for line_id, ops_indices in lines.items():
        print(f"    {line_id}: {len(ops_indices)} operations")
    
    print("\n[6/6] Running COST-BASED optimization...")
    results_df, max_buoys, names_used, infeasible_ops, physical_breakdown = optimize_buoy_allocation(ops_df, buoy_df, lines)
    
    print("\n=== Saving results ===")
    results_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Results saved to: {OUTPUT_CSV}")
    
    # Save physical buoy breakdown
    if physical_breakdown:
        breakdown_df = pd.DataFrame([
            {'PhysicalID': pid, 'BaseCode': pid[:2], 'ModuleCount': int(pid[2:]), 'Quantity': count}
            for pid, count in sorted(physical_breakdown.items())
        ])
        breakdown_csv = OUTPUT_CSV.replace('.csv', '_physical_breakdown.csv')
        breakdown_df.to_csv(breakdown_csv, index=False)
        print(f"  Physical buoy breakdown saved to: {breakdown_csv}")
    
    # Save infeasible operations if any
    if infeasible_ops:
        infeasible_df = pd.DataFrame(infeasible_ops)
        infeasible_csv = OUTPUT_CSV.replace('.csv', '_INFEASIBLE.csv')
        infeasible_df.to_csv(infeasible_csv, index=False)
        print(f"  [!] Infeasible operations saved to: {infeasible_csv}")
    
    # Display summary with COST BREAKDOWN
    print("\n" + "=" * 60)
    print("COST-BASED OPTIMIZATION SUMMARY")
    print("=" * 60)
    print(f"\nPhysical buoys to purchase: {max_buoys}")
    
    # Calculate actual costs (DYNAMIC from CSV metadata)
    total_buoy_cost = 0.0
    uses_large = False
    
    print(f"\nCost breakdown by buoy type:")
    for physical_id, count in sorted(physical_breakdown.items()):
        base_code = physical_id[:2]
        if base_code in BUOY_METADATA:
            family_info = BUOY_METADATA[base_code]
            buoy_cost = family_info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
            subtotal = buoy_cost * count
            total_buoy_cost += subtotal
            
            if family_info['needs_mold']:
                uses_large = True
            
            print(f"  {physical_id} ({family_info['name']}): {count}x @ ${buoy_cost:,.0f} = ${subtotal:,.0f}")
    
    mold_cost = COST_LARGE_BUOY_MOLD if uses_large else 0.0
    total_purchase_cost = total_buoy_cost + mold_cost
    
    if uses_large:
        print(f"\n  Large buoy mold (one-time): ${mold_cost:,.0f}")
    
    print(f"\n  TOTAL PURCHASE COST: ${total_purchase_cost:,.0f}")
    print(f"\nBuoy family diversity: {len(names_used)} types")
    
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
    
    if infeasible_ops:
        print(f"\n[!] NOTE: {len(infeasible_ops)} operation(s) could not be allocated due to insufficient buoy capacity.")
        print(f"    See {OUTPUT_CSV.replace('.csv', '_INFEASIBLE.csv')} for details.")
        print(f"    Consider adding larger buoys or 3-buoy configurations to handle these operations.")
    else:
        print("\n[OK] All operations successfully allocated!")

if __name__ == "__main__":
    main()
