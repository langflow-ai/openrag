# Relevance Test Corpus — OpenRAG Scoring QA

This document is designed to test the **High / Medium / Low** relevance tier display
introduced in the `overhaul/avg_score` branch.  It is large enough that the default
ingestion settings (chunk size 1000 chars, overlap 200) will produce **8–12 chunks**,
each with different keyword density, so a range of raw OpenSearch scores is produced
for a single file.  Upload this one file and run the search queries listed at the bottom.

---

## Section 1 — Quantum Computing (dense keyword section)

Quantum computing harnesses quantum mechanics to process information in ways that
classical computers cannot.  Unlike classical bits that are either 0 or 1, quantum bits
(qubits) can exist in superposition — both 0 and 1 simultaneously.  Entanglement allows
two qubits to be correlated regardless of physical distance, enabling quantum computers
to explore many solutions at once.  Major quantum algorithms include Shor's algorithm for
integer factorisation and Grover's algorithm for unstructured search.  Quantum decoherence
remains the primary engineering challenge: maintaining qubit coherence long enough to
complete a computation.  IBM Quantum, Google Sycamore, and IonQ are leading hardware
platforms.  Quantum error correction codes such as the surface code and stabiliser codes
are actively researched to achieve fault-tolerant quantum computing.  The quantum volume
metric measures the overall capability of a quantum computer across gate fidelity, qubit
connectivity, and circuit depth.  Variational quantum eigensolvers (VQE) and quantum
approximate optimisation algorithms (QAOA) represent near-term applications on noisy
intermediate-scale quantum (NISQ) devices.

---

## Section 2 — Classical Computer Architecture (moderate keyword density)

Classical computers execute instructions using a central processing unit (CPU) that
fetches, decodes, and executes operations stored in memory.  The von Neumann architecture
separates compute from storage, creating the famous memory bottleneck.  Cache hierarchies
(L1, L2, L3) mitigate latency by keeping frequently accessed data closer to the processor.
Pipelining, branch prediction, and out-of-order execution are micro-architectural techniques
used to improve instruction throughput.  Multi-core processors enable parallel execution
of threads, while simultaneous multi-threading (SMT / Hyper-Threading) increases utilisation
of execution units within a single core.  Graphics processing units (GPUs) extend this
parallelism to thousands of smaller cores, making them ideal for matrix-heavy workloads
such as deep learning.  Instruction set architectures such as x86-64 and ARM define the
interface between software and hardware.

---

## Section 3 — Fruit Taxonomy (deliberately off-topic, low keyword density for quantum/computing queries)

Apples, pears, and plums belong to the Rosaceae family.  Citrus fruits such as oranges,
lemons, and grapefruits are classified under Rutaceae.  Tropical varieties including
mangoes, papayas, and pineapples grow in equatorial climates.  Stone fruits are
characterised by a hard endocarp surrounding the seed.  Ripeness is determined by
ethylene gas production, which softens the cell walls and increases sugar concentration.
Fruit bats are primary pollinators and seed dispersers for many tropical species.
The nutritional composition of most fruits includes fructose, dietary fibre, vitamin C,
and potassium.  Heirloom cultivars are maintained for flavour characteristics rather than
shelf life or shipping durability.

---

## Section 4 — Ocean Currents (off-topic, filler content)

The thermohaline circulation, sometimes called the global ocean conveyor belt, is driven
by differences in temperature and salinity.  Warm surface currents such as the Gulf Stream
transport heat from the tropics toward higher latitudes, moderating the climate of Western
Europe.  Deep water formation occurs primarily in the North Atlantic and around Antarctica
where cold, dense water sinks to the ocean floor.  El Niño–Southern Oscillation (ENSO)
is an irregular periodic variation in winds and sea surface temperatures that affects
global weather patterns.  Upwelling along continental coasts brings cold, nutrient-rich
water to the surface, supporting productive marine ecosystems.  Ocean acidification caused
by the absorption of atmospheric CO₂ threatens coral reefs and shell-forming organisms.

---

## Section 5 — Quantum Error Correction (back to quantum, second dense hit)

Quantum error correction is essential for building reliable quantum computers because
qubits are highly susceptible to environmental noise.  The most promising approach is the
surface code, which encodes a single logical qubit in a two-dimensional lattice of physical
qubits.  Syndrome measurements detect errors without collapsing the quantum state.
Threshold theorems state that if the physical error rate per gate is below a certain
threshold (typically around 1%), fault-tolerant quantum computation becomes possible with
sufficient overhead.  Magic state distillation produces high-fidelity ancilla states needed
for universal quantum gate sets.  Concatenated codes and topological codes represent two
broad families of quantum error correcting codes.  The toric code, introduced by Kitaev,
is a foundational example of a topological code.  Hardware-efficient ansätze reduce the
depth of quantum circuits to stay within the coherence time of current qubits.

---

## Section 6 — Renewable Energy (off-topic, filler)

Solar photovoltaic cells convert sunlight directly into electricity through the
photoelectric effect.  Monocrystalline silicon panels offer the highest efficiency among
commercially available solar modules.  Wind turbines extract kinetic energy from moving
air using rotor blades connected to a generator.  Offshore wind farms benefit from stronger
and more consistent wind speeds compared to onshore installations.  Battery energy storage
systems, particularly lithium-ion and emerging solid-state chemistries, address the
intermittency of renewable generation.  Pumped hydroelectric storage remains the largest
source of utility-scale energy storage globally.  Grid-scale deployment of renewables
requires advances in smart grid technology, demand response, and long-duration storage.

---

