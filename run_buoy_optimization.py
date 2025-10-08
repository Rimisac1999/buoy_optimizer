"""
Master Buoy Optimization Script with Financial Analysis

This script runs the complete buoy optimization workflow:
1. Loads financial parameters from CSV
2. Runs constraint optimization
3. Analyzes intra-line reuse opportunities
4. Calculates complete financial costs
5. Generates comprehensive report
6. Saves everything to a versioned scenario folder

Usage: python run_buoy_optimization.py
"""

import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
from typing import Dict, List, Tuple
from collections import defaultdict
import os
from datetime import datetime
import shutil

# ============ FILE PATHS ============
PLANNING_CSV = "20251008_Data_From_Planning_and_TECH.csv"
BUOYS_CSV = "20251008_Buoys_Config_Table.csv"
PARAMS_CSV = "financial_parameters.csv"

# ============ LOAD PARAMETERS ============

def load_financial_parameters(filepath: str = PARAMS_CSV) -> Dict:
    """Load financial and operational parameters from CSV"""
    try:
        df = pd.read_csv(filepath)
        params = {}
        for _, row in df.iterrows():
            param_name = row['Parameter']
            value = float(row['Value'])
            params[param_name] = value
        return params
    except FileNotFoundError:
        print(f"⚠️  Warning: {filepath} not found. Using default parameters.")
        return get_default_parameters()

def get_default_parameters() -> Dict:
    """Default parameters if CSV not found"""
    return {
        'COST_PER_TONNE_BUOYANCY': 11000.0,
        'COST_86T_MOLD': 250000.0,
        'COST_MSV_COLLECTION': 90000.0,
        'COST_PER_HOUR': 10000.0,
        'TIME_MODULE_CHANGE': 3.0,
        'TIME_SHACKLE_CHANGE': 1.0,
        'TIME_STRING_CHANGE': 5.0,
        'DOWN_THRUST_MIN': 1.5,
        'DOWN_THRUST_MAX': 3.0,
        'MIN_OPS_FOR_INTRALINE_REUSE': 4,
        'COLLECTION_INTERVAL': 2,
        'MAX_SOLVE_TIME': 120.0,
        'NUM_WORKERS': 8
    }

# ============ FOLDER MANAGEMENT ============

def create_scenario_folder(scenario_name: str) -> str:
    """Create versioned scenario folder in Results/"""
    
    # Create Results folder if it doesn't exist
    results_dir = "Results"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    
    # Clean scenario name
    scenario_name = scenario_name.strip().replace(' ', '_')
    
    # Check for existing folders and version
    base_folder = os.path.join(results_dir, scenario_name)
    
    if not os.path.exists(base_folder):
        folder = base_folder
    else:
        # Find next version number
        version = 2
        while True:
            folder = os.path.join(results_dir, f"{scenario_name}_v{version}")
            if not os.path.exists(folder):
                break
            version += 1
    
    os.makedirs(folder)
    return folder

# ============ BUOY FAMILY DEFINITIONS ============

BUOY_FAMILIES = {
    'BA': {'name': 'Tandem Big 3m', 'base_buoyancy': 50.8, 'is_86t': False},
    'BB': {'name': 'Tandem Small 3m', 'base_buoyancy': 44.5, 'is_86t': False},
    'BC': {'name': 'Single Big (4.5 m)', 'base_buoyancy': 86.0, 'is_86t': True},
    'BD': {'name': 'Single Small (3.0 m)', 'base_buoyancy': 38.0, 'is_86t': False},
}

# ============ IMPORT CORE FUNCTIONS ============

# Import from existing scripts
import sys
sys.path.insert(0, os.path.dirname(__file__))

# Core optimization logic (simplified inline version)
def parse_config(config_code: str) -> Dict:
    """Parse configuration code: XY#.# where XY=base, #=modules, .#=shackles"""
    if pd.isna(config_code) or not isinstance(config_code, str) or len(config_code) < 2:
        return {'base': None, 'modules': 0, 'shackles': 0}
    
    base = config_code[:2]
    
    try:
        parts = config_code[2:].split('.')
        modules = int(parts[0]) if len(parts) > 0 and parts[0] else 0
        shackles = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except:
        modules = 0
        shackles = 0
    
    return {'base': base, 'modules': modules, 'shackles': shackles}

