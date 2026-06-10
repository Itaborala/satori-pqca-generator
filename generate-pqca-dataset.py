import pqca
from qiskit import QuantumCircuit, qasm3
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
import sys

from aer_metadata_util import probe_simulation_method
import numpy as np
import time
import argparse
import json
import tqdm
import os
from typing import Callable
from pathlib import Path

sys.path.append('./qcircuit-relayer')
from qcircuit_relayer import PlatformLibrary, JobType

#backend = platform.get_backend()           # the same backend you submit to
#method = probe_simulation_method(backend, circuit, shots=1024)
#job = engine.submit(circuit, JobType.SAMPLER, shots=1024)
# store `method` (str, or list for batched circuits) as your metadata

OUT_DIR = Path("data-candidates")
DONE = {"done", "jobstatus.done"}
FAILED = {"error", "cancelled"}
DEFAULT_SHOTS = 128


def load_json(filename):
    with open(filename, 'r') as f:
        return json.load(f)

def parse_backend_name(backend_name):
    parts = backend_name.split('.')

    if len(parts) == 1:
        return parts[0], None

    elif len(parts) == 2:
        return parts[0], parts[1]

    else:
        raise ValueError(f"Invalid backend name format: {backend_name}")

def build_initial_state(config: dict)-> list[int]:
    system_size = config['system_size']
    total_size = np.prod(system_size)
    initial_state = np.zeros(total_size, dtype=int)
    for i in config['initial_state_indexes']:
        if i >= total_size:
            raise ValueError(f"Initial state index {i} exceeds total system size {total_size}")
        initial_state[i] = 1
    return initial_state.tolist()

def build_frames(config: dict)-> list:
    frames = [] 
    for partition in config['partitions']:
        shape = partition['shape']
        with open(partition['file'], 'r') as f:
            circuit = qasm3.loads(f.read())
        if circuit.num_qubits != int(np.prod(shape)):
            raise ValueError(f"Partition circuit qubits {circuit.num_qubits} does not match partition size {shape}")

        tess = pqca.tessellation.n_dimensional(config['system_size'], shape)
        shift = partition.get('shift', 0)
        if shift != 0:
            tess = tess.shifted_by(shift)
        frames.append(pqca.UpdateFrame(tess, circuit))
    return frames

def build_evolution(config: dict, backend=None):
    initial_state = build_initial_state(config)

    frames = build_frames(config)
    shots = int(config.get('shots', DEFAULT_SHOTS))
    evo = pqca.BatchedEvolutionPQCA(initial_state, frames, backend=backend, shots=shots)
    steps = list(range(1, int(config['iterations'])+1))
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
    if b_name:
        platform_backend = platform.get_backend(b_name)
    else:
        platform_backend = platform.get_backend()

    engine = platform.engine(platform_backend)
    return engine

def submit_kwargs(config: dict):
    kw = {"shots": int(config.get('shots', DEFAULT_SHOTS))}
    if config.get('noise_model'):
        kw['noise_model'] = config['noise_model']
    #kw['memory'] = True
    return kw


def manifest_path(config: dict):
    return OUT_DIR / f"{config['name']}_manifest.json"

def dataset_path(config: dict):

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR / f"{config['name']}.json"

    if not base.exists():
        return base
    i = 1
    while (OUT_DIR / f"{config['name']}_{i}.json").exists():
        i += 1
    return OUT_DIR / f"{config['name']}_{i}.json"

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


def submit_evolution(config: dict):

    engine = connect_engine(config)

    evo, steps = build_evolution(config, backend=engine._backend)
    print(evo._step_circuit.draw(output="text", fold=-1))

    circuits = evo.build_circuits(steps, measure=True)

    kwargs = submit_kwargs(config)

    jobs = []

    for t, circ in zip(steps, circuits):

        job = engine.submit(circ, JobType.SAMPLER, memory=True, **kwargs)

        jobs.append({"t": t, "job_id": job.id})
        print(f"  submitted t={t:>4} -> {job.id}")

    manifest = {**config, 
                "initial_state": list(evo.initial_state),
                "steps": steps,
                "jobs": jobs}
    write_json(manifest_path(config), manifest)
    print(f"\n{len(jobs)} jobs submitted. Manifest: {manifest_path(config)}")
    print(f"This process can be safely terminated. run 'collect' once the jobs are complete to gather results and assemble the dataset.")

