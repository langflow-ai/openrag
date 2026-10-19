package openrag_test

import (
	"bytes"
	"encoding/json"
	"io"
	"os/exec"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/util/yaml"
)

func TestFrontendBasePathHelmRouting(t *testing.T) {
	if _, err := exec.LookPath("helm"); err != nil {
		t.Skip("helm is required to render the chart")
	}

	for _, tc := range []struct {
		name, basePath, ingressPath, probePath string
	}{
		{name: "root", ingressPath: "/", probePath: "/"},
		{name: "nested prefix", basePath: "/workspace/openrag", ingressPath: "/workspace/openrag", probePath: "/workspace/openrag"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args := []string{"template", "review", ".",
				"--set-string", "ingress.hosts.frontend.host=openrag.example.com",
				"--set-string", "ingress.hosts.frontend.paths[0].path=" + tc.ingressPath,
			}
			if tc.basePath != "" {
				args = append(args, "--set-string", "frontend.basePath="+tc.basePath)
			}
			cmd := exec.Command("helm", args...)
			output, err := cmd.CombinedOutput()
			require.NoError(t, err, "%s", output)

			var deployment appsv1.Deployment
			var ingress networkingv1.Ingress
			decoder := yaml.NewYAMLOrJSONDecoder(bytes.NewReader(output), 4096)
			for {
				var manifest map[string]any
				err := decoder.Decode(&manifest)
				if err == io.EOF {
					break
				}
				require.NoError(t, err)
				data, err := json.Marshal(manifest)
				require.NoError(t, err)
				switch manifest["kind"] {
				case "Deployment":
					if manifest["metadata"].(map[string]any)["name"] == "openrag-frontend" {
						require.NoError(t, json.Unmarshal(data, &deployment))
					}
				case "Ingress":
					require.NoError(t, json.Unmarshal(data, &ingress))
				}
			}

			require.NotEmpty(t, deployment.Name)
			require.NotEmpty(t, ingress.Name)
			require.NotEmpty(t, deployment.Spec.Template.Spec.Containers)
			frontend := deployment.Spec.Template.Spec.Containers[0]
			assert.Empty(t, frontend.Command, "the image entrypoint must perform runtime substitution")
			require.NotNil(t, frontend.SecurityContext)
			require.NotNil(t, frontend.SecurityContext.RunAsUser)
			require.NotNil(t, frontend.SecurityContext.RunAsGroup)
			assert.Equal(t, int64(1001), *frontend.SecurityContext.RunAsUser)
			assert.Equal(t, int64(0), *frontend.SecurityContext.RunAsGroup)
			var configured []string
			for _, env := range frontend.Env {
				if env.Name == "OPENRAG_FRONTEND_BASE_PATH" {
					configured = append(configured, env.Value)
				}
			}
			require.Len(t, configured, 1)
			assert.Equal(t, tc.basePath, configured[0])
			require.NotNil(t, frontend.LivenessProbe)
			require.NotNil(t, frontend.LivenessProbe.HTTPGet)
			require.NotNil(t, frontend.ReadinessProbe)
			require.NotNil(t, frontend.ReadinessProbe.HTTPGet)
			assert.Equal(t, tc.probePath, frontend.LivenessProbe.HTTPGet.Path)
			assert.Equal(t, tc.probePath, frontend.ReadinessProbe.HTTPGet.Path)
			require.NotEmpty(t, ingress.Spec.Rules)
			require.NotNil(t, ingress.Spec.Rules[0].HTTP)
			require.NotEmpty(t, ingress.Spec.Rules[0].HTTP.Paths)
			assert.Equal(t, tc.ingressPath, ingress.Spec.Rules[0].HTTP.Paths[0].Path)
			require.NotNil(t, ingress.Spec.Rules[0].HTTP.Paths[0].PathType)
			assert.Equal(t, networkingv1.PathTypePrefix, *ingress.Spec.Rules[0].HTTP.Paths[0].PathType)
			assert.NotContains(t, ingress.Annotations, "nginx.ingress.kubernetes.io/rewrite-target")
		})
	}
}

func TestFrontendBasePathHelmRejectsNonCanonicalPrefix(t *testing.T) {
	if _, err := exec.LookPath("helm"); err != nil {
		t.Skip("helm is required to render the chart")
	}

	for _, path := range []string{"/", "/openrag/", "//openrag", "openrag"} {
		t.Run(path, func(t *testing.T) {
			cmd := exec.Command("helm", "template", "review", ".",
				"--set-string", "frontend.basePath="+path)
			output, err := cmd.CombinedOutput()
			require.Error(t, err, "base path %q unexpectedly rendered: %s", path, output)
			assert.Contains(t, string(output), "frontend.basePath must be empty or an absolute path")
		})
	}
}
