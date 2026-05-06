package controller

import (
	"fmt"
	"os"

	corev1 "k8s.io/api/core/v1"
)

// Example demonstrates the three-level environment variable priority system
func Example_envVarPriority() {
	// Create the EnvVarManager with hardcoded defaults
	manager := NewEnvVarManager()

	// Simulate operator environment variables (Level 2)
	// In production, these would be set in the operator's deployment
	_ = os.Setenv("OPTLF_LANGFLOW_WORKERS", "8")
	_ = os.Setenv("OPTLF_LANGFLOW_LOG_LEVEL", "INFO")
	defer func() {
		_ = os.Unsetenv("OPTLF_LANGFLOW_WORKERS")
		_ = os.Unsetenv("OPTLF_LANGFLOW_LOG_LEVEL")
	}()

	// Simulate CR spec env vars (Level 3 - highest priority)
	crEnvVars := []corev1.EnvVar{
		{Name: "LANGFLOW_LOG_LEVEL", Value: "ERROR"},
	}

	// Get merged env vars with all three levels applied
	mergedEnvVars := manager.GetLangflowEnvVars(crEnvVars)

	// Check the results
	fmt.Printf("LANGFLOW_AUTO_LOGIN: %s (from defaults)\n", mergedEnvVars["LANGFLOW_AUTO_LOGIN"])
	fmt.Printf("LANGFLOW_WORKERS: %s (from operator env)\n", mergedEnvVars["LANGFLOW_WORKERS"])
	fmt.Printf("LANGFLOW_LOG_LEVEL: %s (from CR spec)\n", mergedEnvVars["LANGFLOW_LOG_LEVEL"])

	// Build the .env file content
	envFileContent := manager.BuildEnvFileContent(mergedEnvVars)
	fmt.Printf("\n.env file would contain %d bytes\n", len(envFileContent))

	// Output:
	// LANGFLOW_AUTO_LOGIN: true (from defaults)
	// LANGFLOW_WORKERS: 8 (from operator env)
	// LANGFLOW_LOG_LEVEL: ERROR (from CR spec)
	//
	// .env file would contain 1246 bytes
}

// Example showing how different components use different prefixes
func Example_componentSpecificPrefixes() {
	manager := &EnvVarManager{
		DefaultLangflowEnvVars: map[string]string{
			"WORKERS": "4",
		},
		DefaultOpenRagBEEnvVars: map[string]string{
			"WORKERS": "2",
		},
		DefaultOpenRagFEEnvVars: map[string]string{
			"WORKERS": "1",
		},
	}

	// Set operator env vars with different prefixes
	_ = os.Setenv("OPTLF_WORKERS", "langflow_8")
	_ = os.Setenv("OPTORBE_WORKERS", "backend_6")
	_ = os.Setenv("OPTORFE_WORKERS", "frontend_4")
	defer func() {
		_ = os.Unsetenv("OPTLF_WORKERS")
		_ = os.Unsetenv("OPTORBE_WORKERS")
		_ = os.Unsetenv("OPTORFE_WORKERS")
	}()

	// Each component gets its own prefix
	lfVars := manager.GetLangflowEnvVars(nil)
	beVars := manager.GetBackendEnvVars(nil)
	feVars := manager.GetFrontendEnvVars(nil)

	fmt.Printf("Langflow WORKERS: %s\n", lfVars["WORKERS"])
	fmt.Printf("Backend WORKERS: %s\n", beVars["WORKERS"])
	fmt.Printf("Frontend WORKERS: %s\n", feVars["WORKERS"])

	// Output:
	// Langflow WORKERS: langflow_8
	// Backend WORKERS: backend_6
	// Frontend WORKERS: frontend_4
}