## Section 7 — Quantum Cryptography (moderate quantum density)

Quantum key distribution (QKD) uses the principles of quantum mechanics to establish
a secret key between two parties with information-theoretic security.  The BB84 protocol
encodes key bits in the polarisation states of individual photons.  Any eavesdropping
attempt disturbs the quantum state, revealing the intrusion to the communicating parties.
Post-quantum cryptography refers to classical algorithms that are believed to be secure
against quantum computers; lattice-based and hash-based schemes are leading candidates
being standardised by NIST.  Quantum repeaters would extend QKD over long distances by
overcoming photon loss in fibre-optic cables.  Quantum networks could eventually form the
backbone of a quantum internet capable of distributing entanglement globally.

---

## Section 8 — Miscellaneous Technical Glossary (sparse, catch-all)

This section contains brief definitions that may appear as partial keyword matches.

- **Algorithm**: a finite sequence of instructions to solve a problem.
- **Bit**: the fundamental unit of classical information, 0 or 1.
- **Coherence time**: the duration over which a qubit maintains its quantum state.
- **Decoherence**: loss of quantum superposition due to environmental interaction.
- **Entanglement**: a quantum correlation between two or more qubits.
- **Fidelity**: a measure of how close a quantum state is to an ideal target state.
- **Gate**: a basic operation applied to one or more qubits.
- **Hamiltonian**: the operator describing the total energy of a quantum system.
- **Interference**: the quantum effect exploited by algorithms to amplify correct answers.
- **NISQ**: Noisy Intermediate-Scale Quantum — devices with 50–1000 qubits but no error correction.

---

<!--
==============================================================================
SEARCH QUERY TEST PLAN
==============================================================================

Upload this single file to OpenRAG.  After ingestion, run the queries below in
the Knowledge search bar.  Alongside the relevance badge, check what tier is
assigned and whether the tooltip breakdown makes sense.

──────────────────────────────────────────────────────────────────────────────
QUERY 1 — Single strong-match term
  Query:   quantum
  Expected result for THIS file:
    • Multiple chunks returned (Sections 1, 5, 7, 8 all contain "quantum")
    • Section 1 and Section 5 are the densest → their chunks score highest
    • Section 7 moderate → middle raw score
    • Section 8 glossary → lowest raw score (scattered mentions)
    • After min-max normalisation across all returned chunks (from any files),
      this file should land on  HIGH  because at least one chunk has a very
      strong hit.
    • Tooltip should show several High/Medium chunks and 1–2 Low chunks.

──────────────────────────────────────────────────────────────────────────────
QUERY 2 — Multi-word phrase (strong, concentrated)
  Query:   quantum error correction surface code
  Expected result:
    • Only Sections 5 and 7 have dense matches; Sections 1 and 8 partial.
    • Scores will be tighter (multi-phrase evens things out) but Section 5
      dominates → file badge should be  HIGH.
    • Tooltip: mostly High/Medium chunks, fewer Low.

──────────────────────────────────────────────────────────────────────────────
QUERY 3 — Single weak-match term (semantic drift risk)
  Query:   apple
  Expected result:
    • Only Section 3 (fruit) has "Apples" — direct keyword hit but only once.
    • Sections 1, 5 may score weakly via KNN if the embedding model drifts
      (e.g. "Apple" the company → tech content).
    • The one strong chunk (Section 3) normalises to 1.0 → file badge HIGH.
    • If the query produces very few chunk hits, the badge will still be HIGH
      because the one hit IS the maximum.
  What this tests:
    → Validates that max-score correctly avoids dilution from off-topic chunks.

──────────────────────────────────────────────────────────────────────────────
QUERY 4 — Off-topic query (expected low relevance)
  Query:   ocean thermohaline upwelling
  Expected result:
    • Section 4 has a direct keyword hit — but only one section.
    • If THIS file appears in results at all, its badge should be  LOW  or
      MEDIUM  relative to other documents in your corpus that may not match.
    • If it is the only file returned, the one-file result normalises to HIGH
      (it is the best match — there is nothing else).
  What this tests:
    → Confirms relative normalisation: a weak absolute hit still shows HIGH
      when it is the only result (which is the correct behaviour — it IS the
      most relevant document in the result set).

──────────────────────────────────────────────────────────────────────────────
QUERY 5 — Two-file comparison (upload a SECOND file to trigger multi-file tiers)
  Second file suggestion: create a short Markdown file containing ONLY the
  text from Section 1 of this document (the dense quantum section) — call it
  "quantum-dense-only.md".  Then search:

  Query:   quantum computing qubits superposition
  Expected result WITH BOTH FILES:
    • quantum-dense-only.md  → the highest raw scores (pure density) → HIGH
    • relevance-test-corpus.md → mixed scores (some high, some off-topic) → MEDIUM or HIGH
  What this tests:
    → Cross-file normalisation: the dense file steals the top of the score
      range, pushing the mixed file's normalised max downward.

──────────────────────────────────────────────────────────────────────────────
QUERY 6 — Zero-spread edge case (all chunks score identically)
  This is hard to trigger manually but can happen for very generic queries.
  Query:   the
  Expected result:
    • If OpenSearch returns results at all (threshold may filter them),
      all chunks have similar BM25 contributions from "the".
    • If the spread is near-zero, every chunk normalises to ~1.0 → HIGH.
    • The tooltip should show all chunks as High with 0 Medium / 0 Low.
  What this tests:
    → The `scoreSpread === 0` guard in useGetSearchQuery that prevents
      division-by-zero and defaults to normalised score 1.0.

==============================================================================
-->
