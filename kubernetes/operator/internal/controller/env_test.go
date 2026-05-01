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
