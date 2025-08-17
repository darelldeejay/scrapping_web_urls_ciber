# run_vendor.py
import argparse, importlib, sys, traceback

REGISTRY = {
    "netskope": "vendors.netskope",
    "proofpoint": "vendors.proofpoint",
    "qualys": "vendors.qualys",
    "aruba": "vendors.aruba",
    "imperva": "vendors.imperva",
    "cyberark": "vendors.cyberark",  # ← NUEVO
}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vendor", required=True, choices=REGISTRY.keys())
    args = p.parse_args()
    modname = REGISTRY[args.vendor]
    try:
        mod = importlib.import_module(modname)
        mod.run()
    except Exception as e:
        print(f"[{args.vendor}] ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
