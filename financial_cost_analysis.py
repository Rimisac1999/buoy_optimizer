"""
Financial Cost Analysis for Buoy Campaign

Calculates total campaign cost including:
- Buoy purchase costs (by buoyancy)
- 86T mold cost (if applicable)
- MSV collection costs (intra-line reuse)
- Reconfiguration costs (shackles, modules, strings)
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from typing import Dict, List, Tuple

# ============ LOAD PARAMETERS FROM CSV ============
PARAMS_CSV = "financial_parameters.csv"

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
        print(f"WARNING: {filepath} not found. Using default hardcoded values.")
        return {
            'COST_PER_TONNE_BUOYANCY': 11000.0,
            'COST_86T_MOLD': 250000.0,
            'COST_MSV_COLLECTION': 90000.0,
            'COST_PER_HOUR': 10000.0,
            'TIME_MODULE_CHANGE': 3.0,
            'TIME_SHACKLE_CHANGE': 1.0,
            'TIME_STRING_CHANGE': 5.0
        }

# Parameters will be loaded in main() to ensure fresh values

# ============ BUOY FAMILY MAPPING ============

BUOY_FAMILIES = {
    'BA': {'name': 'Tandem Big 3m', 'base_buoyancy': 50.8, 'is_86t': False},
    'BB': {'name': 'Tandem Small 3m', 'base_buoyancy': 44.5, 'is_86t': False},
    'BC': {'name': 'Single Big (4.5 m)', 'base_buoyancy': 86.0, 'is_86t': True},
    'BD': {'name': 'Single Small (3.0 m)', 'base_buoyancy': 38.0, 'is_86t': False},
}

def extract_base_family(config_code: str) -> str:
    """Extract base family code (BA, BB, BC, BD) from config"""
    if pd.isna(config_code):
        return None
    return config_code[:2] if len(config_code) >= 2 else config_code

def parse_config(config_code: str) -> Dict:
    """
    Parse configuration code into components.
    
    Format: XY#.#
    - XY: base code (BA, BB, BC, BD)
    - #: module count (0, 1, 2)
    - .#: shackle count (0, 1, 2)
    
    Example: BC1.2 → base=BC, modules=1, shackles=2
    """
    if pd.isna(config_code) or not isinstance(config_code, str):
        return {'base': None, 'modules': 0, 'shackles': 0}
    
    base = config_code[:2]
    
    try:
        # Split by '.' to get modules and shackles
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
        # Different buoy family - full string change
        return params['TIME_STRING_CHANGE']
    
    # Same family - add time for module and shackle changes
    time = 0.0
    time += abs(from_parsed['modules'] - to_parsed['modules']) * params['TIME_MODULE_CHANGE']
    time += abs(from_parsed['shackles'] - to_parsed['shackles']) * params['TIME_SHACKLE_CHANGE']
    
    return time

def calculate_reconfig_cost(from_config: str, to_config: str, params: Dict) -> float:
    """Calculate reconfiguration cost in USD"""
    time_hours = calculate_reconfig_time(from_config, to_config, params)
    return time_hours * params['COST_PER_HOUR']

# ============ PHYSICAL BUOY INVENTORY CALCULATION ============

def count_physical_buoys(allocation_df: pd.DataFrame) -> Dict:
    """
    Count actual physical buoys needed.
    
    CRITICAL: A physical buoy is identified by (BaseCode + ModuleCount)
    Examples:
    - BC0.0, BC0.1, BC0.2 = 1 physical buoy (BC with 0 modules, different shackles)
    - BC1.1, BC1.2, BC1.3 = 1 physical buoy (BC with 1 module, different shackles)
    - BC2.0, BC2.1 = 1 physical buoy (BC with 2 modules, different shackles)
    
    Shackles can be added/removed quickly; modules define the physical buoy.
    """
    # For each line, count unique physical buoys (BaseCode + ModuleCount)
    line_physical_counts = {}
    line_physical_details = {}
    
    for line_id in allocation_df['LineID'].unique():
        line_data = allocation_df[allocation_df['LineID'] == line_id].sort_values('Order')
        
        # Track physical buoys: (base_code, module_count)
        physical_buoys_needed = defaultdict(int)
        
        for _, row in line_data.iterrows():
            # Get all buoys in this operation
            buoy_configs = []
            
            if row['IsSeries']:
                buoy_configs.append(row['Buoy1_Config'])
                buoy_configs.append(row['Buoy2_Config'])
            else:
                buoy_configs.append(row['BuoyConfig'])
            
            # Count physical buoys by (base, modules)
            operation_physical = defaultdict(int)
            for config in buoy_configs:
                parsed = parse_config(config)
                physical_id = f"{parsed['base']}{parsed['modules']}"
                operation_physical[physical_id] += 1
            
            # Track max needed across all operations in this line
            for physical_id, count in operation_physical.items():
                physical_buoys_needed[physical_id] = max(
                    physical_buoys_needed[physical_id],
                    count
                )
        
        line_physical_counts[line_id] = sum(physical_buoys_needed.values())
        line_physical_details[line_id] = dict(physical_buoys_needed)
    
    # Calculate max across all lines
    family_counts = defaultdict(int)
    for line_id, buoys in line_physical_details.items():
        for physical_id, count in buoys.items():
            family_counts[physical_id] = max(family_counts[physical_id], count)
    
    # Convert physical_id back to base codes for reporting
    base_code_counts = defaultdict(int)
    for physical_id, count in family_counts.items():
        base_code = physical_id[:2]  # First 2 chars (BA, BB, BC, BD)
        base_code_counts[base_code] += count
    
    return {
        'total_physical': sum(family_counts.values()),
        'by_physical_id': dict(family_counts),
        'by_base_family': dict(base_code_counts),
        'by_line': line_physical_counts,
        'details_by_line': line_physical_details
    }

# ============ COST CALCULATIONS ============

def calculate_purchase_costs(physical_inventory: Dict, params: Dict) -> Dict:
    """Calculate buoy purchase costs"""
    costs = {}
    total_cost = 0.0
    
    uses_86t = False
    
    for base_code, count in physical_inventory['by_base_family'].items():
        if base_code in BUOY_FAMILIES:
            family_info = BUOY_FAMILIES[base_code]
            buoy_cost = family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY'] * count
            costs[base_code] = {
                'name': family_info['name'],
                'count': count,
                'buoyancy_per_unit': family_info['base_buoyancy'],
                'cost_per_unit': family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY'],
                'total_cost': buoy_cost
            }
            total_cost += buoy_cost
            
            if family_info['is_86t']:
                uses_86t = True
    
    # Add 86T mold cost if applicable
    mold_cost = params['COST_86T_MOLD'] if uses_86t else 0.0
    if uses_86t and 'BC' in costs:
        costs['BC']['mold_cost'] = params['COST_86T_MOLD']
        costs['BC']['mold_cost_per_unit'] = params['COST_86T_MOLD'] / costs['BC']['count']
    
    return {
        'by_family': costs,
        'total_buoyancy_cost': total_cost,
        'mold_cost': mold_cost,
        'total_purchase': total_cost + mold_cost,
        'physical_details': physical_inventory['by_physical_id']
    }

def calculate_reconfig_costs(allocation_df: pd.DataFrame, params: Dict) -> Dict:
    """Calculate reconfiguration costs across the campaign"""
    total_reconfig_cost = 0.0
    total_reconfig_time = 0.0
    reconfig_details = []
    
    # Group by line
    for line_id in sorted(allocation_df['LineID'].unique()):
        line_data = allocation_df[allocation_df['LineID'] == line_id].sort_values('Order')
        
        # Track reconfigurations within this line
        for i in range(len(line_data) - 1):
            curr_row = line_data.iloc[i]
            next_row = line_data.iloc[i + 1]
            
            # Get configurations
            if curr_row['IsSeries']:
                curr_configs = [curr_row['Buoy1_Config'], curr_row['Buoy2_Config']]
            else:
                curr_configs = [curr_row['BuoyConfig']]
            
            if next_row['IsSeries']:
                next_configs = [next_row['Buoy1_Config'], next_row['Buoy2_Config']]
            else:
                next_configs = [next_row['BuoyConfig']]
            
            # Calculate reconfiguration cost
            # Simplified: calculate cost for each config transition
            for curr_conf in curr_configs:
                # Find best match in next configs
                min_reconfig_time = float('inf')
                best_match = None
                
                for next_conf in next_configs:
                    reconfig_time = calculate_reconfig_time(curr_conf, next_conf, params)
                    if reconfig_time < min_reconfig_time:
                        min_reconfig_time = reconfig_time
                        best_match = (curr_conf, next_conf)
                
                if min_reconfig_time > 0 and min_reconfig_time < float('inf'):
                    reconfig_cost = min_reconfig_time * params['COST_PER_HOUR']
                    total_reconfig_time += min_reconfig_time
                    total_reconfig_cost += reconfig_cost
                    
                    reconfig_details.append({
                        'LineID': line_id,
                        'FromOrder': curr_row['Order'],
                        'ToOrder': next_row['Order'],
                        'FromConfig': best_match[0],
                        'ToConfig': best_match[1],
                        'Time_Hours': min_reconfig_time,
                        'Cost_USD': reconfig_cost
                    })
    
    return {
        'total_cost': total_reconfig_cost,
        'total_time_hours': total_reconfig_time,
        'details': pd.DataFrame(reconfig_details) if reconfig_details else pd.DataFrame()
    }

def calculate_collection_costs(reuse_df: pd.DataFrame, params: Dict) -> Dict:
    """Calculate MSV collection costs for intra-line reuse"""
    if reuse_df.empty:
        return {
            'num_collections': 0,
            'total_cost': 0.0
        }
    
    # Count unique collection points
    # Each collection point in reuse_df represents one MSV operation
    collection_points = reuse_df[['LineID', 'FromOrder']].drop_duplicates()
    num_collections = len(collection_points)
    
    return {
        'num_collections': num_collections,
        'total_cost': num_collections * params['COST_MSV_COLLECTION'],
        'details': collection_points
    }

# ============ MAIN ANALYSIS ============

def main():
    print("\n" + "=" * 80)
    print("FINANCIAL COST ANALYSIS")
    print("=" * 80)
    
    # Load parameters freshly from CSV
    params = load_financial_parameters()
    
    # Show loaded parameters
    print(f"\nUsing parameters from: {PARAMS_CSV}")
    print(f"  Cost per tonne: ${params['COST_PER_TONNE_BUOYANCY']:,.0f}")
    print(f"  86T mold cost: ${params['COST_86T_MOLD']:,.0f}")
    print(f"  MSV collection: ${params['COST_MSV_COLLECTION']:,.0f}")
    print(f"  Reconfiguration: ${params['COST_PER_HOUR']:,.0f}/hour")
    print(f"  Module change time: {params['TIME_MODULE_CHANGE']:.1f}h")
    print(f"  Shackle change time: {params['TIME_SHACKLE_CHANGE']:.1f}h")
    print(f"  String change time: {params['TIME_STRING_CHANGE']:.1f}h")
    
    # Load allocation results
    print("\n[1/5] Loading allocation results...")
    allocation = pd.read_csv('buoy_optimization_plan_19lines.csv')
    print(f"  Loaded {len(allocation)} operations")
    
    # Load reuse analysis (if available)
    try:
        reuse = pd.read_csv('buoy_plan_reuse_summary.csv')
        print(f"  Loaded {len(reuse)} intra-line reuse instances")
    except:
        reuse = pd.DataFrame()
        print("  No intra-line reuse data found")
    
    # Count physical buoys
    print("\n[2/5] Calculating physical buoy inventory...")
    physical_inventory = count_physical_buoys(allocation)
    
    print(f"\n  Physical buoys by base family:")
    for base_code, count in sorted(physical_inventory['by_base_family'].items()):
        family_name = BUOY_FAMILIES.get(base_code, {}).get('name', base_code)
        print(f"    {family_name} ({base_code}): {count} buoys")
    
    print(f"\n  Detailed breakdown (by module count):")
    for physical_id, count in sorted(physical_inventory['by_physical_id'].items()):
        base = physical_id[:2]
        module_count = physical_id[2]
        family_name = BUOY_FAMILIES.get(base, {}).get('name', base)
        print(f"    {physical_id} ({family_name} with {module_count} module(s)): {count} buoy(s)")
    
    print(f"\n  📦 TOTAL PHYSICAL BUOYS: {physical_inventory['total_physical']}")
    
    # Calculate costs
    print("\n[3/5] Calculating purchase costs...")
    purchase_costs = calculate_purchase_costs(physical_inventory, params)
    
    print("\n[4/5] Calculating reconfiguration costs...")
    reconfig_costs = calculate_reconfig_costs(allocation, params)
    
    print("\n[5/5] Calculating collection costs...")
    collection_costs = calculate_collection_costs(reuse, params)
    
    # ============ COST SUMMARY ============
    print("\n" + "=" * 80)
    print("FINANCIAL COST BREAKDOWN")
    print("=" * 80)
    
    print("\n💰 PURCHASE COSTS:")
    print("-" * 80)
    
    for base_code, info in sorted(purchase_costs['by_family'].items()):
        print(f"\n  {info['name']} ({base_code}):")
        print(f"    Quantity: {info['count']} buoys")
        print(f"    Buoyancy per unit: {info['buoyancy_per_unit']:.1f} tonnes")
        print(f"    Cost per unit: ${info['cost_per_unit']:,.0f}")
        print(f"    Subtotal: ${info['total_cost']:,.0f}")
        
        if 'mold_cost' in info:
            print(f"    Special mold cost: ${info['mold_cost']:,.0f}")
            print(f"    Mold cost per unit: ${info['mold_cost_per_unit']:,.0f}")
    
    print(f"\n  Total buoyancy cost: ${purchase_costs['total_buoyancy_cost']:,.0f}")
    if purchase_costs['mold_cost'] > 0:
        print(f"  86T mold cost:       ${purchase_costs['mold_cost']:,.0f}")
    print(f"  {'='*40}")
    print(f"  TOTAL PURCHASE:      ${purchase_costs['total_purchase']:,.0f}")
    
    print("\n\n🔧 RECONFIGURATION COSTS:")
    print("-" * 80)
    print(f"  Total reconfigurations: {len(reconfig_costs['details'])}")
    print(f"  Total time: {reconfig_costs['total_time_hours']:.1f} hours")
    print(f"  Total cost: ${reconfig_costs['total_cost']:,.0f}")
    
    if not reconfig_costs['details'].empty:
        # Show top reconfigurations
        top_reconfigs = reconfig_costs['details'].nlargest(5, 'Cost_USD')
        print(f"\n  Top 5 most expensive reconfigurations:")
        for _, row in top_reconfigs.iterrows():
            print(f"    {row['LineID']}: Order {row['FromOrder']} → {row['ToOrder']}")
            print(f"      {row['FromConfig']} → {row['ToConfig']}")
            print(f"      {row['Time_Hours']:.1f}h, ${row['Cost_USD']:,.0f}")
    
    print("\n\n🚢 MSV COLLECTION COSTS (Intra-Line Reuse):")
    print("-" * 80)
    print(f"  Mid-line collections: {collection_costs['num_collections']}")
    print(f"  Cost per collection: ${params['COST_MSV_COLLECTION']:,.0f}")
    print(f"  Total cost: ${collection_costs['total_cost']:,.0f}")
    
    if collection_costs['num_collections'] > 0:
        print(f"\n  Collection points:")
        for _, row in collection_costs['details'].iterrows():
            print(f"    {row['LineID']}: After Order {row['FromOrder']}")
    
    # ============ TOTAL CAMPAIGN COST ============
    print("\n\n" + "=" * 80)
    print("TOTAL CAMPAIGN COST")
    print("=" * 80)
    
    total_cost = (
        purchase_costs['total_purchase'] +
        reconfig_costs['total_cost'] +
        collection_costs['total_cost']
    )
    
    print(f"\n  Purchase (buoys + mold):     ${purchase_costs['total_purchase']:>15,.0f}")
    print(f"  Reconfiguration:             ${reconfig_costs['total_cost']:>15,.0f}")
    print(f"  MSV collections:             ${collection_costs['total_cost']:>15,.0f}")
    print(f"  {'='*42}")
    print(f"  TOTAL CAMPAIGN COST:         ${total_cost:>15,.0f}")
    
    # ============ COST BREAKDOWN BY PERCENTAGE ============
    print("\n\n📊 COST BREAKDOWN:")
    print("-" * 80)
    
    purchase_pct = (purchase_costs['total_purchase'] / total_cost) * 100
    reconfig_pct = (reconfig_costs['total_cost'] / total_cost) * 100
    collection_pct = (collection_costs['total_cost'] / total_cost) * 100
    
    print(f"  Purchase costs:        {purchase_pct:5.1f}%")
    print(f"  Reconfiguration costs: {reconfig_pct:5.1f}%")
    print(f"  Collection costs:      {collection_pct:5.1f}%")
    
    # ============ SAVE DETAILED REPORT ============
    print("\n\n" + "=" * 80)
    print("SAVING DETAILED REPORTS")
    print("=" * 80)
    
    # Create summary DataFrame
    summary = pd.DataFrame([{
        'Total_Physical_Buoys': physical_inventory['total_physical'],
        'Purchase_Cost_USD': purchase_costs['total_purchase'],
        'Reconfiguration_Cost_USD': reconfig_costs['total_cost'],
        'Collection_Cost_USD': collection_costs['total_cost'],
        'Total_Campaign_Cost_USD': total_cost,
        'Reconfiguration_Hours': reconfig_costs['total_time_hours'],
        'MSV_Collections': collection_costs['num_collections']
    }])
    
    summary.to_csv('cost_summary.csv', index=False)
    print(f"\n  ✓ Cost summary: cost_summary.csv")
    
    if not reconfig_costs['details'].empty:
        reconfig_costs['details'].to_csv('reconfiguration_details.csv', index=False)
        print(f"  ✓ Reconfiguration details: reconfiguration_details.csv")
    
    # Create inventory report
    inventory_report = []
    
    # Add base family summary
    for base_code, count in sorted(physical_inventory['by_base_family'].items()):
        if base_code in BUOY_FAMILIES:
            family_info = BUOY_FAMILIES[base_code]
            cost_info = purchase_costs['by_family'][base_code]
            
            inventory_report.append({
                'Physical_ID': f"{base_code} (all modules)",
                'Buoy_Family': family_info['name'],
                'Quantity': count,
                'Base_Buoyancy_Tonnes': family_info['base_buoyancy'],
                'Cost_Per_Unit_USD': cost_info['cost_per_unit'],
                'Total_Cost_USD': cost_info['total_cost'],
                'Is_86T': 'Yes' if family_info['is_86t'] else 'No'
            })
    
    # Add detailed breakdown by module count
    for physical_id, count in sorted(purchase_costs['physical_details'].items()):
        base = physical_id[:2]
        module_count = physical_id[2] if len(physical_id) > 2 else '0'
        
        if base in BUOY_FAMILIES:
            family_info = BUOY_FAMILIES[base]
            
            inventory_report.append({
                'Physical_ID': physical_id,
                'Buoy_Family': f"{family_info['name']} ({module_count} modules)",
                'Quantity': count,
                'Base_Buoyancy_Tonnes': family_info['base_buoyancy'],
                'Cost_Per_Unit_USD': family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY'],
                'Total_Cost_USD': family_info['base_buoyancy'] * params['COST_PER_TONNE_BUOYANCY'] * count,
                'Is_86T': 'Yes' if family_info['is_86t'] else 'No'
            })
    
    inventory_df = pd.DataFrame(inventory_report)
    inventory_df.to_csv('physical_inventory_costs.csv', index=False)
    print(f"  ✓ Physical inventory: physical_inventory_costs.csv")
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    
    print(f"\n💰 CAMPAIGN TOTAL: ${total_cost:,.0f}")
    print(f"📦 Physical Buoys: {physical_inventory['total_physical']}")
    print(f"🔧 Reconfigurations: {len(reconfig_costs['details'])} ({reconfig_costs['total_time_hours']:.1f} hours)")
    print(f"🚢 MSV Collections: {collection_costs['num_collections']}")

if __name__ == "__main__":
    main()
