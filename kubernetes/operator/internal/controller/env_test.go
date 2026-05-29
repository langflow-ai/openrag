package controller

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	corev1 "k8s.io/api/core/v1"
)

func TestEnvVarManager_ThreeLevelPriority(t *testing.T) {
	// Create a manager with some defaults
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"VAR_A": "default_a",
			"VAR_B": "default_b",
			"VAR_C": "default_c",
		},
	}

	// Set up operator environment variables (level 2)
	_ = os.Setenv("OPTLF_VAR_B", "operator_b")
	_ = os.Setenv("OPTLF_VAR_C", "operator_c")
	defer func() {
		_ = os.Unsetenv("OPTLF_VAR_B")
		_ = os.Unsetenv("OPTLF_VAR_C")
	}()

	// CR spec env vars (level 3 - highest priority)
	crEnvVars := []corev1.EnvVar{
		{Name: "VAR_C", Value: "cr_c"},
	}

	result := manager.GetLangflowEnvVars(crEnvVars)

	// Verify priority:
	// VAR_A: only in defaults -> should be "default_a"
	// VAR_B: in defaults and operator env -> should be "operator_b"
	// VAR_C: in all three levels -> should be "cr_c" (highest priority)
	assert.Equal(t, "default_a", result["VAR_A"], "VAR_A should use default value")
	assert.Equal(t, "operator_b", result["VAR_B"], "VAR_B should use operator env value")
	assert.Equal(t, "cr_c", result["VAR_C"], "VAR_C should use CR value (highest priority)")
}

func TestEnvVarManager_OperatorEnvPrefixFiltering(t *testing.T) {
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"TEST_VAR": "default",
		},
	}

	// Set various env vars - only OPTLF_ should be picked up
	_ = os.Setenv("OPTLF_TEST_VAR", "langflow_value")
	_ = os.Setenv("OPTORBE_TEST_VAR", "backend_value")
	_ = os.Setenv("OPTORFE_TEST_VAR", "frontend_value")
	_ = os.Setenv("RANDOM_VAR", "random_value")
	defer func() {
		_ = os.Unsetenv("OPTLF_TEST_VAR")
		_ = os.Unsetenv("OPTORBE_TEST_VAR")
		_ = os.Unsetenv("OPTORFE_TEST_VAR")
		_ = os.Unsetenv("RANDOM_VAR")
	}()

	// Test Langflow - should only pick up OPTLF_
	lfResult := manager.GetLangflowEnvVars(nil)
	assert.Equal(t, "langflow_value", lfResult["TEST_VAR"], "Langflow should use OPTLF_ prefixed var")

	// Test Backend - should only pick up OPTORBE_
	manager.DefaultOpenRagBEEnvVars = map[string]string{"TEST_VAR": "default"}
	beResult := manager.GetBackendEnvVars(nil)
	assert.Equal(t, "backend_value", beResult["TEST_VAR"], "Backend should use OPTORBE_ prefixed var")

	// Test Frontend - should only pick up OPTORFE_
	manager.DefaultOpenRagFEEnvVars = map[string]string{"TEST_VAR": "default"}
	feResult := manager.GetFrontendEnvVars(nil)
	assert.Equal(t, "frontend_value", feResult["TEST_VAR"], "Frontend should use OPTORFE_ prefixed var")
}

func TestEnvVarManager_CREnvVarOverride(t *testing.T) {
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"DATABASE_URL": "sqlite:///default.db",
			"LOG_LEVEL":    "INFO",
		},
	}

	_ = os.Setenv("OPTLF_DATABASE_URL", "sqlite:///operator.db")
	defer func() {
		_ = os.Unsetenv("OPTLF_DATABASE_URL")
	}()

	// CR overrides everything
	crEnvVars := []corev1.EnvVar{
		{Name: "DATABASE_URL", Value: "postgresql://cr.db"},
		{Name: "LOG_LEVEL", Value: "DEBUG"},
	}

	result := manager.GetLangflowEnvVars(crEnvVars)

	assert.Equal(t, "postgresql://cr.db", result["DATABASE_URL"], "CR should override operator env")
	assert.Equal(t, "DEBUG", result["LOG_LEVEL"], "CR should override defaults")
}

