# Buoy Optimization Report: expensive_86t_mold

Generated: 2025-10-08 16:35:22

================================================================================

## EXECUTIVE SUMMARY

**Total Campaign Cost:** $7,729,800

**Physical Buoys Required:** 9

**Operations:** 51
**Flowlines:** 19

## COST BREAKDOWN

| Category | Amount | Percentage |
|----------|--------|------------|
| Purchase (buoys + mold) | $6,379,800 | 82.5% |
| Reconfiguration | $1,350,000 | 17.5% |
| MSV Collections | $0 | 0.0% |
| **TOTAL** | **$7,729,800** | **100.0%** |

## PHYSICAL BUOY INVENTORY

| Physical ID | Buoy Family | Quantity | Buoyancy/Unit | Cost/Unit |
|-------------|-------------|----------|---------------|------------|
| BA0 | Tandem Big 3m (0 mod) | 1 | 50.8t | $558,800 |
| BB0 | Tandem Small 3m (0 mod) | 2 | 44.5t | $489,500 |
| BC0 | Single Big (4.5 m) (0 mod) | 1 | 86.0t | $946,000 |
| BC1 | Single Big (4.5 m) (1 mod) | 1 | 86.0t | $946,000 |
| BC2 | Single Big (4.5 m) (2 mod) | 1 | 86.0t | $946,000 |
| BD0 | Single Small (3.0 m) (0 mod) | 1 | 38.0t | $418,000 |
| BD1 | Single Small (3.0 m) (1 mod) | 1 | 38.0t | $418,000 |
| BD2 | Single Small (3.0 m) (2 mod) | 1 | 38.0t | $418,000 |

**Total:** 9 physical buoys

**86T Mold Cost:** $750,000 (one-time)

## RECONFIGURATION ANALYSIS

**Total Reconfigurations:** 30
**Total Time:** 135.0 hours
**Total Cost:** $1,350,000

**Top 5 Most Expensive Reconfigurations:**

20. Line_16: Order 37->38
   - BD2.2 -> BD0.1
   - 7.0h, $70,000

23. Line_16: Order 40->41
   - BD0.1 -> BD2.2
   - 7.0h, $70,000

24. Line_16: Order 41->42
   - BD2.2 -> BD0.1
   - 7.0h, $70,000

7. Line_07: Order 13->14
   - BD2.2 -> BC0.3
   - 5.0h, $50,000

9. Line_08: Order 18->19
   - BB0.2 -> BD0.0
   - 5.0h, $50,000

## INTRA-LINE REUSE (MSV Collections)

**Mid-Line Collections:** 0
**Cost per Collection:** $90,000
**Total Cost:** $0

## PARAMETERS USED

| Parameter | Value | Unit |
|-----------|-------|------|
| COLLECTION_INTERVAL | 2.0 | - |
| COST_86T_MOLD | 750000.0 | - |
| COST_MSV_COLLECTION | 90000.0 | - |
| COST_PER_HOUR | 10000.0 | - |
| COST_PER_TONNE_BUOYANCY | 11000.0 | - |
| DOWN_THRUST_MAX | 3.0 | - |
| DOWN_THRUST_MIN | 1.5 | - |
| MAX_SOLVE_TIME | 120.0 | - |
| MIN_OPS_FOR_INTRALINE_REUSE | 4.0 | - |
| NUM_WORKERS | 8.0 | - |
| TIME_MODULE_CHANGE | 3.0 | - |
| TIME_SHACKLE_CHANGE | 1.0 | - |
| TIME_STRING_CHANGE | 5.0 | - |

## GENERATED FILES

**Input Files:**
- 20251008_Data_From_Planning_and_TECH.csv
- 20251008_Buoys_Config_Table.csv
- financial_parameters.csv

**Output Files:**
- `COMPREHENSIVE_REPORT.md` - This report
- `buoy_optimization_plan_19lines.csv` - Line-by-line allocation
- `buoy_plan_with_intraline_reuse.csv` - With collection points
- `physical_inventory_costs.csv` - Purchase requirements
- `cost_summary.csv` - Cost overview
- `reconfiguration_details.csv` - All reconfigurations
- `buoy_plan_reuse_summary.csv` - Reuse tracking

---

**Report generated:** 2025-10-08 16:35:22
