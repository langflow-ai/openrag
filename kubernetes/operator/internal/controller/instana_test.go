package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// The Instana agent address is the pod's own node IP, so it is the one backend
// variable that cannot be rendered into the mounted .env file. These tests pin
// the injection rules in InstanaAgentHostEnvVar.
//
// InstanaAgentHostEnvVar reads the *resolved* backend env — the map
// GetBackendEnvVars returns — so the decision cannot drift from what the backend
// will actually read out of its .env. The three-level precedence itself is
// mergeEnvVars' contract; the tests below exercise it through GetBackendEnvVars
// wherever the origin of a value is the thing under test.

// resolvedBackendEnv runs the real merge so these tests decide from the same map
// the reconciler hands to InstanaAgentHostEnvVar.
func resolvedBackendEnv(t *testing.T, crEnvVars []corev1.EnvVar, objs ...client.Object) map[string]string {
	t.Helper()

	r, c := reconciler(newScheme(t), objs...)
	env, err := r.EnvVarManager.GetBackendEnvVars(context.Background(), c, "test-ns", crEnvVars)
	require.NoError(t, err)
	return env
}

func TestInstanaAgentHostEnvVar_DisabledByDefault(t *testing.T) {
	m := NewEnvVarManager()

	assert.Nil(t, m.InstanaAgentHostEnvVar(resolvedBackendEnv(t, nil)),
		"Instana is opt-in; nothing should be injected when the flag is unset")
	assert.Equal(t, "false", m.DefaultOpenRagBEEnvVars["INSTANA_ENABLED"],
		"the default must keep the feature off")
}

func TestInstanaAgentHostEnvVar_InjectsNodeIPWhenEnabled(t *testing.T) {
	m := NewEnvVarManager()

	got := m.InstanaAgentHostEnvVar(map[string]string{"INSTANA_ENABLED": "true"})

	require.NotNil(t, got)
	assert.Equal(t, "INSTANA_AGENT_HOST", got.Name)
	assert.Empty(t, got.Value, "the value must come from the Downward API, not a literal")
	require.NotNil(t, got.ValueFrom)
	require.NotNil(t, got.ValueFrom.FieldRef)
	assert.Equal(t, "status.hostIP", got.ValueFrom.FieldRef.FieldPath)
}

func TestInstanaAgentHostEnvVar_TruthinessMatchesBackendGate(t *testing.T) {
	m := NewEnvVarManager()

	// Mirrors the gate in src/observability/instana_boot.py: ("true", "1", "yes"),
	// case-insensitive.
	for _, v := range []string{"true", "TRUE", "True", "1", "yes", "YES", " true "} {
		assert.NotNil(t, m.InstanaAgentHostEnvVar(map[string]string{"INSTANA_ENABLED": v}),
			"expected %q to enable Instana", v)
	}
	for _, v := range []string{"false", "0", "no", "", "off", "enabled"} {
		assert.Nil(t, m.InstanaAgentHostEnvVar(map[string]string{"INSTANA_ENABLED": v}),
			"expected %q to leave Instana disabled", v)
	}
}

func TestInstanaAgentHostEnvVar_ExplicitHostWins(t *testing.T) {
	m := NewEnvVarManager()

	got := m.InstanaAgentHostEnvVar(map[string]string{
		"INSTANA_ENABLED":    "true",
		"INSTANA_AGENT_HOST": "instana-agent.instana-agent.svc",
	})

	assert.Nil(t, got,
		"an operator-injected fieldRef would override the .env value, so an explicit host must suppress it")
}

func TestInstanaAgentHostEnvVar_HonoursOperatorEnvPrefix(t *testing.T) {
	m := NewEnvVarManager()

	t.Setenv(OPENRAGBE_ENV_PREFIX+"INSTANA_ENABLED", "true")
	assert.NotNil(t, m.InstanaAgentHostEnvVar(resolvedBackendEnv(t, nil)),
		"level 2 (operator env) must be able to enable Instana on its own")

	// Level 3 (CR spec) still outranks level 2.
	assert.Nil(t, m.InstanaAgentHostEnvVar(
		resolvedBackendEnv(t, []corev1.EnvVar{{Name: "INSTANA_ENABLED", Value: "false"}})),
		"the CR spec must be able to turn it back off")
}

