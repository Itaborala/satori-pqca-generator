# Examples

Two ways to use pqca here: write Python against the `pqca` library directly
(`scripts/`), or drive experiments from config files making full use of this repository (`presets/`).

```
examples/
├── scripts/              # runnable tutorials — pqca directly, no config files
│   ├── 01_quickstart.py
│   ├── 02_make_dataset.py
│   ├── 03_batched.py
│   └── data/             # 02 writes its datasets here
└── presets/              # experiment configs for generate-pqca-dataset.py
    ├── *.pqcapreset      # system size, partitions, initial state, iterations, backend
    └── *.qasm            # the cell circuit applied to each partition
```

## scripts/ — learn the library

Run them in order; each adds one idea. Edit the `PARAMETERS` block at the top
and re-run.

1. `01_quickstart.py` — one automaton, printing the state each step.
2. `02_make_dataset.py` — evolve a 2-D lattice for N steps, save a JSON dataset.
3. `03_batched.py` — build circuits / execute / ingest: the pattern used for
   circuit simulators and real hardware.

```
python scripts/01_quickstart.py
```

## presets/ — run experiments

A `.pqcapreset` is a JSON config; each partition in it names a `.qasm` cell
circuit. `generate-pqca-dataset.py` (at the project root) consumes one. 

From the project root, run:
```
# local (Aer): build the whole dataset in one shot
python generate-pqca-dataset.py run      --config 04_hector_miranda_ex0.pqcapreset

# IonQ: price the deepest step first (submits nothing), then submit / collect
python generate-pqca-dataset.py estimate  --config shallow_rot_36q.pqcapreset --steps last
python generate-pqca-dataset.py submit    --config shallow_rot_36q.pqcapreset --steps last
python generate-pqca-dataset.py collect   --config shallow_rot_36q.pqcapreset
```

- `run` — one-shot, for fast local backends.
- `submit` / `collect` — defer IonQ jobs (one per time step, resumable across
  restarts); `--steps` submits a subset (`last`, `1,2,4,8`, `25-32`).
- `estimate` — gate counts and cost for the selected steps, no submission.

Datasets are written to `data-candidates/`.

## make your own

Copy a preset and its `.qasm`, edit the shape, partitions, or gates, and run.
Two rules the loader checks: every partition shape must divide the system size,
and its `.qasm` must act on exactly `prod(shape)` qubits.
