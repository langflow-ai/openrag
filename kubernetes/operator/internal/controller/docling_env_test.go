package controller

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"k8s.io/apimachinery/pkg/api/resource"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

func TestResolveDoclingServeURL_DoclingComponents(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
		Enabled: true,
		Serve: &openragv1alpha1.DoclingServeSpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ghcr.io/docling-project/docling-serve-cpu:v1.15.1"},
		},
	}

	url, ok := resolveDoclingServeURL(cr)
	require.True(t, ok)
	assert.Equal(t, "http://"+resourceName("ds")+":5001", url)
}

func TestResolveDoclingServeURL_DoclingComponentsCustomPortAndService(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
		Enabled: true,
		Serve: &openragv1alpha1.DoclingServeSpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{
				Image:       "ghcr.io/docling-project/docling-serve-cpu:v1.15.1",
				ServiceName: "my-docling-serve",
			},
			Port: 5002,
		},
	}

	url, ok := resolveDoclingServeURL(cr)
	require.True(t, ok)
	assert.Equal(t, "http://my-docling-serve:5002", url)
}

func TestResolveDoclingServeURL_ExternalDocling(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.Docling = &openragv1alpha1.DoclingSpec{
		Host:   "docling.example.svc",
		Port:   5001,
		Scheme: "https",
	}

	url, ok := resolveDoclingServeURL(cr)
	require.True(t, ok)
	assert.Equal(t, "https://docling.example.svc:5001", url)
}

func TestResolveDoclingServeURL_ComponentsTakePriority(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
		Enabled: true,
		Serve: &openragv1alpha1.DoclingServeSpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ghcr.io/docling-project/docling-serve-cpu:v1.15.1"},
		},
	}
	cr.Spec.Docling = &openragv1alpha1.DoclingSpec{
		Host: "external.example.svc",
		Port: 9999,
	}

	url, ok := resolveDoclingServeURL(cr)
	require.True(t, ok)
	assert.Equal(t, "http://"+resourceName("ds")+":5001", url)
}

func TestResolveDoclingServeURL_None(t *testing.T) {
	cr := minimalCR("test", "default")

	_, ok := resolveDoclingServeURL(cr)
	assert.False(t, ok)
}

func TestSetDoclingServeURLIfUnset_SkipsWhenPreset(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
		Enabled: true,
		Serve: &openragv1alpha1.DoclingServeSpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ghcr.io/docling-project/docling-serve-cpu:v1.15.1"},
		},
	}

	envVars := map[string]string{"DOCLING_SERVE_URL": "http://custom:5001"}
	setDoclingServeURLIfUnset(envVars, cr)
	assert.Equal(t, "http://custom:5001", envVars["DOCLING_SERVE_URL"])
}

func TestSetDoclingServeURLIfUnset_SetsFromCR(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.Docling = &openragv1alpha1.DoclingSpec{Host: "docling.internal", Port: 5001}

	envVars := map[string]string{}
	setDoclingServeURLIfUnset(envVars, cr)
	assert.Equal(t, "http://docling.internal:5001", envVars["DOCLING_SERVE_URL"])
}

func TestApplyLangflowWatsonxAliases(t *testing.T) {
	envVars := map[string]string{
		"WATSONX_API_KEY":  "secret-key",
		"WATSONX_ENDPOINT": "https://custom.ml.cloud.ibm.com",
	}
	applyLangflowWatsonxAliases(envVars)
	assert.Equal(t, "secret-key", envVars["WATSONX_APIKEY"])
	assert.Equal(t, "https://custom.ml.cloud.ibm.com", envVars["WATSONX_URL"])
}

func TestApplyLangflowWatsonxAliases_SkipsNoneDefaults(t *testing.T) {
	envVars := map[string]string{
		"WATSONX_API_KEY":  "None",
		"WATSONX_ENDPOINT": "None",
	}
	applyLangflowWatsonxAliases(envVars)
	_, hasAPIKey := envVars["WATSONX_APIKEY"]
	_, hasURL := envVars["WATSONX_URL"]
	assert.False(t, hasAPIKey)
	assert.False(t, hasURL)
}

func TestApplyLangflowPersistencePaths_WithPVC(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.Langflow.Storage = &openragv1alpha1.PersistenceSpec{Enabled: true, Size: resource.MustParse("1Gi")}

	envVars := map[string]string{
		"LANGFLOW_DATABASE_URL": "sqlite:////app/data/langflow.db",
		"LANGFLOW_CONFIG_DIR":   "/tmp",
	}
	applyLangflowPersistencePaths(envVars, cr)

	assert.Equal(t, langflowSQLiteDatabaseURL, envVars["LANGFLOW_DATABASE_URL"])
	assert.Equal(t, langflowDataMountPath, envVars["LANGFLOW_CONFIG_DIR"])
}

func TestApplyLangflowPersistencePaths_NoStorage(t *testing.T) {
	cr := minimalCR("test", "default")
	envVars := map[string]string{
		"LANGFLOW_DATABASE_URL": "sqlite:////app/data/langflow.db",
		"LANGFLOW_CONFIG_DIR":   "/tmp",
	}
	applyLangflowPersistencePaths(envVars, cr)

	assert.Equal(t, "/tmp", envVars["LANGFLOW_CONFIG_DIR"])
}

func TestApplyLangflowPersistencePaths_RespectsOverride(t *testing.T) {
	cr := minimalCR("test", "default")
	cr.Spec.Langflow.Storage = &openragv1alpha1.PersistenceSpec{Enabled: true, Size: resource.MustParse("1Gi")}

	envVars := map[string]string{
		"LANGFLOW_CONFIG_DIR": "/custom/config",
	}
	applyLangflowPersistencePaths(envVars, cr)

	assert.Equal(t, "/custom/config", envVars["LANGFLOW_CONFIG_DIR"])
}

func TestNewEnvVarManager_LangflowDefaultsMatchHelm(t *testing.T) {
	m := NewEnvVarManager()
	vars := m.DefaultLangflowEnvVars["LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT"]
	assert.Contains(t, vars, "OPENRAG-QUERY-FILTER")
	assert.Contains(t, vars, "DOCLING_SERVE_URL")
	assert.Contains(t, vars, "WATSONX_APIKEY")
	assert.Contains(t, vars, "WATSONX_URL")
	assert.NotContains(t, vars, "OPENRAG_QUERY_FILTER")
	assert.Equal(t, "{}", m.DefaultLangflowEnvVars["OPENRAG-QUERY-FILTER"])
}
