package controller

import (
	"testing"

	"github.com/stretchr/testify/assert"
	corev1 "k8s.io/api/core/v1"
)

// Backend tracing to Langfuse is opt-in, and content capture is a separate
// opt-in on top of it. These pin both defaults off and confirm a CR can turn
// tracing on and supply the Langfuse keys to the backend.

func TestBackendTracing_OffByDefault(t *testing.T) {
	env := resolvedBackendEnv(t, nil)

	assert.Equal(t, "false", env["OPENRAG_TRACING_ENABLED"])
	assert.Equal(t, "false", env["OPENRAG_TRACING_CAPTURE_CONTENT"])
	assert.Equal(t, "false", env["OPENRAG_TRACING_ALLOW_CONTENT_IN_SAAS"])
}

func TestBackendTracing_EnabledFromCRSpec(t *testing.T) {
	env := resolvedBackendEnv(t, []corev1.EnvVar{
		{Name: "OPENRAG_TRACING_ENABLED", Value: "true"},
		{Name: "LANGFUSE_PUBLIC_KEY", Value: "pk-lf-test"},
	})

	assert.Equal(t, "true", env["OPENRAG_TRACING_ENABLED"])
	assert.Equal(t, "pk-lf-test", env["LANGFUSE_PUBLIC_KEY"])
	assert.Equal(t, "false", env["OPENRAG_TRACING_CAPTURE_CONTENT"],
		"enabling tracing must not enable content capture")
}
