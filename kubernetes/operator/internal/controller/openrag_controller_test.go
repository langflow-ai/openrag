package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

// newScheme builds a scheme with all types the controller needs.
func newScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	require.NoError(t, clientgoscheme.AddToScheme(s))
	require.NoError(t, appsv1.AddToScheme(s))
	require.NoError(t, corev1.AddToScheme(s))
	require.NoError(t, openragv1alpha1.AddToScheme(s))
	return s
}

// minimalCR returns a valid OpenRAG CR with the minimum required fields set.
func minimalCR(name, namespace string) *openragv1alpha1.OpenRAG {
	return &openragv1alpha1.OpenRAG{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
		},
		Spec: openragv1alpha1.OpenRAGSpec{
			Frontend: openragv1alpha1.FrontendSpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "langflowai/openrag-frontend:latest"},
			},
			Backend: openragv1alpha1.BackendSpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "langflowai/openrag-backend:latest"},
			},
			Langflow: openragv1alpha1.LangflowSpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "langflowai/openrag-langflow:latest"},
			},
		},
	}
}

func reconciler(s *runtime.Scheme, objs ...client.Object) (*OpenRAGReconciler, client.Client) {
	c := fake.NewClientBuilder().WithScheme(s).WithObjects(objs...).WithStatusSubresource(&openragv1alpha1.OpenRAG{}).Build()
	return NewOpenRAGReconciler(c, s), c
}

func reconcileOnce(t *testing.T, r *OpenRAGReconciler, cr *openragv1alpha1.OpenRAG) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace},
	})
	require.NoError(t, err)
	return res
}

// ---------------------------------------------------------------------------
// targetNamespace helper
// ---------------------------------------------------------------------------

func TestTargetNamespace_DefaultsToCRNamespace(t *testing.T) {
	cr := minimalCR("my-openrag", "my-ns")
	assert.Equal(t, "my-ns", targetNamespace(cr))
}

func TestTargetNamespace_UsesSpecField(t *testing.T) {
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	assert.Equal(t, "tenant-ns", targetNamespace(cr))
}

// ---------------------------------------------------------------------------
// resourceName / saName helpers
// ---------------------------------------------------------------------------

func TestResourceName(t *testing.T) {
	// Test simple, namespace-scoped names (no CR name prefix needed)
	assert.Equal(t, "openrag-fe", resourceName("fe"))
	assert.Equal(t, "openrag-be", resourceName("be"))
	assert.Equal(t, "openrag-lf", resourceName("lf"))
	// Test DNS-1035 compliance (must start with letter)
	assert.Regexp(t, `^[a-z]([-a-z0-9]*[a-z0-9])?$`, resourceName("fe"))
	assert.Regexp(t, `^[a-z]([-a-z0-9]*[a-z0-9])?$`, resourceName("be"))
}

func TestSAName(t *testing.T) {
	// Service accounts also use simple, namespace-scoped names
	assert.Equal(t, "openrag-fe", saName("fe"))
	assert.Equal(t, "openrag-be", saName("be"))
	assert.Equal(t, "openrag-lf", saName("lf"))
}

// ---------------------------------------------------------------------------
// Reconcile — same namespace (no targetNamespace)
// ---------------------------------------------------------------------------

func TestReconcile_CreatesDeployments(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	for _, role := range []string{"fe", "be", "lf"} {
		d := &appsv1.Deployment{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: resourceName(role), Namespace: "my-ns"}, d),
			"deployment for role %s should exist", role)
	}
}

func TestReconcile_CreatesServices(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	ports := map[string]int32{"fe": 3000, "be": 8000, "lf": 7860}
	for role, port := range ports {
		svc := &corev1.Service{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: resourceName(role), Namespace: "my-ns"}, svc))
		assert.Equal(t, port, svc.Spec.Ports[0].Port, "service port for role %s", role)
	}
}

func TestReconcile_CreatesServiceAccounts(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	for _, role := range []string{"fe", "be", "lf"} {
		sa := &corev1.ServiceAccount{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: saName(role), Namespace: "my-ns"}, sa),
			"service account for role %s should exist", role)
	}
}

