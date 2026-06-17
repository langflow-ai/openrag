package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// TestComponentSpec_Env_DirectValues_GoToEnvFileOnly verifies that
// env vars with direct values (e.g., {Name: "FOO", Value: "bar"}) are included in
// the .env file ONLY, and NOT in the container's environment variables.
func TestComponentSpec_Env_DirectValues_GoToEnvFileOnly(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "custom_value"},
		{Name: "ANOTHER_VAR", Value: "another_value"},
	}

	// Check .env file content contains direct values
	backendEnvContent, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent, `CUSTOM_VAR=custom_value`,
		"Direct value should be in .env file")
	assert.Contains(t, backendEnvContent, `ANOTHER_VAR=another_value`,
		"Direct value should be in .env file")

	// Check container env is EMPTY (no spec.Env)
	deploy := r.backendDeployment(cr, "test-ns", "hash123")
	containerEnv := deploy.Spec.Template.Spec.Containers[0].Env

	// Container Env should be empty or only contain operator-managed vars
	// It should NOT contain CUSTOM_VAR or ANOTHER_VAR
	for _, env := range containerEnv {
		assert.NotEqual(t, "CUSTOM_VAR", env.Name, "CUSTOM_VAR should NOT be in container env")
		assert.NotEqual(t, "ANOTHER_VAR", env.Name, "ANOTHER_VAR should NOT be in container env")
	}
}

// TestComponentSpec_Env_SecretRefs_ResolvedToEnvFile verifies that
// env vars with secret references (e.g., {Name: "FOO", ValueFrom: {SecretKeyRef: ...}})
// are RESOLVED at reconcile time and the actual value is embedded in the .env file.
// They do NOT appear in the container's environment variables.
func TestComponentSpec_Env_SecretRefs_ResolvedToEnvFile(t *testing.T) {
	s := newScheme(t)

	// Create a secret with password
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "db-secret",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"password": []byte("super-secret-password"),
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, secret)

	cr.Spec.Backend.Env = []corev1.EnvVar{
		{
			Name: "DATABASE_PASSWORD",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "db-secret"},
					Key:                  "password",
				},
			},
		},
		{Name: "REGULAR_VAR", Value: "regular_value"},
	}

	// Check .env file content - should contain RESOLVED secret value
	backendEnvContent, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent, `DATABASE_PASSWORD=super-secret-password`,
		".env file should contain RESOLVED secret value")
	assert.Contains(t, backendEnvContent, `REGULAR_VAR=regular_value`,
		".env file should contain direct values")

	// Check container env - should be EMPTY (no spec.Env)
	deploy := r.backendDeployment(cr, "test-ns", "hash123")
	containerEnv := deploy.Spec.Template.Spec.Containers[0].Env

	// Container Env should NOT contain DATABASE_PASSWORD or REGULAR_VAR
	for _, env := range containerEnv {
		assert.NotEqual(t, "DATABASE_PASSWORD", env.Name, "DATABASE_PASSWORD should NOT be in container env")
		assert.NotEqual(t, "REGULAR_VAR", env.Name, "REGULAR_VAR should NOT be in container env")
	}
}

// TestComponentSpec_Env_ConfigMapRefs_ResolvedToEnvFile verifies that
// configmap references are resolved and embedded in .env file.
func TestComponentSpec_Env_ConfigMapRefs_ResolvedToEnvFile(t *testing.T) {
	s := newScheme(t)

	// Create a configmap
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "api-config",
			Namespace: "test-ns",
		},
		Data: map[string]string{
			"endpoint": "https://api.example.com",
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, configMap)

	cr.Spec.Backend.Env = []corev1.EnvVar{
		{
			Name: "API_ENDPOINT",
			ValueFrom: &corev1.EnvVarSource{
				ConfigMapKeyRef: &corev1.ConfigMapKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "api-config"},
					Key:                  "endpoint",
				},
			},
		},
	}

	// Check .env file - should contain resolved value
	backendEnvContent, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent, `API_ENDPOINT=https://api.example.com`,
		".env file should contain resolved configmap value")

	// Check container env - should be empty
	deploy := r.backendDeployment(cr, "test-ns", "hash123")
	containerEnv := deploy.Spec.Template.Spec.Containers[0].Env

	for _, env := range containerEnv {
		assert.NotEqual(t, "API_ENDPOINT", env.Name, "API_ENDPOINT should NOT be in container env")
	}
}

