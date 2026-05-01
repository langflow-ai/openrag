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
	assert.Equal(t, "my-openrag-openrag-fe", resourceName("my-openrag", "fe"))
	assert.Equal(t, "my-openrag-openrag-be", resourceName("my-openrag", "be"))
	assert.Equal(t, "my-openrag-openrag-lf", resourceName("my-openrag", "lf"))
}

func TestSAName(t *testing.T) {
	assert.Equal(t, "openrag-my-openrag-fe", saName("my-openrag", "fe"))
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
			types.NamespacedName{Name: resourceName(cr.Name, role), Namespace: "my-ns"}, d),
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
			types.NamespacedName{Name: resourceName(cr.Name, role), Namespace: "my-ns"}, svc))
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
			types.NamespacedName{Name: saName(cr.Name, role), Namespace: "my-ns"}, sa),
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
		types.NamespacedName{Name: resourceName(cr.Name, "fe"), Namespace: "my-ns"}, d))
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
		types.NamespacedName{Name: resourceName(cr.Name, "fe"), Namespace: "my-ns"}, d))

	var backendHost string
	for _, e := range d.Spec.Template.Spec.Containers[0].Env {
		if e.Name == "OPENRAG_BACKEND_HOST" {
			backendHost = e.Value
		}
	}
	assert.Equal(t, resourceName(cr.Name, "be"), backendHost)
}

func TestReconcile_BackendMountsOperatorManagedEnvSecret(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName(cr.Name, "be"), Namespace: "my-ns"}, d))

	expectedSecret := resourceName(cr.Name, "be-env")
	var found bool
	for _, v := range d.Spec.Template.Spec.Volumes {
		if v.Name == "backend-env" {
			assert.Equal(t, expectedSecret, v.Secret.SecretName)
			found = true
		}
	}
	assert.True(t, found, "backend-env volume should exist with operator-managed secret")
}

func TestReconcile_CreatesEnvSecrets(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	for _, role := range []string{"be-env", "lf-env", "gen-creds"} {
		sec := &corev1.Secret{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: resourceName(cr.Name, role), Namespace: "my-ns"}, sec),
			"secret for role %s should exist", role)
	}
}

func TestReconcile_BackendEnvContainsLangflowURL(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	sec := &corev1.Secret{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName(cr.Name, "be-env"), Namespace: "my-ns"}, sec))

	// In the test environment, StringData is not converted to Data
	// Use StringData if Data is empty (test env), otherwise use Data (real cluster)
	envContent := string(sec.Data[".env"])
	if envContent == "" && sec.StringData != nil {
		envContent = sec.StringData[".env"]
	}
	assert.Contains(t, envContent, "LANGFLOW_URL=http://"+resourceName(cr.Name, "lf")+":7860")
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
		types.NamespacedName{Name: resourceName(cr.Name, "lf"), Namespace: "my-ns"}, d))

	var found bool
	for _, v := range d.Spec.Template.Spec.Volumes {
		if v.Name == "langflow-data" {
			assert.Equal(t, resourceName(cr.Name, "lf-data"), v.PersistentVolumeClaim.ClaimName)
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

	reconcileOnce(t, r, cr)

	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: resourceName(cr.Name, "fe"), Namespace: "tenant-ns"}, d))
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
