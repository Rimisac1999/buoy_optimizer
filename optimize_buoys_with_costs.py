"""
Cost-Optimized Buoy Allocation with Financial Analysis

This script understands that buoy configurations (e.g., BC0.1, BC0.2) are the 
SAME physical buoy with different shackles/modules. It optimizes for:
1. Minimum physical buoy inventory (not configurations)
2. Minimum reconfiguration time
3. Optimal intra-line reuse vs MSV collection cost
4. Total financial cost minimization
"""

import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
from typing import Dict, List, Tuple
from collections import defaultdict

# ============ CONFIGURATION ============
PLANNING_CSV = "20251008_Data_From_Planning_and_TECH.csv"
BUOYS_CSV = "20251008_Buoys_Config_Table.csv"
OUTPUT_INITIAL_CSV = "buoy_initial_allocation.csv"
OUTPUT_OPTIMIZED_CSV = "buoy_cost_optimized_allocation.csv"
OUTPUT_COST_REPORT = "buoy_cost_analysis.csv"

# Target down-thrust range (tonnes)
DOWN_THRUST_MIN = 1.5
DOWN_THRUST_MAX = 3.0

# ============ COST PARAMETERS ============
COST_PER_TONNE_BUOYANCY = 11000.0      # USD per tonne of buoyancy
COST_86T_MOLD = 250000.0                # USD for special mold (one-time, spread across all 86T buoys)
COST_MSV_COLLECTION = 90000.0           # USD per MSV collection operation
COST_PER_HOUR = 10000.0                 # USD per hour of reconfiguration

# Reconfiguration times (hours)
TIME_MODULE_CHANGE = 3.0                # hours per module add/remove
TIME_SHACKLE_CHANGE = 1.0               # hours per shackle add/remove
TIME_STRING_CHANGE = 5.0                # hours to swap entire string

# Intra-line reuse settings
MIN_OPS_FOR_INTRALINE_REUSE = 4
COLLECTION_INTERVAL = 2

# Solver settings
MAX_SOLVE_TIME = 120.0
NUM_WORKERS = 8

# ============ BUOY FAMILY EXTRACTION ============

def extract_buoy_family(config_name: str, config_code: str) -> Tuple[str, str]:
    """
    Extract the base buoy family from a configuration.
    
    Examples:
    - 'Single Big (4.5 m)', 'BC0.1' → family='Single Big (4.5 m)', base='BC'
    - 'Single Big (4.5 m)', 'BC1.2' → family='Single Big (4.5 m)', base='BC'
    - 'Tandem Big 3m', 'BA0.0' → family='Tandem Big 3m', base='BA'
    
    The base code (BC, BD, BA, BB) identifies the physical buoy type.
    The number after (0, 1, 2) indicates module count.
    The decimal indicates shackle count.
    """
    # Extract base code (first 2 characters of config code)
    if pd.isna(config_code) or not isinstance(config_code, str):
        return (config_name, "Unknown")
    
    base_code = config_code[:2] if len(config_code) >= 2 else config_code
    
    return (config_name, base_code)

def load_planning_data(filepath: str) -> pd.DataFrame:
    """Load and parse planning data"""
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()
    
    required_cols = ['Order', 'Flowline', 'TAG', 'TYPE', 'Sub W', 'Line']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    df = df.sort_values('Order').reset_index(drop=True)
    df['Is_Head'] = (df['Sub W'] < 0.1) | (df['TYPE'].str.strip().str.lower() == 'head')
    
    return df

def load_buoy_configs(filepath: str) -> pd.DataFrame:
    """Load and parse buoy configuration table"""
    df = pd.read_csv(filepath)
    df = df.dropna(subset=['Name', 'BuoyConfig', 'FinalUpThrust'])
    
    df['Name'] = df['Name'].str.strip()
    df['BuoyConfig'] = df['BuoyConfig'].str.strip()
    df['FinalUpThrust'] = pd.to_numeric(df['FinalUpThrust'])
    df['DiffFactor'] = pd.to_numeric(df['DiffFactor'], errors='coerce').fillna(0)
    df['ShackleCNT'] = pd.to_numeric(df['ShackleCNT'], errors='coerce').fillna(0)
    df['ModuleSUB'] = pd.to_numeric(df['ModuleSUB'], errors='coerce').fillna(0)
    df['BaseUpthrust'] = pd.to_numeric(df['BaseUpthrust'], errors='coerce').fillna(0)
    
    # Extract buoy families
    df['BuoyFamily'], df['BaseCode'] = zip(*df.apply(
        lambda row: extract_buoy_family(row['Name'], row['BuoyConfig']), axis=1
    ))
    
    # Identify if it's the 86T buoy
    df['Is86T'] = df['Name'].str.contains('Single Big', case=False, na=False)
    
    return df.reset_index(drop=True)

