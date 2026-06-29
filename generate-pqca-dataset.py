"""
generate-pqca-dataset.py
========================
Build PQCA datasets. Synchronous backends (Aer) run in one shot; asynchronous
backends (IonQ) submit one job per time step, persist a manifest, and collect
later -- including partial submits, so you can price/submit the deepest step
first and trickle the rest in over time.

Subcommands
-----------
    estimate  Build circuits for the selected steps and report qubits / 1Q / 2Q
              gate counts (the cost driver) plus a pre-submission USD estimate
              (IonQ only). Submits nothing.
    submit    Submit the selected steps (one job each), merging into the
              manifest. Re-runnable: already-submitted steps are skipped.
    collect   Retrieve every submitted job; assemble the dataset once *all*
              steps are present and done. Reports done/pending/failed/missing.
    run       Synchronous one-shot for fast local backends (Aer).
    cancel    Cancel any pending jobs (IonQ only).

--steps selects a subset for estimate/submit:
    (omitted) or 'all'   every step 1..iterations
    'last' / 'deepest'   only the deepest (most expensive) step
    '32'                 a single step
    '1,2,4,8'            a list
    '25-32'              a range  (combine: '1,4,8-10,32')

Examples
--------
    python generate-pqca-dataset.py estimate --config ex.pqcapreset --steps last --for qpu.forte-1
    python generate-pqca-dataset.py submit   --config ex.pqcapreset --steps last
    python generate-pqca-dataset.py collect  --config ex.pqcapreset
    python generate-pqca-dataset.py submit   --config ex.pqcapreset --steps 1-7
    python generate-pqca-dataset.py collect  --config ex.pqcapreset --poll 20
    python generate-pqca-dataset.py run      --config aer_ex.pqcapreset
"""

import pqca
from qiskit import QuantumCircuit, qasm3
import sys
import numpy as np
import time
import argparse
import json
import tqdm
import os
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "qcircuit-relayer"))
from qcircuit_relayer import PlatformLibrary, JobType

DEFAULT_OUT_DIR = Path("data")
DONE = {"done", "jobstatus.done"}
FAILED = {"error", "cancelled"}
DEFAULT_SHOTS = 128

# gate names that cost on IonQ (cost_model: 2QGE_operations)
TWO_Q = {"cx", "cy", "cz", "ch", "crx", "cry", "crz", "cp", "cu", "csx",
         "swap", "rxx", "ryy", "rzz", "rzx", "ms", "zz", "xx_plus_yy"}


# ------------------------------- config -------------------------------------
def load_json(filename):
    with open(filename, 'r') as f:
        return json.load(f)


def parse_backend_name(backend_name):
    parts = backend_name.split('.')
    if len(parts) == 1:
        return parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 3 and parts[1] == 'qpu':
        return parts[0], f"{parts[1]}.{parts[2]}"
    raise ValueError(f"Invalid backend name format: {backend_name}")


def parse_steps(spec, iterations):
    """'last'/'32'/'1,2,4,8'/'25-32'/'1,4,8-10' -> sorted list within 1..iterations."""
    if spec is None or spec == "all":
        return list(range(1, iterations + 1))
    if spec in ("last", "deepest"):
        return [iterations]
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(t for t in out if 1 <= t <= iterations)


def build_initial_state(config: dict) -> list[int]:
    system_size = config['system_size']
    total_size = np.prod(system_size)
    initial_state = np.zeros(total_size, dtype=int)
    for i in config['initial_state_indexes']:
        if i >= total_size:
            raise ValueError(f"Initial state index {i} exceeds total system size {total_size}")
        initial_state[i] = 1
    return initial_state.tolist()


def build_frames(config: dict, base_dir: Path) -> list:
    frames = []
    for partition in config['partitions']:
        shape = partition['shape']
        qasm_path = (base_dir / partition['file']).resolve()
        with open(qasm_path, 'r') as f:
            circuit = qasm3.loads(f.read())
        if circuit.num_qubits != int(np.prod(shape)):
            raise ValueError(f"Partition circuit qubits {circuit.num_qubits} does not match partition size {shape}")
        tess = pqca.tessellation.n_dimensional(config['system_size'], shape)
        shift = partition.get('shift', 0)
        if shift != 0:
            tess = tess.shifted_by(shift)
        frames.append(pqca.UpdateFrame(tess, circuit))
    return frames


