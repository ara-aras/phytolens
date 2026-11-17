# GPU docking path (WSL2 + Uni-Dock)

Status: **installed and validated on 2026-11-17.** The GPU path works, but it is
not on the demo's critical path — see §6 before deciding to use it.

Hardware: Acer Predator PHN16-71, i7-13700HX, RTX 4050 Laptop 6141 MiB,
compute capability 8.9, driver 610.47.

---

## 1. Short version

Uni-Dock does not run on Windows. It is a Linux CUDA binary, published only on
conda-forge. It therefore needs WSL2, and nothing else: the CUDA runtime is
linked statically into the binary, so **no CUDA toolkit, no compiler, no CMake,
no Boost headers and no Python environment are required.**

`uv` cannot substitute for conda here. `unidock` returns HTTP 404 on PyPI — it is
a compiled C++/CUDA executable, not a Python package. (`unidock-tools` *is* on
PyPI, but that is only the SDF/PDBQT input-output helper, not the docking engine.)

Final install footprint: **29 MB** — a 27 MB binary plus four Boost shared
libraries totalling under 1 MB.

## 2. What was installed

| Component | Version | Why |
|---|---|---|
| WSL 2 | 3.0.5, kernel 6.18.58.1 | Uni-Dock is Linux-only |
| Ubuntu | 24.04.5 LTS | host distro |
| `libgomp1` | apt | OpenMP runtime; was previously supplied by conda |
| Uni-Dock | 1.2.0, `cuda129` build | the docking engine |

Enabled Windows features: `Microsoft-Windows-Subsystem-Linux` and
`VirtualMachinePlatform`. **No reboot was required** — the MSIX WSL 3.0.5 package
became usable immediately after feature enablement on build 26300.

The NVIDIA Windows driver supplies GPU passthrough via `/dev/dxg` and
`/usr/lib/wsl/lib/libcuda.so`. Do **not** install a Linux display driver inside
WSL — it will break passthrough.

## 3. Why the conda environment was thrown away

The only practical way to obtain the binary is a conda solve, but the resulting
environment is **3.9 GB** — a full Python 3.14 stack, numpy, scipy, xorg
libraries — for one 27 MB executable. The binary declares `RPATH $ORIGIN/../lib`
and needs only four Boost libraries, so it was copied to `/usr/local/bin` with
those in `/usr/local/lib`, verified with an empty environment
(`env -i /usr/local/bin/unidock --version`), and miniconda was deleted.

One trap worth recording: `ldd` on the main binary lists three Boost libraries,
but `libboost_filesystem` has its own unmet dependency on `libboost_system`. A
copy driven purely by the binary's `ldd` output produces something that links
cleanly and then dies at startup with `error while loading shared libraries`. The
installer therefore names the four libraries explicitly and refuses to finish if
`ldd` reports anything missing.

Reproduce with `engine/scripts/setup_unidock.sh`.

## 4. Validation against the CPU baseline

Docking the 24 demo ligands against COX-2 (PDB 3NT1, box 20 Å centred on
naproxen, seed 42) and comparing to the cached Vina 1.2.7 results.

Only cache entries matching the demo configuration were used: receptor `3NT1`,
box `20 Å`, exhaustiveness 8, seed 42. The cache still contains 26 entries from
the rejected 26 Å box and other configurations; those are excluded.

**Agreement at equal search effort (exhaustiveness 8):**

| metric | value |
|---|---|
| ligands matched | 24 / 24 |
| mean \|Δ affinity\| | **0.093 kcal/mol** |
| max \|Δ affinity\| | 0.613 (piperine) |
| ranking | top-4 set identical; eugenol #17 on both |

The single outlier is piperine, a long flexible molecule (5 rotatable bonds)
that exhaustiveness 8 under-samples. Given `--search_mode balance` it converges
to Δ0.095, which confirms the cause was search effort rather than a difference
in the scoring function.

`engine/scripts/compare_scores.py` reproduces this table.

## 5. The counter-intuitive timing result

| backend | search | ligands | wall time | per ligand |
|---|---|---|---|---|
| Vina 1.2.7, CPU | exhaustiveness 8 | 24 | 97.19 s | 4.05 s |
| Uni-Dock, GPU | exhaustiveness 8 | 26 | 84.4–89.3 s | 3.25–3.43 s |
| Uni-Dock, GPU | `balance` = exh 384, max_step 40 | 26 | **10.2–11.3 s** | **0.40 s** |

**48× the search, and 8× faster.** This is reproducible across four runs.

The explanation is in the batch report: the exhaustiveness-8 run spent
`Batch 1 running time: ~49 900 ms`, while the balance run spent
`~3 600 ms`. Low exhaustiveness gives each ligand so little work that kernel
launch and host-device transfer dominate; the GPU is idle waiting on overhead.
The balance preset supplies enough work per launch to fill the device.

Practical consequence: **do not run Uni-Dock at exhaustiveness 8.** It is the
worst of both worlds — slow and under-sampled. Use `--search_mode balance`.

## 6. Why this is still off the critical path

1. **The demo does not need it.** 24 ligands cost 97 s on CPU. There is no
   bottleneck to remove.
2. **Backends cannot be mixed in one table.** GPU scores differ from CPU scores
   by ~0.1 kcal/mol mean, up to 0.4. Blending them in one ranking would be
   exactly the kind of apples-to-oranges comparison this project has already
   been burned by. Switching the demo to GPU means re-docking and re-publishing
   every number in `docs/DEMO_PLAN.md` §8.
3. **The ranking is stable anyway** — top-4 is the three curcuminoids plus
   cholesterol under every configuration tested, so the GPU changes the runtime,
   not the story.

The GPU becomes worth using for a **full-corpus sweep**: 2 944 compounds with
target links would take ~3.3 hours single-core on CPU versus roughly 20 minutes
on the GPU at balance settings.

## 7. Commands

```bash
# from Windows
wsl -d Ubuntu-24.04 -u root

# equal-search comparison against the CPU baseline
bash /mnt/c/Projects/Photolens/engine/scripts/bench_unidock.sh

# the setting you should actually use
bash /mnt/c/Projects/Photolens/engine/scripts/bench_balance.sh

# score agreement table
python3 /mnt/c/Projects/Photolens/engine/scripts/compare_scores.py /root/bench/out_balance
```

Direct invocation:

```bash
unidock --receptor 3NT1.pdbqt --gpu_batch ligs/*.pdbqt \
  --scoring vina --seed 42 --search_mode balance \
  --center_x -43.833 --center_y -47.237 --center_z -43.958 \
  --size_x 20 --size_y 20 --size_z 20 --num_modes 9 --dir out/
```

Keep working files inside the WSL filesystem. Running from `/mnt/c/...` is slow
enough to distort any benchmark. If the 6 GB of VRAM overflows, cap it with
`--max_gpu_memory`.

## 8. Licence

Uni-Dock is **Apache-2.0**, relicensed from LGPL-3 on 2025-03-10. Clean for the
licensing table in `docs/BACKEND_SPEC.md`, unlike fpocket (GPL) and
SwissTargetPrediction (ToS forbids automation).
