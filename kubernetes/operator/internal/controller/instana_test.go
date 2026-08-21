package controller

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
)

// The Instana agent address is the pod's own node IP, so it is the one backend
// variable that cannot be rendered into the mounted .env file. These tests pin
// the injection rules in InstanaAgentHostEnvVar.

func TestInstanaAgentHostEnvVar_DisabledByDefault(t *testing.T) {
	m := NewEnvVarManager()

	assert.Nil(t, m.InstanaAgentHostEnvVar(nil),
		"Instana is opt-in; nothing should be injected when the flag is unset")
	assert.Equal(t, "false", m.DefaultOpenRagBEEnvVars["INSTANA_ENABLED"],
		"the default must keep the feature off")
}

func TestInstanaAgentHostEnvVar_InjectsNodeIPWhenEnabled(t *testing.T) {
	m := NewEnvVarManager()

	got := m.InstanaAgentHostEnvVar([]corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: "true"}})

	require.NotNil(t, got)
	assert.Equal(t, "INSTANA_AGENT_HOST", got.Name)
	assert.Empty(t, got.Value, "the value must come from the Downward API, not a literal")
	require.NotNil(t, got.ValueFrom)
	require.NotNil(t, got.ValueFrom.FieldRef)
	assert.Equal(t, "status.hostIP", got.ValueFrom.FieldRef.FieldPath)
}

func TestInstanaAgentHostEnvVar_TruthinessMatchesBackendGate(t *testing.T) {
	m := NewEnvVarManager()

	// Mirrors the gate in src/main.py: ("true", "1", "yes"), case-insensitive.
	for _, v := range []string{"true", "TRUE", "True", "1", "yes", "YES", " true "} {
		assert.NotNil(t, m.InstanaAgentHostEnvVar([]corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: v}}),
			"expected %q to enable Instana", v)
	}
	for _, v := range []string{"false", "0", "no", "", "off", "enabled"} {
		assert.Nil(t, m.InstanaAgentHostEnvVar([]corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: v}}),
			"expected %q to leave Instana disabled", v)
	}
}

func TestInstanaAgentHostEnvVar_ExplicitHostWins(t *testing.T) {
	m := NewEnvVarManager()

	got := m.InstanaAgentHostEnvVar([]corev1.EnvVar{
		{Name: "INSTANA_ENABLED", Value: "true"},
		{Name: "INSTANA_AGENT_HOST", Value: "instana-agent.instana-agent.svc"},
	})

	assert.Nil(t, got,
		"an operator-injected fieldRef would override the .env value, so an explicit host must suppress it")
}

func TestInstanaAgentHostEnvVar_HonoursOperatorEnvPrefix(t *testing.T) {
	m := NewEnvVarManager()

	t.Setenv(OPENRAGBE_ENV_PREFIX+"INSTANA_ENABLED", "true")
	assert.NotNil(t, m.InstanaAgentHostEnvVar(nil),
		"level 2 (operator env) must be able to enable Instana on its own")

	// Level 3 (CR spec) still outranks level 2.
	assert.Nil(t, m.InstanaAgentHostEnvVar([]corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: "false"}}),
		"the CR spec must be able to turn it back off")
}

func TestInstanaAgentHostEnvVar_IgnoresValueFrom(t *testing.T) {
	m := NewEnvVarManager()

	// valueFrom entries are resolved against the cluster during reconcile, which
	// this helper has no client for. It must fall back rather than panic.
	got := m.InstanaAgentHostEnvVar([]corev1.EnvVar{{
		Name: "INSTANA_ENABLED",
		ValueFrom: &corev1.EnvVarSource{
			SecretKeyRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "s"}, Key: "k",
			},
		},
	}})

	assert.Nil(t, got, "unresolvable enable flag should leave the default (off) in place")
}

func TestInstanaPresenceSensitiveVarsAreNotDefaulted(t *testing.T) {
	m := NewEnvVarManager()

	// BuildEnvFileContent writes an empty default as `KEY=`, which dotenv turns
	// into an empty string. The tracer tests these for presence, not truthiness,
	// so an empty default would set a blank service name and warn on every boot.
	for _, k := range []string{"INSTANA_SERVICE_NAME", "INSTANA_LOG_LEVEL", "INSTANA_ZONE", "INSTANA_AGENT_HOST"} {
		_, ok := m.DefaultOpenRagBEEnvVars[k]
		assert.False(t, ok, "%s must not carry an empty default", k)
	}
}

func TestBackendDeploymentInjectsInstanaHost(t *testing.T) {
	r, _ := reconciler(newScheme(t))

	cr := minimalCR("my-openrag", "my-ns")
	backendEnv := func() []corev1.EnvVar {
		return r.backendDeployment(cr, "my-ns", "hash").Spec.Template.Spec.Containers[0].Env
	}

	assert.Empty(t, backendEnv(),
		"the backend container keeps an empty Env by design; everything else lives in .env")

	cr.Spec.Backend.Env = []corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: "true"}}
	env := backendEnv()

	require.Len(t, env, 1, "only the agent host may be injected")
	assert.Equal(t, "INSTANA_AGENT_HOST", env[0].Name)
	require.NotNil(t, env[0].ValueFrom)
	require.NotNil(t, env[0].ValueFrom.FieldRef)
	assert.Equal(t, "status.hostIP", env[0].ValueFrom.FieldRef.FieldPath)
}