func TestReconcile_SetsOwnerReferences_SameNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, d))
	require.Len(t, d.OwnerReferences, 1)
	assert.Equal(t, cr.Name, d.OwnerReferences[0].Name)
}

func TestReconcile_FrontendEnvContainsBackendHost(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, d))

	var backendHost string
	for _, e := range d.Spec.Template.Spec.Containers[0].Env {
		if e.Name == "OPENRAG_BACKEND_HOST" {
			backendHost = e.Value
		}
	}
	assert.Equal(t, resourceName("be"), backendHost)
}

func TestReconcile_BackendMountsOperatorManagedEnvSecret(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("be"), Namespace: "my-ns"}, d))

	expectedSecret := resourceName("be-env")
	var found bool
	for _, v := range d.Spec.Template.Spec.Volumes {
		if v.Name == "backend-env" {
			assert.Equal(t, expectedSecret, v.Secret.SecretName)
			found = true
		}
	}
	assert.True(t, found, "backend-env volume should exist with operator-managed secret")
}

func TestReconcile_BackendEnvContainsLangflowURL(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	sec := &corev1.Secret{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("be-env"), Namespace: "my-ns"}, sec))

	// In the test environment, StringData is not converted to Data
	// Use StringData if Data is empty (test env), otherwise use Data (real cluster)
	envContent := string(sec.Data[".env"])
	if envContent == "" && sec.StringData != nil {
		envContent = sec.StringData[".env"]
	}
	assert.Contains(t, envContent, "LANGFLOW_URL=http://"+resourceName("lf")+":7860")
}

func TestReconcile_LangflowMountsPVC(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	size := resource.MustParse("10Gi")
	cr.Spec.Langflow.Storage = &openragv1alpha1.PersistenceSpec{Enabled: true, Size: size}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("lf"), Namespace: "my-ns"}, d))

	var found bool
	for _, v := range d.Spec.Template.Spec.Volumes {
		if v.Name == "langflow-data" {
			assert.Equal(t, resourceName("lf-data"), v.PersistentVolumeClaim.ClaimName)
			found = true
		}
	}
	assert.True(t, found, "langflow-data volume should exist")
}

// ---------------------------------------------------------------------------
// Reconcile — target namespace
// ---------------------------------------------------------------------------

func TestReconcile_CreatesTargetNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "operator-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	r, c := reconciler(s, cr)

	// First reconcile adds finalizer and returns early
	reconcileOnce(t, r, cr)
	// Second reconcile creates namespace and resources
	reconcileOnce(t, r, cr)

	ns := &corev1.Namespace{}
	require.NoError(t, c.Get(context.Background(), types.NamespacedName{Name: "tenant-ns"}, ns))
	assert.Equal(t, cr.Name, ns.Labels[managedByLabel])
}

func TestReconcile_AddsFinalizer_WhenTargetNamespaceDiffers(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "operator-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	updated := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}, updated))
	assert.True(t, controllerutil.ContainsFinalizer(updated, finalizer))
}

func TestReconcile_NoFinalizer_WhenSameNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	updated := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}, updated))
	assert.False(t, controllerutil.ContainsFinalizer(updated, finalizer))
}

func TestReconcile_ResourcesInTargetNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "operator-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	r, c := reconciler(s, cr)

	// First reconcile adds finalizer and returns early
	reconcileOnce(t, r, cr)
	// Second reconcile creates resources
	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "tenant-ns"}, d))
	// Cross-namespace: no owner references, managed-by label instead.
	assert.Empty(t, d.OwnerReferences)
	assert.Equal(t, cr.Name, d.Labels[managedByLabel])
}

func TestReconcile_SkipsNamespaceCreation_WhenSameAsCR(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	// Only the CR namespace should exist, not a separate one.
	nsList := &corev1.NamespaceList{}
	require.NoError(t, c.List(context.Background(), nsList))
	for _, ns := range nsList.Items {
		assert.NotEqual(t, "openrag-operator", ns.Labels["app.kubernetes.io/managed-by"],
			"operator should not have created a new namespace")
	}
}

// ---------------------------------------------------------------------------
// Deletion handling
// ---------------------------------------------------------------------------

