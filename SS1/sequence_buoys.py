# pip install ortools pandas

import pandas as pd
from ortools.sat.python import cp_model
import math
import os

# ---------------- USER SETTINGS ----------------
PLETS_CSV = "plets.csv"            # your sequence (Order, TYPE, Sub W, Flowline, TAG, ...)
BUOYS_CSV = "buoy_configs.csv"     # your Name, BuoyConfig, FinalUpThrust, DiffFactor, Shackles, Modules, ...

# Which rows need buoy compensation? (common: ILT + PLET ends like Initiation/Laydown)
TYPES_TO_INCLUDE = {"ILT", "Initiation", "Laydown"}   # change to {"ILT"} if you only want ILTs.

# Target down-thrust window (t)
DOWN_MIN = 1.5
DOWN_MAX = 3.0

# Unit conversion for Sub W -> tonnes
UNIT_W_TO_T = 1.0   # if Sub W is kN, set to 1/9.81

# Cost weights (tune to your deck reality)
COST_BUY_NAME        = 100.0   # penalty per unique buoy "Name" used (inventory)
COST_BASE_SWITCH     = 1.0     # base cost whenever config changes op-to-op
COST_SWITCH_NAME     = 10.0    # extra if buoy "Name" changes (e.g., Single→Tandem or model family swap)
COST_DELTA_SHACKLES  = 1.0     # per absolute delta in ShackleCNT
COST_DELTA_MODULES   = 1.0     # per absolute delta in ModuleSUB
COST_DIFF_WEIGHT     = 1.0     # weight on (DiffFrom + DiffTo) when switching
COST_USE_TANDEM_STEP = 0.5     # small handling penalty when using a "Tandem ..." config at a step

MAX_SOLVE_TIME_S     = 30.0
NUM_WORKERS          = 8

OUT_CSV = "buoy_plan.csv"

# ------------------------------------------------

def load_operations(path):
    df = pd.read_csv(path)
    # Clean/normalize
    df["TYPE"] = df["TYPE"].astype(str).str.strip().str.title()
    # Keep only requested types
    df = df[df["TYPE"].isin(TYPES_TO_INCLUDE)].copy()
    # Use Sub W as the submerged weight
    df["W_t"] = df["Sub W"].astype(float) * UNIT_W_TO_T
    # Order
    df["Order"] = df["Order"].astype(int)
    df = df.sort_values("Order").reset_index(drop=True)
    return df

def load_buoy_configs(path):
    # Expect columns:
    # Name, BuoyConfig, BaseUpthrust, ShackleCNT, ShackleDownThrust, ModuleSUB, ModuleUpThrust, FinalUpThrust, DiffFactor
    bc = pd.read_csv(path, sep=",")
    # Normalize
    bc["Name"] = bc["Name"].astype(str).str.strip()
    bc["BuoyConfig"] = bc["BuoyConfig"].astype(str).str.strip()
    for col in ["FinalUpThrust", "DiffFactor", "ShackleCNT", "ModuleSUB"]:
        bc[col] = pd.to_numeric(bc[col], errors="coerce")
    # Infer series count from Name (Single vs Tandem). Adjust if your naming differs.
    def series_count(name):
        n = name.lower()
        if "tandem" in n: return 2
        if "single" in n: return 1
        # Fallback: assume 1 if unknown
        return 1
    bc["Series"] = bc["Name"].apply(series_count)
    return bc

def feasible_configs_for_weight(W_t, buoy_df):
    # Feasible if W - FinalUpThrust in [DOWN_MIN, DOWN_MAX] and Series in {1,2}
    feas = buoy_df[
        (W_t - buoy_df["FinalUpThrust"] >= DOWN_MIN - 1e-6) &
        (W_t - buoy_df["FinalUpThrust"] <= DOWN_MAX + 1e-6) &
        (buoy_df["Series"].isin([1,2]))
    ].index.tolist()
    return feas

def reconfig_cost(rowA, rowB):
    # Cost to move from config A to config B between consecutive ops.
    # Components:
    #  - base switch cost
    #  - name change (big)
    #  - shackle delta
    #  - module delta
    #  - "difficulty" perception (sum of DiffFactors)
    c = 0.0
    c += COST_BASE_SWITCH
    if rowA["Name"] != rowB["Name"]:
        c += COST_SWITCH_NAME
    c += COST_DELTA_SHACKLES * abs(float(rowA["ShackleCNT"]) - float(rowB["ShackleCNT"]))
    c += COST_DELTA_MODULES  * abs(float(rowA["ModuleSUB"])   - float(rowB["ModuleSUB"]))
    c += COST_DIFF_WEIGHT    * (float(rowA["DiffFactor"]) + float(rowB["DiffFactor"]))
    # Per-step handling bias for tandem usage at the *next* step
    if rowB["Series"] == 2:
        c += COST_USE_TANDEM_STEP
    return c