def build_evolution(config: dict, backend=None, base_dir: Path = Path(".")):
    initial_state = build_initial_state(config)
    frames = build_frames(config, base_dir)
    shots = int(config.get('shots', DEFAULT_SHOTS))
    evo = pqca.BatchedEvolutionPQCA(initial_state, frames, backend=backend, shots=shots)
    steps = list(range(1, int(config['iterations']) + 1))
    return evo, steps


def connect_engine(config: dict):
    library = PlatformLibrary()
    p_name, b_name = parse_backend_name(config['backend'])
    print(f"Selected platform: {p_name}, backend: {b_name}")
    platform = library.get(p_name)
    if p_name == 'ionq':
        platform.connect(project_name=config.get('project_name', "qpattr"))
    else:
        platform.connect()
    platform_backend = platform.get_backend(b_name) if b_name else platform.get_backend()
    return platform.engine(platform_backend)


def submit_kwargs(config: dict):
    kw = {"shots": int(config.get('shots', DEFAULT_SHOTS))}
    if config.get('noise_model'):
        kw['noise_model'] = config['noise_model']
    return kw


# ------------------------------- paths --------------------------------------
def manifest_path(config: dict, out_dir: Path):
    return out_dir / f"{config['name']}_manifest.json"


def dataset_path(config: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{config['name']}.json"
    if not base.exists():
        return base
    i = 1
    while (out_dir / f"{config['name']}_{i}.json").exists():
        i += 1
    return out_dir / f"{config['name']}_{i}.json"


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def assemble_dataset(config: dict, initial_state, frames) -> dict:
    backend_str = config['backend']
    if config.get('method', None) is not None:
        backend_str += f".{config['method']}"
    return {
        "name": config['name'],
        "metadata": {
            "system_size": config['system_size'],
            "partitions": [part['shape'] for part in config['partitions']],
            "partition_shifts": [part.get('shift', 0) for part in config['partitions']],
            "dimensions": config['dimensions'],
            "iterations": config['iterations'],
            "total_qubits": int(np.prod(config['system_size'])),
            "mode": config.get('mode', 'unknown'),
            "backend": backend_str,
            "shots": int(config.get('shots', DEFAULT_SHOTS)),
        },
        "initial_state": list(initial_state),
        "frames": frames,
    }


# -------------------------------- cost --------------------------------------
def gate_profile(circ):
    """(qubits, 1-qubit gate count, 2-qubit gate count), excluding measure/barrier."""
    ops = circ.count_ops()
    twoq = sum(n for g, n in ops.items() if g in TWO_Q)
    oneq = sum(n for g, n in ops.items() if g not in TWO_Q and g not in {"measure", "barrier"})
    return circ.num_qubits, oneq, twoq


def ionq_estimate_usd(engine, qubits, oneq, twoq, shots, backend_name):
    """Best-effort pre-submission USD estimate. Returns None on the simulator or any API mismatch."""
    try:
        est = engine._backend.client.estimate_job(
            backend=backend_name, oneq_gates=oneq, twoq_gates=twoq,
            qubits=qubits, shots=shots)
        d = est.to_dict() if hasattr(est, "to_dict") else dict(est)
        for k in ("cost", "estimated_cost", "cost_usd", "usd"):
            v = d.get(k)
            if isinstance(v, dict) and "value" in v:
                return float(v["value"])
            if isinstance(v, (int, float)):
                return float(v)
    except Exception:
        return None
    return None


def estimate_cost(config: dict, steps_spec=None, for_backend=None, base_dir: Path =None):
    evo, _ = build_evolution(config, base_dir=base_dir)
    iterations = int(config['iterations'])
    steps = parse_steps(steps_spec, iterations)
    if not steps:
        sys.exit(f"no steps selected from {steps_spec!r} (valid 1..{iterations})")
    circuits = evo.build_circuits(steps, measure=True)
    shots = int(config.get('shots', DEFAULT_SHOTS))

    engine, bname = None, for_backend
    if config['backend'].startswith('ionq'):
        engine = connect_engine(config)
        if bname is None:
            _, b = parse_backend_name(config['backend'])
            bname = b or "simulator"

    print(f"\n{'step':>5} {'qubits':>7} {'1Q':>6} {'2Q':>6} {'~USD':>10}")
    tot2q, totusd = 0, 0.0
    for t, circ in zip(steps, circuits):
        q, oneq, twoq = gate_profile(circ)
        tot2q += twoq
        usd = ionq_estimate_usd(engine, q, oneq, twoq, shots, bname) if engine else None
        if usd:
            totusd += usd
        print(f"{t:>5} {q:>7} {oneq:>6} {twoq:>6} {('$%.4f' % usd) if usd else 'n/a':>10}")
    tail = f"   ~total ${totusd:.4f} on '{bname}'" if totusd else ""
    print(f"\n{len(steps)} step(s); {tot2q} two-qubit gates total{tail}")
    if engine and not totusd:
        print("(no USD figure: simulator is free, or estimate_job is unavailable in this "
              "qiskit-ionq version -- the 2Q gate count is your cost proxy)")

def confirm_qpu_spend(config:dict):
    if config['backend'].startswith('ionq.qpu') and input(
            f"WARNING: You are about to submit jobs to a real IonQ QPU ({config['backend']}). confirm? [y/N] ").strip().lower() != 'y':
        sys.exit("Submission cancelled")



# ------------------------------- submit -------------------------------------
def submit_evolution(config: dict, steps_spec=None, out_dir: Path=None, base_dir: Path=None):
    confirm_qpu_spend(config)
    engine = connect_engine(config)
    evo, _ = build_evolution(config, base_dir=base_dir)
    iterations = int(config['iterations'])
    all_steps = list(range(1, iterations + 1))
    steps = parse_steps(steps_spec, iterations)
    if not steps:
        sys.exit(f"no steps selected from {steps_spec!r} (valid 1..{iterations})")

    if evo._step_circuit.num_qubits <= 30:
        print(evo._step_circuit.draw(output="text", fold=-1))

    circuits = evo.build_circuits(steps, measure=True)
    kwargs = submit_kwargs(config)

    mpath = manifest_path(config, out_dir)
    if mpath.exists():
        manifest = load_json(mpath)                  # merge into the existing manifest
    else:
        manifest = {**config,
                    "initial_state": list(evo.initial_state),
                    "steps": all_steps,
                    "jobs": []}
    have = {j["t"] for j in manifest["jobs"]}

    new = 0
    for t, circ in zip(steps, circuits):
        if t in have:
            print(f"  t={t:>4} already submitted; skipping")
            continue
        _, _, twoq = gate_profile(circ)
        job = engine.submit(circ, JobType.SAMPLER, memory=True, **kwargs)
        manifest["jobs"].append({"t": t, "job_id": job.id, "twoq_gates": twoq})
        new += 1
        print(f"  submitted t={t:>4} -> {job.id}   (2Q gates: {twoq})")

    manifest["jobs"].sort(key=lambda j: j["t"])
    write_json(mpath, manifest)
    submitted = {j["t"] for j in manifest["jobs"]}
    missing = [t for t in all_steps if t not in submitted]
    print(f"\n{new} new job(s); manifest now has {len(submitted)}/{iterations} steps."
          + (f" Still to submit: {missing}" if missing else " Complete -- run 'collect'."))
    print(f"Manifest: {mpath}. This process can be safely terminated.")


# ------------------------------- collect ------------------------------------
def collect_results(config: dict, out_dir: Path, base_dir: Path):
    mpath = manifest_path(config, out_dir)
    if not mpath.exists():
        sys.exit(f"Manifest file not found: {mpath}. Run 'submit' first.")
    manifest = load_json(mpath)

    engine = connect_engine(config)
    shots = int(manifest.get('shots', config.get('shots', DEFAULT_SHOTS)))
    all_steps = manifest.get('steps', list(range(1, int(config['iterations']) + 1)))

    done, pending, failed = {}, [], []
    for entry in manifest["jobs"]:
        job = engine.retrieve(entry["job_id"])
        status = job.status
        print(f"  t={entry['t']:>4} -> {status}")
        if status in DONE:
            done[entry["t"]] = job.memory(shots=shots)
        elif status in FAILED:
            failed.append(entry["t"])
        else:
            pending.append(entry["t"])

    submitted = {j["t"] for j in manifest["jobs"]}
    missing = [t for t in all_steps if t not in submitted]

    print(f"\nsteps: {len(done)} done | {len(pending)} pending | "
          f"{len(failed)} failed | {len(missing)} unsubmitted")
    for label, lst in (("failed", failed), ("pending", pending), ("unsubmitted", missing)):
        if lst:
            print(f"  {label}: {sorted(lst)}")

    if pending or missing or failed:
        print("Dataset incomplete; submit/collect the remaining steps later.")
        return None

    evo, _ = build_evolution(config, base_dir=base_dir)
    evo.ingest(all_steps, [done[t] for t in all_steps])
    frames = [list(manifest["initial_state"])] + [next(evo) for _ in all_steps]

    out = dataset_path(config, out_dir)
    write_json(out, assemble_dataset(config, manifest["initial_state"], frames))
    print(f"Complete -- dataset written to {out}")
    return True

# ------------------------------- cancel -------------------------------------
def cancel_jobs(config: dict, steps_spec=None, out_dir: Path=None, base_dir: Path=None):
    mpath = manifest_path(config, out_dir)
    if not mpath.exists():
        sys.exit(f"Manifest file not found: {mpath}. Nothing to cancel.")
    manifest = load_json(mpath)

    iterations = int(config['iterations'])
    targets = set(parse_steps(steps_spec, iterations)) if steps_spec else None

    engine = connect_engine(config)
    cancelled, skipped = [], 0
    for entry in manifest["jobs"]:
        t = entry["t"]
        if targets is not None and t not in targets:
            continue
        job = engine.retrieve(entry["job_id"])
        status = job.status
        if status in DONE or status in FAILED:
            print(f"  t={t:>4} -> {status}; terminal, skipping")
            skipped += 1
            continue
        job.cancel()
        print(f"  cancelled t={t:>4} -> {entry['job_id']}")
        cancelled.append(t)

    manifest["jobs"] = [j for j in manifest["jobs"] if j["t"] not in cancelled]
    write_json(mpath, manifest)
    print(f"\ncancelled {len(cancelled)} job(s); {skipped} terminal job(s) untouched. "
          f"manifest now has {len(manifest['jobs'])}/{iterations} steps.")


# --------------------------------- run --------------------------------------
def run_evolution(config: dict, out_dir: Path, base_dir: Path):
    confirm_qpu_spend(config)
    engine = connect_engine(config)
    shots = int(config.get('shots', DEFAULT_SHOTS))

    def run_aer_pqca_batch(circuits, shots=shots):
        job = engine.submit(circuits, JobType.SAMPLER, shots=shots)
        job.result()
        return [job.memory(i) for i in range(len(circuits))]

    evo, steps = build_evolution(config, backend=run_aer_pqca_batch, base_dir=base_dir)
    if evo._step_circuit.num_qubits <= 30:
        print(evo._step_circuit.draw(output="text"))
    evo.run(steps)

    initial = list(evo.initial_state)
    frames = [initial] + [next(evo) for _ in tqdm.tqdm(steps, desc="Running evolution")]

    out = dataset_path(config, out_dir)
    write_json(out, assemble_dataset(config, initial, frames))
    print(f"Dataset assembled and written to {out}")


# --------------------------------- cli --------------------------------------
if __name__ == '__main__':
    descr = ("Generate Datasets of PQCA routines and structure the metadata for using "
             "with Satori/pqca. See more at https://pqca.cephasteom.co.uk/")
    p = argparse.ArgumentParser(description=descr)
    p.add_argument("command", choices=['estimate', 'submit', 'collect', 'run', 'cancel'])
    p.add_argument('--config', type=str, required=True,
                   help="json-formatted '<name>.pqcapreset' configuration file.")
    p.add_argument('--steps', type=str, default=None,
                   help="estimate/submit/cance/cancel subset: 'last', '32', '1,2,4,8', '25-32' (default: all)")
    p.add_argument('--for', dest='for_backend', type=str, default=None,
                   help="estimate: IonQ backend to price against, e.g. qpu.forte-1")
    p.add_argument("--poll", type=int, default=0,
                   help="collect: poll every N seconds until complete (default: 0, check once)")
    p.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR,
                   help="directory to write manifests (default: data/). "
                        "submit and collect must use the same out-dir to find the manifest and dataset.")
    args = p.parse_args()

    config = load_json(args.config)
    out_dir = args.out_dir
    base_dir = Path(args.config).parent

    if args.command == 'estimate':
        estimate_cost(config, args.steps, args.for_backend)
    elif args.command == 'submit':
        submit_evolution(config, args.steps, out_dir, base_dir)
    elif args.command == 'run':
        run_evolution(config, out_dir, base_dir)
    elif args.command == 'cancel':
        cancel_jobs(config, args.steps, out_dir, base_dir)
    else:  # collect
        if args.poll > 0:
            while collect_results(config, out_dir, base_dir) is None:
                time.sleep(args.poll)
        else:
            collect_results(config, out_dir, base_dir)
