# Cost-Based Optimizer Enhancement

## Overview

This branch (`full_cost_optimizer`) implements **true cost-based optimization** where the optimizer minimizes **actual dollar costs** instead of just minimizing the number of physical buoys.

## The Problem

The original optimizer (on `main` branch) minimized the COUNT of buoys, treating all buoys equally. This meant:
- 1 buoy was always better than 2 buoys (even if the 1 buoy costs $1M and 2 buoys cost $900k total)
- Could not intelligently decide between:
  - **Option A:** 1x 86T buoy ($946k) + $50k mold = **$996k**
  - **Option B:** 2x 44.5T buoys @ $489k each = **$979k** ✅ (cheaper but more buoys!)

## The Solution

The cost-based optimizer uses **real dollar costs** in the objective function:

### Real Buoy Costs (Based on Buoyancy):
| Buoy Type | Base Buoyancy | Cost Formula | Cost per Buoy |
|-----------|---------------|--------------|---------------|
| BA (Tandem Big 3m) | 50.8t | 50.8 × $11,000 | **$558,800** |
| BB (Tandem Small 3m) | 44.5t | 44.5 × $11,000 | **$489,500** |
| BC (Single Big 4.5m) | 86.0t | 86.0 × $11,000 | **$946,000** |
| BD (Single Small 3.0m) | 38.0t | 38.0 × $11,000 | **$418,000** |

Plus: **$50,000 one-time mold cost** if any 86T (BC) buoys are purchased

### Reconfiguration Costs:
- Module change: 3 hours × $10,000/hr = **$30,000** per module
- Shackle change: 1 hour × $10,000/hr = **$10,000** per shackle
- Full string change: 5 hours × $10,000/hr = **$50,000**

## Results Comparison

### Count-Based Optimizer (main branch):
```
Physical Buoys: 6
- 2x BA0 (Tandem Big)
- 2x BB0 (Tandem Small) 
- 1x BC2 (Single Big)
- 1x BD1 (Single Small)

Purchase Cost: $3,510,600
```

### Cost-Based Optimizer (full_cost_optimizer branch):
```
Physical Buoys: 6
- 1x BA0 (Tandem Big)
- 1x BB0 (Tandem Small)
- 1x BC2 (Single Big)  
- 1x BD0 (Single Small)
- 1x BD1 (Single Small)
- 1x BD2 (Single Small)

Purchase Cost: $3,298,300
SAVINGS: $212,300 (6.4%)
```

## Key Insights

### What the Cost-Based Optimizer Discovered:
The optimizer realized that:
- **BD (Single Small) @ $418k** is much cheaper than **BB (Tandem Small) @ $489k**
- Instead of buying 2x BB0 buoys ($979k), it's cheaper to buy 3x BD buoys with different module counts ($1,254k total) but save elsewhere
- The overall system cost is minimized by diversifying BD module variants rather than buying multiple identical BB buoys

### Smart Trade-offs:
The cost-based optimizer can now intelligently decide:
- ✅ Buy more cheaper buoys instead of fewer expensive ones
- ✅ Whether the $50k mold cost for 86T is justified vs buying 2x smaller buoys
- ✅ Balance reconfiguration time/cost against purchasing additional buoys
- ✅ Optimize module/shackle configurations based on change costs

## Technical Implementation

### Key Changes:

1. **Load Financial Parameters:**
   ```python
   BUOY_FAMILIES = {
       'BA': {'base_buoyancy': 50.8, 'is_86t': False},
       'BB': {'base_buoyancy': 44.5, 'is_86t': False},
       'BC': {'base_buoyancy': 86.0, 'is_86t': True},   # Special mold cost
       'BD': {'base_buoyancy': 38.0, 'is_86t': False},
   }
   ```

2. **Calculate Real Dollar Costs:**
   ```python
   buoyancy_cost = family_info['base_buoyancy'] * COST_PER_TONNE_BUOYANCY
   # For 86T buoys, add amortized mold cost
   ```

3. **Updated Objective Function:**
   ```python
   # OLD: Minimize buoy COUNT
   purchase_cost = COST_BUY_BUOY * max_simultaneous
   
   # NEW: Minimize real DOLLAR COST
   total_purchase_cost = sum(buoy_costs) + (mold_cost if uses_86t else 0)
   model.Minimize(total_purchase_cost + reconfiguration_costs)
   ```

4. **Proper 86T Mold Handling:**
   - Created binary variable `uses_86t` 
   - Mold cost only applied once if ANY 86T buoys purchased
   - Allows optimizer to decide if mold investment is worthwhile

## Performance

- **Solve Time:** ~0.4 seconds (similar to count-based)
- **Solution Quality:** OPTIMAL (CP-SAT found proven optimal solution)
- **Cost Savings:** $212,300 (6.4% reduction)
- **Buoy Count:** Same (6 buoys) but smarter allocation

## How to Use

### Run the Cost-Based Optimizer:
```bash
git checkout full_cost_optimizer
python optimize_buoys.py
```

### Modify Financial Parameters:
Edit `financial_parameters.csv`:
```csv
Parameter,Value,Unit
COST_PER_TONNE_BUOYANCY,11000,USD/tonne
COST_86T_MOLD,50000,USD
COST_PER_HOUR,10000,USD/hour
```

The optimizer will automatically use the updated costs!

## Validation

✅ All down-thrust values within 1.5-3.0 tonne range  
✅ Proper MSV collection and reuse logic maintained  
✅ Real reconfiguration time/costs calculated  
✅ 86T mold cost properly amortized  
✅ Objective value matches actual purchase cost  

## Recommendation

**Merge this branch to main** to enable true cost-based optimization. The optimizer will continue to:
- Minimize MSV collections when cost-effective
- Reuse buoys between lines
- Handle intra-line reuse for long lines
- BUT NOW: Make purchasing decisions based on actual dollars, not just counting buoys

This represents a **significant improvement** in decision-making capability and can save substantial costs on future campaigns.
