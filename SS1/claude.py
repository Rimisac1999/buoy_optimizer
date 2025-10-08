import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass

@dataclass
class BuoyConfig:
    name: str
    base_upthrust: float
    shackle_cnt: int
    shackle_downthrust: float
    module_sub: int
    module_upthrust: float
    final_upthrust: float
    diff_factor: int

@dataclass
class InstallationItem:
    flowline: str
    tag: str
    comp_d: float
    sub_w: float
    sf_1: float
    sf_0: float
    type: str
    order: int

def load_installation_data(csv_data: str) -> pd.DataFrame:
    """Load and parse installation data from CSV string"""
    from io import StringIO
    df = pd.read_csv(StringIO(csv_data), sep='\t')
    df = df.sort_values('Order')
    return df

def load_buoy_configs() -> List[BuoyConfig]:
    """Load available buoy configurations"""
    buoys = [
        BuoyConfig("Tandem Big 3m BA0.0", 50.8, 0, 1.5, 0, 0, 50.8, 0),
        BuoyConfig("Tandem Big 3m BA0.1", 50.8, 1, 1.5, 0, 0, 49.3, 1),
        BuoyConfig("Tandem Big 3m BA0.2", 50.8, 2, 1.5, 0, 0, 47.8, 1),
        BuoyConfig("Tandem Small 3m BB0.0", 44.5, 0, 1.5, 0, 0, 44.5, 0),
        BuoyConfig("Tandem Small 3m BB0.1", 44.5, 1, 1.5, 0, 0, 43, 1),
        BuoyConfig("Tandem Small 3m BB0.2", 44.5, 2, 1.5, 0, 0, 41.5, 1),
        BuoyConfig("Single Big (4.5 m) BC0.1", 86, 0, 1.5, 0, 0, 86, 0),
        BuoyConfig("Single Big (4.5 m) BC0.2", 86, 1, 1.5, 0, 0, 84.5, 1),
        BuoyConfig("Single Big (4.5 m) BC0.3", 86, 2, 1.5, 0, 0, 83, 1),
        BuoyConfig("Single Big (4.5 m) BC1.1", 86, 0, 1.5, 1, 6.2, 79.8, 2),
        BuoyConfig("Single Big (4.5 m) BC1.2", 86, 1, 1.5, 1, 6.2, 78.3, 3),
        BuoyConfig("Single Big (4.5 m) BC1.3", 86, 2, 1.5, 1, 6.2, 76.8, 3),
        BuoyConfig("Single Big (4.5 m) BC2.0", 86, 0, 1.5, 2, 6.2, 73.6, 2),
        BuoyConfig("Single Big (4.5 m) BC2.1", 86, 1, 1.5, 2, 6.2, 72.1, 3),
        BuoyConfig("Single Big (4.5 m) BC2.2", 86, 2, 1.5, 2, 6.2, 70.6, 3),
        BuoyConfig("Single Small (3.0 m) BD0.0", 38, 0, 1.5, 0, 0, 38, 0),
        BuoyConfig("Single Small (3.0 m) BD0.1", 38, 1, 1.5, 0, 0, 36.5, 1),
        BuoyConfig("Single Small (3.0 m) BD0.2", 38, 2, 1.5, 0, 0, 35, 1),
        BuoyConfig("Single Small (3.0 m) BD1.0", 38, 0, 1.5, 1, 4.8, 33.2, 2),
        BuoyConfig("Single Small (3.0 m) BD1.1", 38, 1, 1.5, 1, 4.8, 31.7, 3),
        BuoyConfig("Single Small (3.0 m) BD1.2", 38, 2, 1.5, 1, 4.8, 30.2, 3),
        BuoyConfig("Single Small (3.0 m) BD2.0", 38, 0, 1.5, 2, 4.8, 28.4, 2),
        BuoyConfig("Single Small (3.0 m) BD2.1", 38, 1, 1.5, 2, 4.8, 26.9, 3),
        BuoyConfig("Single Small (3.0 m) BD2.2", 38, 2, 1.5, 2, 4.8, 25.4, 3),
    ]
    return buoys

def identify_flowlines(df: pd.DataFrame) -> Dict[str, List[int]]:
    """Group installation items by flowline"""
    flowlines = {}
    for _, row in df.iterrows():
        flowline = row['Flowline']
        if flowline not in flowlines:
            flowlines[flowline] = []
        flowlines[flowline].append(row['Order'])
    return flowlines