def calculate_reconfig_time(from_config: str, to_config: str, params: Dict) -> float:
    """Calculate reconfiguration time in hours"""
    if from_config == to_config:
        return 0.0
    
    from_parsed = parse_config(from_config)
    to_parsed = parse_config(to_config)
    
    if from_parsed['base'] != to_parsed['base']:
        return params['TIME_STRING_CHANGE']
    
    time = 0.0
    time += abs(from_parsed['modules'] - to_parsed['modules']) * params['TIME_MODULE_CHANGE']
    time += abs(from_parsed['shackles'] - to_parsed['shackles']) * params['TIME_SHACKLE_CHANGE']
    
    return time

def count_physical_buoys(allocation_df: pd.DataFrame) -> Dict:
    """Count physical buoys (BaseCode + ModuleCount = 1 physical buoy)"""
    line_physical_details = {}
    
    for line_id in allocation_df['LineID'].unique():
        line_data = allocation_df[allocation_df['LineID'] == line_id].sort_values('Order')
        physical_buoys_needed = defaultdict(int)
        
        for _, row in line_data.iterrows():
            buoy_configs = []
            if row['IsSeries']:
                buoy_configs.append(row['Buoy1_Config'])
                buoy_configs.append(row['Buoy2_Config'])
            else:
                buoy_configs.append(row['BuoyConfig'])
            
            operation_physical = defaultdict(int)
            for config in buoy_configs:
                parsed = parse_config(config)
                physical_id = f"{parsed['base']}{parsed['modules']}"
                operation_physical[physical_id] += 1
            
            for physical_id, count in operation_physical.items():
                physical_buoys_needed[physical_id] = max(
                    physical_buoys_needed[physical_id], count
                )
        
        line_physical_details[line_id] = dict(physical_buoys_needed)
    
    family_counts = defaultdict(int)
    for line_id, buoys in line_physical_details.items():
        for physical_id, count in buoys.items():
            family_counts[physical_id] = max(family_counts[physical_id], count)
    
    base_code_counts = defaultdict(int)
    for physical_id, count in family_counts.items():
        base_code = physical_id[:2]
        base_code_counts[base_code] += count
    
    return {
        'total_physical': sum(family_counts.values()),
        'by_physical_id': dict(family_counts),
        'by_base_family': dict(base_code_counts),
        'details_by_line': line_physical_details
    }

# ============ MAIN WORKFLOW ============

