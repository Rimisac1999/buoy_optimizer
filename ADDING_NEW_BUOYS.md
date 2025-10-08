# How to Add New Buoy Types (e.g., JSM BE, BF)

## The Problem (FIXED)

Previously, buoy types were **hardcoded** in the optimizer, making it impossible to add new types like JSM buoys without modifying the code.

## The Solution

The system is now **100% dynamic** - all buoy information is read from the CSV files.

## How to Add New Buoys (Example: JSM BE and BF)

### Step 1: Add Rows to `20251008_Buoys_Config_Table.csv`

Just add new rows with your JSM buoys. The optimizer will automatically detect them!

```csv
Name,BuoyConfig,BaseUpthrust,ShackleCNT,ModuleSUB,FinalUpThrust,DiffFactor
JSM Medium (BE),BE0.0,60.0,0,0,60.0,3
JSM Medium (BE),BE0.1,60.0,1,0,61.5,4
JSM Medium (BE),BE0.2,60.0,2,0,63.0,5
JSM Medium (BE),BE1.0,60.0,0,1,63.0,5
JSM Large (BF),BF0.0,75.0,0,0,75.0,3
JSM Large (BF),BF0.1,75.0,1,0,76.5,4
JSM Large (BF),BF0.2,75.0,2,0,78.0,5
JSM Large (BF),BF1.0,75.0,0,1,78.0,5
```

### Step 2: Run the Optimizer

That's it! No code changes needed.

```bash
python optimize_buoys.py
```

The optimizer will automatically:
- ✅ Detect BE and BF buoy families
- ✅ Calculate costs: BE = 60t × $11,000 = **$660,000**
- ✅ Calculate costs: BF = 75t × $11,000 = **$825,000**  
- ✅ Apply mold cost for BF (>=70t threshold)
- ✅ Use them in optimization decisions

### Example Output

```
Detected 6 buoy families from CSV:
  BA (Tandem Big 3m): 50.8t @ $558,800
  BB (Tandem Small 3m): 44.5t @ $489,500
  BC (Single Big (4.5 m)): 86.0t @ $946,000 [MOLD COST]
  BD (Single Small (3.0 m)): 38.0t @ $418,000
  BE (JSM Medium): 60.0t @ $660,000
  BF (JSM Large): 75.0t @ $825,000 [MOLD COST]
```

## How It Works

### 1. Automatic Detection
```python
# System reads BaseUpthrust from CSV
base_buoyancy = float(row['BaseUpthrust'])

# Automatically detects if mold is needed
needs_mold = base_buoyancy >= LARGE_BUOY_THRESHOLD  # 70t default
```

### 2. Dynamic Cost Calculation
```python
# Cost calculated from CSV data, not hardcoded
buoy_cost = base_buoyancy * COST_PER_TONNE_BUOYANCY

# Mold cost automatically added for large buoys
if needs_mold:
    total_cost += COST_LARGE_BUOY_MOLD
```

### 3. Intelligent Optimization
The optimizer will compare ALL buoy types and choose the cheapest option:
- **BE (60t) @ $660k** vs **BC (86t) @ $946k + $50k mold** vs **2x BB @ $979k total**
- Makes intelligent trade-offs based on **real dollar costs**

## Configurable Parameters

You can adjust these in `financial_parameters.csv`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `COST_PER_TONNE_BUOYANCY` | $11,000 | Cost per tonne |
| `LARGE_BUOY_THRESHOLD` | 70.0t | Buoys >= this need mold |
| `COST_86T_MOLD` | $50,000 | One-time mold cost |

### Example: Adjust Mold Threshold

If JSM BE (60t) also needs a mold, just change the threshold:

```csv
Parameter,Value,Unit,Description
LARGE_BUOY_THRESHOLD,55.0,tonnes,Buoys >= this size need special mold
```

Now both BE and BF will automatically get mold cost!

## What Can Be Configured

### In `20251008_Buoys_Config_Table.csv`:
- ✅ Add any buoy type (BA, BB, BC, BD, BE, BF, BG, ...)
- ✅ Set buoyancy (`BaseUpthrust`)
- ✅ Configure shackles, modules
- ✅ Set difficulty factors

### In `financial_parameters.csv`:
- ✅ Cost per tonne
- ✅ Large buoy threshold
- ✅ Mold cost
- ✅ Reconfiguration times/costs

## Series Combinations

The system also auto-generates series (2-buoy) combinations:
- BE + BA = 110.8t combined
- BF + BB = 119.5t combined
- BE + BE = 120t combined

All automatically calculated and optimized!

## Benefits

1. **No Code Changes:** Just update CSV files
2. **Automatic Detection:** System finds all buoy types
3. **Smart Optimization:** Uses real costs to choose best option
4. **Fully Flexible:** Add/remove/modify buoys anytime
5. **Extensible:** Works with any future buoy types

## Summary

**Before:** Hardcoded BA, BB, BC, BD only. Couldn't add JSM buoys.

**After:** Fully dynamic. Add BE, BF, BG, BH... anything! Just update the CSV.

No more "quite fucking annoying" hardcoding! 🎉