def analyze_installation_sequence(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze installation sequence and identify when buoys can be collected"""
    df['FlowlineBase'] = df['Flowline'].str.extract(r'(\d+-\d+"-[A-Z]+-\d+)')[0]
    df['CanCollectBuoy'] = False
    
    # Group by flowline base (without suffix)
    for flowline_base in df['FlowlineBase'].unique():
        flowline_items = df[df['FlowlineBase'] == flowline_base].sort_values('Order')
        
        # Check if last item in flowline is Laydown
        if len(flowline_items) > 0 and flowline_items.iloc[-1]['TYPE'] == 'Laydown':
            df.loc[flowline_items.iloc[-1].name, 'CanCollectBuoy'] = True
    
    return df

def find_best_buoy(required_upthrust: float, buoys: List[BuoyConfig], 
                   tolerance: float = 5.0) -> Tuple[BuoyConfig, float]:
    """Find best matching buoy for required upthrust with tolerance"""
    best_buoy = None
    best_diff = float('inf')
    
    for buoy in buoys:
        diff = abs(buoy.final_upthrust - required_upthrust)
        # Prefer buoy that meets or slightly exceeds requirement
        if buoy.final_upthrust >= required_upthrust - tolerance:
            if diff < best_diff:
                best_diff = diff
                best_buoy = buoy
    
    return best_buoy, best_diff

def optimize_buoy_allocation(df: pd.DataFrame, buoys: List[BuoyConfig]) -> pd.DataFrame:
    """Optimize buoy allocation to minimize count and reconfigurations"""
    results = []
    buoy_inventory = {}  # Track available buoys
    buoy_in_use = {}  # Track which buoys are in use on which flowline
    
    for _, row in df.iterrows():
        required_upthrust = row['Sub W']
        flowline = row['FlowlineBase']
        install_type = row['TYPE']
        order = row['Order']
        can_collect = row['CanCollectBuoy']
        
        # Find best buoy for this requirement
        best_buoy, diff = find_best_buoy(required_upthrust, buoys)
        
        # Check if we can reuse a buoy from inventory
        buoy_source = "NEW"
        reused_from = None
        
        for inv_buoy_name, inv_count in buoy_inventory.items():
            if inv_count > 0 and inv_buoy_name == best_buoy.name:
                buoy_source = "REUSED"
                buoy_inventory[inv_buoy_name] -= 1
                break
        
        # Allocate new buoy if needed
        if buoy_source == "NEW":
            if best_buoy.name not in buoy_inventory:
                buoy_inventory[best_buoy.name] = 0
        
        # Track buoy in use
        if flowline not in buoy_in_use:
            buoy_in_use[flowline] = []
        buoy_in_use[flowline].append(best_buoy.name)
        
        # Collect buoy after laydown
        if can_collect and flowline in buoy_in_use:
            for used_buoy in buoy_in_use[flowline]:
                if used_buoy not in buoy_inventory:
                    buoy_inventory[used_buoy] = 0
                buoy_inventory[used_buoy] += 1
            buoy_in_use[flowline] = []
        
        results.append({
            'Order': order,
            'Flowline': row['Flowline'],
            'TAG': row['TAG'],
            'TYPE': install_type,
            'Required_Upthrust': required_upthrust,
            'Buoy_Config': best_buoy.name,
            'Buoy_Upthrust': best_buoy.final_upthrust,
            'Difference': diff,
            'Source': buoy_source,
            'Can_Collect': can_collect
        })
    
    return pd.DataFrame(results), buoy_inventory

def calculate_buoy_summary(results_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate summary of buoys needed"""
    # Count maximum simultaneous usage
    buoy_counts = results_df['Buoy_Config'].value_counts()
    
    summary = pd.DataFrame({
        'Buoy_Config': buoy_counts.index,
        'Max_Simultaneous': buoy_counts.values
    })
    
    return summary

# Main execution
if __name__ == "__main__":
    # Sample CSV data (replace with your actual data)
    csv_data = """Comp D	Sub W	Flowline	TAG	CNT	1SF	0SF	TYPE	Order
86.44576323	88.44576323	31-12"-PR-10-0201	31‐FT‐10‐0201	X	86.4	86	Laydown	2
83.57284227	85.57284227	31-12"-PR-10-0201	31‐FT‐10‐1201	X	83.6	83	Initiation	1"""
    
    # Load data
    print("Loading installation data...")
    df = load_installation_data(csv_data)
    
    # Load buoy configurations
    buoys = load_buoy_configs()
    
    # Analyze sequence
    print("Analyzing installation sequence...")
    df = analyze_installation_sequence(df)
    
    # Optimize buoy allocation
    print("Optimizing buoy allocation...")
    results_df, final_inventory = optimize_buoy_allocation(df, buoys)
    
    # Calculate summary
    summary = calculate_buoy_summary(results_df)
    
    # Display results
    print("\n=== DETAILED ALLOCATION ===")
    print(results_df.to_string(index=False))
    
    print("\n=== BUOY SUMMARY ===")
    print(summary.to_string(index=False))
    
    print(f"\n=== TOTAL UNIQUE BUOYS NEEDED: {len(summary)} ===")
    print(f"Total buoys to purchase: {summary['Max_Simultaneous'].sum()}")
    
    print("\n=== FINAL INVENTORY (Available after campaign) ===")
    for buoy, count in final_inventory.items():
        if count > 0:
            print(f"{buoy}: {count}")