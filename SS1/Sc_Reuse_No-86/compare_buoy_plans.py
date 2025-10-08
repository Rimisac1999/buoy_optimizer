"""
Compare original and intra-line reuse optimized plans
"""

import pandas as pd
from collections import defaultdict

print("=" * 80)
print("COMPARING BUOY PLANS: ORIGINAL vs INTRA-LINE REUSE")
print("=" * 80)

# Load both plans
original = pd.read_csv('buoy_optimization_plan_19lines.csv')
optimized = pd.read_csv('buoy_plan_with_intraline_reuse.csv')

def count_total_buoys(df):
    """Count total unique buoys needed based on max per line"""
    line_max_per_config = {}
    
    for line_id in df['LineID'].unique():
        line_data = df[df['LineID'] == line_id]
        line_max_per_config[line_id] = defaultdict(int)
        
        for _, row in line_data.iterrows():
            operation_buoy_count = defaultdict(int)
            
            if row['IsSeries']:
                buoy1 = f"{row['Buoy1_Name']}|{row['Buoy1_Config']}"
                buoy2 = f"{row['Buoy2_Name']}|{row['Buoy2_Config']}"
                operation_buoy_count[buoy1] += 1
                operation_buoy_count[buoy2] += 1
            else:
                buoy = f"{row['BuoyName']}|{row['BuoyConfig']}"
                operation_buoy_count[buoy] += 1
            
            for buoy_config, count in operation_buoy_count.items():
                line_max_per_config[line_id][buoy_config] = max(
                    line_max_per_config[line_id][buoy_config], 
                    count
                )
    
    # Max across all lines
    max_usage = defaultdict(int)
    for line_id, buoy_counts in line_max_per_config.items():
        for buoy, count in buoy_counts.items():
            max_usage[buoy] = max(max_usage[buoy], count)
    
    return sum(max_usage.values()), max_usage, line_max_per_config

original_total, original_usage, original_lines = count_total_buoys(original)
optimized_total, optimized_usage, optimized_lines = count_total_buoys(optimized)

print(f"\n📊 TOTAL BUOY INVENTORY REQUIRED:")
print(f"   Original plan:              {original_total} buoys")
print(f"   With intra-line reuse:      {optimized_total} buoys")
print(f"   Savings:                    {original_total - optimized_total} buoys")

if original_total - optimized_total > 0:
    percent = ((original_total - optimized_total) / original_total) * 100
    print(f"   Reduction:                  {percent:.1f}%")

print("\n" + "=" * 80)
print("LINE-BY-LINE PEAK BUOY USAGE")
print("=" * 80)

print(f"\n{'Line ID':<15} {'Ops':<6} {'Original':<12} {'Optimized':<12} {'Savings'}")
print("-" * 80)

for line_id in sorted(original_lines.keys(), key=lambda x: int(x.split('_')[1])):
    ops = original[original['LineID'] == line_id].shape[0]
    orig_count = sum(original_lines[line_id].values())
    opt_count = sum(optimized_lines[line_id].values())
    savings = orig_count - opt_count
    
    marker = " 🎯" if savings > 0 else ""
    print(f"{line_id:<15} {ops:<6} {orig_count:<12} {opt_count:<12} {savings:+d}{marker}")

print("\n" + "=" * 80)
