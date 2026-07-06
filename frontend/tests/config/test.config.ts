import * as dotenv from "dotenv";
import * as path from "path";

dotenv.config();
/**
 * Test configuration constants
 * Centralized configuration for all tests
 */

export const TEST_CONFIG = {
  // Base URLs
  baseUrl: process.env.BASE_URL || "http://localhost:3000",
  chatUrl: process.env.BASE_URL
    ? `${process.env.BASE_URL}/chat`
    : "http://localhost:3000/chat",

  //Watsonx config
  watsonx: {
    url: process.env.WATSONX_ENDPOINT!,
    projectId: process.env.WATSONX_PROJECT_ID!,
    apiKey: process.env.WATSONX_API_KEY!,
  },
  openaiApiKey: process.env.OPENAI_API_KEY!,
  // Timeouts (in milliseconds)
  timeouts: {
    default: 60000, // 1 minute
    upload: 120000, // 2 minutes
    indexing: 180000, // 3 minutes
    authentication: 30000, // 30 seconds
  },

  // Test documents (using relative paths from project root)
  documents: {
    kubernetes: {
      path: path.join(__dirname, "../test-data/kubernetes.pdf"),
      name: "kubernetes.pdf",
    },
    docling: {
      path: path.join(__dirname, "../test-data/docling.pdf"),
      name: "docling.pdf",
    },
    versioning: {
      path: path.join(__dirname, "../test-data/08_Versioning.pdf"),
      name: "08_Versioning.pdf",
    },
    // Folder containing all sample files for format testing
    allSampleFiles: {
      path: path.join(__dirname, "../test-data/all_sample_files"),
      name: "all_sample_files",
    },
  },

  // Supported file formats for ingestion testing
  supportedFormats: [
    "txt",
    "md",
    "html",
    "adoc",
    "asciidoc",
    "asc",
    "pdf",
    "docx",
    "csv",
    "pptx",
    "htm",
  ],

  // Chunk settings for performance tests
  chunkSettings: {
    sizes: [200, 500, 1000],
    overlaps: [0, 50, 100, 150, 200],
    defaultSize: "500",
    defaultOverlap: "50",
  },

  // Test questions
  questions: {
    kubernetes: {
      controlPlane: "What are the components of the Kubernetes Control Plane?",
      inventor: "Who invented Kubernetes?",
      scheduling: "Explain how Kubernetes scheduling works.",
    },
    general: {
      capital: "What is the capital of France?",
      moon: "Write a poem about the moon",
    },
    docling: {
      pipeline:
        "Explain the Docling processing pipeline in detail, including all stages from PDF parsing to final output.",
      models:
        "What are the two AI models released with Docling, explain their specific purposes, the datasets they were trained on, and their performance characteristics?",
    },
    fallback: {
      unrelated:
        "What is Myasthenia Gravis explain from document from knowledge section?",
    },
  },
};

export default TEST_CONFIG;
