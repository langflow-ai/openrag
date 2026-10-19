"""Search configuration and scoring constants."""

# Baseline k-NN vector score floor under OpenSearch L2 space with 0.7 boost.
# Vectors at or below ~1.34-1.37 are orthogonal noise; 1.39 filters out spurious matches.
DEFAULT_SEARCH_SCORE_THRESHOLD: float = 1.37
