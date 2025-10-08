"""
Analyze buoy optimization results to determine exact purchasing requirements
"""

import pandas as pd
from collections import defaultdict

# Load the optimization results
results = pd.read_csv('buoy_optimization_plan_19lines.csv')

print("=" * 80)
print("BUOY PURCHASING REQUIREMENTS")
print("=" * 80)

# Track buoy usage by line
# Key insight: Within a line, operations are SEQUENTIAL
# So we need the MAX number of each buoy config needed in any SINGLE operation
# Then take the MAX across all lines (since buoys are collected/reused between lines)

line_max_per_config = {}  # line_id -> {buoy_config: max_count_in_any_operation}

for line_id in results['LineID'].unique():
    line_data = results[results['LineID'] == line_id]
    line_max_per_config[line_id] = defaultdict(int)
    
    # For each operation in this line, count buoy configs needed
    for _, row in line_data.iterrows():
        operation_buoy_count = defaultdict(int)
        
        if row['IsSeries']:
            # 2-buoy series
            buoy1 = f"{row['Buoy1_Name']} [{row['Buoy1_Config']}]"
            buoy2 = f"{row['Buoy2_Name']} [{row['Buoy2_Config']}]"
            operation_buoy_count[buoy1] += 1
            operation_buoy_count[buoy2] += 1
        else:
            # Single buoy
            buoy = f"{row['BuoyName']} [{row['BuoyConfig']}]"
            operation_buoy_count[buoy] += 1
        
        # Update line maximum for each config
        for buoy_config, count in operation_buoy_count.items():
            line_max_per_config[line_id][buoy_config] = max(
                line_max_per_config[line_id][buoy_config], 
                count
            )

# Find maximum usage for each buoy configuration ACROSS all lines
max_usage = defaultdict(int)
for line_id, buoy_counts in line_max_per_config.items():
    for buoy, count in buoy_counts.items():
        max_usage[buoy] = max(max_usage[buoy], count)

# Calculate total buoys needed
total_buoys = sum(max_usage.values())

print(f"\n📊 TOTAL PHYSICAL BUOYS TO PURCHASE: {total_buoys}\n")

# Group by buoy family
buoy_families = defaultdict(list)
for buoy_full, count in sorted(max_usage.items()):
    # Extract name and config
    name = buoy_full.split('[')[0].strip()
    config = buoy_full.split('[')[1].strip(']')
    buoy_families[name].append((config, count))

print("=" * 80)
print("DETAILED BREAKDOWN BY BUOY TYPE")
print("=" * 80)

family_totals = {}
for family_name in sorted(buoy_families.keys()):
    configs = buoy_families[family_name]
    family_total = sum(count for _, count in configs)
    family_totals[family_name] = family_total
    
    print(f"\n🔹 {family_name}")
    print(f"   Subtotal: {family_total} buoys")
    print(f"   Configurations needed:")
    
    for config, count in sorted(configs):
        print(f"      • {config}: {count} buoy{'s' if count > 1 else ''}")

print("\n" + "=" * 80)
print("SUMMARY BY FAMILY")
print("=" * 80)
for family, total in sorted(family_totals.items(), key=lambda x: -x[1]):
    print(f"  {family:40s} {total:2d} buoys")

print(f"\n  {'TOTAL':40s} {total_buoys:2d} buoys")

# Show which lines require the most buoys
print("\n" + "=" * 80)
print("PEAK BUOY USAGE BY LINE")
print("=" * 80)

line_totals = {}
for line_id, buoy_counts in line_max_per_config.items():
    line_totals[line_id] = sum(buoy_counts.values())

for line_id in sorted(line_totals.keys(), key=lambda x: int(x.split('_')[1])):
    total = line_totals[line_id]
    marker = " ⭐ PEAK" if total == max(line_totals.values()) else ""
    print(f"  {line_id}: {total:2d} buoys{marker}")

print("\n" + "=" * 80)
print("PURCHASING CHECKLIST")
print("=" * 80)
print("\n✓ Order the following buoys:\n")

purchase_list = []
for family_name in sorted(buoy_families.keys()):
    configs = buoy_families[family_name]
    for config, count in sorted(configs):
        purchase_list.append({
            'Buoy Type': family_name,
            'Configuration': config,
            'Quantity': count
        })

purchase_df = pd.DataFrame(purchase_list)
print(purchase_df.to_string(index=False))

# Save to CSV
purchase_df.to_csv('buoy_purchase_list.csv', index=False)
print("\n✓ Purchase list saved to: buoy_purchase_list.csv")

print("\n" + "=" * 80)
