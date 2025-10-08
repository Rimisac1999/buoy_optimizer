# ACT_160 Buoy Campaign Optimization Suite

Complete optimization and cost analysis system for buoy allocation campaigns.

## Quick Start

### Run Complete Analysis:
```bash
python run_buoy_optimization.py
```

The script will ask for a scenario name and automatically:
1. Run optimization
2. Analyze intra-line reuse
3. Calculate all costs
4. Generate comprehensive report
5. Save everything to `Results/YourScenarioName/`

## Input Files Required

Place these in the same directory:
- `20251008_Data_From_Planning_and_TECH.csv` - Installation sequence
- `20251008_Buoys_Config_Table.csv` - Available buoy configurations
- `financial_parameters.csv` - Cost parameters (editable!)

## Financial Parameters

Edit `financial_parameters.csv` to adjust costs:
- Buoyancy cost per tonne
- 86T mold cost
- MSV collection cost
- Reconfiguration hourly rate
- Reconfiguration times (modules, shackles, strings)

## Understanding Physical Buoys vs Configurations

**Key Concept:** BC0.1, BC0.2, BC0.3 are ONE physical buoy!

- **Physical Buoy = Base Code + Module Count**
- Example: BC0 = Single Big with 0 modules
  - BC0.0 = BC0 with 0 shackles
  - BC0.1 = BC0 with 1 shackle (same physical buoy!)
  - BC0.2 = BC0 with 2 shackles (same physical buoy!)

- **BC1** = Single Big with 1 module (DIFFERENT physical buoy)

### Why This Matters:
- **Shackles:** Quick to add/remove (1 hour)
- **Modules:** Define the physical buoy (3 hours to change)
- **String:** Complete buoy swap (5 hours)

## Output Files

All saved to `Results/YourScenarioName/`:

### Financial:
- `SCENARIO_SUMMARY.csv` - One-line cost summary
- `PHYSICAL_INVENTORY.csv` - Exact buoys to purchase
- `RECONFIGURATIONS.csv` - All reconfiguration details
- `MSV_COLLECTIONS.csv` - Collection point details

### Operational:
- `buoy_optimization_plan_19lines.csv` - Base allocation
- `buoy_plan_with_intraline_reuse.csv` - With collection points marked
- `buoy_plan_reuse_summary.csv` - Reuse tracking

### Report:
- `COMPREHENSIVE_REPORT.md` - Complete analysis report

## Typical Results (Main Scenario)

**Physical Buoys:** 9  
**Total Campaign Cost:** ~$7.6M  
- Purchase: $5.9M (78%)
- Reconfiguration: $1.2M (16%)  
- MSV Collections: $0.5M (6%)

## Scripts Overview

- `run_buoy_optimization.py` - **MASTER SCRIPT** (run this!)
- `optimize_buoys.py` - Core optimization engine
- `optimize_intraline_reuse.py` - Intra-line collection analysis
- `financial_cost_analysis.py` - Standalone cost calculator
- `analyze_buoy_purchases.py` - Configuration-based purchase list

## Testing Different Scenarios

1. Modify buoy config table (e.g., remove 86T buoys)
2. Run: `python run_buoy_optimization.py`
3. Enter scenario name (e.g., "No_86T")
4. Review results in `Results/No_86T/`

Running again with same name creates versioned folder (No_86T_v2, etc.)

## Key Optimizations

1. **Minimize physical buoys** (primary)
2. **Minimize reconfigurations** (secondary)
3. **Balance MSV costs** vs inventory
4. **Sequential reuse** within and between lines
5. **Down-thrust compliance** (1.5-3.0 tonnes)

---

**All optimization results are mathematically optimal (CP-SAT solver)** ✓
