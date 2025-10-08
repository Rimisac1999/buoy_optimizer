"""
Intra-Line Buoy Reuse Optimizer

This script post-processes the results from optimize_buoys.py to enable
buoy collection and reuse WITHIN long lines (4+ operations).

Key concept: For long lines, buoys from early operations can be collected
and reused for later operations in the same line, reducing total buoy inventory.
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# ============ CONFIGURATION ============
INPUT_PLAN_CSV = "buoy_optimization_plan_19lines.csv"
OUTPUT_PLAN_CSV = "buoy_plan_with_intraline_reuse.csv"
OUTPUT_SUMMARY_CSV = "buoy_plan_reuse_summary.csv"

# Minimum operations in a line to enable intra-line reuse
MIN_OPS_FOR_INTRALINE_REUSE = 4

# Collection point: after how many operations should we try to collect?
# e.g., 2 means: after ops 1-2, collect and reuse for ops 3+
COLLECTION_INTERVAL = 2

# ============ ANALYSIS ============

def load_optimization_results(filepath: str) -> pd.DataFrame:
    """Load results from optimize_buoys.py"""
    df = pd.read_csv(filepath)
    return df

def identify_long_lines(df: pd.DataFrame) -> Dict[str, int]:
    """Identify lines with enough operations for intra-line reuse"""
    line_counts = df.groupby('LineID').size().to_dict()
    long_lines = {line_id: count for line_id, count in line_counts.items() 
                  if count >= MIN_OPS_FOR_INTRALINE_REUSE}
    return long_lines

def extract_buoy_list(row: pd.Series) -> List[Tuple[str, str]]:
    """
    Extract list of physical buoys from a row.
    Returns: [(buoy_name, buoy_config), ...]
    """
    buoys = []
    
    if row['IsSeries']:
        # 2-buoy series
        buoys.append((row['Buoy1_Name'], row['Buoy1_Config']))
        buoys.append((row['Buoy2_Name'], row['Buoy2_Config']))
    else:
        # Single buoy
        buoys.append((row['BuoyName'], row['BuoyConfig']))
    
    return buoys

def can_reuse_buoy(buoy: Tuple[str, str], required_config: Tuple[str, str], 
                   reconfiguration_allowed: bool = True) -> bool:
    """
    Check if a buoy can be reused for a required configuration.
    
    Args:
        buoy: (name, config) of available buoy
        required_config: (name, config) of required buoy
        reconfiguration_allowed: If True, same buoy name can be reconfigured
    """
    buoy_name, buoy_config = buoy
    req_name, req_config = required_config
    
    if buoy_name == req_name:
        if buoy_config == req_config:
            # Exact match - ideal
            return True
        elif reconfiguration_allowed:
            # Same buoy type, different config - can reconfigure
            return True
    
    return False

def optimize_intraline_reuse(df: pd.DataFrame, long_lines: Dict[str, int]) -> pd.DataFrame:
    """
    Optimize buoy allocation within long lines by enabling mid-line collection and reuse.
    """
    df = df.copy()
    df['CollectionPoint'] = df['CanCollectBuoys']  # Start with end-of-line collection
    df['ReusedFromOperation'] = None
    df['RequiresReconfiguration'] = False
    
    reuse_stats = []
    
    for line_id, num_ops in long_lines.items():
        line_data = df[df['LineID'] == line_id].sort_values('Order').copy()
        
        print(f"\n🔍 Analyzing {line_id} ({num_ops} operations):")
        
        # Determine collection points (every COLLECTION_INTERVAL operations)
        collection_points = []
        for i in range(COLLECTION_INTERVAL, num_ops, COLLECTION_INTERVAL):
            if i < num_ops - 1:  # Don't add if it's the last operation
                collection_points.append(i)
        
        if collection_points:
            print(f"   Potential collection points after operations: {[i+1 for i in collection_points]}")
        
        # Track available buoys at each step
        buoy_pool = []  # List of (buoy_name, buoy_config, released_at_order)
        
        line_ops = line_data.reset_index(drop=True)
        
        for idx, row in line_ops.iterrows():
            order = row['Order']
            required_buoys = extract_buoy_list(row)
            
            # Try to match required buoys with available pool
            reused_buoys = []
            new_buoys = []
            
            for req_buoy in required_buoys:
                matched = False
                
                # Try exact match first
                for pool_idx, (pool_name, pool_config, released_order) in enumerate(buoy_pool):
                    if pool_name == req_buoy[0] and pool_config == req_buoy[1]:
                        reused_buoys.append({
                            'buoy': req_buoy,
                            'from_order': released_order,
                            'needs_reconfig': False
                        })
                        buoy_pool.pop(pool_idx)
                        matched = True
                        break
                
                # Try reconfiguration match
                if not matched:
                    for pool_idx, (pool_name, pool_config, released_order) in enumerate(buoy_pool):
                        if pool_name == req_buoy[0]:  # Same buoy type
                            reused_buoys.append({
                                'buoy': req_buoy,
                                'from_order': released_order,
                                'needs_reconfig': True
                            })
                            buoy_pool.pop(pool_idx)
                            matched = True
                            break
                
                if not matched:
                    new_buoys.append(req_buoy)
            
            # Report reuse
            if reused_buoys:
                for reuse in reused_buoys:
                    reconfig_note = " (reconfiguration needed)" if reuse['needs_reconfig'] else ""
                    print(f"   Order {order:2d}: Reusing {reuse['buoy'][0]} [{reuse['buoy'][1]}] from Order {reuse['from_order']}{reconfig_note}")
                    
                    # Update dataframe
                    df_idx = df[(df['LineID'] == line_id) & (df['Order'] == order)].index[0]
                    if df.at[df_idx, 'ReusedFromOperation'] is None:
                        df.at[df_idx, 'ReusedFromOperation'] = reuse['from_order']
                    if reuse['needs_reconfig']:
                        df.at[df_idx, 'RequiresReconfiguration'] = True
                    
                    reuse_stats.append({
                        'LineID': line_id,
                        'ToOrder': order,
                        'FromOrder': reuse['from_order'],
                        'BuoyName': reuse['buoy'][0],
                        'BuoyConfig': reuse['buoy'][1],
                        'NeedsReconfig': reuse['needs_reconfig']
                    })
            
            # Check if this is a collection point
            if idx in collection_points:
                # Add current operation's buoys to pool
                for buoy in required_buoys:
                    buoy_pool.append((buoy[0], buoy[1], order))
                
                # Mark as collection point
                df_idx = df[(df['LineID'] == line_id) & (df['Order'] == order)].index[0]
                df.at[df_idx, 'CollectionPoint'] = True
                
                print(f"   ✓ Collection point at Order {order}: {len(buoy_pool)} buoy(s) available for reuse")
    
    return df, pd.DataFrame(reuse_stats) if reuse_stats else pd.DataFrame()

def calculate_buoy_savings(original_df: pd.DataFrame, optimized_df: pd.DataFrame) -> Dict:
    """Calculate the reduction in buoy requirements"""
    
    # Calculate max simultaneous for original (total unique configs across whole line)
    original_line_max = {}
    original_line_phys = {}  # Physical count including duplicates
    
    for line_id in original_df['LineID'].unique():
        line_data = original_df[original_df['LineID'] == line_id]
        
        # Count physical buoys (not just unique configs)
        buoy_counter = defaultdict(int)
        for _, row in line_data.iterrows():
            if row['IsSeries']:
                buoy_counter[f"{row['Buoy1_Name']}|{row['Buoy1_Config']}"] += 1
                buoy_counter[f"{row['Buoy2_Name']}|{row['Buoy2_Config']}"] += 1
            else:
                buoy_counter[f"{row['BuoyName']}|{row['BuoyConfig']}"] += 1
        
        # Maximum of any single config in this line
        original_line_phys[line_id] = sum(buoy_counter.values())
        original_line_max[line_id] = max(buoy_counter.values()) if buoy_counter else 0
    
    # Calculate max simultaneous for optimized (with intra-line reuse)
    optimized_line_max = {}
    optimized_line_phys = {}
    
    for line_id in optimized_df['LineID'].unique():
        line_data = optimized_df[optimized_df['LineID'] == line_id].sort_values('Order')
        
        # Simulate buoy usage over time with collection points
        max_simultaneous = 0
        current_buoys = defaultdict(int)
        
        for idx, row in line_data.iterrows():
            # Add buoys needed for this operation (if not reused)
            operation_buoys = []
            if row['IsSeries']:
                operation_buoys.append(f"{row['Buoy1_Name']}|{row['Buoy1_Config']}")
                operation_buoys.append(f"{row['Buoy2_Name']}|{row['Buoy2_Config']}")
            else:
                operation_buoys.append(f"{row['BuoyName']}|{row['BuoyConfig']}")
            
            # Only add if not reused (reused buoys are already in current_buoys from previous ops)
            if pd.isna(row.get('ReusedFromOperation')):
                for buoy in operation_buoys:
                    current_buoys[buoy] += 1
            
            # Track maximum
            total_current = sum(current_buoys.values())
            max_simultaneous = max(max_simultaneous, total_current)
            
            # Check if we can collect after this operation
            if row.get('CollectionPoint', False) and not row['CanCollectBuoys']:
                # Mid-line collection - remove these buoys (they'll be reused later)
                for buoy in operation_buoys:
                    if current_buoys[buoy] > 0:
                        current_buoys[buoy] -= 1
            elif row['CanCollectBuoys']:
                # End of line - clear all
                current_buoys.clear()
        
        optimized_line_max[line_id] = max_simultaneous
        optimized_line_phys[line_id] = max_simultaneous
    
    # Total inventory needed = max across all lines
    original_max = max(original_line_phys.values()) if original_line_phys else 0
    optimized_max = max(optimized_line_phys.values()) if optimized_line_phys else 0
    
    return {
        'original_max': original_max,
        'optimized_max': optimized_max,
        'savings': original_max - optimized_max,
        'original_line_max': original_line_phys,
        'optimized_line_max': optimized_line_phys
    }

# ============ MAIN ============

def main():
    print("=" * 80)
    print("INTRA-LINE BUOY REUSE OPTIMIZER")
    print("=" * 80)
    
    print("\n[1/4] Loading optimization results...")
    df = load_optimization_results(INPUT_PLAN_CSV)
    print(f"  Loaded {len(df)} operations from {df['LineID'].nunique()} lines")
    
    print("\n[2/4] Identifying long lines for intra-line reuse...")
    long_lines = identify_long_lines(df)
    print(f"  Found {len(long_lines)} line(s) with {MIN_OPS_FOR_INTRALINE_REUSE}+ operations:")
    for line_id, count in sorted(long_lines.items()):
        print(f"    {line_id}: {count} operations")
    
    if not long_lines:
        print("\n  ℹ️  No lines long enough for intra-line reuse optimization.")
        print(f"     (Minimum {MIN_OPS_FOR_INTRALINE_REUSE} operations required)")
        print("\n  Using original allocation plan.")
        df.to_csv(OUTPUT_PLAN_CSV, index=False)
        return
    
    print("\n[3/4] Optimizing intra-line buoy reuse...")
    optimized_df, reuse_stats = optimize_intraline_reuse(df, long_lines)
    
    print("\n[4/4] Calculating savings...")
    savings = calculate_buoy_savings(df, optimized_df)
    
    # Save results
    optimized_df.to_csv(OUTPUT_PLAN_CSV, index=False)
    print(f"\n✓ Optimized plan saved to: {OUTPUT_PLAN_CSV}")
    
    if not reuse_stats.empty:
        reuse_stats.to_csv(OUTPUT_SUMMARY_CSV, index=False)
        print(f"✓ Reuse summary saved to: {OUTPUT_SUMMARY_CSV}")
    
    # Display results
    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS")
    print("=" * 80)
    
    print(f"\n📊 Buoy Requirements Comparison:")
    print(f"   Original maximum simultaneous buoys: {savings['original_max']}")
    print(f"   With intra-line reuse:                {savings['optimized_max']}")
    
    if savings['savings'] > 0:
        percent_savings = (savings['savings'] / savings['original_max']) * 100
        print(f"   💰 Savings:                           {savings['savings']} buoys ({percent_savings:.1f}% reduction)")
    elif savings['savings'] == 0:
        print(f"   ℹ️  No inventory savings (original plan already optimal)")
        print(f"      However, {len(reuse_stats)} buoy reuses were identified for operational efficiency")
    
    print(f"\n📋 Reuse Statistics:")
    print(f"   Total reuse instances: {len(reuse_stats)}")
    if not reuse_stats.empty:
        reconfigs = reuse_stats['NeedsReconfig'].sum()
        exact_reuse = len(reuse_stats) - reconfigs
        print(f"   - Exact match reuse: {exact_reuse}")
        print(f"   - Requires reconfiguration: {reconfigs}")
    
    # Show line-by-line comparison
    print("\n" + "=" * 80)
    print("LINE-BY-LINE BUOY REQUIREMENTS")
    print("=" * 80)
    
    print(f"\n{'Line ID':<20} {'Operations':<12} {'Original':<10} {'Optimized':<10} {'Savings'}")
    print("-" * 80)
    
    for line_id in sorted(savings['original_line_max'].keys(), key=lambda x: int(x.split('_')[1])):
        orig = savings['original_line_max'].get(line_id, 0)
        opt = savings['optimized_line_max'].get(line_id, 0)
        save = orig - opt
        ops = df[df['LineID'] == line_id].shape[0]
        
        marker = " ⭐" if save > 0 else ""
        print(f"{line_id:<20} {ops:<12} {orig:<10} {opt:<10} {save:+d}{marker}")
    
    # Show detailed allocation for long lines
    print("\n" + "=" * 80)
    print("DETAILED ALLOCATION FOR LONG LINES")
    print("=" * 80)
    
    for line_id in sorted(long_lines.keys(), key=lambda x: int(x.split('_')[1])):
        line_data = optimized_df[optimized_df['LineID'] == line_id].sort_values('Order')
        
        print(f"\n{line_id} ({len(line_data)} operations):")
        
        for _, row in line_data.iterrows():
            # Build buoy display
            if row['IsSeries']:
                buoy_display = f"{row['Buoy1_Config']}+{row['Buoy2_Config']}"
                series_marker = " [2 BUOYS]"
            else:
                buoy_display = f"{row['BuoyConfig']}"
                series_marker = ""
            
            # Reuse markers
            reuse_marker = ""
            if pd.notna(row.get('ReusedFromOperation')):
                reuse_marker = f" [REUSED from Order {int(row['ReusedFromOperation'])}]"
                if row.get('RequiresReconfiguration', False):
                    reuse_marker += " [RECONFIG]"
            
            # Collection marker
            collection_marker = ""
            if row.get('CollectionPoint', False):
                if row['CanCollectBuoys']:
                    collection_marker = " [COLLECT & END LINE]"
                else:
                    collection_marker = " [COLLECT for reuse]"
            
            print(f"  Order {row['Order']:2d} | {row['TYPE']:12s} | "
                  f"SubW: {row['SubW_tonnes']:6.2f}t | "
                  f"{buoy_display:15s}{series_marker}{reuse_marker}{collection_marker}")
    
    print("\n" + "=" * 80)
    print("OPTIMIZATION COMPLETE")
    print("=" * 80)
    
    if savings['savings'] > 0:
        print(f"\n✅ Intra-line reuse optimization reduced buoy requirements by {savings['savings']} buoy(s)!")
        print(f"   New total: {savings['optimized_max']} buoys (was {savings['original_max']})")
    elif not reuse_stats.empty:
        print(f"\n✓ Intra-line reuse analysis complete.")
        print(f"\n   💡 OPERATIONAL BENEFITS (even without inventory savings):")
        print(f"      • {len(reuse_stats)} buoy reuses identified")
        print(f"      • Reduced handling time (fewer buoy deployments)")
        print(f"      • Less wear on equipment (buoys stay in water longer)")
        print(f"      • Improved logistics (fewer trips to/from deck)")
    else:
        print(f"\n✓ No intra-line reuse opportunities found.")
        print(f"   Consider adjusting COLLECTION_INTERVAL parameter if needed.")

if __name__ == "__main__":
    main()