// A Secret- or ConfigMap-backed INSTANA_ENABLED reaches the backend through the
// .env file, so it must reach the host decision too. Deciding from the raw
// spec.Env instead would boot the tracer with no agent to talk to.
func TestInstanaAgentHostEnvVar_EnabledFromSecretRef(t *testing.T) {
	m := NewEnvVarManager()

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: "apm-config", Namespace: "test-ns"},
		Data:       map[string][]byte{"instana-enabled": []byte("true")},
	}
	env := resolvedBackendEnv(t, []corev1.EnvVar{{
		Name: "INSTANA_ENABLED",
		ValueFrom: &corev1.EnvVarSource{
			SecretKeyRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "apm-config"},
				Key:                  "instana-enabled",
			},
		},
	}}, secret)

	require.Equal(t, "true", env["INSTANA_ENABLED"], "precondition: the .env gets the resolved value")
	assert.NotNil(t, m.InstanaAgentHostEnvVar(env),
		"a Secret-backed enable flag must still inject the agent host")
}

func TestInstanaAgentHostEnvVar_EnabledFromConfigMapRef(t *testing.T) {
	m := NewEnvVarManager()

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "apm-config", Namespace: "test-ns"},
		Data:       map[string]string{"instana-enabled": "true"},
	}
	env := resolvedBackendEnv(t, []corev1.EnvVar{{
		Name: "INSTANA_ENABLED",
		ValueFrom: &corev1.EnvVarSource{
			ConfigMapKeyRef: &corev1.ConfigMapKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "apm-config"},
				Key:                  "instana-enabled",
			},
		},
	}}, cm)

	require.Equal(t, "true", env["INSTANA_ENABLED"], "precondition: the .env gets the resolved value")
	assert.NotNil(t, m.InstanaAgentHostEnvVar(env),
		"a ConfigMap-backed enable flag must still inject the agent host")
}

// The mirror case: an explicit host from a Secret or ConfigMap lands in the .env,
// and a fieldRef injected next to it would silently win (bootstrap loads .env
// with override=False), so it must suppress the injection.
func TestInstanaAgentHostEnvVar_ExplicitHostFromRefWins(t *testing.T) {
	m := NewEnvVarManager()

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "apm-config", Namespace: "test-ns"},
		Data:       map[string]string{"agent-host": "instana-agent.instana-agent.svc"},
	}
	env := resolvedBackendEnv(t, []corev1.EnvVar{
		{Name: "INSTANA_ENABLED", Value: "true"},
		{Name: "INSTANA_AGENT_HOST", ValueFrom: &corev1.EnvVarSource{
			ConfigMapKeyRef: &corev1.ConfigMapKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "apm-config"},
				Key:                  "agent-host",
			},
		}},
	}, cm)

	require.Equal(t, "instana-agent.instana-agent.svc", env["INSTANA_AGENT_HOST"],
		"precondition: the .env gets the resolved host")
	assert.Nil(t, m.InstanaAgentHostEnvVar(env),
		"a ConfigMap-backed explicit host must suppress the node-IP fieldRef that would override it")
}

// An optional reference that does not resolve leaves the default in place rather
// than half-enabling the feature.
func TestInstanaAgentHostEnvVar_UnresolvedOptionalRefLeavesDefault(t *testing.T) {
	m := NewEnvVarManager()

	optional := true
	env := resolvedBackendEnv(t, []corev1.EnvVar{{
		Name: "INSTANA_ENABLED",
		ValueFrom: &corev1.EnvVarSource{
			SecretKeyRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "missing"},
				Key:                  "k",
				Optional:             &optional,
			},
		},
	}})

	assert.Nil(t, m.InstanaAgentHostEnvVar(env),
		"an unresolvable enable flag should leave the default (off) in place")
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
	backendEnv := func(instanaHost *corev1.EnvVar) []corev1.EnvVar {
		return r.backendDeployment(cr, "my-ns", "hash", instanaHost).Spec.Template.Spec.Containers[0].Env
	}

	assert.Empty(t, backendEnv(nil),
		"the backend container keeps an empty Env by design; everything else lives in .env")

	env := backendEnv(r.EnvVarManager.InstanaAgentHostEnvVar(map[string]string{"INSTANA_ENABLED": "true"}))

	require.Len(t, env, 1, "only the agent host may be injected")
	assert.Equal(t, "INSTANA_AGENT_HOST", env[0].Name)
	require.NotNil(t, env[0].ValueFrom)
	require.NotNil(t, env[0].ValueFrom.FieldRef)
	assert.Equal(t, "status.hostIP", env[0].ValueFrom.FieldRef.FieldPath)
}