func TestEnvVarManager_EmptyCREnvVars(t *testing.T) {
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"VAR1": "default1",
		},
	}

	result := manager.GetLangflowEnvVars(nil)
	assert.Equal(t, "default1", result["VAR1"], "Should use defaults when no CR env vars")

	result = manager.GetLangflowEnvVars([]corev1.EnvVar{})
	assert.Equal(t, "default1", result["VAR1"], "Should use defaults when empty CR env vars")
}

func TestEnvVarManager_CREnvVarWithValueFrom(t *testing.T) {
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"SECRET_KEY": "default_secret",
		},
	}

	// CR env var with valueFrom should be ignored (can't be evaluated in this context)
	crEnvVars := []corev1.EnvVar{
		{
			Name: "SECRET_KEY",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "my-secret"},
					Key:                  "key",
				},
			},
		},
	}

	result := manager.GetLangflowEnvVars(crEnvVars)
	// Should keep default since valueFrom can't be evaluated here
	assert.Equal(t, "default_secret", result["SECRET_KEY"], "Should keep default when CR has valueFrom")
}

func TestEnvVarManager_BuildEnvFileContent(t *testing.T) {
	manager := &EnvVarManager{}

	envVars := map[string]string{
		"VAR1": "value1",
		"VAR2": "value2",
		"VAR3": "value3",
	}

	content := manager.BuildEnvFileContent(envVars)

	// Should contain all three vars in key=value format
	assert.Contains(t, content, "VAR1=value1")
	assert.Contains(t, content, "VAR2=value2")
	assert.Contains(t, content, "VAR3=value3")

	// Should have newlines
	assert.Contains(t, content, "\n")

	// Should be deterministic (alphabetically sorted)
	expected := "VAR1=value1\nVAR2=value2\nVAR3=value3\n"
	assert.Equal(t, expected, content, "Output should be deterministic and sorted")

	// Verify determinism by calling multiple times
	for i := 0; i < 10; i++ {
		result := manager.BuildEnvFileContent(envVars)
		assert.Equal(t, expected, result, "Output should be identical on iteration %d", i)
	}
}

func TestEnvVarManager_RealWorldScenario(t *testing.T) {
	// Simulate a real deployment scenario
	manager := NewEnvVarManager()

	// Operator running with some env vars set
	_ = os.Setenv("OPTLF_LANGFLOW_WORKERS", "8")
	_ = os.Setenv("OPTLF_LANGFLOW_LOG_LEVEL", "INFO")
	defer func() {
		_ = os.Unsetenv("OPTLF_LANGFLOW_WORKERS")
		_ = os.Unsetenv("OPTLF_LANGFLOW_LOG_LEVEL")
	}()

	// User's CR overrides LOG_LEVEL
	crEnvVars := []corev1.EnvVar{
		{Name: "LANGFLOW_LOG_LEVEL", Value: "ERROR"},
	}

	result := manager.GetLangflowEnvVars(crEnvVars)

	// Verify the three-level priority worked correctly
	assert.Equal(t, "true", result["LANGFLOW_AUTO_LOGIN"], "Default should be used")
	assert.Equal(t, "8", result["LANGFLOW_WORKERS"], "Operator env should override default")
	assert.Equal(t, "ERROR", result["LANGFLOW_LOG_LEVEL"], "CR should override operator env")
}

