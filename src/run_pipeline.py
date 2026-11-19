"""Run the complete data-quality pipeline on any operating system."""
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
SCRIPTS = [
    "clean_customers.py",
    "clean_amortization.py",
    "clean_membership_fee.py",
    "clean_proc_fee.py",
]


def main():
    for script in SCRIPTS:
        print(f"Running {script}...")
        subprocess.run([sys.executable, str(SRC_DIR / script)], check=True)
    print("Pipeline completed successfully.")


if __name__ == "__main__":
    main()
