import pqca
import qiskit
import sys
import json
sys.path.append("./qcircuit-relayer")
from qcircuit_relayer import PlatformLibrary, JobType
from qiskit import qasm3
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

library = PlatformLibrary()
aer= library.get("aer")
aer.connect()
backnd = aer.get_backend()
engine = aer.engine(backnd)

#ionq = library.get("ionq")
#ionq.connect(project_name="qpattr")
#backnd = ionq.get_backend("simulator")
#engine = ionq.engine(backnd)


CELL_SIZE_X = 2
CELL_SIZE_Y = 3
SYSTEM_SIZE_X = 4
SYSTEM_SIZE_Y = 6
SHOTS = 128
TIME_STEPS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]

# Create circuit
cx_circuit_1 = qiskit.QuantumCircuit(CELL_SIZE_X)
cx_circuit_1.cx(0, 1)
cx_circuit_1.h(0)
print(cx_circuit_1.draw(output='text'))

cx_circuit_2 = qiskit.QuantumCircuit(CELL_SIZE_Y)
cx_circuit_2.cx(0, 1)
cx_circuit_2.x(1)
cx_circuit_2.cx(1, 2)
print(cx_circuit_2.draw(output='text'))

# Create tessellation
tes = pqca.tessellation.n_dimensional([SYSTEM_SIZE_X, SYSTEM_SIZE_Y], [CELL_SIZE_X,1])
tes2 = pqca.tessellation.n_dimensional([SYSTEM_SIZE_X, SYSTEM_SIZE_Y], [1,CELL_SIZE_Y])
# Create update frames
update_1 = pqca.UpdateFrame(tes, cx_circuit_1)
update_2 = pqca.UpdateFrame(tes2, cx_circuit_2)

# Create initial state
initial_state = [0]*SYSTEM_SIZE_X*SYSTEM_SIZE_Y
initial_state[10] = 1



# Create the automaton DEPRECATED IN THIS VERSION
#automaton = pqca.Automaton(initial_state, [update_1, update_2], backend)
#print(automaton.update_circuit.draw(output='text'))

puqca = pqca.PUQCA(initial_state, [update_1, update_2])
circuits = puqca.build_circuits(TIME_STEPS, measure=False)
print(puqca.update_circuit.draw(output='text'))

print('transpiling circuits...')
pm = generate_preset_pass_manager(backend=backnd, optimization_level=3)
isa_circuits = [pm.run(circuit) for circuit in circuits]
for c in isa_circuits:
    c.measure_all()

# experiment metadata
qasm_string1 = qasm3.dumps(cx_circuit_1)
qasm_string2 = qasm3.dumps(cx_circuit_2)

pqca_dataset = {"name": 'True Rx and CNOT blinker',
                "metadata": {
                    "partitions": [(CELL_SIZE_X, 1), (1, CELL_SIZE_Y)],
                    "system_size": (SYSTEM_SIZE_X,SYSTEM_SIZE_Y),
                    "dimensions": 2,
                    "total_qubits": SYSTEM_SIZE_X*SYSTEM_SIZE_Y,
                    "iterations": TIME_STEPS[-1],
                    "parition_circuits_qasm": [qasm_string1, qasm_string2],
                    "feed-forward": False
                },
                "initial_state": initial_state,
                "frames": []
                }
#For IonQ, it uses the backend.run(), so maybe qcircuitrelayer should normalise that into a primitive job further down the line? For now, adaptation is client-side
#job = engine.submit(isa_circuits, job_type=JobType.SAMPLER, shots=SHOTS, memory=True)
print('submitting job...')
job = engine.submit(isa_circuits, job_type=JobType.SAMPLER, shots=SHOTS)

result = job.result()
print(result)

trajectory = []
trajectory.append([initial_state])
for i, t in enumerate(TIME_STEPS):
    counts = result[i].data.meas.get_bitstrings()
    trajectory.append([[int(x) for x in s[::-1]] for s in counts ])

    #IonQ tentative version
    #counts = result[i].data.meas.get_memory() #IonQ version
    #print(counts)
    #trajectory.append({"step": t, "counts": counts})


pqca_dataset["frames"] = trajectory

with open('pqca_trajectory.json', 'w') as f:
    json.dump(pqca_dataset, f, indent=2)