def collect_results(config: dict):

    mpath = manifest_path(config)
    if not mpath.exists():
        sys.exit(f"Manifest file not found: {mpath}. Run 'submit' first to create the manifest and submit jobs.")
    manifest = load_json(mpath)

    engine = connect_engine(config)
    shots = int(manifest.get('shots', config.get('shots', DEFAULT_SHOTS)))


    memory, pending, failed = [], [], []

    for entry in manifest["jobs"]:
        job = engine.retrieve(entry["job_id"])
        status = job.status

        print(f"Job for t={entry['t']:>4} -> status: {status}")

        if status in DONE:
            memory.append(job.memory())
        elif status in FAILED:
            failed.append(entry["t"])
        else:
            pending.append(entry["t"])

    if failed:
        print(f"Warning: Jobs for time steps {failed} failed.")

    if pending:
        print(f"Warning: Jobs for time steps {pending} are still pending. Run 'collect' again once they are complete.")
        return None


    evo, steps = build_evolution(config)

    evo.ingest(manifest["steps"], memory)
    frames = [list(manifest["initial_state"])] + [next(evo) for _ in manifest["steps"]]

    out = dataset_path(config)
    write_json(out, assemble_dataset(config, manifest["initial_state"], frames))
    print(f"Dataset assembled and written to {out}")
    return True

def run_evolution(config: dict):

    engine = connect_engine(config)
    shots = int(config.get('shots', DEFAULT_SHOTS))

    def run_aer_pqca_batch(circuits, shots=shots):
        #circuit.measure_all()
        job = engine.submit(circuits, JobType.SAMPLER, shots=shots)
        job.result()
        return [job.memory(i) for i in range(len(circuits))]
        # string_result = job.result()[0].data.meas.get_bitstrings()
        # return [int(x) for x in list(string_result.keys())[0]]
        # return string_result
    evo, steps = build_evolution(config, backend=run_aer_pqca_batch)
    print(evo._step_circuit.draw(output="text"))
    evo.run(steps)

    initial = list(evo.initial_state)

    frames = [initial] + [next(evo) for _ in tqdm.tqdm(steps, desc="Running evolution")]

    out = dataset_path(config)
    write_json(out, assemble_dataset(config, initial, frames))
    print(f"Dataset assembled and written to {out}")

# def pqca_runner(engine)-> Callable:

    # def run_pqca_circuit(circuit, shots):
        # circuit.measure_all()
        # job = engine.submit(circuit, JobType.SAMPLER, shots=shots)
        # string_result = job.result()[0].data.meas.get_bitstrings()
        # #return [int(x) for x in list(string_result.keys())[0]]
        # return string_result
    # return run_pqca_circuit

# def pqca_batch_runner(engine)-> Callable:

    # def run_pqca_circuits(circuits, shots):

        # job = engine.submit(circuits, JobType.SAMPLER, shots=shots)
        # print("Submitted batch job, waiting for results...")
        # string_results = []
        # results = job.result()
        # print(results)
        # for result in results:
            # string_results.append(result.data.meas.get_bitstrings())
        # #string_result = job.result()[0].data.meas.get_bitstrings()
        # #return [int(x) for x in list(string_result.keys())[0]]
        # print("Batch job completed, results obtained.")
        # return string_results
    # return run_pqca_circuits

