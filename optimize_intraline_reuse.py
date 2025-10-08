"""
Intra-Line Buoy Reuse Optimizer

This script post-processes the results from optimize_buoys.py to enable
buoy collection and reuse WITHIN long lines (4+ operations).

IMPORTANT: This provides OPERATIONAL efficiency, not necessarily inventory reduction!
The original optimizer already assumes sequential operations can reuse buoys.
This script EXPLICITLY identifies collection points for field operations planning.
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

def optimize_intraline_reuse(df: pd.DataFrame, long_lines: Dict[str, int]) -> pd.DataFrame:
    """
    Identify explicit collection and reuse points within long lines.
    
    This provides operational planning clarity, not inventory reduction
    (the optimizer already handles sequential reuse).
    """
    df = df.copy()
    df['MidLineCollection'] = False  # Mid-line collection points
    df['BuoyReusedFromOrder'] = None
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
            print(f"   Collection points after local operation index: {collection_points}")
        
        # Track available buoys at each step
        buoy_pool = []  # List of (buoy_name, buoy_config, released_at_order)
        
        line_ops = line_data.reset_index(drop=True)
        
        for idx, row in line_ops.iterrows():
            order = row['Order']
            required_buoys = extract_buoy_list(row)
            
            # Try to match required buoys with available pool
            reused_buoys = []
            
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
                
                # Try reconfiguration match (same buoy type)
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
            
            # Report reuse
            if reused_buoys:
                for reuse in reused_buoys:
                    reconfig_note = " (reconfiguration needed)" if reuse['needs_reconfig'] else ""
                    print(f"   Order {order:2d}: Reusing {reuse['buoy'][0]} [{reuse['buoy'][1]}] from Order {reuse['from_order']}{reconfig_note}")
                    
                    # Update dataframe
                    df_idx = df[(df['LineID'] == line_id) & (df['Order'] == order)].index[0]
                    df.at[df_idx, 'BuoyReusedFromOrder'] = reuse['from_order']
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
                # Add current operation's buoys to pool for later reuse
                for buoy in required_buoys:
                    buoy_pool.append((buoy[0], buoy[1], order))
                
                # Mark as mid-line collection point
                df_idx = df[(df['LineID'] == line_id) & (df['Order'] == order)].index[0]
                df.at[df_idx, 'MidLineCollection'] = True
                
                print(f"   ✓ Collection point at Order {order}: {len(buoy_pool)} buoy(s) available for reuse")
    
    return df, pd.DataFrame(reuse_stats) if reuse_stats else pd.DataFrame()

# ============ MAIN ============

def main():
    print("=" * 80)
    print("INTRA-LINE BUOY REUSE ANALYSIS")
    print("=" * 80)
    print("\nNOTE: This analysis identifies explicit collection/reuse points")
    print("for operational planning. The original optimizer already handles")
    print("sequential reuse, so inventory savings may be minimal.")
    
    print("\n[1/3] Loading optimization results...")
    df = load_optimization_results(INPUT_PLAN_CSV)
    print(f"  Loaded {len(df)} operations from {df['LineID'].nunique()} lines")
    
    print("\n[2/3] Identifying long lines for intra-line collection...")
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
    
    print("\n[3/3] Identifying collection and reuse points...")
    optimized_df, reuse_stats = optimize_intraline_reuse(df, long_lines)
    
    # Save results
    optimized_df.to_csv(OUTPUT_PLAN_CSV, index=False)
    print(f"\n✓ Plan with collection points saved to: {OUTPUT_PLAN_CSV}")
    
    if not reuse_stats.empty:
        reuse_stats.to_csv(OUTPUT_SUMMARY_CSV, index=False)
        print(f"✓ Reuse tracking saved to: {OUTPUT_SUMMARY_CSV}")
    
    # Display results
    print("\n" + "=" * 80)
    print("OPERATIONAL BENEFITS")
    print("=" * 80)
    
    print(f"\n📋 Collection & Reuse Analysis:")
    print(f"   Mid-line collection points: {optimized_df['MidLineCollection'].sum()}")
    print(f"   Total reuse instances: {len(reuse_stats)}")
    
    if not reuse_stats.empty:
        reconfigs = reuse_stats['NeedsReconfig'].sum()
        exact_reuse = len(reuse_stats) - reconfigs
        print(f"   - Exact match reuse: {exact_reuse}")
        print(f"   - Requires reconfiguration: {reconfigs}")
        
        print(f"\n   💡 OPERATIONAL BENEFITS:")
        print(f"      • Explicit collection points for deck crew")
        print(f"      • Clear redeployment sequences")
        print(f"      • Reduced handling time ({len(reuse_stats)} fewer deployments)")
        print(f"      • Better logistics planning")
    
    # Show detailed allocation
    print("\n" + "=" * 80)
    print("DETAILED ALLOCATION WITH COLLECTION POINTS")
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
            if pd.notna(row.get('BuoyReusedFromOrder')):
                reuse_marker = f" [REUSED from Order {int(row['BuoyReusedFromOrder'])}]"
                if row.get('RequiresReconfiguration', False):
                    reuse_marker += " [RECONFIG]"
            
            # Collection markers
            collection_marker = ""
            if row.get('MidLineCollection', False):
                collection_marker = " [🔄 COLLECT for reuse]"
            elif row.get('CanCollectBuoys', False):
                collection_marker = " [📦 COLLECT & END LINE]"
            
            print(f"  Order {row['Order']:2d} | {row['TYPE']:12s} | "
                  f"SubW: {row['SubW_tonnes']:6.2f}t | "
                  f"{buoy_display:15s}{series_marker}{reuse_marker}{collection_marker}")
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    
    print(f"\n✓ This analysis provides explicit collection/reuse points for")
    print(f"  operational planning on long lines ({len(long_lines)} lines with {MIN_OPS_FOR_INTRALINE_REUSE}+ operations).")

if __name__ == "__main__":
    main()