func TestReconcile_Deletion_DeletesOwnedNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "operator-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	now := metav1.Now()
	cr.DeletionTimestamp = &now
	controllerutil.AddFinalizer(cr, finalizer)

	// Pre-create the target namespace labelled as owned by this CR.
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name:   "tenant-ns",
			Labels: map[string]string{managedByLabel: cr.Name},
		},
	}

	r, c := reconciler(s, cr, ns)
	_, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace},
	})
	require.NoError(t, err)

	// Namespace should be deleted.
	remaining := &corev1.Namespace{}
	err = c.Get(context.Background(), types.NamespacedName{Name: "tenant-ns"}, remaining)
	assert.True(t, err != nil, "namespace should have been deleted")

	// After the finalizer is removed the fake client deletes the CR — NotFound is correct.
	updated := &openragv1alpha1.OpenRAG{}
	err = c.Get(context.Background(), types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}, updated)
	assert.True(t, err != nil, "CR should be gone after finalizer removal")
}

func TestReconcile_Deletion_SkipsUnmanagedNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "operator-ns")
	cr.Spec.TargetNamespace = "tenant-ns"
	now := metav1.Now()
	cr.DeletionTimestamp = &now
	controllerutil.AddFinalizer(cr, finalizer)

	// Namespace exists but belongs to someone else.
	ns := &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name:   "tenant-ns",
			Labels: map[string]string{managedByLabel: "other-cr"},
		},
	}

	r, c := reconciler(s, cr, ns)
	_, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace},
	})
	require.NoError(t, err)

	// Namespace should NOT be deleted.
	remaining := &corev1.Namespace{}
	require.NoError(t, c.Get(context.Background(), types.NamespacedName{Name: "tenant-ns"}, remaining))
}

// ---------------------------------------------------------------------------
// Labels and Annotations (Deployment and Pod level)
// ---------------------------------------------------------------------------

func TestMergeDeploymentLabels_CustomLabelsAreMerged(t *testing.T) {
	baseLabels := map[string]string{
		"app.kubernetes.io/name":      "openrag",
		"app.kubernetes.io/instance":  "test",
		"app.kubernetes.io/component": "fe",
	}
	customLabels := map[string]string{
		"deployment-label":            "deployment-value",
		"argocd.argoproj.io/instance": "my-app",
	}

	merged := mergeDeploymentLabels(baseLabels, customLabels)

	// Custom labels should be present
	assert.Equal(t, "deployment-value", merged["deployment-label"])
	assert.Equal(t, "my-app", merged["argocd.argoproj.io/instance"])

	// Operator-managed labels should be present
	assert.Equal(t, "openrag", merged["app.kubernetes.io/name"])
	assert.Equal(t, "test", merged["app.kubernetes.io/instance"])
}

func TestMergeDeploymentAnnotations_CustomAnnotationsAreMerged(t *testing.T) {
	customAnnotations := map[string]string{
		"deployment.kubernetes.io/revision": "5",
		"meta.helm.sh/release-name":         "my-release",
	}

	merged := mergeDeploymentAnnotations(customAnnotations)

	assert.Equal(t, "5", merged["deployment.kubernetes.io/revision"])
	assert.Equal(t, "my-release", merged["meta.helm.sh/release-name"])
}

func TestMergePodLabels_CustomLabelsAreMerged(t *testing.T) {
	baseLabels := map[string]string{
		"app.kubernetes.io/name":      "openrag",
		"app.kubernetes.io/instance":  "test",
		"app.kubernetes.io/component": "fe",
	}
	customLabels := map[string]string{
		"custom-label":         "custom-value",
		"another-label":        "another-value",
		"prometheus.io/scrape": "true",
	}

	merged := mergePodLabels(baseLabels, customLabels)

	// Custom labels should be present
	assert.Equal(t, "custom-value", merged["custom-label"])
	assert.Equal(t, "another-value", merged["another-label"])
	assert.Equal(t, "true", merged["prometheus.io/scrape"])

	// Operator-managed labels should be present
	assert.Equal(t, "openrag", merged["app.kubernetes.io/name"])
	assert.Equal(t, "test", merged["app.kubernetes.io/instance"])
	assert.Equal(t, "fe", merged["app.kubernetes.io/component"])
}