def build_and_solve(ops_df, buoy_df):
    model = cp_model.CpModel()

    # Indexing
    ops = ops_df.reset_index(drop=True)
    buoys = buoy_df.reset_index()  # ensure integer index 0..M-1
    N = len(ops)
    M = len(buoys)

    # Precompute feasible config lists for each op
    feas = {}
    for i in range(N):
        W_t = float(ops.at[i, "W_t"])
        feas[i] = feasible_configs_for_weight(W_t, buoys)
        if not feas[i]:
            # Give a helpful hint with closest options
            # (find nearest FinalUpThrusts to meet window)
            # Needed buoy = ~ W_t - target_down; pick target ~ 2.25 mid-window
            target_up = W_t - 2.25
            buoys["up_err"] = (buoys["FinalUpThrust"] - target_up).abs()
            close = buoys.nsmallest(5, "up_err")[["Name","BuoyConfig","FinalUpThrust"]]
            raise RuntimeError(
                f"No feasible buoy config for op {i} (Order={ops.at[i,'Order']}, TYPE={ops.at[i,'TYPE']}, "
                f"W={W_t:.2f} t). Check units (UNIT_W_TO_T) or expand buoy set.\n"
                f"Closest by upthrust:\n{close.to_string(index=False)}"
            )

    # Decision vars x[i,c] ∈ {0,1}
    x = {}
    for i in range(N):
        for c in feas[i]:
            x[(i,c)] = model.NewBoolVar(f"x_{i}_{c}")

    # One config per operation
    for i in range(N):
        model.Add(sum(x[(i,c)] for c in feas[i]) == 1)

    # Inventory y[name] ∈ {0,1} if any config with that Name is used
    unique_names = sorted(buoys["Name"].unique().tolist())
    y = {name: model.NewBoolVar(f"y_{name}") for name in unique_names}

    for name in unique_names:
        uses = []
        name_rows = buoys[buoys["Name"] == name].index.tolist()
        for i in range(N):
            for c in feas[i]:
                if c in name_rows:
                    uses.append(x[(i,c)])
        if uses:
            model.AddMaxEquality(y[name], uses)
        else:
            model.Add(y[name] == 0)

    # Transition vars z[i,c,d] for adjacent operations
    z = {}
    for i in range(N - 1):
        for c in feas[i]:
            for d in feas[i+1]:
                var = model.NewBoolVar(f"z_{i}_{c}_{d}")
                z[(i,c,d)] = var
                model.Add(var <= x[(i,c)])
                model.Add(var <= x[(i+1,d)])

        # Exactly one (c,d) per adjacent pair
        model.Add(sum(z[(i,c,d)] for c in feas[i] for d in feas[i+1]) == 1)

    # Objective: purchase + reconfiguration
    # Purchase cost
    purchase_cost = sum(COST_BUY_NAME * y[name] for name in unique_names)

    # Reconfig cost
    reconfig_terms = []
    for i in range(N - 1):
        for c in feas[i]:
            for d in feas[i+1]:
                rc = reconfig_cost(buoys.loc[c], buoys.loc[d])
                if rc != 0.0:
                    # Scale to int to help CP-SAT
                    reconfig_terms.append(int(1000 * rc) * z[(i,c,d)])

    obj = int(1000 * COST_BUY_NAME) * sum(y.values()) + sum(reconfig_terms)
    model.Minimize(obj)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVE_TIME_S
    solver.parameters.num_search_workers = NUM_WORKERS

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No solution found. Try adjusting costs or config set.")

    # Extract solution
    chosen_idx = []
    for i in range(N):
        chosen_c = None
        for c in feas[i]:
            if solver.Value(x[(i,c)]) == 1:
                chosen_c = c
                break
        chosen_idx.append(chosen_c)

    # Build report
    rows = []
    used_names = set()
    for i, c in enumerate(chosen_idx):
        W_t = float(ops.at[i, "W_t"])
        down = W_t - float(buoys.at[c, "FinalUpThrust"])
        name = buoys.at[c, "Name"]
        used_names.add(name)
        rows.append({
            "Order": int(ops.at[i, "Order"]),
            "TYPE":  ops.at[i, "TYPE"],
            "Flowline": ops.at[i, "Flowline"],
            "TAG":   ops.at[i, "TAG"],
            "W_t":   round(W_t, 3),
            "ChosenName": name,
            "BuoyConfig": buoys.at[c, "BuoyConfig"],
            "Series": int(buoys.at[c, "Series"]),
            "ShackleCNT": int(buoys.at[c, "ShackleCNT"]) if not math.isnan(buoys.at[c, "ShackleCNT"]) else 0,
            "ModuleSUB": int(buoys.at[c, "ModuleSUB"]) if not math.isnan(buoys.at[c, "ModuleSUB"]) else 0,
            "FinalUpThrust": round(float(buoys.at[c, "FinalUpThrust"]), 3),
            "DownThrust": round(down, 3),
        })

    plan_df = pd.DataFrame(rows).sort_values("Order").reset_index(drop=True)
    # Write to CSV for handover
    plan_df.to_csv(OUT_CSV, index=False)

    # Compute totals (rough)
    total_names = sum(int(solver.Value(y[n]) == 1) for n in unique_names)

    # Reconfig cost (float, not the scaled int)
    total_reconfig = 0.0
    for i in range(len(chosen_idx) - 1):
        cA, cB = chosen_idx[i], chosen_idx[i+1]
        total_reconfig += reconfig_cost(buoys.loc[cA], buoys.loc[cB])

    return plan_df, sorted(list(used_names)), total_names, total_reconfig, solver.StatusName(status)

def main():
    ops = load_operations(PLETS_CSV)
    buoys = load_buoy_configs(BUOYS_CSV)
    plan_df, used_names, n_names, reconfig_cost_total, status = build_and_solve(ops, buoys)

    print(f"Solve status: {status}")
    print(f"Unique buoy Names used: {n_names} -> {used_names}")
    print(f"Estimated reconfiguration cost: {reconfig_cost_total:.1f}")

    # Show a concise printout
    print("\n--- Chosen sequence ---")
    for _, r in plan_df.iterrows():
        print(f"Order {int(r['Order']):02d} | {r['TYPE']:<10} | W={r['W_t']:6.2f} t | "
              f"{r['ChosenName']} [{r['BuoyConfig']}] | Series={r['Series']} | "
              f"Up={r['FinalUpThrust']:6.2f} t -> Down={r['DownThrust']:5.2f} t")

    print(f"\nPlan saved to: {os.path.abspath(OUT_CSV)}")

if __name__ == "__main__":
    main()
