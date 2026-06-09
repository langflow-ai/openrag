package controller

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
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
			"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "JWT,OPENRAG_QUERY_FILTER,OPENSEARCH_PASSWORD,OPENSEARCH_URL,OPENSEARCH_INDEX_NAME,DOCLING_SERVE_URL,DOCLING_SERVE_VERIFY_SSL,DOCLING_TASK_ID,OWNER,OWNER_NAME,OWNER_EMAIL,CONNECTOR_TYPE,DOCUMENT_ID,SOURCE_URL,ALLOWED_USERS,ALLOWED_GROUPS,ALLOWED_PRINCIPALS,FILENAME,MIMETYPE,FILESIZE,SELECTED_EMBEDDING_MODEL,OPENAI_API_KEY,ANTHROPIC_API_KEY,WATSONX_API_KEY,WATSONX_ENDPOINT,WATSONX_PROJECT_ID,OLLAMA_BASE_URL,OPENRAG_INGEST_URL,OPENRAG_INGEST_TOKEN,OPENRAG_INGEST_RUN_ID,OPENRAG_INGEST_BATCH_SIZE",

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
			"JWT":                       "None",
			"OWNER":                     "None",
			"OWNER_NAME":                "None",
			"OWNER_EMAIL":               "None",
			"DOCLING_TASK_ID":           "None",
			"CONNECTOR_TYPE":            "system",
			"CONNECTOR_TYPE_URL":        "url",
			"DOCUMENT_ID":               "",
			"SOURCE_URL":                "",
			"ALLOWED_USERS":             "[]",
			"ALLOWED_GROUPS":            "[]",
			"ALLOWED_PRINCIPALS":        "[]",
			"OPENRAG_QUERY_FILTER":      "{}",
			"OPENRAG_INGEST_URL":        "OPENRAG_INGEST_URL",
			"OPENRAG_INGEST_TOKEN":      "OPENRAG_INGEST_TOKEN",
			"OPENRAG_INGEST_RUN_ID":     "OPENRAG_INGEST_RUN_ID",
			"OPENRAG_INGEST_BATCH_SIZE": "100",
			"FILENAME":                  "None",
			"MIMETYPE":                  "None",
			"FILESIZE":                  "0",
			"SELECTED_EMBEDDING_MODEL":  "",

			// OpenSearch defaults (for variables in LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT)
			"OPENSEARCH_PASSWORD":   "None",
			"OPENSEARCH_URL":        "None",
			"OPENSEARCH_INDEX_NAME": "None",

			// Docling defaults (for variables in LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT)
			"DOCLING_SERVE_URL":        "None",
			"DOCLING_SERVE_VERIFY_SSL": "false",

			// Provider API keys (defaults to None, overridden by CR spec)
			"OPENAI_API_KEY":     "None",
			"ANTHROPIC_API_KEY":  "None",
			"WATSONX_API_KEY":    "None",
			"OLLAMA_BASE_URL":    "None",
			"WATSONX_ENDPOINT":   "https://us-south.ml.cloud.ibm.com",
			"WATSONX_PROJECT_ID": "None",
			"LLM_MODEL":          "ibm/granite-3-2-8b-instruct",
			"LLM_PROVIDER":       "watsonx",
		},
		DefaultOpenRagBEEnvVars: map[string]string{
			// Langflow connection
			"LANGFLOW_URL":                  "http://langflow:7860",
			"OPENRAG_BACKEND_INTERNAL_URL":  "http://openrag-be:8000",
			"OPENRAG_BACKEND_ROUTER_ENABLE": "false",
			"OPENRAG_BACKEND_ROUTER_PORT":   "8100",
			"LANGFLOW_TIMEOUT":              "2400",
			"LANGFLOW_CONNECT_TIMEOUT":      "30",
			"LANGFLOW_AUTO_LOGIN":           "true",
			"LANGFLOW_KEY_RETRIES":          "15",
			"LANGFLOW_KEY_RETRY_DELAY":      "2",
			"LANGFLOW_KEY":                  "",

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

			// Embedding model configuration
			"EMBEDDING_MODEL":    "",
			"EMBEDDING_PROVIDER": "",

			"WATSONX_API_KEY":          "",
			"WATSONX_ENDPOINT":         "",
			"WATSONX_PROJECT_ID":       "",
			"DOCLING_SERVE_VERIFY_SSL": "false",
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
func (m *EnvVarManager) GetLangflowEnvVars(ctx context.Context, c client.Client, namespace string, crEnvVars []corev1.EnvVar) (map[string]string, error) {
	return m.mergeEnvVars(ctx, c, namespace, m.DefaultLangflowEnvVars, LANGFLOW_ENV_PREFIX, crEnvVars)
}

// GetBackendEnvVars returns merged Backend env vars with three-level priority:
// 1. Highest priority: CR spec env vars (including resolved secrets/configmaps)
// 2. Medium priority: Operator env vars with OPTORBE_ prefix
// 3. Lowest priority: Hardcoded defaults
func (m *EnvVarManager) GetBackendEnvVars(ctx context.Context, c client.Client, namespace string, crEnvVars []corev1.EnvVar) (map[string]string, error) {
	return m.mergeEnvVars(ctx, c, namespace, m.DefaultOpenRagBEEnvVars, OPENRAGBE_ENV_PREFIX, crEnvVars)
}

// GetFrontendEnvVars returns merged Frontend env vars with three-level priority:
// 1. Highest priority: CR spec env vars (including resolved secrets/configmaps)
// 2. Medium priority: Operator env vars with OPTORFE_ prefix
// 3. Lowest priority: Hardcoded defaults
func (m *EnvVarManager) GetFrontendEnvVars(ctx context.Context, c client.Client, namespace string, crEnvVars []corev1.EnvVar) (map[string]string, error) {
	return m.mergeEnvVars(ctx, c, namespace, m.DefaultOpenRagFEEnvVars, OPENRAGFE_ENV_PREFIX, crEnvVars)
}

// mergeEnvVars implements the three-level override priority:
// Level 1 (Lowest):  hardcoded defaults
// Level 2 (Medium):  operator environment variables with prefix
// Level 3 (Highest): CR spec env vars (including resolved secret/configmap references)
//
// ALL env vars (including those from secrets) are resolved and added to the result map.
// This ensures they appear ONLY in the .env file, not in the container's Env field,
// so they don't show up when users run 'env' command in the pod.
func (m *EnvVarManager) mergeEnvVars(ctx context.Context, c client.Client, namespace string, defaults map[string]string, prefix string, crEnvVars []corev1.EnvVar) (map[string]string, error) {
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
	// CR values are always respected as-is, including empty string.
	for _, envVar := range crEnvVars {
		if envVar.ValueFrom != nil {
			value, found, err := resolveEnvVarValue(ctx, c, namespace, &envVar)
			if err != nil {
				return nil, fmt.Errorf("failed to resolve env var %s: %w", envVar.Name, err)
			}
			if !found {
				// Optional reference not found — leave any existing value in place
				continue
			}
			result[envVar.Name] = value
		} else {
			// Direct value: always set, even if empty. CR is authoritative.
			result[envVar.Name] = envVar.Value
		}
	}

	return result, nil
}

// resolveEnvVarValue resolves a Kubernetes EnvVarSource to its actual string value.
// Supports secretKeyRef and configMapKeyRef. fieldRef is not supported as it requires
// runtime pod information (like pod name, namespace) that isn't available at reconcile time.
func resolveEnvVarValue(ctx context.Context, c client.Client, namespace string, envVar *corev1.EnvVar) (string, bool, error) {
	if envVar.ValueFrom == nil {
		return "", false, nil
	}

	// Resolve secret reference
	if envVar.ValueFrom.SecretKeyRef != nil {
		secret := &corev1.Secret{}
		secretName := envVar.ValueFrom.SecretKeyRef.Name
		secretKey := envVar.ValueFrom.SecretKeyRef.Key

		err := c.Get(ctx, client.ObjectKey{Namespace: namespace, Name: secretName}, secret)
		if err != nil {
			// If optional is true, don't fail on missing secret
			if envVar.ValueFrom.SecretKeyRef.Optional != nil && *envVar.ValueFrom.SecretKeyRef.Optional {
				return "", false, nil
			}
			return "", false, fmt.Errorf("failed to get secret %s: %w", secretName, err)
		}

		value, ok := secret.Data[secretKey]
		if !ok {
			if envVar.ValueFrom.SecretKeyRef.Optional != nil && *envVar.ValueFrom.SecretKeyRef.Optional {
				return "", false, nil
			}
			return "", false, fmt.Errorf("key %s not found in secret %s", secretKey, secretName)
		}

		return string(value), true, nil
	}

	// Resolve configmap reference
	if envVar.ValueFrom.ConfigMapKeyRef != nil {
		configMap := &corev1.ConfigMap{}
		configMapName := envVar.ValueFrom.ConfigMapKeyRef.Name
		configMapKey := envVar.ValueFrom.ConfigMapKeyRef.Key

		err := c.Get(ctx, client.ObjectKey{Namespace: namespace, Name: configMapName}, configMap)
		if err != nil {
			if envVar.ValueFrom.ConfigMapKeyRef.Optional != nil && *envVar.ValueFrom.ConfigMapKeyRef.Optional {
				return "", false, nil
			}
			return "", false, fmt.Errorf("failed to get configmap %s: %w", configMapName, err)
		}

		value, ok := configMap.Data[configMapKey]
		if !ok {
			if envVar.ValueFrom.ConfigMapKeyRef.Optional != nil && *envVar.ValueFrom.ConfigMapKeyRef.Optional {
				return "", false, nil
			}
			return "", false, fmt.Errorf("key %s not found in configmap %s", configMapKey, configMapName)
		}

		return value, true, nil
	}

	// fieldRef and resourceFieldRef cannot be resolved at reconcile time
	if envVar.ValueFrom.FieldRef != nil {
		return "", false, fmt.Errorf("fieldRef is not supported in spec.env (requires runtime pod info). Use direct values or secretKeyRef instead")
	}

	if envVar.ValueFrom.ResourceFieldRef != nil {
		return "", false, fmt.Errorf("resourceFieldRef is not supported in spec.env. Use direct values or secretKeyRef instead")
	}

	// no supported valueFrom type found
	return "", false, nil
}

// BuildEnvFileContent converts a map of env vars to .env file format.
// Values are written raw unless they contain characters that would break dotenv
// parsing without quoting: newlines, carriage returns, or '#' (comment marker).
// Those values are double-quoted via strconv.Quote so the content is preserved.
func (m *EnvVarManager) BuildEnvFileContent(envVars map[string]string) string {
	// Sort keys to ensure deterministic output
	keys := make([]string, 0, len(envVars))
	for k := range envVars {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var b strings.Builder
	for _, k := range keys {
		v := envVars[k]
		b.WriteString(k)
		b.WriteString("=")
		if strings.ContainsAny(v, "\n\r#") {
			b.WriteString(strconv.Quote(v))
		} else {
			b.WriteString(v)
		}
		b.WriteString("\n")
	}
	return b.String()
}

// EnsureRequiredEnvVars ensures all variables listed in LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT
// exist in the envVars map with at least a "None" value. This is critical because Langflow components
// expect these variables to be present in the environment, and the list can be customized via CR spec,
// operator env vars (OPTLF_LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT), or defaults.
func (m *EnvVarManager) EnsureRequiredEnvVars(envVars map[string]string) {
	// Get the list of required variables
	requiredVarsStr, exists := envVars["LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT"]
	if !exists || requiredVarsStr == "" {
		return
	}

	// Parse comma-separated list
	requiredVars := strings.Split(requiredVarsStr, ",")

	// Ensure each variable exists with at least "None" value
	for _, varName := range requiredVars {
		varName = strings.TrimSpace(varName)
		if varName == "" {
			continue
		}

		// Only add if not already present
		if _, exists := envVars[varName]; !exists {
			envVars[varName] = "None"
		}
	}
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
