# Retrieval-Augmented Generation Overview

## What Is Retrieval-Augmented Generation

Retrieval-augmented generation (RAG) combines a large language model with an external retrieval system. Instead of relying only on knowledge stored in model weights during training, a RAG system fetches relevant passages from a knowledge base and supplies them to the model as context. The model then generates an answer grounded in that retrieved evidence.

## The Dense Retriever

At the heart of most RAG pipelines is a dense retriever. It uses an embedding model to convert both documents and user queries into fixed-length numerical vectors. Texts with similar meaning land close together in vector space, even when they share few exact words. This lets the system match "how do I reset my password" with a document titled "account recovery steps". The embedding model is usually a transformer encoder trained with contrastive learning on pairs of related texts.

## Vector Index and Nearest Neighbours

Document embeddings are stored in a vector index. At query time, the query is embedded with the same embedding model, and the index returns the nearest neighbours: the stored vectors with the highest similarity, typically by cosine similarity or inner product. Exact search is expensive at scale, so production systems use approximate algorithms such as HNSW graphs, trading a little recall for large gains in speed.

## Inference Time Retrieval

Retrieval happens at inference time, not during training. Each request triggers a fresh lookup, so the system can answer using documents added to the knowledge base minutes ago. Updating knowledge only requires re-indexing new content, which is far cheaper than fine-tuning a model. The retrieved chunks are inserted into the prompt, and the language model composes the final response from them.

## Hallucination Reduction

A major motivation for RAG is hallucination reduction. A model without grounding may produce fluent but incorrect statements. Conditioning generation on retrieved passages gives the model verifiable source text, and answers can include citations users can check. Poor retrieval can still produce unsupported answers, so retrieval quality sets the ceiling for answer quality.
