# Buoy Counting Methods Explained

## The Apparent Contradiction

You noticed that different scripts are giving different buoy counts. Here's what's actually happening:

## Three Different Counting Methods:

### Method 1: Physical Buoys (optimize_buoys.py output = 12)
**Counts:** Total physical buoy units including duplicates
- Example: `BB0.0+BB0.0` = **2 physical buoys** of type BB0.0
- Example: If Line_08 uses `BB0.0+BB0.0` 3 times, that's 2 physical BB0.0 buoys (reused across 3 operations)
- **This is what the optimizer reports**

### Method 2: Unique Configurations (debug script = 5)
**Counts:** Number of distinct buoy configurations
- Line_16 might use: BD0.1+BA0.0, BD2.2+BC1.2, BD2.2+BC1.3
- That's 3 unique configurations
- Peak line has 5 unique configurations
- **This assumes unlimited reconfiguration between operations**

### Method 3: Sum of All Configs (compare_buoy_plans.py = 16)
**Counts:** Sum of max count needed for each unique config across all lines
- If BD0.1 is used max 4 times in any line, count 4
- If BA0.0 is used max 1 time, count 1
- Sum all: 16 buoys
- **This assumes NO reconfiguration allowed**

## What Does "12 Buoys" Actually Mean?

The optimizer's "12 buoys" means:

**You need to purchase 12 physical buoy units to handle the peak line (Line_16 or similar)**

Example breakdown for a peak line:
- Operation needs: `BD0.1+BA0.0` (2 physical buoys)
- Next operation needs: `BD0.1+BA0.0` (reuse same 2 buoys)
- Next operation needs: `BD2.2+BC1.2` (need 2 NEW buoys, now have 4 total)
- Etc.

The 12 represents the maximum PHYSICAL inventory on deck at any moment.

## Intra-Line Reuse Script Purpose

The `optimize_intraline_reuse.py` script:
- **Does NOT** change the base optimization (already optimal)
- **DOES** explicitly mark when to collect and redeploy buoys
- **Benefit:** Operational clarity for field crews
- **Benefit:** Shows which buoys can stay in water vs. return to deck

## The Correct Answer

**For purchasing: Use the analysis from `analyze_buoy_purchases.py`**

This correctly calculates: **16 unique buoy configurations needed**

Why 16 not 12?
- You need enough buoys to handle any single operation in isolation
- Some configs appear in multiple simultaneous operations within a line
- Example: If 3 sequential ILTs all use `BD0.1+BA0.0`, you still need 1x BD0.1 and 1x BA0.0 (with reconfiguration between ops)

## Recommendation

**Purchase 16 buoys as shown in `buoy_purchase_list.csv`**

The "12 buoys" from the optimizer is an intermediate calculation and shouldn't be used for procurement.

The intra-line reuse script is useful for:
- Operational planning
- Identifying when crews can collect/redeploy
- NOT for changing the purchasing decision
