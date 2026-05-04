from __future__ import annotations
import numpy as np

def cosine_sim_matrix(X: np.ndarray) -> np.ndarray:
    # normalize
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    Xn = X / norms
    return Xn @ Xn.T
