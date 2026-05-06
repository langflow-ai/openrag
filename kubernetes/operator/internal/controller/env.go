package controller

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"os"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
)

const (
	LANGFLOW_ENV_PREFIX  = "OPTLF_"
	OPENRAGBE_ENV_PREFIX = "OPTORBE_"
	OPENRAGFE_ENV_PREFIX = "OPTORFE_"
)

type EnvVarManager struct {
	// a map makes look up faster and easier
	DefaultLangflowEnvVars  map[string]string
	DefaultOpenRagBEEnvVars map[string]string
	DefaultOpenRagFEEnvVars map[string]string
}

func NewEnvVarManager() *EnvVarManager {
	return &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			// Database configuration
			"LANGFLOW_DATABASE_URL": "sqlite:////app/data/langflow.db",

			// Variables to expose to Langflow components
			"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "JWT,OPENRAG_QUERY_FILTER,OPENSEARCH_PASSWORD,OPENSEARCH_URL,OPENSEARCH_INDEX_NAME,DOCLING_SERVE_URL,OWNER,OWNER_NAME,OWNER_EMAIL,CONNECTOR_TYPE,DOCUMENT_ID,SOURCE_URL,ALLOWED_USERS,ALLOWED_GROUPS,FILENAME,MIMETYPE,FILESIZE,SELECTED_EMBEDDING_MODEL,OPENAI_API_KEY,ANTHROPIC_API_KEY,WATSONX_API_KEY,WATSONX_ENDPOINT,WATSONX_PROJECT_ID,OLLAMA_BASE_URL",

			// Authentication and user management
			"LANGFLOW_SKIP_AUTH_AUTO_LOGIN": "true",
			"LANGFLOW_NEW_USER_IS_ACTIVE":   "false",
			"LANGFLOW_AUTO_LOGIN":           "true",
			"LANGFLOW_ENABLE_SUPERUSER_CLI": "false",

			// Langflow runtime configuration
			"LANGFLOW_WORKERS":               "4",
			"LANGFLOW_CONFIG_DIR":            "/tmp",
			"LANGFLOW_LOG_LEVEL":             "DEBUG",
			"HIDE_GETTING_STARTED_PROGRESS":  "true",
			"LANGFLOW_ALEMBIC_LOG_TO_STDOUT": "true",
			"LANGFLOW_DEACTIVATE_TRACING":    "true",
			"LANGFLOW_LOAD_FLOWS_PATH":       "/app/flows",
			"LANGFUSE_HOST":                  "https://cloud.langfuse.com",
			"LANGFLOW_KEY_RETRIES":           "15",
			"LANGFLOW_KEY_RETRY_DELAY":       "2",

			// Flow context defaults
			"JWT":                      "None",
			"OWNER":                    "None",
			"OWNER_NAME":               "None",
			"OWNER_EMAIL":              "None",
			"CONNECTOR_TYPE":           "system",
			"CONNECTOR_TYPE_URL":       "url",
			"DOCUMENT_ID":              "",
			"SOURCE_URL":               "",
			"ALLOWED_USERS":            "[]",
			"ALLOWED_GROUPS":           "[]",
			"OPENRAG_QUERY_FILTER":     "{}",
			"FILENAME":                 "None",
			"MIMETYPE":                 "None",
			"FILESIZE":                 "0",
			"SELECTED_EMBEDDING_MODEL": "",

			// Provider API keys (defaults to None, overridden by CR spec)
			"OPENAI_API_KEY":    "None",
			"ANTHROPIC_API_KEY": "None",
			"WATSONX_API_KEY":   "None",
			"OLLAMA_BASE_URL":   "None",
		},
		DefaultOpenRagBEEnvVars: map[string]string{
			// Langflow connection
			"LANGFLOW_URL":             "http://langflow:7860",
			"LANGFLOW_TIMEOUT":         "2400",
			"LANGFLOW_CONNECT_TIMEOUT": "30",
			"LANGFLOW_AUTO_LOGIN":      "true",
			"LANGFLOW_KEY_RETRIES":     "15",
			"LANGFLOW_KEY_RETRY_DELAY": "2",
			"LANGFLOW_KEY":             "",

			// Backend data paths
			"OPENRAG_DATA_PATH":         "/app/backend-data",
			"OPENRAG_DOCUMENTS_PATH":    "/app/openrag-documents",
			"OPENRAG_FLOWS_BACKUP_PATH": "/app/backend-data/flow-backups",
			"OPENRAG_KEYS_PATH":         "/app/backend-data/keys",
			"OPENRAG_CONFIG_PATH":       "/app/backend-data/config",
			"OPENRAG_VERSION":           "latest",

			// OpenSearch configuration
			"OPENSEARCH_DATA_PATH": "",

			// Logging configuration
			"LOG_LEVEL":    "DEBUG",
			"LOG_FORMAT":   "json",
			"ACCESS_LOG":   "true",
			"SERVICE_NAME": "openrag",

			// Environment
			"ENVIRONMENT": "development",

			// Ingestion configuration
			"INGEST_SAMPLE_DATA":           "true",
			"DISABLE_INGEST_WITH_LANGFLOW": "false",
			"INGESTION_TIMEOUT":            "3600",
			"UPLOAD_BATCH_SIZE":            "25",
			"MAX_WORKERS":                  "4",

			// Segment analytics (default empty, set via CR or operator env)
			"SEGMENT_WRITE_KEY": "",
		},
		DefaultOpenRagFEEnvVars: map[string]string{
			// Frontend environment variables will be added here
		},
	}
}

