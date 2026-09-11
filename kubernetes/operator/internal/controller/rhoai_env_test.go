package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

// TestRHOAI_SpecSeedsBackendEnv verifies that spec.rhoai lands in the backend
// .env as the RHOAI_* variables the backend seeds its stored config from, with
// the bearer token resolved from the referenced Secret.
func TestRHOAI_SpecSeedsBackendEnv(t *testing.T) {
	s := newScheme(t)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rhoai-token",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"token": []byte("sa-bearer-token"),
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, secret)

	cr.Spec.RHOAI = &openragv1alpha1.RHOAISpec{
		Endpoint:           "https://openrag-chat-predictor.openrag-models.svc.cluster.local:8443/v1",
		EmbeddingsEndpoint: "https://openrag-embed-predictor.openrag-models.svc.cluster.local:8443/v1",
		TLSVerify:          "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
		APIKeySecret: &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: "rhoai-token"},
			Key:                  "token",
		},
	}

	backendEnvContent, _, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent,
		`RHOAI_ENDPOINT=https://openrag-chat-predictor.openrag-models.svc.cluster.local:8443/v1`)
	assert.Contains(t, backendEnvContent,
		`RHOAI_EMBEDDINGS_ENDPOINT=https://openrag-embed-predictor.openrag-models.svc.cluster.local:8443/v1`)
	assert.Contains(t, backendEnvContent,
		`RHOAI_TLS_VERIFY=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`)
	assert.Contains(t, backendEnvContent, `RHOAI_API_KEY=sa-bearer-token`,
		"the bearer token should be resolved from the Secret into the .env file")
}

// TestRHOAI_UnsetFieldsAreNotRendered verifies that a partial spec only emits
// the variables that were set: a blank RHOAI_EMBEDDINGS_ENDPOINT would be read
// by the backend as "no separate embeddings endpoint", which is the default
// anyway, and a blank RHOAI_TLS_VERIFY must not override system trust.
func TestRHOAI_UnsetFieldsAreNotRendered(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)

	cr.Spec.RHOAI = &openragv1alpha1.RHOAISpec{
		Endpoint: "https://chat.svc:8443/v1",
	}

	backendEnvContent, _, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, backendEnvContent, `RHOAI_ENDPOINT=https://chat.svc:8443/v1`)
	assert.NotContains(t, backendEnvContent, "RHOAI_EMBEDDINGS_ENDPOINT")
	assert.NotContains(t, backendEnvContent, "RHOAI_TLS_VERIFY")
	assert.NotContains(t, backendEnvContent, "RHOAI_API_KEY")
}

// TestRHOAI_AbsentSpecEmitsNothing verifies that a CR without spec.rhoai does
// not put any RHOAI_* variable in the backend .env, so an install that does
// not use the provider is unchanged.
func TestRHOAI_AbsentSpecEmitsNothing(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)

	backendEnvContent, _, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.NotContains(t, backendEnvContent, "RHOAI_")
}

// TestRHOAI_CredentialsStayOutOfLangflow verifies that the RHOAI endpoints and
// token never reach the Langflow .env: every model call goes through the
// backend's LLM gateway, which is what keeps provider secrets server-side.
func TestRHOAI_CredentialsStayOutOfLangflow(t *testing.T) {
	s := newScheme(t)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rhoai-token",
			Namespace: "test-ns",
		},
		Data: map[string][]byte{
			"token": []byte("sa-bearer-token"),
		},
	}

	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr, secret)

	cr.Spec.RHOAI = &openragv1alpha1.RHOAISpec{
		Endpoint:           "https://chat.svc:8443/v1",
		EmbeddingsEndpoint: "https://embed.svc:8443/v1",
		APIKeySecret: &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: "rhoai-token"},
			Key:                  "token",
		},
	}

	langflowEnvContent, err := r.buildLangflowEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.NotContains(t, langflowEnvContent, "RHOAI_")
	assert.NotContains(t, langflowEnvContent, "sa-bearer-token")
}

// TestRHOAI_MissingSecretFails verifies that a dangling apiKeySecret reference
// is a reconcile error rather than a silently unauthenticated provider.
func TestRHOAI_MissingSecretFails(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)

	cr.Spec.RHOAI = &openragv1alpha1.RHOAISpec{
		Endpoint: "https://chat.svc:8443/v1",
		APIKeySecret: &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: "does-not-exist"},
			Key:                  "token",
		},
	}

	_, _, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to read RHOAI API key")
}