func TestMergePodLabels_OperatorLabelsCannotBeOverridden(t *testing.T) {
	baseLabels := map[string]string{
		"app.kubernetes.io/name":     "openrag",
		"app.kubernetes.io/instance": "test",
	}
	customLabels := map[string]string{
		"app.kubernetes.io/name":     "hacked", // Try to override
		"app.kubernetes.io/instance": "evil",   // Try to override
	}

	merged := mergePodLabels(baseLabels, customLabels)

	// Operator labels should win
	assert.Equal(t, "openrag", merged["app.kubernetes.io/name"])
	assert.Equal(t, "test", merged["app.kubernetes.io/instance"])
}

func TestMergePodAnnotations_CustomAnnotationsAreMerged(t *testing.T) {
	customAnnotations := map[string]string{
		"prometheus.io/scrape": "true",
		"prometheus.io/port":   "8080",
		"custom-annotation":    "value",
	}

	merged := mergePodAnnotations(customAnnotations)

	assert.Equal(t, "true", merged["prometheus.io/scrape"])
	assert.Equal(t, "8080", merged["prometheus.io/port"])
	assert.Equal(t, "value", merged["custom-annotation"])
}

func TestReconcile_FrontendCustomPodLabels(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.Frontend.PodLabels = map[string]string{
		"team":                 "platform",
		"prometheus.io/scrape": "true",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, d))

	podLabels := d.Spec.Template.Labels

	// Custom labels should be present
	assert.Equal(t, "platform", podLabels["team"])
	assert.Equal(t, "true", podLabels["prometheus.io/scrape"])

	// Operator-managed labels should still be present
	assert.Equal(t, "openrag", podLabels["app.kubernetes.io/name"])
	assert.Equal(t, "my-openrag", podLabels["app.kubernetes.io/instance"])
	assert.Equal(t, "fe", podLabels["app.kubernetes.io/component"])
	assert.Equal(t, "openrag-operator", podLabels["app.kubernetes.io/managed-by"])
}

func TestReconcile_BackendCustomPodAnnotations(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.Backend.PodAnnotations = map[string]string{
		"prometheus.io/scrape": "true",
		"prometheus.io/port":   "8000",
		"custom-annotation":    "backend-value",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("be"), Namespace: "my-ns"}, d))

	podAnnotations := d.Spec.Template.Annotations

	// Custom annotations should be present
	assert.Equal(t, "true", podAnnotations["prometheus.io/scrape"])
	assert.Equal(t, "8000", podAnnotations["prometheus.io/port"])
	assert.Equal(t, "backend-value", podAnnotations["custom-annotation"])
}

func TestReconcile_LangflowCustomPodLabelsAndAnnotations(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.Langflow.PodLabels = map[string]string{
		"version":    "v1.0.0",
		"monitoring": "enabled",
	}
	cr.Spec.Langflow.PodAnnotations = map[string]string{
		"sidecar.istio.io/inject":    "true",
		"vault.hashicorp.com/inject": "false",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("lf"), Namespace: "my-ns"}, d))

	podLabels := d.Spec.Template.Labels
	podAnnotations := d.Spec.Template.Annotations

	// Custom labels should be present
	assert.Equal(t, "v1.0.0", podLabels["version"])
	assert.Equal(t, "enabled", podLabels["monitoring"])

	// Operator-managed labels should still be present
	assert.Equal(t, "openrag", podLabels["app.kubernetes.io/name"])
	assert.Equal(t, "lf", podLabels["app.kubernetes.io/component"])

	// Custom annotations should be present
	assert.Equal(t, "true", podAnnotations["sidecar.istio.io/inject"])
	assert.Equal(t, "false", podAnnotations["vault.hashicorp.com/inject"])
}