# def generate_frames(dimensions, system_size, iterations, partitions, init_indexes, mode, backend_name, description):
    
    # if len(system_size) != dimensions:
        # raise ValueError(f"System size must have {dimensions} elements, got {len(system_size)}")
    # for partition in partitions:
        # if len(partition['shape']) != dimensions:
            # raise ValueError(f"Partition must have {dimensions} elements, got {len(partition['shape'])}")


        # for i, element in enumerate(partition['shape']):
            # if system_size[i]%element != 0:
                # raise ValueError(f"Partition shape {partition['shape']} must be divisible by system axis size {system_size} at dimension {i}, got {element} and {system_size[i]}")

        
        # with open(partition['file'], 'r') as f:
            # partition['circuit'] = qasm3.loads(f.read())

        # if partition['circuit'].num_qubits != np.prod(partition['shape']):
            # raise ValueError(f"Partition circuit qubits {partition['circuit'].num_qubits} does not match partition size {partition['shape']}")




    # total_size = np.prod(system_size)
    # initial_state = np.zeros(total_size, dtype=int)
    # for i in init_indexes:
        # if i >= np.prod(system_size):
            # raise ValueError(f"Initial state index {i} exceeds total system size {total_size}")
        # initial_state[i] = 1


    # library = PlatformLibrary()
    
    # p_name, b_name = parse_backend_name(backend_name)
    # print(f"Selected platform: {p_name}, backend: {b_name}")

    # platform = library.get(p_name)
    # if p_name == 'ionq':
        # platform.connect(project_name="qpattr")
    # else:
        # platform.connect()
    # if b_name:
        # platform_backend = platform.get_backend(b_name)
    # else:
        # platform_backend = platform.get_backend()

    # engine = platform.engine(platform_backend)
    

    # if p_name == 'aer':
        # for partition in partitions:
            # partition['method'] = probe_simulation_method(platform_backend, partition['circuit'], shots=1024)

    # print(partitions)
    # tess = []
    # updates = []
    # for partition in partitions:
        # tess.append(pqca.tessellation.n_dimensional(system_size, partition['shape']))
        # updates.append(pqca.UpdateFrame(tess[-1], partition['circuit']))


    # pqca_dataset = {"name": description,
                    # "metadata": {
                        # "partitions": [partition['shape'] for partition in partitions],
                        # "system_size": system_size,
                        # "dimensions": dimensions,
                        # "mode": mode,
                        # "total_qubits": int(total_size),
                        # "iterations": iterations,
                        # "backend": backend_name,
                        # "partition_circuits_qasm": [qasm3.dumps(partition['circuit']) for partition in partitions],
                        # "partition_shifts": [partition['shift'] for partition in partitions],
                        # },
                    # "initial_state": initial_state.tolist(),
                    # "frames": []
                    # }

    # if 'batch' not in mode:
        # backend = pqca_runner(engine)
        # automaton = pqca.Automaton(initial_state, updates, mode=pqca.UnitaryPQCA(), backend=backend)


        # print("Starting automaton...")

        # pqca_dataset['frames'].append(initial_state.tolist())
        # for i in tqdm.tqdm(range(iterations)):
            # pqca_dataset['frames'].append(next(automaton))

    # else:
        # backend = pqca_batch_runner(engine)
        # evolution = pqca.BatchedEvolutionPQCA(initial_state, updates, backend=backend, shots=2)
        # evolution.run(range(1, iterations+1))

        # for sample in evolution:
            # pqca_dataset['frames'].append(sample)



    # # save dataset into json file, if the file already exists, append a number to the end of the filename.
    # filename = f"data-tests/{description.replace(' ', '_')}.json"
    # if os.path.exists(filename):
        # i = 1
        # while os.path.exists(f"data-tests/{description.replace(' ', '_')}_{i}.json"):
            # i += 1
        # filename = f"data-tests/{description.replace(' ', '_')}_{i}.json"
    # print(pqca_dataset)
    # with open(filename, 'w') as f:
        # json.dump(pqca_dataset, f, indent=2)





if __name__ == '__main__':

    descr = "Generate Datasets of PQCA routines and structure the metadata for using with Satori/pqca. See more at https://satori.cephasteom.co.uk/pqca/"
    p = argparse.ArgumentParser(description=descr)
    p.add_argument("command", choices=['submit', 'collect', "run"])



    p.add_argument('--config', type=str, required=True, help="Overwrites arguments with a json-formatted configuration '<name>.pqcapreset' file.")


    p.add_argument("--poll", type=int, default=0, help="collect results by polling every N seconds (default: 0, no polling)")
    

    args = p.parse_args()

    config = load_json(args.config)


    if args.command == 'submit':
        submit_evolution(config)

    elif args.command == 'run':
        run_evolution(config)

    else:
        if args.poll > 0:
            while collect_results(config) is None:
                time.sleep(args.poll)
        else:
            collect_results(config)

    # if args.config:
        # print(f"Loanding configuration from file: {args.config}")
        # with open(args.config, 'r') as f:
            # configargs = json.load(f)

        # for key, value in configargs.items():
            # setattr(args, key, value)

    # generate_frames(args.dimensions, args.system_size, args.iterations, args.partitions, args.initial_state_indexes, args.mode, args.backend, args.name)
