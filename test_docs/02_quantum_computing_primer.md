# Introduction to Quantum Computing & Superposition

Quantum computing leverages the fundamental principles of quantum mechanics—superposition, entanglement, and quantum interference—to perform complex calculations exponentially faster than classical computers for specific problem classes.

A classical bit can exist in a deterministic state of either 0 or 1. In contrast, a quantum bit (qubit) is represented by a two-level quantum system described by state vectors in a complex Hilbert space:

$$|\psi\rangle = \alpha|0\rangle + \beta|1\rangle$$

where $\alpha$ and $\beta$ are complex probability amplitudes satisfying the normalization constraint $|\alpha|^2 + |\beta|^2 = 1$. When measured, the superposition collapses into one of the basis states with probabilities corresponding to $|\alpha|^2$ and $|\beta|^2$.

---

# Quantum Entanglement and Shor's Algorithm

Quantum entanglement occurs when pairs or groups of particles interact such that the quantum state of each particle cannot be described independently of the state of the others, even when separated by macroscopic distances.

Quantum algorithms utilize entanglement and interference to cancel out destructive computational paths and amplify constructive amplitudes corresponding to correct solutions:
- **Shor's Algorithm**: Solves integer factorization in polynomial time, posing cryptographic challenges to classical RSA and elliptic-curve cryptography.
- **Grover's Algorithm**: Provides a quadratic speedup for unstructured database searches, reducing search complexity from $O(N)$ to $O(\sqrt{N})$.
- **Quantum Phase Estimation (QPE)**: A foundational subroutine in quantum chemistry simulations and Hamiltonian energy calculations.
