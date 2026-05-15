import pqca
import qiskit
from typing import Callable
import sys
import json
sys.path.append("./qcircuit-relayer")
from qcircuit_relayer import PlatformLibrary, JobType

library = PlatformLibrary()
aer= library.get("aer")
aer.connect()
backnd = aer.get_backend()
engine = aer.engine(backnd)


CELL_SIZE = 2
SYSTEM_SIZE = 8
ITERATIONS = 1000


def pqca_runner(engine)-> Callable:

    def run_pqca_circuit(circuit, shots=1):
        circuit.measure_all()
        job = engine.submit(circuit, type=JobType.SAMPLER, shots=shots)
        string_result = job.result()[0].data.meas.get_counts()
        return [int(x) for x in list(string_result.keys())[0]]
    return run_pqca_circuit

# Create circuit
cx_circuit = qiskit.QuantumCircuit(CELL_SIZE**2)
cx_circuit.cx(0, 1)
cx_circuit.draw(output='text')
# Create tessellation
tes = pqca.tessellation.n_dimensional([SYSTEM_SIZE, SYSTEM_SIZE], [CELL_SIZE, CELL_SIZE])
# Create update frames
update_1 = pqca.UpdateFrame(tes, cx_circuit)
update_2 = pqca.UpdateFrame(tes.shifted_by(1), cx_circuit)

# Create initial state
initial_state = [1]*SYSTEM_SIZE**2

# Specify a backend; `pqca.backend.aer()` returns IBM's Aer simulator
# See backend.py for more details and instructions on coding your own backend
#backend = pqca.backend.qiskit()
backend = pqca_runner(engine)
# Create the automaton
automaton = pqca.Automaton(initial_state, [update_1, update_2], backend)
print(automaton.update_circuit.draw(output='text'))
# The automaton can be called like any other iterator
# The following line advances the internal state, and returns the new state

pqca_dataset = {"name": 'simple_test',
                "description": 'A simple test of the pqca library',
                "metadata": {
                    "cell_size": CELL_SIZE,
                    "system_size": SYSTEM_SIZE,
                    "iterations": ITERATIONS
                },
                "frames": []
                }


for i in range(ITERATIONS):
    pqca_dataset["frames"].append(next(automaton))
    print(pqca_dataset["frames"][-1])


#save dataset into json

with open('pqca_dataset.json', 'w') as f:
    json.dump(pqca_dataset, f)




