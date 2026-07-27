package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

func filenetSpec(enabled bool) *openragv1alpha1.FileNetMCPSpec {
	return &openragv1alpha1.FileNetMCPSpec{
		Enabled:     enabled,
		GraphQLURL:  "https://cpe.example.com/content-services-graphql/graphql",
		ObjectStore: "FNOS1DS",
		CredentialsSecret: &corev1.LocalObjectReference{
			Name: "filenet-creds",
		},
		Sidecar: &openragv1alpha1.FileNetMCPSidecarSpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{
				Image: "langflowai/openrag-filenet-mcp:latest",
			},
		},
	}
}

func TestBuildBackendEnv_FileNetEnabled_SetsFlagAndURL(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.FileNetMCP = filenetSpec(true)
	r, _ := reconciler(s, cr)

	content, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, content, "OPENRAG_FILENET_MCP_ENABLED=true")
	assert.Contains(t, content, "OPENRAG_FILENET_MCP_URL=http://openrag-filenet-mcp:8811/mcp")
	assert.NotContains(t, content, "OPENRAG_FILENET_MCP_TOKEN",
		"no token env when no authTokenSecret is configured")
}

func TestBuildBackendEnv_FileNetDisabled_SetsFlagFalse(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.FileNetMCP = filenetSpec(false)
	r, _ := reconciler(s, cr)

	content, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, content, "OPENRAG_FILENET_MCP_ENABLED=false")
	assert.NotContains(t, content, "OPENRAG_FILENET_MCP_URL")
}

func TestBuildBackendEnv_FileNetOmitted_NoFileNetVars(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, _ := reconciler(s, cr)

	content, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.NotContains(t, content, "OPENRAG_FILENET_MCP")
}

func TestBuildBackendEnv_FileNetAuthTokenResolvedFromSecret(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	spec := filenetSpec(true)
	spec.AuthTokenSecret = &corev1.SecretKeySelector{
		LocalObjectReference: corev1.LocalObjectReference{Name: "filenet-token"},
		Key:                  "token",
	}
	cr.Spec.FileNetMCP = spec
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: "filenet-token", Namespace: "test-ns"},
		Data:       map[string][]byte{"token": []byte("shared-secret")},
	}
	r, _ := reconciler(s, cr, secret)

	content, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	assert.Contains(t, content, "OPENRAG_FILENET_MCP_TOKEN=shared-secret")
}

func TestBuildBackendEnv_FileNetAuthTokenSecretMissing_Errors(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	spec := filenetSpec(true)
	spec.AuthTokenSecret = &corev1.SecretKeySelector{
		LocalObjectReference: corev1.LocalObjectReference{Name: "missing-secret"},
		Key:                  "token",
	}
	cr.Spec.FileNetMCP = spec
	r, _ := reconciler(s, cr)

	_, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "FileNet MCP auth token")
}