// GetLangflowEnvVars returns merged Langflow env vars with three-level priority:
// 1. Highest priority: CR spec env vars
// 2. Medium priority: Operator env vars with OPTLF_ prefix
// 3. Lowest priority: Hardcoded defaults
func (m *EnvVarManager) GetLangflowEnvVars(crEnvVars []corev1.EnvVar) map[string]string {
	return m.mergeEnvVars(m.DefaultLangflowEnvVars, LANGFLOW_ENV_PREFIX, crEnvVars)
}

// GetBackendEnvVars returns merged Backend env vars with three-level priority:
// 1. Highest priority: CR spec env vars
// 2. Medium priority: Operator env vars with OPTORBE_ prefix
// 3. Lowest priority: Hardcoded defaults
func (m *EnvVarManager) GetBackendEnvVars(crEnvVars []corev1.EnvVar) map[string]string {
	return m.mergeEnvVars(m.DefaultOpenRagBEEnvVars, OPENRAGBE_ENV_PREFIX, crEnvVars)
}

// GetFrontendEnvVars returns merged Frontend env vars with three-level priority:
// 1. Highest priority: CR spec env vars
// 2. Medium priority: Operator env vars with OPTORFE_ prefix
// 3. Lowest priority: Hardcoded defaults
func (m *EnvVarManager) GetFrontendEnvVars(crEnvVars []corev1.EnvVar) map[string]string {
	return m.mergeEnvVars(m.DefaultOpenRagFEEnvVars, OPENRAGFE_ENV_PREFIX, crEnvVars)
}

// mergeEnvVars implements the three-level override priority:
// Level 1 (Lowest):  hardcoded defaults
// Level 2 (Medium):  operator environment variables with prefix
// Level 3 (Highest): CR spec env vars
func (m *EnvVarManager) mergeEnvVars(defaults map[string]string, prefix string, crEnvVars []corev1.EnvVar) map[string]string {
	result := make(map[string]string)

	// Level 1: Start with hardcoded defaults (lowest priority)
	for k, v := range defaults {
		result[k] = v
	}

	// Level 2: Override with operator environment variables (medium priority)
	// Read operator's environment and apply any variables with the matching prefix
	for _, envVar := range os.Environ() {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key, value := parts[0], parts[1]

		// Check if this env var has the expected prefix
		if strings.HasPrefix(key, prefix) {
			// Remove the prefix to get the actual env var name
			actualKey := strings.TrimPrefix(key, prefix)
			result[actualKey] = value
		}
	}

	// Level 3: Override with CR spec env vars (highest priority)
	for _, envVar := range crEnvVars {
		// Only process direct value assignments (not valueFrom)
		if envVar.Value != "" {
			result[envVar.Name] = envVar.Value
		}
	}

	return result
}

// BuildEnvFileContent converts a map of env vars to .env file format
func (m *EnvVarManager) BuildEnvFileContent(envVars map[string]string) string {
	// Sort keys to ensure deterministic output
	keys := make([]string, 0, len(envVars))
	for k := range envVars {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var b strings.Builder
	for _, k := range keys {
		b.WriteString(k)
		b.WriteString("=")
		b.WriteString(envVars[k])
		b.WriteString("\n")
	}
	return b.String()
}

// Generates a base64-encoded string of exactly 32 bytes for Fernet
func generateBase64SecretKey() (string, error) {
	randomBytes := make([]byte, 32)
	_, err := rand.Read(randomBytes)
	if err != nil {
		return "", fmt.Errorf("failed to generate random bytes: %w", err)
	}

	// Use URL-safe base64 encoding
	password := base64.URLEncoding.EncodeToString(randomBytes)
	return password, nil
}

func GenerateAESKey(size int) ([]byte, error) {
	switch size {
	case 16, 24, 32:
	default:
		return nil, fmt.Errorf("invalid AES key size %d: must be 16, 24, or 32 bytes", size)
	}

	key := make([]byte, size)
	if _, err := rand.Read(key); err != nil {
		return nil, fmt.Errorf("failed to generate AES key: %w", err)
	}

	return key, nil
}

func GenerateAESKeyString(size int) (string, error) {
	key, err := GenerateAESKey(size)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(key), nil
}

func GenerateAESKeyString32() (string, error) {
	return GenerateAESKeyString(32)
}