func TestEnvVarManager_NewEnvVarManagerDefaults(t *testing.T) {
	manager := NewEnvVarManager()

	// Verify Langflow defaults
	assert.NotNil(t, manager.DefaultLangflowEnvVars)
	assert.Equal(t, "sqlite:////app/data/langflow.db", manager.DefaultLangflowEnvVars["LANGFLOW_DATABASE_URL"])
	assert.Equal(t, "true", manager.DefaultLangflowEnvVars["LANGFLOW_AUTO_LOGIN"])
	assert.Equal(t, "/app/flows", manager.DefaultLangflowEnvVars["LANGFLOW_LOAD_FLOWS_PATH"])
	assert.Equal(t, "4", manager.DefaultLangflowEnvVars["LANGFLOW_WORKERS"])

	// Verify Backend defaults
	assert.NotNil(t, manager.DefaultOpenRagBEEnvVars)
	assert.Equal(t, "http://openrag-be:8000", manager.DefaultOpenRagBEEnvVars["OPENRAG_BACKEND_INTERNAL_URL"])
	assert.Equal(t, "2400", manager.DefaultOpenRagBEEnvVars["LANGFLOW_TIMEOUT"])
	assert.Equal(t, "/app/backend-data", manager.DefaultOpenRagBEEnvVars["OPENRAG_DATA_PATH"])
	assert.Equal(t, "/app/openrag-documents", manager.DefaultOpenRagBEEnvVars["OPENRAG_DOCUMENTS_PATH"])
	assert.Equal(t, "DEBUG", manager.DefaultOpenRagBEEnvVars["LOG_LEVEL"])
	assert.Equal(t, "json", manager.DefaultOpenRagBEEnvVars["LOG_FORMAT"])
	assert.Equal(t, "3600", manager.DefaultOpenRagBEEnvVars["INGESTION_TIMEOUT"])
	assert.Equal(t, "4", manager.DefaultOpenRagBEEnvVars["MAX_WORKERS"])

	// Verify Frontend defaults (empty for now)
	assert.NotNil(t, manager.DefaultOpenRagFEEnvVars)
}

func TestEnvVarManager_EnsureRequiredEnvVars(t *testing.T) {
	tests := []struct {
		name           string
		inputEnvVars   map[string]string
		expectedResult map[string]string
		description    string
	}{
		{
			name: "adds missing variables with None",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,VAR2,VAR3",
				"VAR1": "existing_value",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,VAR2,VAR3",
				"VAR1": "existing_value",
				"VAR2": "None",
				"VAR3": "None",
			},
			description: "Should add VAR2 and VAR3 with 'None' value, preserve VAR1",
		},
		{
			name: "handles whitespace in variable list",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1, VAR2 , VAR3",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1, VAR2 , VAR3",
				"VAR1": "None",
				"VAR2": "None",
				"VAR3": "None",
			},
			description: "Should trim whitespace from variable names",
		},
		{
			name: "skips empty variable names",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,,VAR2,  ,VAR3",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,,VAR2,  ,VAR3",
				"VAR1": "None",
				"VAR2": "None",
				"VAR3": "None",
			},
			description: "Should skip empty strings and whitespace-only entries",
		},
		{
			name: "does nothing when LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT is missing",
			inputEnvVars: map[string]string{
				"VAR1": "value1",
			},
			expectedResult: map[string]string{
				"VAR1": "value1",
			},
			description: "Should not modify envVars when the list variable is missing",
		},
		{
			name: "does nothing when LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT is empty",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "",
				"VAR1": "value1",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "",
				"VAR1": "value1",
			},
			description: "Should not modify envVars when the list is empty",
		},
		{
			name: "preserves existing values including empty strings",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,VAR2,VAR3",
				"VAR1": "",
				"VAR2": "0",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "VAR1,VAR2,VAR3",
				"VAR1": "",
				"VAR2": "0",
				"VAR3": "None",
			},
			description: "Should preserve empty string and '0' values, only add missing VAR3",
		},
		{
			name: "handles real-world variable list",
			inputEnvVars: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "JWT,OPENSEARCH_PASSWORD,OPENSEARCH_URL,DOCLING_SERVE_URL",
				"JWT":                 "token123",
				"OPENSEARCH_PASSWORD": "secret",
			},
			expectedResult: map[string]string{
				"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "JWT,OPENSEARCH_PASSWORD,OPENSEARCH_URL,DOCLING_SERVE_URL",
				"JWT":                 "token123",
				"OPENSEARCH_PASSWORD": "secret",
				"OPENSEARCH_URL":      "None",
				"DOCLING_SERVE_URL":   "None",
			},
			description: "Should add missing OpenSearch and Docling variables",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			manager := &EnvVarManager{}

			// Call the function
			manager.EnsureRequiredEnvVars(tt.inputEnvVars)

			// Verify the result
			assert.Equal(t, tt.expectedResult, tt.inputEnvVars, tt.description)
		})
	}
}

