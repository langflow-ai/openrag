package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
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
	// First reconcile: adds finalizer and returns early
	_, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace},
	})
	require.NoError(t, err)

	// Second reconcile: actually creates resources
	// This is needed because adding finalizer triggers an Update() which returns early
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
	assert.Equal(t, "openrag-my-cr-fe", resourceName("my-cr", "fe"))
	assert.Equal(t, "openrag-my-cr-be", resourceName("my-cr", "be"))
	assert.Equal(t, "openrag-my-cr-lf", resourceName("my-cr", "lf"))
	assert.Equal(t, "openrag-my-cr-docling-serve", resourceName("my-cr", "ds"))
	assert.Equal(t, "openrag-my-cr-docling-worker", resourceName("my-cr", "dw"))
	// DNS-1035 compliance: must start with letter even when crName starts with a digit
	uuidLike := "9a826efa-112d-4e2d-9f8d-ce103880ab41"
	assert.Regexp(t, `^[a-z]([-a-z0-9]*[a-z0-9])?$`, resourceName(uuidLike, "fe"))
	assert.Regexp(t, `^[a-z]([-a-z0-9]*[a-z0-9])?$`, resourceName(uuidLike, "be"))
}

func TestSAName(t *testing.T) {
	assert.Equal(t, "openrag-my-cr-fe", saName("my-cr", "fe"))
	assert.Equal(t, "openrag-my-cr-be", saName("my-cr", "be"))
	assert.Equal(t, "openrag-my-cr-lf", saName("my-cr", "lf"))
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
			types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, d),
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
			types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
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
			types.NamespacedName{Name: instanceSAName(cr, role), Namespace: "my-ns"}, sa),
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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))
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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))

	var backendHost string
	for _, e := range d.Spec.Template.Spec.Containers[0].Env {
		if e.Name == "OPENRAG_BACKEND_HOST" {
			backendHost = e.Value
		}
	}
	assert.Equal(t, instanceResourceName(cr, "be"), backendHost)
}

