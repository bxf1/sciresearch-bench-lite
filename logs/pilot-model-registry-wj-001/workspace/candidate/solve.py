import argparse
import json
import os

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    manifest_path = os.path.join(args.input, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        case_id = case["id"]
        out_dir = os.path.join(args.output, "cases", case_id)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "u0.npy")
        u0 = np.zeros(256, dtype="<f8")
        np.save(out_path, u0)


if __name__ == "__main__":
    main()