// TestComponentSpec_Env_Langflow_SameBehavior verifies that Langflow component
// has the same behavior: all env vars resolved and in .env file only.
func TestComponentSpec_Env_Langflow_SameBehavior(t *testing.T) {
	s := newScheme(t)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "lf-secret",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"key": []byte("secret-value"),
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, secret)

	cr.Spec.Langflow.Env = []corev1.EnvVar{
		{Name: "DIRECT_VAR", Value: "direct_value"},
		{
			Name: "SECRET_VAR",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "lf-secret"},
					Key:                  "key",
				},
			},
		},
	}

	// Check .env file
	langflowEnvContent, err := r.buildLangflowEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, langflowEnvContent, `DIRECT_VAR=direct_value`,
		"Direct value should be in Langflow .env file")
	assert.Contains(t, langflowEnvContent, `SECRET_VAR=secret-value`,
		"Resolved secret value should be in Langflow .env file")

	// Check container env is empty
	deploy := r.langflowDeployment(cr, "test-ns", "hash123")
	containerEnv := deploy.Spec.Template.Spec.Containers[0].Env

	for _, env := range containerEnv {
		assert.NotEqual(t, "DIRECT_VAR", env.Name, "DIRECT_VAR should NOT be in container env")
		assert.NotEqual(t, "SECRET_VAR", env.Name, "SECRET_VAR should NOT be in container env")
	}
}

// TestComponentSpec_Env_FieldRef_RejectedWithError verifies that field references
// (like pod name, namespace) are rejected because they cannot be resolved at reconcile time.
func TestComponentSpec_Env_FieldRef_RejectedWithError(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)

	cr.Spec.Backend.Env = []corev1.EnvVar{
		{
			Name: "POD_NAME",
			ValueFrom: &corev1.EnvVarSource{
				FieldRef: &corev1.ObjectFieldSelector{
					FieldPath: "metadata.name",
				},
			},
		},
	}

	// Should fail with clear error message
	_, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "fieldRef is not supported",
		"Should reject fieldRef with helpful error message")
}

// TestComponentSpec_Env_MixedTypes_AllResolvedToEnvFile verifies that when a CR has
// a mix of direct values and references, they are ALL resolved and put in .env file only.
func TestComponentSpec_Env_MixedTypes_AllResolvedToEnvFile(t *testing.T) {
	s := newScheme(t)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "my-secret",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"key1": []byte("secret-value-1"),
		},
	}

	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "my-config",
			Namespace: "test-ns",
		},
		Data: map[string]string{
			"key2": "config-value-2",
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, secret, configMap)

	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "LITERAL_1", Value: "value1"},
		{
			Name: "SECRET_REF",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "my-secret"},
					Key:                  "key1",
				},
			},
		},
		{Name: "LITERAL_2", Value: "value2"},
		{
			Name: "CONFIGMAP_REF",
			ValueFrom: &corev1.EnvVarSource{
				ConfigMapKeyRef: &corev1.ConfigMapKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: "my-config"},
					Key:                  "key2",
				},
			},
		},
		{Name: "LITERAL_3", Value: "value3"},
	}

	// Check .env file - should contain ALL 5 resolved values
	backendEnvContent, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent, `LITERAL_1=value1`)
	assert.Contains(t, backendEnvContent, `SECRET_REF=secret-value-1`)
	assert.Contains(t, backendEnvContent, `LITERAL_2=value2`)
	assert.Contains(t, backendEnvContent, `CONFIGMAP_REF=config-value-2`)
	assert.Contains(t, backendEnvContent, `LITERAL_3=value3`)

	// Check container env - should be empty (no spec.Env vars)
	deploy := r.backendDeployment(cr, "test-ns", "hash123")
	containerEnv := deploy.Spec.Template.Spec.Containers[0].Env

	// Verify none of the 5 env vars are in container env
	envNames := make(map[string]bool)
	for _, env := range containerEnv {
		envNames[env.Name] = true
	}

	assert.False(t, envNames["LITERAL_1"], "LITERAL_1 should NOT be in container env")
	assert.False(t, envNames["SECRET_REF"], "SECRET_REF should NOT be in container env")
	assert.False(t, envNames["LITERAL_2"], "LITERAL_2 should NOT be in container env")
	assert.False(t, envNames["CONFIGMAP_REF"], "CONFIGMAP_REF should NOT be in container env")
	assert.False(t, envNames["LITERAL_3"], "LITERAL_3 should NOT be in container env")
}
