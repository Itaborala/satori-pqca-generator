"""
Batched evolution: build one circuit per time step, run them, read a sample per
step. Unlike the local Unitary mode, each step is its own circuit -- the pattern
you use on a circuit simulator or real hardware.

BatchedEvolution exposes two *pure* ends you can drive separately:

    build_circuits(steps)  ->  one measured circuit per step   (circuits out)
    ingest(steps, memory)  <-  one memory list per step         (results in)

run(steps) is just the synchronous shorthand: build -> execute -> ingest. When
execution is asynchronous (submit now, collect later) or runs on a remote
backend, you call build_circuits / ingest yourself and do whatever runs the
circuits in between. pqca never needs to know which of the two happened, or how
much time passed between them.

The batched executor signature is:

    (circuits, shots) -> list[list[str]]

one list of '0'/'1' bitstrings per circuit, in the same order build_circuits
returned them. Swap the local statevector executor below for your hardware or
cloud backend with the same signature.

    python 03_batched.py
"""

from typing import List

import qiskit
from qiskit.quantum_info import Statevector
import pqca

# ============================ PARAMETERS ============================
NUM_QUBITS = 8
CELL_SIZE = 2
STEPS = [1, 2, 4, 8]                          # the time steps you want samples for
SHOTS = 256
INITIAL = [1] + [0] * (NUM_QUBITS - 1)
# ====================================================================


def statevector_batch_executor(
    circuits: List[qiskit.QuantumCircuit], shots: int
) -> List[List[str]]:
    """(circuits, shots) -> one list of per-shot bitstrings per circuit."""
    out = []
    for circ in circuits:
        bare = circ.remove_final_measurements(inplace=False) or circ
        out.append(Statevector.from_instruction(bare).sample_memory(shots))
    return out


cell = qiskit.QuantumCircuit(CELL_SIZE)
cell.cx(0, 1)

tes = pqca.tessellation.one_dimensional(NUM_QUBITS, CELL_SIZE)
frames = [
    pqca.UpdateFrame(tes, cell),
    pqca.UpdateFrame(tes.shifted_by(1), cell),
]


# --- Option A: synchronous, one call ----------------------------------------
# run() builds the circuits, executes them through the backend, and ingests the
# results in a single blocking call. Use this for fast local backends.
evo = pqca.BatchedEvolutionPQCA(
    INITIAL, frames, backend=statevector_batch_executor, shots=SHOTS
)
evo.run(STEPS)

print("synchronous run():")
for step, sample in zip(STEPS, evo):
    print(f"  t={step}  {sample}")


# --- Option B: drive the two pure ends yourself -----------------------------
# Identical result, but you own execution. On real hardware this is where you
# would submit each circuit, persist the job ids, come back later, collect the
# results, and only then call ingest. Here we just call the same local executor
# in between, to show the seam.
evo2 = pqca.BatchedEvolutionPQCA(INITIAL, frames, shots=SHOTS)   # no backend needed to build
circuits = evo2.build_circuits(STEPS, measure=True)             # circuits out
memory = statevector_batch_executor(circuits, SHOTS)            # ... run them however ...
evo2.ingest(STEPS, memory)                                      # results in

print("\nbuild_circuits / execute / ingest:")
for step, sample in zip(STEPS, evo2):
    print(f"  t={step}  {sample}")


# --- Re-iterating draws a fresh trajectory each time ------------------------
# ingest keeps the full per-step memory, so the object is a reusable sampling
# source: each `for` loop re-arms the iterator and draws new samples.
print("\nthree independent draws at the final step:")
for _ in range(3):
    trajectory = list(evo2)
    print(f"  t={STEPS[-1]}  {trajectory[-1]}")