func TestReconcile_BackendMountsOperatorManagedEnvSecret(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, d))

	expectedSecret := instanceResourceName(cr, "be-env")
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
		types.NamespacedName{Name: instanceResourceName(cr, "be-env"), Namespace: "my-ns"}, sec))

	// In the test environment, StringData is not converted to Data
	// Use StringData if Data is empty (test env), otherwise use Data (real cluster)
	envContent := string(sec.Data[".env"])
	if envContent == "" && sec.StringData != nil {
		envContent = sec.StringData[".env"]
	}
	assert.Contains(t, envContent, `LANGFLOW_URL="http://`+instanceResourceName(cr, "lf")+`:7860"`)
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL="http://`+instanceResourceName(cr, "be")+`:8000"`)
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
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, d))

	var found bool
	for _, v := range d.Spec.Template.Spec.Volumes {
		if v.Name == "langflow-data" {
			assert.Equal(t, instanceResourceName(cr, "lf-data"), v.PersistentVolumeClaim.ClaimName)
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

func TestReconcile_AlwaysAddsFinalizer_SameNamespace(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	updated := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}, updated))
	// Finalizer is always added (even for same namespace) to ensure .env secret finalizers are cleaned up on deletion
	assert.True(t, controllerutil.ContainsFinalizer(updated, finalizer))
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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "tenant-ns"}, d))
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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, d))

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
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, feDeploy))
	assert.Equal(t, "fe-value", feDeploy.Annotations["frontend-deploy-annotation"])
	assert.Equal(t, "fe-pod-value", feDeploy.Spec.Template.Annotations["frontend-pod-annotation"])

	// Check Backend
	beDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, beDeploy))
	assert.Equal(t, "be-value", beDeploy.Labels["backend-deploy-label"])
	assert.Equal(t, "be-pod-value", beDeploy.Spec.Template.Labels["backend-pod-label"])

	// Check Langflow
	lfDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, lfDeploy))
	assert.Equal(t, "lf-value", lfDeploy.Labels["langflow-deploy-label"])
	assert.Equal(t, "lf-annotation", lfDeploy.Annotations["langflow-deploy-annotation"])
	assert.Equal(t, "lf-pod-value", lfDeploy.Spec.Template.Labels["langflow-pod-label"])
	assert.Equal(t, "lf-pod-annotation", lfDeploy.Spec.Template.Annotations["langflow-pod-annotation"])
}

// TestReconcile_UUIDNameDNS1035Compliance verifies that resource names are DNS-1035
// compliant even when the CR name is a UUID starting with a digit.
// The openrag- prefix ensures names always start with a letter.
func TestReconcile_UUIDNameDNS1035Compliance(t *testing.T) {
	s := newScheme(t)
	uuidName := "9a826efa-112d-4e2d-9f8d-ce103880ab41"
	cr := minimalCR(uuidName, "test-ns")
	cr.Spec.MultiInstance = true

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	dns1035Regex := `^[a-z]([-a-z0-9]*[a-z0-9])?$`

	feDeploy := &appsv1.Deployment{}
	feName := instanceResourceName(cr, "fe")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: feName, Namespace: "test-ns"}, feDeploy))
	assert.Regexp(t, dns1035Regex, feName, "Frontend deployment name must be DNS-1035 compliant")
	assert.Regexp(t, dns1035Regex, feDeploy.Name, "Frontend deployment name must be DNS-1035 compliant")

	feSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: feName, Namespace: "test-ns"}, feSvc))
	assert.Regexp(t, dns1035Regex, feSvc.Name, "Frontend service name must be DNS-1035 compliant")

	beDeploy := &appsv1.Deployment{}
	beName := instanceResourceName(cr, "be")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: beName, Namespace: "test-ns"}, beDeploy))
	assert.Regexp(t, dns1035Regex, beName, "Backend deployment name must be DNS-1035 compliant")

	lfDeploy := &appsv1.Deployment{}
	lfName := instanceResourceName(cr, "lf")
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: lfName, Namespace: "test-ns"}, lfDeploy))
	assert.Regexp(t, dns1035Regex, lfName, "Langflow deployment name must be DNS-1035 compliant")

	// Verify names follow the openrag-<crName>-<role> pattern
	assert.Equal(t, "openrag-"+uuidName+"-fe", feName)
	assert.Equal(t, "openrag-"+uuidName+"-be", beName)
	assert.Equal(t, "openrag-"+uuidName+"-lf", lfName)

	// CR name is tracked in labels
	assert.Equal(t, uuidName, feDeploy.Labels["app.kubernetes.io/instance"])
	assert.Equal(t, uuidName, beDeploy.Labels["app.kubernetes.io/instance"])
	assert.Equal(t, uuidName, lfDeploy.Labels["app.kubernetes.io/instance"])
}

// ---------------------------------------------------------------------------
// ImagePullSecrets tests
// ---------------------------------------------------------------------------

func TestMergeImagePullSecrets_BothEmpty(t *testing.T) {
	result := mergeImagePullSecrets(nil, nil)
	assert.Nil(t, result)
}

func TestMergeImagePullSecrets_OnlyGlobal(t *testing.T) {
	global := []corev1.LocalObjectReference{
		{Name: "global-secret"},
	}
	result := mergeImagePullSecrets(global, nil)
	assert.Equal(t, []corev1.LocalObjectReference{{Name: "global-secret"}}, result)
}

func TestMergeImagePullSecrets_OnlyComponent(t *testing.T) {
	component := []corev1.LocalObjectReference{
		{Name: "component-secret"},
	}
	result := mergeImagePullSecrets(nil, component)
	assert.Equal(t, []corev1.LocalObjectReference{{Name: "component-secret"}}, result)
}

func TestMergeImagePullSecrets_BothPresent(t *testing.T) {
	global := []corev1.LocalObjectReference{
		{Name: "global-secret"},
	}
	component := []corev1.LocalObjectReference{
		{Name: "component-secret"},
	}
	result := mergeImagePullSecrets(global, component)
	expected := []corev1.LocalObjectReference{
		{Name: "component-secret"},
		{Name: "global-secret"},
	}
	assert.Equal(t, expected, result)
}

func TestMergeImagePullSecrets_Deduplication(t *testing.T) {
	global := []corev1.LocalObjectReference{
		{Name: "shared-secret"},
		{Name: "global-only"},
	}
	component := []corev1.LocalObjectReference{
		{Name: "component-only"},
		{Name: "shared-secret"}, // Duplicate
	}
	result := mergeImagePullSecrets(global, component)
	// Component secrets come first, dedup keeps first occurrence
	expected := []corev1.LocalObjectReference{
		{Name: "component-only"},
		{Name: "shared-secret"}, // From component (first occurrence)
		{Name: "global-only"},
	}
	assert.Equal(t, expected, result)
}

func TestReconcile_ComponentImagePullSecrets_Frontend(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Frontend.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "frontend-secret"},
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, deploy))

	assert.Equal(t, []corev1.LocalObjectReference{{Name: "frontend-secret"}},
		deploy.Spec.Template.Spec.ImagePullSecrets)
}

func TestReconcile_ComponentImagePullSecrets_Backend(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Backend.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "backend-secret"},
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, deploy))

	assert.Equal(t, []corev1.LocalObjectReference{{Name: "backend-secret"}},
		deploy.Spec.Template.Spec.ImagePullSecrets)
}

func TestReconcile_ComponentImagePullSecrets_Langflow(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Langflow.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "langflow-secret"},
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "test-ns"}, deploy))

	assert.Equal(t, []corev1.LocalObjectReference{{Name: "langflow-secret"}},
		deploy.Spec.Template.Spec.ImagePullSecrets)
}

func TestReconcile_GlobalAndComponentImagePullSecrets(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	// Set global secrets
	cr.Spec.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "global-secret"},
	}
	// Set component-specific secrets
	cr.Spec.Frontend.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "frontend-secret"},
	}
	cr.Spec.Backend.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "backend-secret"},
	}
	cr.Spec.Langflow.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "langflow-secret"},
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Check frontend: should have both frontend-specific and global
	feDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, feDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{
		{Name: "frontend-secret"},
		{Name: "global-secret"},
	}, feDeploy.Spec.Template.Spec.ImagePullSecrets)

	// Check backend: should have both backend-specific and global
	beDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, beDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{
		{Name: "backend-secret"},
		{Name: "global-secret"},
	}, beDeploy.Spec.Template.Spec.ImagePullSecrets)

	// Check langflow: should have both langflow-specific and global
	lfDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "test-ns"}, lfDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{
		{Name: "langflow-secret"},
		{Name: "global-secret"},
	}, lfDeploy.Spec.Template.Spec.ImagePullSecrets)
}

func TestReconcile_OnlyGlobalImagePullSecrets(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.ImagePullSecrets = []corev1.LocalObjectReference{
		{Name: "global-secret"},
	}

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// All components should use the global secret
	feDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, feDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{{Name: "global-secret"}},
		feDeploy.Spec.Template.Spec.ImagePullSecrets)

	beDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, beDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{{Name: "global-secret"}},
		beDeploy.Spec.Template.Spec.ImagePullSecrets)

	lfDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "test-ns"}, lfDeploy))
	assert.Equal(t, []corev1.LocalObjectReference{{Name: "global-secret"}},
		lfDeploy.Spec.Template.Spec.ImagePullSecrets)
}

// ---------------------------------------------------------------------------
// Custom ServiceAccount and Service Name tests
// ---------------------------------------------------------------------------

func TestReconcile_CustomServiceAccountName_OperatorCreates(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Frontend.ServiceAccountName = "my-custom-sa"
	// CreateServiceAccount defaults to true, so operator will create it

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Verify operator created the SA with custom name
	customSA := &corev1.ServiceAccount{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: "my-custom-sa", Namespace: "test-ns"}, customSA))

	// Verify deployment uses the custom SA
	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, deploy))
	assert.Equal(t, "my-custom-sa", deploy.Spec.Template.Spec.ServiceAccountName)

	// Verify operator did NOT create the default SA
	defaultSA := &corev1.ServiceAccount{}
	err := c.Get(context.Background(),
		types.NamespacedName{Name: instanceSAName(cr, "fe"), Namespace: "test-ns"}, defaultSA)
	assert.True(t, errors.IsNotFound(err), "Default SA should not be created when custom name is specified")
}

func TestReconcile_CustomServiceAccountName_UserManaged(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Frontend.ServiceAccountName = "my-custom-sa"
	createSA := false
	cr.Spec.Frontend.CreateServiceAccount = &createSA // User manages the SA

	// Pre-create the user-managed service account
	customSA := &corev1.ServiceAccount{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "my-custom-sa",
			Namespace: "test-ns",
		},
	}

	r, c := reconciler(s, cr, customSA)
	reconcileOnce(t, r, cr)

	// Verify deployment uses the custom SA
	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, deploy))
	assert.Equal(t, "my-custom-sa", deploy.Spec.Template.Spec.ServiceAccountName)

	// Verify the SA still exists and wasn't recreated (check it's the pre-created one)
	sa := &corev1.ServiceAccount{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: "my-custom-sa", Namespace: "test-ns"}, sa))
}

func TestReconcile_DefaultServiceAccountName(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	// No custom SA specified

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Verify operator creates the default SA
	defaultSA := &corev1.ServiceAccount{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceSAName(cr, "fe"), Namespace: "test-ns"}, defaultSA))

	// Verify deployment uses the default SA
	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, deploy))
	assert.Equal(t, instanceSAName(cr, "fe"), deploy.Spec.Template.Spec.ServiceAccountName)
}

func TestReconcile_CustomServiceName_OperatorCreates(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Backend.ServiceName = "my-backend-svc"
	// CreateService defaults to true, so operator will create it

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Verify operator created the Service with custom name
	customSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: "my-backend-svc", Namespace: "test-ns"}, customSvc))
	assert.Equal(t, int32(8000), customSvc.Spec.Ports[0].Port)

	// Verify operator did NOT create the default Service
	defaultSvc := &corev1.Service{}
	err := c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, defaultSvc)
	assert.True(t, errors.IsNotFound(err), "Default Service should not be created when custom name is specified")

	// Verify backend env secret references the custom service name
	secret := &corev1.Secret{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be-env"), Namespace: "test-ns"}, secret))

	envContent := string(secret.Data[".env"])
	if envContent == "" && secret.StringData != nil {
		envContent = secret.StringData[".env"]
	}
	assert.Contains(t, envContent, `LANGFLOW_URL="http://`+instanceResourceName(cr, "lf")+`:7860"`,
		"Backend env should reference default langflow service")
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL="http://my-backend-svc:8000"`,
		"Backend env should reference custom backend service name")
}

