"""
PQCA quickstart -- a partitioned quantum cellular automaton in a dozen lines.

Edit the PARAMETERS block, run the file, watch the state evolve.
No backend or account needed: the default Unitary mode evolves a statevector
locally inside Qiskit and samples one state per step without collapsing it.

    python 01_quickstart.py
"""

import qiskit
import pqca

# ============================ PARAMETERS ============================
NUM_QUBITS = 10                              # length of the 1-D line of qubits
CELL_SIZE = 2                                # qubits per cell
STEPS = 6                                    # how many time steps to print
INITIAL = [1] + [0] * (NUM_QUBITS - 1)       # one excitation at the left edge
# ====================================================================

# The circuit applied to every cell. Here: a single CX on 2 qubits.
# Change CELL_SIZE above and this circuit together -- the cell circuit must
# act on exactly CELL_SIZE qubits.
cell = qiskit.QuantumCircuit(CELL_SIZE)
cell.cx(0, 1)

# Two offset tessellations make the update couple across cell borders.
tes = pqca.tessellation.one_dimensional(NUM_QUBITS, CELL_SIZE)
frames = [
    pqca.UpdateFrame(tes, cell),
    pqca.UpdateFrame(tes.shifted_by(1), cell),
]

# Unitary mode evolves the statevector directly; the backend argument is unused.
automaton = pqca.Automaton(INITIAL, frames, mode=pqca.UnitaryPQCA())

print(f"t=0  {INITIAL}")
for t in range(1, STEPS + 1):
    print(f"t={t}  {next(automaton)}")