func TestEnvVarManager_EnsureRequiredEnvVars_Integration(t *testing.T) {
	// Test with the actual default configuration
	manager := NewEnvVarManager()

	// Get the default Langflow env vars
	envVars := manager.GetLangflowEnvVars(nil)

	// Verify LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT exists
	requiredVarsStr, exists := envVars["LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT"]
	assert.True(t, exists, "LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT should exist in defaults")
	assert.NotEmpty(t, requiredVarsStr, "LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT should not be empty")

	// Call EnsureRequiredEnvVars
	manager.EnsureRequiredEnvVars(envVars)

	// Parse the required variables list
	requiredVars := []string{"JWT", "OPENRAG_QUERY_FILTER", "OPENSEARCH_PASSWORD", "OPENSEARCH_URL",
		"OPENSEARCH_INDEX_NAME", "DOCLING_SERVE_URL", "DOCLING_TASK_ID", "OWNER", "OWNER_NAME",
		"OWNER_EMAIL", "CONNECTOR_TYPE", "DOCUMENT_ID", "SOURCE_URL", "ALLOWED_USERS",
		"ALLOWED_GROUPS", "FILENAME", "MIMETYPE", "FILESIZE", "SELECTED_EMBEDDING_MODEL",
		"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "WATSONX_API_KEY", "WATSONX_ENDPOINT",
		"WATSONX_PROJECT_ID", "OLLAMA_BASE_URL"}

	// Verify all required variables exist in the envVars map
	for _, varName := range requiredVars {
		_, exists := envVars[varName]
		assert.True(t, exists, "Variable %s should exist in envVars", varName)
		// Note: Some variables may have empty string as their default value (e.g., DOCUMENT_ID, SOURCE_URL, SELECTED_EMBEDDING_MODEL)
		// The important thing is that they exist in the map
	}

	// Verify the newly added defaults are present
	assert.Equal(t, "None", envVars["OPENSEARCH_PASSWORD"], "OPENSEARCH_PASSWORD should have default 'None'")
	assert.Equal(t, "None", envVars["OPENSEARCH_URL"], "OPENSEARCH_URL should have default 'None'")
	assert.Equal(t, "None", envVars["OPENSEARCH_INDEX_NAME"], "OPENSEARCH_INDEX_NAME should have default 'None'")
	assert.Equal(t, "None", envVars["DOCLING_SERVE_URL"], "DOCLING_SERVE_URL should have default 'None'")
}

func TestEnvVarManager_EnsureRequiredEnvVars_CustomList(t *testing.T) {
	// Test with a custom LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT value
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT": "CUSTOM_VAR1,CUSTOM_VAR2",
			"CUSTOM_VAR1": "value1",
		},
	}

	envVars := manager.GetLangflowEnvVars(nil)
	manager.EnsureRequiredEnvVars(envVars)

	// Verify custom variables are handled
	assert.Equal(t, "value1", envVars["CUSTOM_VAR1"], "CUSTOM_VAR1 should preserve existing value")
	assert.Equal(t, "None", envVars["CUSTOM_VAR2"], "CUSTOM_VAR2 should be added with 'None'")
}
