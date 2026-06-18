# satori-pqca-generator

Generate datasets of Partitioned Quantum Cellular Automata (PQCA) evolutions and
structure their metadata for **[Satori/PQCA](https://pqca.cephasteom.co.uk/)
sonification**. Each dataset is a JSON sequence of bit-pattern frames — the lattice
state at every time step — that Satori consumes as material for live-coded,
quantum-driven sound.

The generator drives the `pqca` evolution engine and routes circuit execution
through `qcircuit-relayer`, so the same setup runs on a local Aer
simulator or on IonQ cloud with just a change in the `backend` field.


---

## How it works

A PQCA evolution is defined by a lattice, a set of partitions (tessellations
tiled by a small per-cell circuit), an initial state, and a number of
iterations. The generator builds one circuit layer per requested time step, executes
them, and reassembles the measured bitstrings into ordered frames. The result is
written to JSON as `metadata` + `initial_state` + `frames`, ready for Satori.

Two execution paths are supported, chosen by the backend in your config:

- **Synchronous** (Aer, local) — one command builds, runs, and writes the dataset.
- **Asynchronous** (IonQ, cloud) — submit one job per time step (or as a batch), 
manifest, collect results later. Submits are partial and config-based, so you can
  submit the deepest (most expensive) step first and trickle the rest in over multiple sessions, even across process restarts.
- **Cost Estimation** - The script can also be used to estimate hardware costs on IonQ before committing to an experiment, 
thanks to the IonQ API.

---

## Requirements

- Python 3.11+
- `qiskit` (2.4+), `qiskit-aer`, `qiskit-ionq`
- `numpy`, `tqdm`, `keyring`
- The `pqca` package (v3) on the path
- `qcircuit-relayer` checked out alongside the script (imported from
  `./qcircuit-relayer`)

```bash
pip install qiskit qiskit-aer qiskit-ionq numpy tqdm keyring
```

### IonQ credentials

Tokens are read from the OS keyring, keyed by service `ionq` and a named
profile (default `qpattr`). Store yours once by running this inside your environment:

```python
import keyring
keyring.set_password("ionq", "qpattr", "<YOUR_IONQ_API_KEY>")
```

You can override the profile per dataset with the `project_name` field in the config, and passing a new token.
Aer needs no credentials.

---

## Configuration: `.pqcapreset`

A preset configuration file is described by a single JSON file:

```json
{
  "name": "quantum_itineraries",
  "dimensions": 2,
  "iterations": 32,
  "system_size": [4, 6],
  "partitions": [
    { "shape": [2, 1], "shift": 0, "file": "ex0_x.qasm" },
    { "shape": [1, 3], "shift": 0, "file": "ex0_y.qasm" }
  ],
  "initial_state_indexes": [10],
  "mode": "unitary-batched",
  "backend": "aer.stabilizer",
  "shots": 128
}
```

| Field | Meaning |
|---|---|
| `name` | Output basename for the dataset and manifest. |
| `dimensions` | Lattice dimensionality (recorded in metadata). |
| `iterations` | Number of evolution steps. |
| `system_size` | Lattice shape, e.g. `[4, 6]`. Total qubits = product. |
| `partitions` | Characterizes the `UpdateFrame`. Each partition has a `shape` (cell tiling), optional `shift` (offset), and `file` (an OpenQASM-3 cell circuit whose qubit count must equal `prod(shape)`). |
| `initial_state_indexes` | Flat qubit indices initialised to \|1⟩; everything else \|0⟩. |
| `mode` | Metadata label for the evolution regime, e.g. `unitary`, `unitary-batched` (see below). |
| `backend` | `aer.<method>` or `ionq.<backend>` (see below). |
| `shots` | Shots per circuit (default 128). |
| `project_name` | *(optional)* IonQ keyring profile to use. |
| `noise_model` | *(optional)* passed through on submit. |

### Backends

**Aer** — pass the simulation method explicitly as the suffix; `automatic` will
not pick MPS or extended-stabilizer for you:

- `aer.stabilizer` — Clifford circuits only
- `aer.statevector` — exact, small systems
- `aer.matrix_product_state` — shallow, locally-entangling circuits up to ~60–80 qubits
- `aer.extended_stabilizer` — Clifford+T only (not viable for generic-angle rules)

**IonQ** — server-side compilation handles transpilation:

- `ionq.simulator`
- `ionq.qpu.forte-1` (and other QPU targets)

---

## Usage

```
python generate-pqca-dataset.py <command> --config <file>.pqcapreset [options]
```

### `run` — synchronous (Aer)

Build, execute, and write the dataset in one shot.

```bash
python generate-pqca-dataset.py run --config aer_ex.pqcapreset
```

### `estimate` — cost preview (no submission)

Build circuits for the selected steps and report qubits, 1-qubit and 2-qubit
gate counts (the cost driver), plus a best-effort USD estimate on IonQ. Submits
nothing.

```bash
python generate-pqca-dataset.py estimate --config ex.pqcapreset --steps last --for qpu.forte-1
```

### `submit` — queue jobs (IonQ)

Submit the selected steps, one job per step, merging into the dataset's
manifest. Re-runnable: already-submitted steps are skipped, so you can submit in
batches.

```bash
python generate-pqca-dataset.py submit --config ex.pqcapreset --steps last
python generate-pqca-dataset.py submit --config ex.pqcapreset --steps 1-7
```

The manifest records a job ID per time step. The process can be terminated
safely after submitting.

### `collect` — retrieve and assemble (IonQ)

Retrieve every submitted job and report `done / pending / failed / unsubmitted`.
The dataset is assembled and written only once **all** steps are present and
done.

```bash
python generate-pqca-dataset.py collect --config ex.pqcapreset
python generate-pqca-dataset.py collect --config ex.pqcapreset --poll 20
```

`--poll N` re-checks every `N` seconds until the dataset is complete.

### Selecting steps with `--steps`

Used by `estimate` and `submit`:

| Spec | Selects |
|---|---|
| *(omitted)* / `all` | every step `1..iterations` |
| `last` / `deepest` | only the deepest (most expensive) step |
| `32` | a single step |
| `1,2,4,8` | a list |
| `25-32` | a range |
| `1,4,8-10,32` | any combination |

---

## Output

Datasets and manifests are written to the output directory (e.g.
`data-candidates/`):

- `<name>.json` — the dataset (auto-suffixed `_1`, `_2`, … if a file already exists)
- `<name>_manifest.json` — the IonQ job manifest (async path only)

Dataset shape:

```json
{
  "name": "...",
  "metadata": {
    "system_size": [...],
    "partitions": [...],
    "partition_shifts": [...],
    "dimensions": 2,
    "iterations": 32,
    "total_qubits": 24,
    "mode": "unitary-batched",
    "backend": "aer.stabilizer",
    "shots": 128
  },
  "initial_state": [...],
  "frames": [[...], [...], ...]
}
```

`frames[0]` is the initial state; each subsequent entry is the lattice after one
more evolution step.

---

## Examples

A curated set of worked configurations lives in a separate examples file. *(To be added.)*