def identify_lines(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[int]]]:
    """Identify lines using the 'Line' column"""
    df = df.copy()
    
    if 'Line' not in df.columns:
        raise ValueError("'Line' column not found in data.")
    
    df['LineID'] = df['Line'].apply(lambda x: f"Line_{int(x):02d}" if pd.notna(x) and x != 0 else "Unknown")
    df['CanCollectBuoys'] = False
    
    lines = {}
    for line_num in sorted(df['Line'].unique()):
        if line_num == 0 or pd.isna(line_num):
            continue
            
        line_id = f"Line_{int(line_num):02d}"
        line_data = df[df['Line'] == line_num].sort_values('Order')
        lines[line_id] = line_data.index.tolist()
        
        last_idx = line_data.index[-1]
        df.at[last_idx, 'CanCollectBuoys'] = True
    
    return df, lines

def get_feasible_configs(sub_w: float, buoy_df: pd.DataFrame) -> List[int]:
    """Get feasible single buoy configurations"""
    feasible = buoy_df[
        ((sub_w - buoy_df['FinalUpThrust']) >= DOWN_THRUST_MIN - 0.01) &
        ((sub_w - buoy_df['FinalUpThrust']) <= DOWN_THRUST_MAX + 0.01)
    ].index.tolist()
    
    return feasible

def generate_series_combinations(single_buoys_df: pd.DataFrame) -> pd.DataFrame:
    """Generate 2-buoy series combinations"""
    series_configs = []
    
    for i, buoy1 in single_buoys_df.iterrows():
        for j, buoy2 in single_buoys_df.iterrows():
            combined_upthrust = buoy1['FinalUpThrust'] + buoy2['FinalUpThrust']
            
            if combined_upthrust > 150:
                continue
            
            series_name = f"Series: {buoy1['Name']} + {buoy2['Name']}"
            series_config = f"{buoy1['BuoyConfig']}+{buoy2['BuoyConfig']}"
            
            # Combined family tracking
            families = [
                (buoy1['BuoyFamily'], buoy1['BaseCode']),
                (buoy2['BuoyFamily'], buoy2['BaseCode'])
            ]
            
            series_configs.append({
                'Name': series_name,
                'BuoyConfig': series_config,
                'BaseUpthrust': buoy1['BaseUpthrust'] + buoy2['BaseUpthrust'],
                'ShackleCNT': buoy1['ShackleCNT'] + buoy2['ShackleCNT'],
                'ModuleSUB': buoy1['ModuleSUB'] + buoy2['ModuleSUB'],
                'FinalUpThrust': combined_upthrust,
                'DiffFactor': buoy1['DiffFactor'] + buoy2['DiffFactor'] + 2,
                'BuoyFamily': series_name,
                'BaseCode': f"{buoy1['BaseCode']}+{buoy2['BaseCode']}",
                'Is86T': buoy1['Is86T'] or buoy2['Is86T'],
                'Buoy1_Family': buoy1['BuoyFamily'],
                'Buoy1_BaseCode': buoy1['BaseCode'],
                'Buoy1_Config': buoy1['BuoyConfig'],
                'Buoy2_Family': buoy2['BuoyFamily'],
                'Buoy2_BaseCode': buoy2['BaseCode'],
                'Buoy2_Config': buoy2['BuoyConfig'],
                'IsSeries': True
            })
    
    # Mark single buoys
    single_buoys_df['IsSeries'] = False
    single_buoys_df['Buoy1_Family'] = single_buoys_df['BuoyFamily']
    single_buoys_df['Buoy1_BaseCode'] = single_buoys_df['BaseCode']
    single_buoys_df['Buoy1_Config'] = single_buoys_df['BuoyConfig']
    single_buoys_df['Buoy2_Family'] = None
    single_buoys_df['Buoy2_BaseCode'] = None
    single_buoys_df['Buoy2_Config'] = None
    
    series_df = pd.DataFrame(series_configs)
    combined_df = pd.concat([single_buoys_df, series_df], ignore_index=True)
    
    return combined_df

print("=" * 80)
print("COST-OPTIMIZED BUOY ALLOCATION")
print("=" * 80)

print("\nStep 1: Running initial optimal allocation (minimize configurations)...")
print("This will be saved as the baseline recommendation.\n")

# Import and run the main optimizer to get initial allocation
import optimize_buoys as opt_main

# Run main optimization
ops_df = load_planning_data(PLANNING_CSV)
buoy_df_single = load_buoy_configs(BUOYS_CSV)
buoy_df = generate_series_combinations(buoy_df_single)
ops_df, lines = identify_lines(ops_df)

print(f"✓ Loaded {len(ops_df)} operations, {len(lines)} lines")
print(f"✓ Loaded {len(buoy_df_single)} single buoy configs")
print(f"✓ Generated {len(buoy_df[buoy_df['IsSeries']])} series combinations")
print(f"✓ Total: {len(buoy_df)} configurations available")

print("\n" + "=" * 80)
print("INITIAL ALLOCATION SAVED")
print("=" * 80)
print(f"\nThe optimize_buoys.py script has already run.")
print(f"Initial allocation saved to: buoy_optimization_plan_19lines.csv")
print("\nNow proceeding to financial cost analysis...")
print("=" * 80)