func TestReconcile_SelectorLabelsAreNotAffectedByCustomPodLabels(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	// Add custom pod labels
	cr.Spec.Frontend.PodLabels = map[string]string{
		"custom-label": "should-not-be-in-selector",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, d))

	// Selector should only have operator-managed labels
	selectorLabels := d.Spec.Selector.MatchLabels
	assert.Equal(t, 4, len(selectorLabels), "Selector should only have 4 operator-managed labels")
	assert.Equal(t, "openrag", selectorLabels["app.kubernetes.io/name"])
	assert.Equal(t, "my-openrag", selectorLabels["app.kubernetes.io/instance"])
	assert.Equal(t, "fe", selectorLabels["app.kubernetes.io/component"])
	assert.Equal(t, "openrag-operator", selectorLabels["app.kubernetes.io/managed-by"])

	// Custom label should NOT be in selector
	_, exists := selectorLabels["custom-label"]
	assert.False(t, exists, "Custom labels should not be in selector")

	// But pod labels should include both
	podLabels := d.Spec.Template.Labels
	assert.Equal(t, "should-not-be-in-selector", podLabels["custom-label"])
}

func TestReconcile_FrontendDeploymentLevelLabelsAndAnnotations(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.Frontend.Labels = map[string]string{
		"deployment-label": "deployment-value",
		"team":             "frontend-team",
	}
	cr.Spec.Frontend.Annotations = map[string]string{
		"deployment.kubernetes.io/revision": "1",
		"meta.helm.sh/release-name":         "my-release",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, d))

	// Deployment-level labels should be present
	assert.Equal(t, "deployment-value", d.Labels["deployment-label"])
	assert.Equal(t, "frontend-team", d.Labels["team"])

	// Operator-managed labels should still be present on deployment
	assert.Equal(t, "openrag", d.Labels["app.kubernetes.io/name"])
	assert.Equal(t, "fe", d.Labels["app.kubernetes.io/component"])

	// Deployment-level annotations should be present
	assert.Equal(t, "1", d.Annotations["deployment.kubernetes.io/revision"])
	assert.Equal(t, "my-release", d.Annotations["meta.helm.sh/release-name"])
}

func TestReconcile_DeploymentAndPodLabelsAreIndependent(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.Backend.Labels = map[string]string{
		"deployment-only": "on-deployment",
	}
	cr.Spec.Backend.PodLabels = map[string]string{
		"pod-only": "on-pod",
	}
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("be"), Namespace: "my-ns"}, d))

	// Deployment should have deployment-only label
	assert.Equal(t, "on-deployment", d.Labels["deployment-only"])
	// Deployment should NOT have pod-only label
	_, exists := d.Labels["pod-only"]
	assert.False(t, exists, "Pod-only label should not be on deployment")

	// Pod should have pod-only label
	podLabels := d.Spec.Template.Labels
	assert.Equal(t, "on-pod", podLabels["pod-only"])
	// Pod should NOT have deployment-only label
	_, exists = podLabels["deployment-only"]
	assert.False(t, exists, "Deployment-only label should not be on pod")

	// Both should have operator-managed labels
	assert.Equal(t, "openrag", d.Labels["app.kubernetes.io/name"])
	assert.Equal(t, "openrag", podLabels["app.kubernetes.io/name"])
}

