"""
Clean up main directory by moving old/temporary files to archive
"""

import os
import shutil
from datetime import datetime

# Files to keep in main directory
KEEP_FILES = {
    # Input files
    '20251008_Data_From_Planning_and_TECH.csv',
    '20251008_Buoys_Config_Table.csv',
    'financial_parameters.csv',
    
    # Main scripts
    'run_buoy_optimization.py',
    'optimize_buoys.py',
    'optimize_intraline_reuse.py',
    'financial_cost_analysis.py',
    'analyze_buoy_purchases.py',
    
    # Documentation
    'README.md',
    'cleanup_main_directory.py',  # This script itself
    
    # Folders
    'Results',
    'Scenario_hors_86',
    'Sc_hors_86-V2',
    'Sc_Reuse_No-86',
    'SS1'
}

# Files to archive (move to Archive folder)
ARCHIVE_PATTERNS = [
    'buoy_optimization_plan*.csv',
    'buoy_plan_*.csv',
    'buoy_purchase_list.csv',
    'cost_summary.csv',
    'reconfiguration_details.csv',
    'physical_inventory_costs.csv',
    '*.md',  # Old markdown files
    'claude.py',
    'sequence_buoys.py',
    'optimize_buoys_with_costs.py'
]

def main():
    print("=" * 80)
    print("CLEANING UP MAIN DIRECTORY")
    print("=" * 80)
    
    # Create Archive folder
    archive_folder = f"Archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(archive_folder, exist_ok=True)
    
    print(f"\n✓ Created archive folder: {archive_folder}")
    
    # List all files in current directory
    all_files = [f for f in os.listdir('.') if os.path.isfile(f)]
    
    # Identify files to archive
    files_to_archive = []
    for file in all_files:
        if file not in KEEP_FILES:
            # Check if it matches any archive pattern
            should_archive = False
            for pattern in ARCHIVE_PATTERNS:
                import fnmatch
                if fnmatch.fnmatch(file, pattern):
                    should_archive = True
                    break
            
            if should_archive or file not in KEEP_FILES:
                files_to_archive.append(file)
    
    # Move files to archive
    if files_to_archive:
        print(f"\nArchiving {len(files_to_archive)} file(s):")
        for file in files_to_archive:
            try:
                shutil.move(file, os.path.join(archive_folder, file))
                print(f"  - {file}")
            except Exception as e:
                print(f"  ! Could not move {file}: {e}")
    else:
        print("\n✓ No files to archive - directory is clean!")
    
    print("\n" + "=" * 80)
    print("CLEANUP COMPLETE")
    print("=" * 80)
    
    print(f"\nMain directory now contains:")
    print("  ✓ Input files (CSVs)")
    print("  ✓ Main scripts")
    print("  ✓ README.md")
    print("  ✓ Results/ folder")
    
    if files_to_archive:
        print(f"\n  Archived files moved to: {archive_folder}/")

if __name__ == "__main__":
    main()