def main():
    print("=" * 80)
    print("COMPREHENSIVE BUOY OPTIMIZATION & FINANCIAL ANALYSIS")
    print("=" * 80)
    print("\nThis script will:")
    print("  1. Run buoy optimization")
    print("  2. Analyze intra-line reuse opportunities")
    print("  3. Calculate complete financial costs")
    print("  4. Generate comprehensive report")
    print("  5. Save everything to a scenario folder")
    
    # Get scenario name
    print("\n" + "=" * 80)
    scenario_name = input("Enter scenario name (e.g., 'Main_Scenario', 'No_86T'): ").strip()
    
    if not scenario_name:
        scenario_name = f"Scenario_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"Using default name: {scenario_name}")
    
    # Create scenario folder
    scenario_folder = create_scenario_folder(scenario_name)
    print(f"\n✓ Created scenario folder: {scenario_folder}")
    
    # Load parameters
    print("\n[1/7] Loading financial parameters...")
    params = load_financial_parameters()
    print(f"  ✓ Loaded {len(params)} parameters from {PARAMS_CSV}")
    
    # Copy input files to scenario folder
    print("\n[2/7] Copying input files...")
    for file in [PLANNING_CSV, BUOYS_CSV, PARAMS_CSV]:
        if os.path.exists(file):
            shutil.copy(file, os.path.join(scenario_folder, file))
    print("  ✓ Input files copied to scenario folder")
    
    # Run main optimization
    print("\n[3/7] Running buoy optimization...")
    print("  (This may take a minute...)")
    
    import subprocess
    result = subprocess.run(
        ['python', 'optimize_buoys.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"\n❌ Optimization failed:")
        print(result.stderr)
        return
    
    print("  ✓ Optimization complete")
    
    # Run intra-line reuse analysis
    print("\n[4/7] Analyzing intra-line reuse opportunities...")
    result = subprocess.run(
        ['python', 'optimize_intraline_reuse.py'],
        capture_output=True,
        text=True
    )
    print("  ✓ Intra-line analysis complete")
    
    # Load results for analysis
    print("\n[5/7] Loading results and calculating costs...")
    
    allocation = pd.read_csv('buoy_optimization_plan_19lines.csv')
    
    try:
        reuse = pd.read_csv('buoy_plan_reuse_summary.csv')
    except:
        reuse = pd.DataFrame()
    
    # Calculate physical inventory
    physical_inventory = count_physical_buoys(allocation)
    
    # Calculate all costs
    purchase_costs = calculate_purchase_costs_detailed(physical_inventory, params)
    reconfig_costs = calculate_reconfig_costs_detailed(allocation, params)
    collection_costs = calculate_collection_costs_detailed(reuse, params)
    
    total_cost = (
        purchase_costs['total'] +
        reconfig_costs['total'] +
        collection_costs['total']
    )
    
    print(f"  ✓ Physical buoys: {physical_inventory['total_physical']}")
    print(f"  ✓ Total cost: ${total_cost:,.0f}")
    
    # Generate comprehensive report
    print("\n[6/7] Generating comprehensive report...")
    generate_comprehensive_report(
        scenario_folder,
        scenario_name,
        physical_inventory,
        purchase_costs,
        reconfig_costs,
        collection_costs,
        total_cost,
        allocation,
        reuse,
        params
    )
    
    # Copy all output files to scenario folder
    print("\n[7/7] Copying output files to scenario folder...")
    files_to_copy = [
        'buoy_optimization_plan_19lines.csv',
        'buoy_plan_with_intraline_reuse.csv',
        'buoy_plan_reuse_summary.csv',
        'cost_summary.csv',
        'reconfiguration_details.csv',
        'physical_inventory_costs.csv',
        'buoy_purchase_list.csv'
    ]
    
    for file in files_to_copy:
        if os.path.exists(file):
            shutil.copy(file, os.path.join(scenario_folder, file))
    
    print(f"  ✓ All output files copied to scenario folder")
    
    # Final summary
    print("\n" + "=" * 80)
    print("OPTIMIZATION COMPLETE!")
    print("=" * 80)
    print(f"\n📁 Scenario: {scenario_name}")
    print(f"📂 Location: {scenario_folder}")
    print(f"\n💰 TOTAL CAMPAIGN COST: ${total_cost:,.0f}")
    print(f"📦 Physical Buoys: {physical_inventory['total_physical']}")
    print(f"🔧 Reconfigurations: {reconfig_costs['count']} ({reconfig_costs['time_hours']:.1f} hours)")
    print(f"🚢 MSV Collections: {collection_costs['count']}")
    print(f"\n✅ All files saved to: {scenario_folder}")

# ============ DETAILED COST CALCULATIONS ============

def calculate_purchase_costs_detailed(physical_inventory: Dict, params: Dict) -> Dict:
    """Calculate detailed purchase costs"""
    costs_by_family = {}
    total_cost = 0.0
    uses_86t = False
    
    for base_code, count in physical_inventory['by_base_family'].items():
        if base_code in BUOY_FAMILIES:
            family_info = BUOY_FAMILIES[base_code]
            buoy_cost = family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY'] * count
            
            costs_by_family[base_code] = {
                'name': family_info['name'],
                'count': count,
                'buoyancy': family_info['base_buoyancy'],
                'cost': buoy_cost
            }
            total_cost += buoy_cost
            
            if family_info['is_86t']:
                uses_86t = True
    
    mold_cost = params['COST_86T_MOLD'] if uses_86t else 0.0
    
    return {
        'by_family': costs_by_family,
        'buoyancy_cost': total_cost,
        'mold_cost': mold_cost,
        'total': total_cost + mold_cost,
        'uses_86t': uses_86t
    }

def calculate_reconfig_costs_detailed(allocation_df: pd.DataFrame, params: Dict) -> Dict:
    """Calculate reconfiguration costs"""
    total_time = 0.0
    details = []
    
    for line_id in allocation_df['LineID'].unique():
        line_data = allocation_df[allocation_df['LineID'] == line_id].sort_values('Order')
        
        for i in range(len(line_data) - 1):
            curr = line_data.iloc[i]
            next_op = line_data.iloc[i + 1]
            
            configs_curr = [curr['Buoy1_Config'], curr['Buoy2_Config']] if curr['IsSeries'] else [curr['BuoyConfig']]
            configs_next = [next_op['Buoy1_Config'], next_op['Buoy2_Config']] if next_op['IsSeries'] else [next_op['BuoyConfig']]
            
            for curr_conf in configs_curr:
                for next_conf in configs_next:
                    reconfig_time = calculate_reconfig_time(curr_conf, next_conf, params)
                    if reconfig_time > 0:
                        total_time += reconfig_time
                        details.append({
                            'Line': line_id,
                            'From_Order': curr['Order'],
                            'To_Order': next_op['Order'],
                            'From_Config': curr_conf,
                            'To_Config': next_conf,
                            'Time_Hours': reconfig_time,
                            'Cost_USD': reconfig_time * params['COST_PER_HOUR']
                        })
                        break  # Only count once per buoy
                break
    
    return {
        'total': total_time * params['COST_PER_HOUR'],
        'time_hours': total_time,
        'count': len(details),
        'details': pd.DataFrame(details)
    }

def calculate_collection_costs_detailed(reuse_df: pd.DataFrame, params: Dict) -> Dict:
    """Calculate MSV collection costs"""
    if reuse_df.empty:
        return {'total': 0.0, 'count': 0, 'details': pd.DataFrame()}
    
    collections = reuse_df[['LineID', 'FromOrder']].drop_duplicates()
    num_collections = len(collections)
    
    return {
        'total': num_collections * params['COST_MSV_COLLECTION'],
        'count': num_collections,
        'details': collections
    }

# ============ REPORT GENERATION ============

def generate_comprehensive_report(folder, scenario_name, physical_inventory, 
                                 purchase_costs, reconfig_costs, collection_costs,
                                 total_cost, allocation_df, reuse_df, params):
    """Generate comprehensive markdown and CSV reports"""
    
    report_path = os.path.join(folder, "COMPREHENSIVE_REPORT.md")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# Buoy Optimization Report: {scenario_name}\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("=" * 80 + "\n\n")
        
        # Executive Summary
        f.write("## EXECUTIVE SUMMARY\n\n")
        f.write(f"**Total Campaign Cost:** ${total_cost:,.0f}\n\n")
        f.write(f"**Physical Buoys Required:** {physical_inventory['total_physical']}\n\n")
        f.write(f"**Operations:** {len(allocation_df)}\n")
        f.write(f"**Flowlines:** {allocation_df['LineID'].nunique()}\n\n")
        
        # Cost Breakdown
        f.write("## COST BREAKDOWN\n\n")
        f.write("| Category | Amount | Percentage |\n")
        f.write("|----------|--------|------------|\n")
        f.write(f"| Purchase (buoys + mold) | ${purchase_costs['total']:,.0f} | {(purchase_costs['total']/total_cost)*100:.1f}% |\n")
        f.write(f"| Reconfiguration | ${reconfig_costs['total']:,.0f} | {(reconfig_costs['total']/total_cost)*100:.1f}% |\n")
        f.write(f"| MSV Collections | ${collection_costs['total']:,.0f} | {(collection_costs['total']/total_cost)*100:.1f}% |\n")
        f.write(f"| **TOTAL** | **${total_cost:,.0f}** | **100.0%** |\n\n")
        
        # Physical Inventory
        f.write("## PHYSICAL BUOY INVENTORY\n\n")
        f.write("| Physical ID | Buoy Family | Quantity | Buoyancy/Unit | Cost/Unit |\n")
        f.write("|-------------|-------------|----------|---------------|------------|\n")
        
        for physical_id, count in sorted(physical_inventory['by_physical_id'].items()):
            base = physical_id[:2]
            if base in BUOY_FAMILIES:
                family_info = BUOY_FAMILIES[base]
                module_count = physical_id[2] if len(physical_id) > 2 else '0'
                cost_per = family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY']
                f.write(f"| {physical_id} | {family_info['name']} ({module_count} mod) | {count} | {family_info['base_buoyancy']}t | ${cost_per:,.0f} |\n")
        
        f.write(f"\n**Total:** {physical_inventory['total_physical']} physical buoys\n\n")
        
        if purchase_costs['uses_86t']:
            f.write(f"**86T Mold Cost:** ${params['COST_86T_MOLD']:,.0f} (one-time)\n\n")
        
        # Reconfiguration Summary
        f.write("## RECONFIGURATION ANALYSIS\n\n")
        f.write(f"**Total Reconfigurations:** {reconfig_costs['count']}\n")
        f.write(f"**Total Time:** {reconfig_costs['time_hours']:.1f} hours\n")
        f.write(f"**Total Cost:** ${reconfig_costs['total']:,.0f}\n\n")
        
        if not reconfig_costs['details'].empty:
            top_reconfigs = reconfig_costs['details'].nlargest(5, 'Cost_USD')
            f.write("**Top 5 Most Expensive Reconfigurations:**\n\n")
            for idx, row in top_reconfigs.iterrows():
                f.write(f"{idx+1}. {row['Line']}: Order {row['From_Order']}->{row['To_Order']}\n")
                f.write(f"   - {row['From_Config']} -> {row['To_Config']}\n")
                f.write(f"   - {row['Time_Hours']:.1f}h, ${row['Cost_USD']:,.0f}\n\n")
        
        # Intra-Line Reuse
        f.write("## INTRA-LINE REUSE (MSV Collections)\n\n")
        f.write(f"**Mid-Line Collections:** {collection_costs['count']}\n")
        f.write(f"**Cost per Collection:** ${params['COST_MSV_COLLECTION']:,.0f}\n")
        f.write(f"**Total Cost:** ${collection_costs['total']:,.0f}\n\n")
        
        if collection_costs['count'] > 0:
            f.write("**Collection Points:**\n\n")
            for _, row in collection_costs['details'].iterrows():
                f.write(f"- {row['LineID']}: After Order {row['FromOrder']}\n")
            f.write("\n")
        
        if not reuse_df.empty:
            f.write(f"**Buoy Reuses:** {len(reuse_df)} instances\n")
            reconfigs_needed = reuse_df['NeedsReconfig'].sum() if 'NeedsReconfig' in reuse_df.columns else 0
            f.write(f"- Exact match: {len(reuse_df) - reconfigs_needed}\n")
            f.write(f"- Requires reconfiguration: {reconfigs_needed}\n\n")
        
        # Parameters Used
        f.write("## PARAMETERS USED\n\n")
        f.write("| Parameter | Value | Unit |\n")
        f.write("|-----------|-------|------|\n")
        for key, value in sorted(params.items()):
            f.write(f"| {key} | {value} | - |\n")
        f.write("\n")
        
        # File List
        f.write("## GENERATED FILES\n\n")
        f.write("**Input Files:**\n")
        f.write(f"- {PLANNING_CSV}\n")
        f.write(f"- {BUOYS_CSV}\n")
        f.write(f"- {PARAMS_CSV}\n\n")
        
        f.write("**Output Files:**\n")
        f.write("- `COMPREHENSIVE_REPORT.md` - This report\n")
        f.write("- `buoy_optimization_plan_19lines.csv` - Line-by-line allocation\n")
        f.write("- `buoy_plan_with_intraline_reuse.csv` - With collection points\n")
        f.write("- `physical_inventory_costs.csv` - Purchase requirements\n")
        f.write("- `cost_summary.csv` - Cost overview\n")
        f.write("- `reconfiguration_details.csv` - All reconfigurations\n")
        f.write("- `buoy_plan_reuse_summary.csv` - Reuse tracking\n\n")
        
        f.write("---\n\n")
        f.write(f"**Report generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Save cost summary
    summary_df = pd.DataFrame([{
        'Scenario': scenario_name,
        'Date': datetime.now().strftime('%Y-%m-%d'),
        'Physical_Buoys': physical_inventory['total_physical'],
        'Purchase_Cost': purchase_costs['total'],
        'Reconfiguration_Cost': reconfig_costs['total'],
        'Collection_Cost': collection_costs['total'],
        'Total_Cost': total_cost,
        'Reconfig_Hours': reconfig_costs['time_hours'],
        'MSV_Collections': collection_costs['count'],
        'Operations': len(allocation_df),
        'Lines': allocation_df['LineID'].nunique()
    }])
    
    summary_df.to_csv(os.path.join(folder, 'SCENARIO_SUMMARY.csv'), index=False)
    
    # Save detailed inventory
    inventory_details = []
    for physical_id, count in sorted(physical_inventory['by_physical_id'].items()):
        base = physical_id[:2]
        if base in BUOY_FAMILIES:
            family_info = BUOY_FAMILIES[base]
            module_count = physical_id[2] if len(physical_id) > 2 else '0'
            cost_per = family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY']
            
            inventory_details.append({
                'Physical_ID': physical_id,
                'Base_Code': base,
                'Buoy_Family': family_info['name'],
                'Module_Count': module_count,
                'Quantity': count,
                'Buoyancy_Per_Unit_Tonnes': family_info['base_buoyancy'],
                'Cost_Per_Unit_USD': cost_per,
                'Total_Cost_USD': cost_per * count,
                'Is_86T': 'Yes' if family_info['is_86t'] else 'No'
            })
    
    inventory_df = pd.DataFrame(inventory_details)
    inventory_df.to_csv(os.path.join(folder, 'PHYSICAL_INVENTORY.csv'), index=False)
    
    # Save reconfiguration details
    if not reconfig_costs['details'].empty:
        reconfig_costs['details'].to_csv(os.path.join(folder, 'RECONFIGURATIONS.csv'), index=False)
    
    # Save MSV collection details
    if collection_costs['count'] > 0:
        collection_costs['details'].to_csv(os.path.join(folder, 'MSV_COLLECTIONS.csv'), index=False)
    
    print(f"  ✓ Report generated: COMPREHENSIVE_REPORT.md")

if __name__ == "__main__":
    main()