func TestFileNetMCPDeployment_Shape(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	spec := filenetSpec(true)
	spec.AuthTokenSecret = &corev1.SecretKeySelector{
		LocalObjectReference: corev1.LocalObjectReference{Name: "filenet-token"},
		Key:                  "token",
	}
	cr.Spec.FileNetMCP = spec
	r, _ := reconciler(s, cr)

	deploy := r.fileNetMCPDeployment(cr, "test-ns")
	assert.Equal(t, "openrag-filenet-mcp", deploy.Name)

	require.Len(t, deploy.Spec.Template.Spec.Containers, 1)
	container := deploy.Spec.Template.Spec.Containers[0]
	assert.Equal(t, "filenet-mcp", container.Name)
	assert.Equal(t, "langflowai/openrag-filenet-mcp:latest", container.Image)
	require.Len(t, container.Ports, 1)
	assert.Equal(t, int32(8811), container.Ports[0].ContainerPort)

	env := map[string]corev1.EnvVar{}
	for _, e := range container.Env {
		env[e.Name] = e
	}
	assert.Equal(t, "https://cpe.example.com/content-services-graphql/graphql", env["SERVER_URL"].Value)
	assert.Equal(t, "FNOS1DS", env["OBJECT_STORE"].Value)
	assert.Equal(t, "true", env["SSL_ENABLED"].Value)
	assert.Equal(t, "Document", env["FILENET_MCP_DOCUMENT_CLASS"].Value)
	// Credentials come from the user Secret via valueFrom, never inline.
	require.NotNil(t, env["USERNAME"].ValueFrom)
	assert.Equal(t, "filenet-creds", env["USERNAME"].ValueFrom.SecretKeyRef.Name)
	assert.Equal(t, "username", env["USERNAME"].ValueFrom.SecretKeyRef.Key)
	require.NotNil(t, env["PASSWORD"].ValueFrom)
	assert.Equal(t, "password", env["PASSWORD"].ValueFrom.SecretKeyRef.Key)
	require.NotNil(t, env["FILENET_MCP_AUTH_TOKEN"].ValueFrom)
	assert.Equal(t, "filenet-token", env["FILENET_MCP_AUTH_TOKEN"].ValueFrom.SecretKeyRef.Name)

	// Probes hit the sidecar /health route.
	require.NotNil(t, container.LivenessProbe)
	assert.Equal(t, "/health", container.LivenessProbe.HTTPGet.Path)
	require.NotNil(t, container.ReadinessProbe)
	assert.Equal(t, "/health", container.ReadinessProbe.HTTPGet.Path)
}

func TestFileNetMCPDeployment_CustomPortAndClass(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	spec := filenetSpec(true)
	spec.Sidecar.Port = 9911
	spec.DocumentClass = "VendorContract"
	spec.SSLEnabled = "/etc/ssl/ca.pem"
	cr.Spec.FileNetMCP = spec
	r, _ := reconciler(s, cr)

	deploy := r.fileNetMCPDeployment(cr, "test-ns")
	container := deploy.Spec.Template.Spec.Containers[0]
	assert.Equal(t, int32(9911), container.Ports[0].ContainerPort)

	env := map[string]string{}
	for _, e := range container.Env {
		env[e.Name] = e.Value
	}
	assert.Equal(t, "9911", env["FILENET_MCP_PORT"])
	assert.Equal(t, "VendorContract", env["FILENET_MCP_DOCUMENT_CLASS"])
	assert.Equal(t, "/etc/ssl/ca.pem", env["SSL_ENABLED"])
}

func TestReconcileFileNetMCP_DisabledIsNoOp(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.FileNetMCP = filenetSpec(false)
	r, c := reconciler(s, cr)

	require.NoError(t, r.reconcileFileNetMCP(context.Background(), cr, "test-ns"))

	var deployments appsv1.DeploymentList
	require.NoError(t, c.List(context.Background(), &deployments))
	for _, d := range deployments.Items {
		assert.NotEqual(t, "openrag-filenet-mcp", d.Name)
	}
}

func TestReconcileFileNetMCP_EnabledCreatesWorkloads(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.FileNetMCP = filenetSpec(true)
	r, c := reconciler(s, cr)

	require.NoError(t, r.reconcileFileNetMCP(context.Background(), cr, "test-ns"))

	var deployments appsv1.DeploymentList
	require.NoError(t, c.List(context.Background(), &deployments))
	found := false
	for _, d := range deployments.Items {
		if d.Name == "openrag-filenet-mcp" {
			found = true
		}
	}
	assert.True(t, found, "filenet-mcp Deployment should be created")

	var services corev1.ServiceList
	require.NoError(t, c.List(context.Background(), &services))
	foundSvc := false
	for _, svc := range services.Items {
		if svc.Name == "openrag-filenet-mcp" {
			foundSvc = true
			require.Len(t, svc.Spec.Ports, 1)
			assert.Equal(t, int32(8811), svc.Spec.Ports[0].Port)
		}
	}
	assert.True(t, foundSvc, "filenet-mcp Service should be created")
}