func TestReconcile_CustomServiceName_UserManaged(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Backend.ServiceName = "my-backend-svc"
	createSvc := false
	cr.Spec.Backend.CreateService = &createSvc // User manages the Service

	// Pre-create the user-managed service
	customSvc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "my-backend-svc",
			Namespace: "test-ns",
		},
		Spec: corev1.ServiceSpec{
			Ports: []corev1.ServicePort{
				{Name: "http", Port: 8000, Protocol: corev1.ProtocolTCP},
			},
		},
	}

	r, c := reconciler(s, cr, customSvc)
	reconcileOnce(t, r, cr)

	// Verify the Service still exists and wasn't recreated
	svc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: "my-backend-svc", Namespace: "test-ns"}, svc))

	// Verify operator did NOT create the default Service
	defaultSvc := &corev1.Service{}
	err := c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, defaultSvc)
	assert.True(t, errors.IsNotFound(err), "Default Service should not be created when custom name is specified")
}

func TestReconcile_CustomServiceName_UsedInFrontendEnv(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Backend.ServiceName = "custom-be-svc"

	// Pre-create the custom service
	customSvc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "custom-be-svc",
			Namespace: "test-ns",
		},
		Spec: corev1.ServiceSpec{
			Ports: []corev1.ServicePort{
				{Name: "http", Port: 8000, Protocol: corev1.ProtocolTCP},
			},
		},
	}

	r, c := reconciler(s, cr, customSvc)
	reconcileOnce(t, r, cr)

	// Verify frontend deployment references the custom backend service name
	deploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, deploy))

	var backendHost string
	for _, env := range deploy.Spec.Template.Spec.Containers[0].Env {
		if env.Name == "OPENRAG_BACKEND_HOST" {
			backendHost = env.Value
			break
		}
	}
	assert.Equal(t, "custom-be-svc", backendHost,
		"Frontend should reference custom backend service name")
}