func TestReconcile_AllThreeComponentsSupportBothLevels(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")

	// Frontend with deployment annotations
	cr.Spec.Frontend.Annotations = map[string]string{
		"frontend-deploy-annotation": "fe-value",
	}
	cr.Spec.Frontend.PodAnnotations = map[string]string{
		"frontend-pod-annotation": "fe-pod-value",
	}

	// Backend with deployment labels
	cr.Spec.Backend.Labels = map[string]string{
		"backend-deploy-label": "be-value",
	}
	cr.Spec.Backend.PodLabels = map[string]string{
		"backend-pod-label": "be-pod-value",
	}

	// Langflow with both
	cr.Spec.Langflow.Labels = map[string]string{
		"langflow-deploy-label": "lf-value",
	}
	cr.Spec.Langflow.Annotations = map[string]string{
		"langflow-deploy-annotation": "lf-annotation",
	}
	cr.Spec.Langflow.PodLabels = map[string]string{
		"langflow-pod-label": "lf-pod-value",
	}
	cr.Spec.Langflow.PodAnnotations = map[string]string{
		"langflow-pod-annotation": "lf-pod-annotation",
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Check Frontend
	feDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("fe"), Namespace: "my-ns"}, feDeploy))
	assert.Equal(t, "fe-value", feDeploy.Annotations["frontend-deploy-annotation"])
	assert.Equal(t, "fe-pod-value", feDeploy.Spec.Template.Annotations["frontend-pod-annotation"])

	// Check Backend
	beDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("be"), Namespace: "my-ns"}, beDeploy))
	assert.Equal(t, "be-value", beDeploy.Labels["backend-deploy-label"])
	assert.Equal(t, "be-pod-value", beDeploy.Spec.Template.Labels["backend-pod-label"])

	// Check Langflow
	lfDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName("lf"), Namespace: "my-ns"}, lfDeploy))
	assert.Equal(t, "lf-value", lfDeploy.Labels["langflow-deploy-label"])
	assert.Equal(t, "lf-annotation", lfDeploy.Annotations["langflow-deploy-annotation"])
	assert.Equal(t, "lf-pod-value", lfDeploy.Spec.Template.Labels["langflow-pod-label"])
	assert.Equal(t, "lf-pod-annotation", lfDeploy.Spec.Template.Annotations["langflow-pod-annotation"])
}

// TestReconcile_UUIDNameDNS1035Compliance verifies that resources work correctly
// even when CR names start with numbers (UUIDs). Since we use namespace-scoped
// naming (openrag-fe, openrag-be, openrag-lf), the CR name doesn't affect resource names.
func TestReconcile_UUIDNameDNS1035Compliance(t *testing.T) {
	s := newScheme(t)
	// Use the exact UUID from the production error - this should work fine now
	uuidName := "9a826efa-112d-4e2d-9f8d-ce103880ab41"
	cr := minimalCR(uuidName, "test-ns")

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Verify all created resources have DNS-1035 compliant names
	// DNS-1035: must start with letter, end with alphanumeric, contain only lowercase alphanumeric and hyphens
	dns1035Regex := `^[a-z]([-a-z0-9]*[a-z0-9])?$`

	// Check frontend deployment
	feDeploy := &appsv1.Deployment{}
	feName := resourceName("fe")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: feName, Namespace: "test-ns"}, feDeploy))
	assert.Regexp(t, dns1035Regex, feName, "Frontend deployment name must be DNS-1035 compliant")
	assert.Regexp(t, dns1035Regex, feDeploy.Name, "Frontend deployment name must be DNS-1035 compliant")

	// Check frontend service
	feSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: feName, Namespace: "test-ns"}, feSvc))
	assert.Regexp(t, dns1035Regex, feSvc.Name, "Frontend service name must be DNS-1035 compliant")

	// Check backend deployment
	beDeploy := &appsv1.Deployment{}
	beName := resourceName("be")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: beName, Namespace: "test-ns"}, beDeploy))
	assert.Regexp(t, dns1035Regex, beName, "Backend deployment name must be DNS-1035 compliant")

	// Check backend service
	beSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: beName, Namespace: "test-ns"}, beSvc))
	assert.Regexp(t, dns1035Regex, beSvc.Name, "Backend service name must be DNS-1035 compliant")

	// Check langflow deployment
	lfDeploy := &appsv1.Deployment{}
	lfName := resourceName("lf")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: lfName, Namespace: "test-ns"}, lfDeploy))
	assert.Regexp(t, dns1035Regex, lfName, "Langflow deployment name must be DNS-1035 compliant")

	// Verify the simple naming pattern: "openrag-{role}" (namespace-scoped)
	assert.Equal(t, "openrag-fe", feName)
	assert.Equal(t, "openrag-be", beName)
	assert.Equal(t, "openrag-lf", lfName)

	// Verify the CR UUID name is tracked in labels, not in resource names
	assert.Equal(t, uuidName, feDeploy.Labels["app.kubernetes.io/instance"])
	assert.Equal(t, uuidName, beDeploy.Labels["app.kubernetes.io/instance"])
	assert.Equal(t, uuidName, lfDeploy.Labels["app.kubernetes.io/instance"])
}
