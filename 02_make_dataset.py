"""
Build a PQCA dataset and save it to JSON.

A small 2-D experiment: a lattice partitioned two ways and evolved for a number
of steps. Edit the PARAMETERS block, run, and a JSON dataset is written under
OUT_DIR. This mirrors the structure of the .pqcapreset configs (system size,
partitions by shape, initial indices, iterations) but as plain Python you edit
in place -- no command line, no config file required.

Runs locally with no account: the default Unitary mode evolves a statevector in
Qiskit. For larger systems or real hardware, see 03_batched.py.

    python 02_make_dataset.py
"""

import json
from pathlib import Path

import numpy as np
import qiskit
import pqca

# ============================ PARAMETERS ============================
NAME = "ex0"
SYSTEM_SIZE = [4, 9]                 # lattice shape, e.g. 4 rows x 9 columns
PARTITIONS = [                       # one UpdateFrame per partition
    {"shape": [2, 1]},               # 2x1 cells -> 2-qubit cell circuit (cell_x)
    {"shape": [1, 3]},               # 1x3 cells -> 3-qubit cell circuit (cell_y)
]
INITIAL_INDEXES = [10]               # flat qubit indices initialised to |1>
ITERATIONS = 32
OUT_DIR = "data-tests"
# ====================================================================

# --- cell circuits, one per partition; qubit count must equal prod(shape) ---
# Built inline here so the example is self-contained. To use your own .qasm
# files instead, replace a circuit with:
#     cell = qiskit.qasm3.loads(Path("ex0_x.qasm").read_text())
cell_x = qiskit.QuantumCircuit(2)              # for the [2, 1] partition
cell_x.cx(0, 1)
cell_x.h(0)

cell_y = qiskit.QuantumCircuit(3)              # for the [1, 3] partition
cell_y.cx(0, 1)
cell_y.x(1)
cell_y.cx(1, 2)

cell_circuits = [cell_x, cell_y]
# ----------------------------------------------------------------------------

total = int(np.prod(SYSTEM_SIZE))
initial_state = [0] * total
for i in INITIAL_INDEXES:
    initial_state[i] = 1

frames = []
for part, cell in zip(PARTITIONS, cell_circuits):
    needed = int(np.prod(part["shape"]))
    assert cell.num_qubits == needed, (
        f"partition {part['shape']} needs a {needed}-qubit cell circuit, "
        f"got {cell.num_qubits}"
    )
    tes = pqca.tessellation.n_dimensional(SYSTEM_SIZE, part["shape"])
    frames.append(pqca.UpdateFrame(tes, cell))

automaton = pqca.Automaton(initial_state, frames, mode=pqca.UnitaryPQCA())

dataset = {
    "name": NAME,
    "metadata": {
        "system_size": SYSTEM_SIZE,
        "partitions": [p["shape"] for p in PARTITIONS],
        "iterations": ITERATIONS,
        "total_qubits": total,
        "mode": "unitary",
    },
    "initial_state": initial_state,
    "frames": [initial_state],
}

for _ in range(ITERATIONS):
    dataset["frames"].append(next(automaton))

Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
out = Path(OUT_DIR) / f"{NAME}.json"
out.write_text(json.dumps(dataset, indent=2))
print(f"wrote {ITERATIONS} steps to {out}")