func TestReconcile_CustomServiceName_Langflow_UsedInBackendEnv(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")
	cr.Spec.Langflow.ServiceName = "custom-lf-svc"

	// Pre-create the custom service
	customSvc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "custom-lf-svc",
			Namespace: "test-ns",
		},
		Spec: corev1.ServiceSpec{
			Ports: []corev1.ServicePort{
				{Name: "http", Port: 7860, Protocol: corev1.ProtocolTCP},
			},
		},
	}

	r, c := reconciler(s, cr, customSvc)
	reconcileOnce(t, r, cr)

	// Verify backend env secret references the custom langflow service name
	secret := &corev1.Secret{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be-env"), Namespace: "test-ns"}, secret))

	envContent := string(secret.Data[".env"])
	if envContent == "" && secret.StringData != nil {
		envContent = secret.StringData[".env"]
	}
	assert.Contains(t, envContent, `LANGFLOW_URL="http://custom-lf-svc:7860"`,
		"Backend env should reference custom langflow service name")
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL="http://`+instanceResourceName(cr, "be")+`:8000"`,
		"Backend env should reference default backend service")
}

func TestReconcile_AllComponentsWithCustomNames_OperatorCreates(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-cr", "test-ns")

	// Set custom names for all components (operator will create them by default)
	cr.Spec.Frontend.ServiceAccountName = "custom-fe-sa"
	cr.Spec.Frontend.ServiceName = "custom-fe-svc"
	cr.Spec.Backend.ServiceAccountName = "custom-be-sa"
	cr.Spec.Backend.ServiceName = "custom-be-svc"
	cr.Spec.Langflow.ServiceAccountName = "custom-lf-sa"
	cr.Spec.Langflow.ServiceName = "custom-lf-svc"

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Verify operator created all custom SAs
	for _, name := range []string{"custom-fe-sa", "custom-be-sa", "custom-lf-sa"} {
		sa := &corev1.ServiceAccount{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: name, Namespace: "test-ns"}, sa),
			"Operator should create SA %s", name)
	}

	// Verify operator created all custom Services
	for _, name := range []string{"custom-fe-svc", "custom-be-svc", "custom-lf-svc"} {
		svc := &corev1.Service{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: name, Namespace: "test-ns"}, svc),
			"Operator should create Service %s", name)
	}

	// Verify all deployments use custom names
	feDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "test-ns"}, feDeploy))
	assert.Equal(t, "custom-fe-sa", feDeploy.Spec.Template.Spec.ServiceAccountName)

	// Verify no default SAs or Services were created
	for _, role := range []string{"fe", "be", "lf"} {
		defaultSA := &corev1.ServiceAccount{}
		err := c.Get(context.Background(),
			types.NamespacedName{Name: instanceSAName(cr, role), Namespace: "test-ns"}, defaultSA)
		assert.True(t, errors.IsNotFound(err), "Default SA for %s should not be created", role)

		defaultSvc := &corev1.Service{}
		err = c.Get(context.Background(),
			types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "test-ns"}, defaultSvc)
		assert.True(t, errors.IsNotFound(err), "Default Service for %s should not be created", role)
	}
}

// ---------------------------------------------------------------------------
// .env Secret Hash and Pod Restart Tests
// ---------------------------------------------------------------------------

func TestCalculateHash_Deterministic(t *testing.T) {
	// Same content should always produce the same hash
	content := "VAR1=value1\nVAR2=value2\nVAR3=value3\n"

	hash1 := calculateHash(content)
	hash2 := calculateHash(content)

	assert.Equal(t, hash1, hash2, "Same content should produce same hash")
	assert.NotEmpty(t, hash1, "Hash should not be empty")
	assert.Len(t, hash1, 64, "SHA256 hash should be 64 hex characters")
}

func TestCalculateHash_DifferentContent(t *testing.T) {
	// Different content should produce different hashes
	content1 := "VAR1=value1\nVAR2=value2\n"
	content2 := "VAR1=value1\nVAR2=different\n"

	hash1 := calculateHash(content1)
	hash2 := calculateHash(content2)

	assert.NotEqual(t, hash1, hash2, "Different content should produce different hash")
}

func TestEnvHash_StableAcrossReconciles(t *testing.T) {
	// Test that identical env produces identical hash even across multiple reconcile loops
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "custom_value"},
	}

	r, _ := reconciler(s, cr)

	// Reconcile multiple times
	var hashes []string
	for i := 0; i < 5; i++ {
		backendEnvContent, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
		require.NoError(t, err)
		hash := calculateHash(backendEnvContent)
		hashes = append(hashes, hash)
	}

	// All hashes should be identical
	for i := 1; i < len(hashes); i++ {
		assert.Equal(t, hashes[0], hashes[i], "Hash should be stable across reconciles (iteration %d)", i)
	}
}

func TestEnvHash_ChangesWhenEnvChanges(t *testing.T) {
	// Test that changing env vars produces different hash
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "original_value"},
	}

	r, _ := reconciler(s, cr)

	// Get hash with original env
	backendEnvContent1, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	hash1 := calculateHash(backendEnvContent1)

	// Change env var value
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "changed_value"},
	}

	// Get hash with changed env
	backendEnvContent2, err := r.buildBackendEnv(context.Background(), cr, "test-ns")
	require.NoError(t, err)
	hash2 := calculateHash(backendEnvContent2)

	assert.NotEqual(t, hash1, hash2, "Hash should change when env vars change")
}

func TestDeployment_ContainsEnvHashAnnotation(t *testing.T) {
	// Test that backend deployment has env hash annotation
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	// Get backend deployment
	backendDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy))

	// Check for hash annotation
	annotations := backendDeploy.Spec.Template.Annotations
	require.NotNil(t, annotations, "Pod template should have annotations")
	assert.Contains(t, annotations, "openr.ag/backend-env-hash", "Backend pod should have env hash annotation")
	assert.NotEmpty(t, annotations["openr.ag/backend-env-hash"], "Hash annotation should not be empty")
	assert.Len(t, annotations["openr.ag/backend-env-hash"], 64, "Hash should be 64 hex characters")

	// Get langflow deployment
	langflowDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "test-ns"}, langflowDeploy))

	// Check for hash annotation
	lfAnnotations := langflowDeploy.Spec.Template.Annotations
	require.NotNil(t, lfAnnotations, "Langflow pod template should have annotations")
	assert.Contains(t, lfAnnotations, "openr.ag/langflow-env-hash", "Langflow pod should have env hash annotation")
	assert.NotEmpty(t, lfAnnotations["openr.ag/langflow-env-hash"], "Hash annotation should not be empty")
	assert.Len(t, lfAnnotations["openr.ag/langflow-env-hash"], 64, "Hash should be 64 hex characters")
}

func TestDeployment_HashChangeTriggersUpdate(t *testing.T) {
	// Test that changing env causes hash annotation to change, triggering pod restart
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "original"},
	}
	r, c := reconciler(s, cr)

	// Initial reconcile
	reconcileOnce(t, r, cr)

	// Get initial hash
	backendDeploy1 := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy1))
	hash1 := backendDeploy1.Spec.Template.Annotations["openr.ag/backend-env-hash"]
	require.NotEmpty(t, hash1, "Initial hash should exist")

	// Update CR with different env value
	updatedCR := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: "test-openrag", Namespace: "test-ns"}, updatedCR))
	updatedCR.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "changed"},
	}
	require.NoError(t, c.Update(context.Background(), updatedCR))

	// Reconcile again with updated CR
	reconcileOnce(t, r, updatedCR)

	// Get updated hash
	backendDeploy2 := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy2))
	hash2 := backendDeploy2.Spec.Template.Annotations["openr.ag/backend-env-hash"]
	require.NotEmpty(t, hash2, "Updated hash should exist")

	// Hash should have changed
	assert.NotEqual(t, hash1, hash2, "Hash should change when env changes, triggering pod restart")
}

func TestDeployment_NoHashChangeWhenEnvUnchanged(t *testing.T) {
	// Test that reconciling without env changes keeps the same hash
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.Backend.Env = []corev1.EnvVar{
		{Name: "CUSTOM_VAR", Value: "constant"},
	}
	r, c := reconciler(s, cr)

	// Initial reconcile
	reconcileOnce(t, r, cr)

	// Get initial hash
	backendDeploy1 := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy1))
	hash1 := backendDeploy1.Spec.Template.Annotations["openr.ag/backend-env-hash"]

	// Reconcile again without changing env
	reconcileOnce(t, r, cr)

	// Get hash after second reconcile
	backendDeploy2 := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy2))
	hash2 := backendDeploy2.Spec.Template.Annotations["openr.ag/backend-env-hash"]

	// Hash should be identical (no unnecessary pod restart)
	assert.Equal(t, hash1, hash2, "Hash should remain same when env unchanged (avoids unnecessary restarts)")
}
