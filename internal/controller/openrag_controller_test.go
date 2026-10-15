package controller

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	openragv1alpha1 "github.com/langflow-ai/openrag-deploy/api/v1alpha1"
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
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	// First reconcile: adds finalizer and returns early.
	// Adding the finalizer triggers an Update() which returns early.
	_, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)

	// Components roll out in dependency order (Langflow → Backend → Frontend), and
	// each step waits for the previous Deployment's current revision to become
	// available. The fake client does not run the Deployment controller, so mark
	// created Deployments as rolled out between passes to let the rollout advance
	// to completion, leaving all resources created for end-state assertions.
	var res ctrl.Result
	for range 12 {
		res, err = r.Reconcile(context.Background(), req)
		require.NoError(t, err)
		if res.RequeueAfter != rolloutPollInterval {
			return res // rollout complete (or not gated) — stop driving
		}
		markDeploymentsRolledOut(t, r.Client)
	}
	t.Fatalf("ordered rollout did not converge within iteration budget")
	return res
}

// markDeploymentsRolledOut simulates the Deployment controller reporting every
// existing Deployment's current revision as fully available, so the operator's
// readiness-gated ordered rollout can advance under the fake client.
func markDeploymentsRolledOut(t *testing.T, c client.Client) {
	t.Helper()
	list := &appsv1.DeploymentList{}
	require.NoError(t, c.List(context.Background(), list))
	for i := range list.Items {
		d := &list.Items[i]
		desired := int32(1)
		if d.Spec.Replicas != nil {
			desired = *d.Spec.Replicas
		}
		d.Status.ObservedGeneration = d.Generation
		d.Status.Replicas = desired
		d.Status.UpdatedReplicas = desired
		d.Status.AvailableReplicas = desired
		d.Status.ReadyReplicas = desired
		require.NoError(t, c.Status().Update(context.Background(), d))
	}
}

// setDeploymentRolledOut simulates the Deployment controller reporting a single
// Deployment's current revision as fully available (ready=true) or still rolling
// (ready=false), so ordered-update gating can be exercised under the fake client.
func setDeploymentRolledOut(t *testing.T, c client.Client, name, ns string, ready bool) {
	t.Helper()
	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(), types.NamespacedName{Name: name, Namespace: ns}, d))
	desired := int32(1)
	if d.Spec.Replicas != nil {
		desired = *d.Spec.Replicas
	}
	d.Status.ObservedGeneration = d.Generation
	if ready {
		d.Status.Replicas = desired
		d.Status.UpdatedReplicas = desired
		d.Status.AvailableReplicas = desired
		d.Status.ReadyReplicas = desired
	} else {
		// New revision created but not yet available (readiness probe pending).
		d.Status.Replicas = desired
		d.Status.UpdatedReplicas = desired
		d.Status.AvailableReplicas = 0
		d.Status.ReadyReplicas = 0
	}
	require.NoError(t, c.Status().Update(context.Background(), d))
}

// setDeploymentProgressDeadlineExceeded simulates Kubernetes giving up on a
// Deployment's rollout: its current revision is observed but no replica is
// available, and it carries a Progressing=False / reason=ProgressDeadlineExceeded
// condition (what the Deployment controller sets after progressDeadlineSeconds).
func setDeploymentProgressDeadlineExceeded(t *testing.T, c client.Client, name, ns string) {
	t.Helper()
	d := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(), types.NamespacedName{Name: name, Namespace: ns}, d))
	desired := int32(1)
	if d.Spec.Replicas != nil {
		desired = *d.Spec.Replicas
	}

	d.Status.ObservedGeneration = d.Generation
	d.Status.Replicas = desired
	d.Status.UpdatedReplicas = desired
	d.Status.AvailableReplicas = 0
	d.Status.ReadyReplicas = 0
	d.Status.Conditions = []appsv1.DeploymentCondition{
		{
			Type:    appsv1.DeploymentProgressing,
			Status:  corev1.ConditionFalse,
			Reason:  "ProgressDeadlineExceeded",
			Message: "ReplicaSet has timed out progressing.",
		},
	}
	require.NoError(t, c.Status().Update(context.Background(), d))
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

// TestReconcile_OrderedRollout_InstallCreatesAllAtOnce verifies that the initial
// install is NOT subject to ordering: all three Deployments are created in a
// single reconcile pass without waiting on any dependency's readiness.
func TestReconcile_OrderedRollout_InstallCreatesAllAtOnce(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	// Pass 1 adds the finalizer and returns early.
	_, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)

	// Pass 2 creates every Deployment at once — all three must exist because
	// creation is never gated. Ordering applies only to *upgrades* of existing
	// components, not to initial creation; pods come up in parallel.
	// The rollout reports RollingOut (fast poll) until each created component
	// becomes available, walking the phase LF→BE→FE as each comes up.
	res, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)
	for _, role := range []string{"lf", "be", "fe"} {
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, &appsv1.Deployment{}),
			"deployment %s should be created on install without waiting on ordering", role)
	}
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter, "install polls until components are available")
	got := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, got))
	assert.Equal(t, rolloutPhaseLangflow, got.Status.RolloutPhase)
}

// TestReconcile_OrderedRollout_RecreatesDeletedDeploymentImmediately verifies that
// a Deployment deleted out from under the operator is recreated on the next pass,
// without observing the ordering.
func TestReconcile_OrderedRollout_RecreatesDeletedDeploymentImmediately(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	reconcileOnce(t, r, cr)
	markDeploymentsRolledOut(t, c) // all healthy at their initial revision

	// Delete the backend Deployment.
	be := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, be))
	require.NoError(t, c.Delete(context.Background(), be))

	// A single reconcile recreates it immediately, regardless of ordering.
	_, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, &appsv1.Deployment{}),
		"deleted backend deployment should be recreated immediately")
}

// TestReconcile_OrderedRollout_UpdatesGatedByDependencyReadiness verifies that once
// the components exist, a *revision update* is applied in dependency order: Backend's
// new revision is withheld until Langflow's new revision is available, and Frontend's
// until Backend's is.
func TestReconcile_OrderedRollout_UpdatesGatedByDependencyReadiness(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	reconcileOnce(t, r, cr)
	markDeploymentsRolledOut(t, c) // baseline: all three healthy at their original image

	origBE := r.backendDeployment(cr, "my-ns", "").Spec.Template.Spec.Containers[0].Image
	origFE := r.frontendDeployment(cr, "my-ns").Spec.Template.Spec.Containers[0].Image

	imageOf := func(role string) string {
		d := &appsv1.Deployment{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, d))
		return d.Spec.Template.Spec.Containers[0].Image
	}
	rolloutPhase := func() string {
		got := &openragv1alpha1.OpenRAG{}
		require.NoError(t, c.Get(context.Background(), req.NamespacedName, got))
		return got.Status.RolloutPhase
	}
	reconcile := func() ctrl.Result {
		res, err := r.Reconcile(context.Background(), req)
		require.NoError(t, err)
		return res
	}

	// Bump all three images at once.
	upd := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, upd))
	upd.Spec.Langflow.Image = "langflow:v2"
	upd.Spec.Backend.Image = "backend:v2"
	upd.Spec.Frontend.Image = "frontend:v2"
	require.NoError(t, c.Update(context.Background(), upd))

	// Pass 1: only Langflow's new revision rolls; Backend and Frontend are withheld.
	res := reconcile()
	assert.Equal(t, "langflow:v2", imageOf("lf"))
	assert.Equal(t, origBE, imageOf("be"), "Backend update must wait for Langflow")
	assert.Equal(t, origFE, imageOf("fe"), "Frontend update must wait for Backend")
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter)
	assert.Equal(t, rolloutPhaseLangflow, rolloutPhase())

	// Langflow's new revision still rolling → Backend stays withheld.
	setDeploymentRolledOut(t, c, instanceResourceName(cr, "lf"), "my-ns", false)
	res = reconcile()
	assert.Equal(t, origBE, imageOf("be"), "Backend must keep waiting while Langflow rolls")
	assert.Equal(t, rolloutPhaseLangflow, rolloutPhase())
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter)

	// Langflow available → Backend's new revision rolls; Frontend withheld.
	setDeploymentRolledOut(t, c, instanceResourceName(cr, "lf"), "my-ns", true)
	res = reconcile()
	assert.Equal(t, "backend:v2", imageOf("be"))
	assert.Equal(t, origFE, imageOf("fe"), "Frontend update must wait for Backend")
	assert.Equal(t, rolloutPhaseBackend, rolloutPhase())
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter)

	// Backend available → Frontend's new revision rolls last.
	setDeploymentRolledOut(t, c, instanceResourceName(cr, "be"), "my-ns", true)
	res = reconcile()
	assert.Equal(t, "frontend:v2", imageOf("fe"))
	assert.Equal(t, rolloutPhaseFrontend, rolloutPhase())
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter)

	// Frontend update applied (last in the chain) → ordered rollout complete.
	res = reconcile()
	assert.Equal(t, rolloutPhaseComplete, rolloutPhase())
	assert.NotEqual(t, rolloutPollInterval, res.RequeueAfter)
}

func TestReconcile_OrderedRollout_StuckUpgradeStaysRollingOutThenDegraded(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	reconcileOnce(t, r, cr)
	markDeploymentsRolledOut(t, c)

	get := func() *openragv1alpha1.OpenRAG {
		got := &openragv1alpha1.OpenRAG{}
		require.NoError(t, c.Get(context.Background(), req.NamespacedName, got))
		return got
	}
	reconcile := func() ctrl.Result {
		res, err := r.Reconcile(context.Background(), req)
		require.NoError(t, err)
		return res
	}

	upd := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, upd))
	upd.Spec.Langflow.Image = "langflowai/openrag-langflow:does-not-exist"
	require.NoError(t, c.Update(context.Background(), upd))

	reconcile()

	// contextdeadline not hit so should stay rollingout
	setDeploymentRolledOut(t, c, instanceResourceName(cr, "lf"), "my-ns", false)
	res := reconcile()
	got := get()
	assert.Equal(t, rolloutPhaseLangflow, got.Status.RolloutPhase, "must keep waiting on Langflow")
	assert.NotEqual(t, rolloutPhaseComplete, got.Status.RolloutPhase, "must not report Complete while Langflow is unavailable")
	assert.NotEqual(t, phaseRunning, got.Status.Phase, "must not report Running while Langflow is unavailable")
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter, "must keep requeuing while rolling out")

	// Kubernetes gives up after progressDeadlineSeconds and shows Degraded.
	setDeploymentProgressDeadlineExceeded(t, c, instanceResourceName(cr, "lf"), "my-ns")
	reconcile()
	got = get()
	assert.Equal(t, "Degraded", got.Status.Phase, "stalled rollout must surface as Degraded")
	assert.Equal(t, rolloutPhaseLangflow, got.Status.RolloutPhase, "Degraded status must retain the stuck component")
	assert.Contains(t, got.Status.Message, "ProgressDeadlineExceeded")
}

// TestReconcile_OrderedRollout_DegradedRecovery verifies that a stalled (Degraded)
// rollout self-heals once a healthy revision is pushed.
func TestReconcile_OrderedRollout_DegradedRecovery(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}}

	reconcileOnce(t, r, cr)
	markDeploymentsRolledOut(t, c)

	// Drive to Degraded.
	upd := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, upd))
	upd.Spec.Langflow.Image = "langflow:bad"
	require.NoError(t, c.Update(context.Background(), upd))
	_, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)
	setDeploymentProgressDeadlineExceeded(t, c, instanceResourceName(cr, "lf"), "my-ns")
	_, err = r.Reconcile(context.Background(), req)
	require.NoError(t, err)
	got := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, got))
	require.Equal(t, phaseDegraded, got.Status.Phase, "pre-condition: must be Degraded before recovery")

	// Push fix → must leave Degraded and re-enter RollingOut.
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, upd))
	upd.Spec.Langflow.Image = "langflow:fixed"
	require.NoError(t, c.Update(context.Background(), upd))
	res, err := r.Reconcile(context.Background(), req)
	require.NoError(t, err)
	require.NoError(t, c.Get(context.Background(), req.NamespacedName, got))
	assert.Equal(t, rolloutPollInterval, res.RequeueAfter)
	assert.Equal(t, phaseRollingOut, got.Status.Phase)
}

func TestUpdateStatusRollingOut_RefreshesBackendReadyCondition(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")

	// Pre-set BackendReady=True as if a prior successful reconcile had run.
	cr.Status.Conditions = []metav1.Condition{{
		Type:   conditionBackendReady,
		Status: metav1.ConditionTrue,
		Reason: "PodRunning",
	}}

	// Backend deployment exists but has no ready replicas (pod is rolling out).
	beDeploy := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"},
		Status:     appsv1.DeploymentStatus{Replicas: 1, ReadyReplicas: 0},
	}
	r, c := reconciler(s, cr, beDeploy)

	// base is snapshotted before the call so writeStatus sees the BackendReady flip
	// (True → False) as a change and actually patches.
	_, err := r.updateStatusRollingOut(context.Background(), cr, cr.DeepCopy(), "my-ns")
	require.NoError(t, err)

	updated := &openragv1alpha1.OpenRAG{}
	require.NoError(t, c.Get(context.Background(), types.NamespacedName{Name: cr.Name, Namespace: cr.Namespace}, updated))
	cond := meta.FindStatusCondition(updated.Status.Conditions, conditionBackendReady)
	require.NotNil(t, cond)
	assert.Equal(t, metav1.ConditionFalse, metav1.ConditionStatus(cond.Status))
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

func TestReconcile_RevertsManualServicePortChange(t *testing.T) {
	cases := []struct {
		role         string
		portIndex    int // which port entry to patch (0 = http, 1 = ingest-router for be)
		expectedPort int32
	}{
		{role: "fe", portIndex: 0, expectedPort: 3000},
		{role: "be", portIndex: 0, expectedPort: 8000},
		{role: "be", portIndex: 1, expectedPort: 8100}, // ingest-router port
		{role: "lf", portIndex: 0, expectedPort: 7860},
	}

	for _, tc := range cases {
		t.Run(tc.role+"_port"+fmt.Sprintf("%d", tc.portIndex), func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			// Simulate a user manually patching the Service port to 9999.
			svc := &corev1.Service{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, tc.role), Namespace: "my-ns"}, svc))
			svc.Spec.Ports[tc.portIndex].Port = 9999
			require.NoError(t, c.Update(context.Background(), svc))

			// Confirm the patch took effect.
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, tc.role), Namespace: "my-ns"}, svc))
			assert.Equal(t, int32(9999), svc.Spec.Ports[tc.portIndex].Port)

			// Reconcile again — the controller must revert the port.
			reconcileOnce(t, r, cr)

			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, tc.role), Namespace: "my-ns"}, svc))
			assert.Equal(t, tc.expectedPort, svc.Spec.Ports[tc.portIndex].Port,
				"role %s port[%d] should be reverted to %d after reconcile", tc.role, tc.portIndex, tc.expectedPort)
		})
	}
}

// TestReconcile_RevertsManualServiceTypeChange verifies that patching a Service's
// type to any non-default value is detected and reverted to ClusterIP on the next
// reconcile, for all three core components.
func TestReconcile_RevertsManualServiceTypeChange(t *testing.T) {
	patchTypes := []corev1.ServiceType{
		corev1.ServiceTypeNodePort,
		corev1.ServiceTypeLoadBalancer,
		corev1.ServiceTypeExternalName,
	}

	for _, role := range []string{"fe", "be", "lf"} {
		for _, patchType := range patchTypes {
			t.Run(role+"_to_"+string(patchType), func(t *testing.T) {
				s := newScheme(t)
				cr := minimalCR("my-openrag", "my-ns")
				r, c := reconciler(s, cr)

				reconcileOnce(t, r, cr)

				// Simulate a user manually patching the Service type.
				svc := &corev1.Service{}
				require.NoError(t, c.Get(context.Background(),
					types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
				svc.Spec.Type = patchType
				require.NoError(t, c.Update(context.Background(), svc))

				// Confirm the patch took effect.
				require.NoError(t, c.Get(context.Background(),
					types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
				assert.Equal(t, patchType, svc.Spec.Type)

				// Reconcile again — the controller must revert to ClusterIP.
				reconcileOnce(t, r, cr)

				require.NoError(t, c.Get(context.Background(),
					types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
				assert.Equal(t, corev1.ServiceTypeClusterIP, svc.Spec.Type,
					"role %s: type %q should be reverted to ClusterIP after reconcile", role, patchType)
			})
		}
	}
}

// TestReconcile_ServiceDefaultSelectors verifies that after a reconcile each of
// the three core Services (frontend, backend, langflow) carries a Spec.Selector
// equal to the four-label set produced by componentLabels — the same labels the
// corresponding Deployment uses as its pod-selector.
func TestReconcile_ServiceDefaultSelectors(t *testing.T) {
	cases := []struct {
		role      string
		component string
	}{
		{role: "be", component: "be"},
		{role: "fe", component: "fe"},
		{role: "lf", component: "lf"},
	}

	for _, tc := range cases {
		t.Run(tc.role, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			svc := &corev1.Service{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, tc.role), Namespace: "my-ns"}, svc))

			sel := svc.Spec.Selector
			require.NotNil(t, sel, "Service %s must have a selector", tc.role)
			assert.Len(t, sel, 4, "selector for service %s should have exactly 4 labels", tc.role)
			assert.Equal(t, "openrag", sel["app.kubernetes.io/name"], "role %s", tc.role)
			assert.Equal(t, cr.Name, sel["app.kubernetes.io/instance"], "role %s", tc.role)
			assert.Equal(t, tc.component, sel["app.kubernetes.io/component"], "role %s", tc.role)
			assert.Equal(t, "openrag-operator", sel["app.kubernetes.io/managed-by"], "role %s", tc.role)
		})
	}
}

// TestReconcile_ServiceSelectorMatchesDeploymentSelector verifies that each
// Service's Spec.Selector is identical to its corresponding Deployment's
// Spec.Selector.MatchLabels, ensuring traffic is always routed to the correct pods.
func TestReconcile_ServiceSelectorMatchesDeploymentSelector(t *testing.T) {
	for _, role := range []string{"be", "fe", "lf"} {
		t.Run(role, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			svc := &corev1.Service{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))

			dep := &appsv1.Deployment{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, dep))

			assert.Equal(t, dep.Spec.Selector.MatchLabels, svc.Spec.Selector,
				"Service and Deployment selectors must match for role %s", role)
		})
	}
}

// TestReconcile_RevertsManualServiceSelectorLabelChange verifies that if a user
// overwrites one of the four managed selector labels on a Service, the next
// reconcile restores the original value for all three core components.
func TestReconcile_RevertsManualServiceSelectorLabelChange(t *testing.T) {
	for _, role := range []string{"be", "fe", "lf"} {
		t.Run(role, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			// Simulate a user overwriting the component label with a wrong value.
			svc := &corev1.Service{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			svc.Spec.Selector["app.kubernetes.io/component"] = "wrong-value"
			require.NoError(t, c.Update(context.Background(), svc))

			// Confirm the patch took effect.
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			assert.Equal(t, "wrong-value", svc.Spec.Selector["app.kubernetes.io/component"])

			// Reconcile — controller must revert to the correct component value.
			reconcileOnce(t, r, cr)

			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			assert.Equal(t, role, svc.Spec.Selector["app.kubernetes.io/component"],
				"role %s: component selector label should be reverted after reconcile", role)
			assert.Equal(t, "openrag", svc.Spec.Selector["app.kubernetes.io/name"],
				"role %s: name selector label must be intact", role)
			assert.Equal(t, cr.Name, svc.Spec.Selector["app.kubernetes.io/instance"],
				"role %s: instance selector label must be intact", role)
			assert.Equal(t, "openrag-operator", svc.Spec.Selector["app.kubernetes.io/managed-by"],
				"role %s: managed-by selector label must be intact", role)
		})
	}
}

// TestReconcile_RevertsManualServiceSelectorLabelAddition verifies that if a
// user injects an extra label into a Service's Spec.Selector, the next reconcile
// removes it and restores the selector to exactly the four managed keys.
func TestReconcile_RevertsManualServiceSelectorLabelAddition(t *testing.T) {
	for _, role := range []string{"be", "fe", "lf"} {
		t.Run(role, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			// Simulate a user adding a spurious selector entry.
			svc := &corev1.Service{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			svc.Spec.Selector["custom-extra-label"] = "should-be-removed"
			require.NoError(t, c.Update(context.Background(), svc))

			// Confirm the extra label is visible before reconcile.
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			assert.Equal(t, "should-be-removed", svc.Spec.Selector["custom-extra-label"])

			// Reconcile — controller must strip the extra label.
			reconcileOnce(t, r, cr)

			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, role), Namespace: "my-ns"}, svc))
			_, exists := svc.Spec.Selector["custom-extra-label"]
			assert.False(t, exists,
				"role %s: extra selector label should be removed after reconcile", role)
			assert.Len(t, svc.Spec.Selector, 4,
				"role %s: selector should have exactly 4 managed labels after reconcile", role)
		})
	}
}

// TestReconcile_RevertsManualNetworkPolicyIngressChange verifies that patching a
// NetworkPolicy's ingress rules to add unauthorized CIDR blocks (e.g., 0.0.0.0/0)
// is detected and reverted to the operator-managed private IP ranges on the next
// reconcile. This is critical for security as manual patches could open the cluster
// to unauthorized internet access.
func TestReconcile_RevertsManualNetworkPolicyIngressChange(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	// Enable NetworkPolicy
	cr.Spec.NetworkPolicy.Enabled = true

	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	// Verify NetworkPolicy was created
	np := &networkingv1.NetworkPolicy{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))

	// Verify initial ingress rules contain only private IP ranges
	require.Len(t, np.Spec.Ingress, 1, "should have exactly one ingress rule")
	require.Len(t, np.Spec.Ingress[0].From, 3, "should have exactly 3 private IP blocks")

	initialCIDRs := make([]string, 0, 3)
	for _, peer := range np.Spec.Ingress[0].From {
		require.NotNil(t, peer.IPBlock, "peer should have IPBlock")
		initialCIDRs = append(initialCIDRs, peer.IPBlock.CIDR)
	}
	assert.Contains(t, initialCIDRs, "10.0.0.0/8", "should contain 10.0.0.0/8")
	assert.Contains(t, initialCIDRs, "172.16.0.0/12", "should contain 172.16.0.0/12")
	assert.Contains(t, initialCIDRs, "192.168.0.0/16", "should contain 192.168.0.0/16")

	// Simulate a malicious user manually patching the NetworkPolicy to add 0.0.0.0/0
	// (opening Langflow to the entire internet)
	np.Spec.Ingress[0].From = append(np.Spec.Ingress[0].From, networkingv1.NetworkPolicyPeer{
		IPBlock: &networkingv1.IPBlock{CIDR: "0.0.0.0/0"},
	})
	require.NoError(t, c.Update(context.Background(), np))

	// Confirm the malicious patch took effect
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	require.Len(t, np.Spec.Ingress[0].From, 4, "should have 4 peers after malicious patch")

	patchedCIDRs := make([]string, 0, 4)
	for _, peer := range np.Spec.Ingress[0].From {
		require.NotNil(t, peer.IPBlock)
		patchedCIDRs = append(patchedCIDRs, peer.IPBlock.CIDR)
	}
	assert.Contains(t, patchedCIDRs, "0.0.0.0/0", "malicious 0.0.0.0/0 should be present")

	// Reconcile again — the controller must detect drift and revert to safe private IPs
	reconcileOnce(t, r, cr)

	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))

	// Verify the malicious 0.0.0.0/0 was removed
	require.Len(t, np.Spec.Ingress[0].From, 3, "should be reverted to exactly 3 private IP blocks")

	revertedCIDRs := make([]string, 0, 3)
	for _, peer := range np.Spec.Ingress[0].From {
		require.NotNil(t, peer.IPBlock)
		revertedCIDRs = append(revertedCIDRs, peer.IPBlock.CIDR)
	}
	assert.Contains(t, revertedCIDRs, "10.0.0.0/8", "should contain 10.0.0.0/8 after revert")
	assert.Contains(t, revertedCIDRs, "172.16.0.0/12", "should contain 172.16.0.0/12 after revert")
	assert.Contains(t, revertedCIDRs, "192.168.0.0/16", "should contain 192.168.0.0/16 after revert")
	assert.NotContains(t, revertedCIDRs, "0.0.0.0/0", "malicious 0.0.0.0/0 should be removed after reconcile")
}

// TestReconcile_RevertsManualNetworkPolicyEgressChange verifies that patching a
// NetworkPolicy's egress rules is detected and reverted on the next reconcile.
func TestReconcile_RevertsManualNetworkPolicyEgressChange(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.NetworkPolicy.Enabled = true

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Get the NetworkPolicy
	np := &networkingv1.NetworkPolicy{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))

	// Verify initial egress rules
	initialEgressCount := len(np.Spec.Egress)
	require.Greater(t, initialEgressCount, 0, "should have egress rules")

	// Simulate a user manually removing all egress rules (malicious or accidental)
	np.Spec.Egress = []networkingv1.NetworkPolicyEgressRule{}
	require.NoError(t, c.Update(context.Background(), np))

	// Confirm the patch took effect
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Len(t, np.Spec.Egress, 0, "egress rules should be cleared after patch")

	// Reconcile again — the controller must restore egress rules
	reconcileOnce(t, r, cr)

	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Len(t, np.Spec.Egress, initialEgressCount, "egress rules should be restored after reconcile")
}

// TestReconcile_RevertsManualNetworkPolicyPodSelectorChange verifies that patching a
// NetworkPolicy's podSelector is detected and reverted on the next reconcile.
func TestReconcile_RevertsManualNetworkPolicyPodSelectorChange(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.NetworkPolicy.Enabled = true

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Get the NetworkPolicy
	np := &networkingv1.NetworkPolicy{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))

	// Verify initial podSelector has the correct labels
	require.NotEmpty(t, np.Spec.PodSelector.MatchLabels, "should have podSelector labels")
	initialLabels := make(map[string]string)
	for k, v := range np.Spec.PodSelector.MatchLabels {
		initialLabels[k] = v
	}

	// Simulate a user manually clearing the podSelector (would affect all pods in namespace)
	np.Spec.PodSelector = metav1.LabelSelector{MatchLabels: map[string]string{}}
	require.NoError(t, c.Update(context.Background(), np))

	// Confirm the patch took effect
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Empty(t, np.Spec.PodSelector.MatchLabels, "podSelector should be cleared after patch")

	// Reconcile again — the controller must restore the correct podSelector
	reconcileOnce(t, r, cr)

	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Equal(t, initialLabels, np.Spec.PodSelector.MatchLabels, "podSelector should be restored after reconcile")
}

// TestReconcile_RevertsManualNetworkPolicyTypeChange verifies that patching a
// NetworkPolicy's policyTypes is detected and reverted on the next reconcile.
func TestReconcile_RevertsManualNetworkPolicyTypeChange(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	cr.Spec.NetworkPolicy.Enabled = true

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	// Get the NetworkPolicy
	np := &networkingv1.NetworkPolicy{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))

	// Verify initial policyTypes includes both Ingress and Egress
	require.Len(t, np.Spec.PolicyTypes, 2, "should have both Ingress and Egress policy types")
	assert.Contains(t, np.Spec.PolicyTypes, networkingv1.PolicyTypeIngress)
	assert.Contains(t, np.Spec.PolicyTypes, networkingv1.PolicyTypeEgress)

	// Simulate a user manually changing policyTypes to only Ingress (removes egress enforcement)
	np.Spec.PolicyTypes = []networkingv1.PolicyType{networkingv1.PolicyTypeIngress}
	require.NoError(t, c.Update(context.Background(), np))

	// Confirm the patch took effect
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Len(t, np.Spec.PolicyTypes, 1, "should have only one policy type after patch")

	// Reconcile again — the controller must restore both policy types
	reconcileOnce(t, r, cr)

	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf-netpol"), Namespace: "my-ns"}, np))
	assert.Len(t, np.Spec.PolicyTypes, 2, "should have both policy types after reconcile")
	assert.Contains(t, np.Spec.PolicyTypes, networkingv1.PolicyTypeIngress)
	assert.Contains(t, np.Spec.PolicyTypes, networkingv1.PolicyTypeEgress)
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

func TestReconcile_FrontendBasePathControlsRuntimeEnvAndProbes(t *testing.T) {
	for _, tc := range []struct {
		name     string
		basePath string
		probe    string
	}{
		{name: "root", probe: "/"},
		{name: "nested prefix", basePath: "/workspace/openrag", probe: "/workspace/openrag"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("my-openrag", "my-ns")
			cr.Spec.Frontend.BasePath = tc.basePath
			r, c := reconciler(s, cr)

			reconcileOnce(t, r, cr)

			d := &appsv1.Deployment{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, d))
			frontend := d.Spec.Template.Spec.Containers[0]
			assert.Empty(t, frontend.Command, "the image entrypoint must perform the runtime substitution")
			var basePathEnv []corev1.EnvVar
			for _, env := range frontend.Env {
				if env.Name == "OPENRAG_FRONTEND_BASE_PATH" {
					basePathEnv = append(basePathEnv, env)
				}
			}
			require.Len(t, basePathEnv, 1)
			assert.Equal(t, tc.basePath, basePathEnv[0].Value)
			require.NotNil(t, frontend.LivenessProbe.HTTPGet)
			assert.Equal(t, tc.probe, frontend.LivenessProbe.HTTPGet.Path)
			require.NotNil(t, frontend.ReadinessProbe.HTTPGet)
			assert.Equal(t, tc.probe, frontend.ReadinessProbe.HTTPGet.Path)
		})
	}
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
	assert.Contains(t, envContent, `LANGFLOW_URL=http://`+instanceResourceName(cr, "lf")+`:7860`)
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL=http://`+instanceResourceName(cr, "be")+`:8000`)
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

// TestReconcileDocling_DoesNotUpdateExistingPVC checks the operator skips (never
// updates) an already-bound docling PVC, for both the serve and worker paths. The
// interceptor rejects an immutable-field change like the real API server, so
// reconcile only succeeds if the PVC is skipped rather than updated.
func TestReconcileDocling_DoesNotUpdateExistingPVC(t *testing.T) {
	storage := func() *openragv1alpha1.PersistenceSpec {
		return &openragv1alpha1.PersistenceSpec{Enabled: true, Size: resource.MustParse("50Gi")}
	}
	tests := []struct {
		name      string
		role      string // suffix passed to instanceResourceName
		configure func(dc *openragv1alpha1.DoclingComponentsSpec)
	}{
		{
			name: "serve",
			role: "ds-data",
			configure: func(dc *openragv1alpha1.DoclingComponentsSpec) {
				dc.Serve = &openragv1alpha1.DoclingServeSpec{
					ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-serve:latest"},
					Storage:       storage(),
				}
			},
		},
		{
			name: "worker",
			role: "dw-data",
			configure: func(dc *openragv1alpha1.DoclingComponentsSpec) {
				dc.Worker = &openragv1alpha1.DoclingWorkerSpec{
					ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-worker:latest"},
					Storage:       storage(),
				}
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := newScheme(t)
			cr := minimalCR("openrag", "openrag-system")
			cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{Enabled: true}
			tc.configure(cr.Spec.DoclingComponents)

			// A PVC a prior reconcile created and the cluster has since bound: it has an
			// assigned volumeName and defaulted storageClassName, and no spec-hash annotation.
			boundClass := "standard"
			existingPVC := &corev1.PersistentVolumeClaim{
				ObjectMeta: metav1.ObjectMeta{
					Name:      instanceResourceName(cr, tc.role),
					Namespace: "openrag-system",
					Labels:    map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"},
				},
				Spec: corev1.PersistentVolumeClaimSpec{
					AccessModes:      []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
					StorageClassName: &boundClass,
					VolumeName:       "pvc-bound",
					Resources: corev1.VolumeResourceRequirements{
						Requests: corev1.ResourceList{corev1.ResourceStorage: resource.MustParse("50Gi")},
					},
				},
			}

			// Reject any Update that changes a bound PVC's volumeName, as the API server does.
			rejectImmutablePVC := interceptor.Funcs{
				Update: func(ctx context.Context, cl client.WithWatch, obj client.Object, opts ...client.UpdateOption) error {
					if pvc, ok := obj.(*corev1.PersistentVolumeClaim); ok {
						cur := &corev1.PersistentVolumeClaim{}
						if err := cl.Get(ctx, client.ObjectKeyFromObject(pvc), cur); err == nil &&
							cur.Spec.VolumeName != "" && pvc.Spec.VolumeName != cur.Spec.VolumeName {
							return errors.NewForbidden(corev1.Resource("persistentvolumeclaims"), pvc.Name,
								fmt.Errorf("spec is immutable after creation except resources.requests for bound claims"))
						}
					}
					return cl.Update(ctx, obj, opts...)
				},
			}

			c := fake.NewClientBuilder().WithScheme(s).
				WithObjects(cr, existingPVC).
				WithStatusSubresource(&openragv1alpha1.OpenRAG{}).
				WithInterceptorFuncs(rejectImmutablePVC).
				Build()
			r := NewOpenRAGReconciler(c, s)

			// Under the bug this issues the immutable Update and returns the forbidden error.
			require.NoError(t, r.reconcileDoclingComponents(context.Background(), cr, "openrag-system"))

			// The bound PVC is left intact.
			got := &corev1.PersistentVolumeClaim{}
			require.NoError(t, c.Get(context.Background(),
				types.NamespacedName{Name: instanceResourceName(cr, tc.role), Namespace: "openrag-system"}, got))
			assert.Equal(t, "pvc-bound", got.Spec.VolumeName)
		})
	}
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
	cr.Spec.Backend.PrometheusPort = 8000
	cr.Spec.Backend.PodAnnotations = map[string]string{
		"custom-annotation": "backend-value",
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
func TestReconcile_InstanceName_UsedInResourceNames(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("9a826efa-112d-4e2d-9f8d-ce103880ab41", "test-ns")
	cr.Spec.InstanceName = "prod"

	r, c := reconciler(s, cr)
	reconcileOnce(t, r, cr)

	dns1035Regex := `^[a-z]([-a-z0-9]*[a-z0-9])?$`

	for _, role := range []string{"fe", "be", "lf"} {
		name := instanceResourceName(cr, role)
		assert.Equal(t, "openrag-prod-"+role, name)
		assert.Regexp(t, dns1035Regex, name, "resource name for role %s must be DNS-1035 compliant", role)

		d := &appsv1.Deployment{}
		require.NoError(t, c.Get(context.Background(),
			types.NamespacedName{Name: name, Namespace: "test-ns"}, d))
	}
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
	assert.Contains(t, envContent, `LANGFLOW_URL=http://`+instanceResourceName(cr, "lf")+`:7860`,
		"Backend env should reference default langflow service")
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL=http://my-backend-svc:8000`,
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
	assert.Contains(t, envContent, `LANGFLOW_URL=http://custom-lf-svc:7860`,
		"Backend env should reference custom langflow service name")
	assert.Contains(t, envContent, `OPENRAG_BACKEND_INTERNAL_URL=http://`+instanceResourceName(cr, "be")+`:8000`,
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

// ---------------------------------------------------------------------------
// Image Drift Detection Tests
// ---------------------------------------------------------------------------

func TestHasDeploymentImageDrift(t *testing.T) {
	tests := []struct {
		name        string
		desired     *appsv1.Deployment
		existing    *appsv1.Deployment
		expectDrift bool
	}{
		{
			name:        "no drift - images match",
			desired:     createTestDeployment("langflowai/openrag-backend:v1.0.0"),
			existing:    createTestDeployment("langflowai/openrag-backend:v1.0.0"),
			expectDrift: false,
		},
		{
			name:        "drift - different tags",
			desired:     createTestDeployment("langflowai/openrag-backend:v1.0.0"),
			existing:    createTestDeployment("langflowai/openrag-backend:v0.9.0"),
			expectDrift: true,
		},
		{
			name:        "drift - completely different image",
			desired:     createTestDeployment("langflowai/openrag-backend:v1.0.0"),
			existing:    createTestDeployment("malicious/backdoor:latest"),
			expectDrift: true,
		},
		{
			name: "drift - second container differs",
			desired: &appsv1.Deployment{
				Spec: appsv1.DeploymentSpec{
					Template: corev1.PodTemplateSpec{
						Spec: corev1.PodSpec{
							Containers: []corev1.Container{
								{Name: "main", Image: "app:v1"},
								{Name: "sidecar", Image: "sidecar:v1"},
							},
						},
					},
				},
			},
			existing: &appsv1.Deployment{
				Spec: appsv1.DeploymentSpec{
					Template: corev1.PodTemplateSpec{
						Spec: corev1.PodSpec{
							Containers: []corev1.Container{
								{Name: "main", Image: "app:v1"},
								{Name: "sidecar", Image: "sidecar:v2"},
							},
						},
					},
				},
			},
			expectDrift: true,
		},
		{
			name: "drift - different container count",
			desired: &appsv1.Deployment{
				Spec: appsv1.DeploymentSpec{
					Template: corev1.PodTemplateSpec{
						Spec: corev1.PodSpec{
							Containers: []corev1.Container{
								{Name: "main", Image: "app:v1"},
								{Name: "sidecar", Image: "sidecar:v1"},
							},
						},
					},
				},
			},
			existing: &appsv1.Deployment{
				Spec: appsv1.DeploymentSpec{
					Template: corev1.PodTemplateSpec{
						Spec: corev1.PodSpec{
							Containers: []corev1.Container{
								{Name: "main", Image: "app:v1"},
							},
						},
					},
				},
			},
			expectDrift: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := hasDeploymentImageDrift(tt.desired, tt.existing)
			assert.Equal(t, tt.expectDrift, result)
		})
	}
}

// Helper function to create a test deployment with a single container
func createTestDeployment(image string) *appsv1.Deployment {
	return &appsv1.Deployment{
		Spec: appsv1.DeploymentSpec{
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{Name: "main", Image: image},
					},
				},
			},
		},
	}
}

// ---------------------------------------------------------------------------
// Image Drift Detection Tests
// ---------------------------------------------------------------------------

func TestReconcile_ImageDriftTriggersRevert(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("test-openrag", "test-ns")
	cr.Spec.Backend.Image = "langflowai/openrag-backend:v1.0.0"
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	backendDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, backendDeploy))
	assert.Equal(t, "langflowai/openrag-backend:v1.0.0", backendDeploy.Spec.Template.Spec.Containers[0].Image)

	// Simulate image drift
	backendDeploy.Spec.Template.Spec.Containers[0].Image = "malicious/backdoor:latest"
	require.NoError(t, c.Update(context.Background(), backendDeploy))

	driftedDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, driftedDeploy))
	assert.Equal(t, "malicious/backdoor:latest", driftedDeploy.Spec.Template.Spec.Containers[0].Image)

	// Reconcile should detect drift and revert
	reconcileOnce(t, r, cr)

	revertedDeploy := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "test-ns"}, revertedDeploy))
	assert.Equal(t, "langflowai/openrag-backend:v1.0.0", revertedDeploy.Spec.Template.Spec.Containers[0].Image)
}

// ---------------------------------------------------------------------------
// Init Container tests
// ---------------------------------------------------------------------------

func TestPodBuilders_AppendInitContainersAndSidecars(t *testing.T) {
	s := newScheme(t)
	r, _ := reconciler(s)

	userInit := corev1.Container{Name: "user-init", Image: "busybox:latest"}
	userSidecar := corev1.Container{Name: "user-sidecar", Image: "busybox:latest"}

	doclingCR := func() *openragv1alpha1.OpenRAG {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-serve:latest"}},
			Worker:  &openragv1alpha1.DoclingWorkerSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-worker:latest"}},
			Valkey:  &openragv1alpha1.ValkeySpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "valkey:latest"}},
		}
		return cr
	}

	cases := []struct {
		name         string
		expectedMain string // operator-managed main container name for this builder, guards against a builder reading the wrong component sub-spec.
		build        func() corev1.PodSpec
	}{
		{"frontend", "frontend", func() corev1.PodSpec {
			cr := minimalCR("x", "ns")
			cr.Spec.Frontend.InitContainers = []corev1.Container{userInit}
			cr.Spec.Frontend.Sidecars = []corev1.Container{userSidecar}
			return r.frontendDeployment(cr, "ns").Spec.Template.Spec
		}},
		{"backend", "backend", func() corev1.PodSpec {
			cr := minimalCR("x", "ns")
			cr.Spec.Backend.InitContainers = []corev1.Container{userInit}
			cr.Spec.Backend.Sidecars = []corev1.Container{userSidecar}
			return r.backendDeployment(cr, "ns", "hash").Spec.Template.Spec
		}},
		{"langflow", "langflow", func() corev1.PodSpec {
			cr := minimalCR("x", "ns")
			cr.Spec.Langflow.InitContainers = []corev1.Container{userInit}
			cr.Spec.Langflow.Sidecars = []corev1.Container{userSidecar}
			return r.langflowDeployment(cr, "ns", "hash").Spec.Template.Spec
		}},
		{"docling-serve", "docling-serve", func() corev1.PodSpec {
			cr := doclingCR()
			cr.Spec.DoclingComponents.Serve.InitContainers = []corev1.Container{userInit}
			cr.Spec.DoclingComponents.Serve.Sidecars = []corev1.Container{userSidecar}
			return r.doclingServeDeployment(cr, "ns").Spec.Template.Spec
		}},
		{"docling-worker", "docling-worker", func() corev1.PodSpec {
			cr := doclingCR()
			cr.Spec.DoclingComponents.Worker.InitContainers = []corev1.Container{userInit}
			cr.Spec.DoclingComponents.Worker.Sidecars = []corev1.Container{userSidecar}
			return r.doclingWorkerDeployment(cr, "ns").Spec.Template.Spec
		}},
		{"valkey", "valkey", func() corev1.PodSpec {
			cr := doclingCR()
			cr.Spec.DoclingComponents.Valkey.InitContainers = []corev1.Container{userInit}
			cr.Spec.DoclingComponents.Valkey.Sidecars = []corev1.Container{userSidecar}
			return r.valkeyStatefulSet(cr, "ns").Spec.Template.Spec
		}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ps := tc.build()

			require.NotEmpty(t, ps.Containers, "%s pod must have at least the main container", tc.name)
			assert.Equal(t, tc.expectedMain, ps.Containers[0].Name, "%s main container must remain first", tc.name)
			assert.Len(t, ps.Containers, 2, "%s pod should have exactly main + one sidecar", tc.name)
			assert.Len(t, ps.InitContainers, 1, "%s pod should have exactly the one user init container", tc.name)

			assert.True(t, containsContainer(ps.InitContainers, "user-init"), "%s pod should include the user init container", tc.name)
			assert.True(t, containsContainer(ps.Containers, "user-sidecar"), "%s pod should include the user sidecar", tc.name)

			assert.False(t, containsContainer(ps.Containers, "user-init"), "%s init container must not leak into Containers", tc.name)
			assert.False(t, containsContainer(ps.InitContainers, "user-sidecar"), "%s sidecar must not leak into InitContainers", tc.name)
		})
	}
}

func TestPodBuilders_AutomountServiceAccountTokenDefaults(t *testing.T) {
	s := newScheme(t)
	r, _ := reconciler(s)

	doclingCR := func() *openragv1alpha1.OpenRAG {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-serve:latest"}},
			Worker:  &openragv1alpha1.DoclingWorkerSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "docling-worker:latest"}},
			Valkey:  &openragv1alpha1.ValkeySpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "valkey:latest"}},
		}
		return cr
	}
	baseCR := func() *openragv1alpha1.OpenRAG { return minimalCR("x", "ns") }

	// Only the backend pod talks to the Kubernetes API, so it defaults to mounting
	// the SA token; every other pod defaults to not mounting it.
	cases := []struct {
		name        string
		wantDefault bool
		newCR       func() *openragv1alpha1.OpenRAG
		set         func(cr *openragv1alpha1.OpenRAG, v *bool)
		build       func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec
	}{
		{"frontend", false, baseCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) { cr.Spec.Frontend.AutomountServiceAccountToken = v },
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.frontendDeployment(cr, "ns").Spec.Template.Spec
			}},
		{"backend", true, baseCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) { cr.Spec.Backend.AutomountServiceAccountToken = v },
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.backendDeployment(cr, "ns", "hash").Spec.Template.Spec
			}},
		{"langflow", false, baseCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) { cr.Spec.Langflow.AutomountServiceAccountToken = v },
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.langflowDeployment(cr, "ns", "hash").Spec.Template.Spec
			}},
		{"docling-serve", false, doclingCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) {
				cr.Spec.DoclingComponents.Serve.AutomountServiceAccountToken = v
			},
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.doclingServeDeployment(cr, "ns").Spec.Template.Spec
			}},
		{"docling-worker", false, doclingCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) {
				cr.Spec.DoclingComponents.Worker.AutomountServiceAccountToken = v
			},
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.doclingWorkerDeployment(cr, "ns").Spec.Template.Spec
			}},
		{"valkey", false, doclingCR,
			func(cr *openragv1alpha1.OpenRAG, v *bool) {
				cr.Spec.DoclingComponents.Valkey.AutomountServiceAccountToken = v
			},
			func(cr *openragv1alpha1.OpenRAG) corev1.PodSpec {
				return r.valkeyStatefulSet(cr, "ns").Spec.Template.Spec
			}},
	}

	for _, tc := range cases {
		t.Run(tc.name+"/default", func(t *testing.T) {
			ps := tc.build(tc.newCR())
			require.NotNil(t, ps.AutomountServiceAccountToken, "%s should set an explicit automount default", tc.name)
			assert.Equal(t, tc.wantDefault, *ps.AutomountServiceAccountToken, "%s default mismatch", tc.name)
		})
		t.Run(tc.name+"/override", func(t *testing.T) {
			override := !tc.wantDefault
			cr := tc.newCR()
			tc.set(cr, &override)
			ps := tc.build(cr)
			require.NotNil(t, ps.AutomountServiceAccountToken, "%s override should be honored", tc.name)
			assert.Equal(t, override, *ps.AutomountServiceAccountToken, "%s override mismatch", tc.name)
		})
	}
}

func containsContainer(cs []corev1.Container, name string) bool {
	for _, c := range cs {
		if c.Name == name {
			return true
		}
	}

	return false
}

func TestDeploymentRolledOut(t *testing.T) {
	replicas := func(n int32) *int32 { return &n }
	cases := []struct {
		name string
		dep  *appsv1.Deployment
		want bool
	}{
		{
			name: "new revision fully available",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 3},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(2)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 3, Replicas: 2, UpdatedReplicas: 2, AvailableReplicas: 2},
			},
			want: true,
		},
		{
			name: "spec update not yet observed",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 4},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(1)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 3, Replicas: 1, UpdatedReplicas: 1, AvailableReplicas: 1},
			},
			want: false,
		},
		{
			name: "new-revision replicas not all created",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 2},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(3)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 2, Replicas: 3, UpdatedReplicas: 1, AvailableReplicas: 1},
			},
			want: false,
		},
		{
			name: "old-revision replicas still terminating",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 2},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(2)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 2, Replicas: 3, UpdatedReplicas: 2, AvailableReplicas: 2},
			},
			want: false,
		},
		{
			name: "new revision created but not yet available (readiness probe failing)",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 2},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(2)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 2, Replicas: 2, UpdatedReplicas: 2, AvailableReplicas: 1},
			},
			want: false,
		},
		{
			name: "scaled to zero is considered rolled out",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 5},
				Spec:       appsv1.DeploymentSpec{Replicas: replicas(0)},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 5},
			},
			want: true,
		},
		{
			name: "nil replicas defaults to one desired",
			dep: &appsv1.Deployment{
				ObjectMeta: metav1.ObjectMeta{Generation: 1},
				Status:     appsv1.DeploymentStatus{ObservedGeneration: 1, Replicas: 1, UpdatedReplicas: 1, AvailableReplicas: 1},
			},
			want: true,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.want, deploymentRolledOut(tc.dep))
		})
	}
}

// --------------------------------------------------------------------------
// docling-serve RQ proxy env var tests
// --------------------------------------------------------------------------

// envVarMap converts a container's Env slice into a name→value map for
// convenient lookup in assertions. Values resolved via ValueFrom are stored
// as "<secretRef:name/key>" or "<configMapRef:name/key>" strings so tests can
// still assert on their presence and source.
func envVarMap(envVars []corev1.EnvVar) map[string]string {
	m := make(map[string]string, len(envVars))
	for _, e := range envVars {
		if e.ValueFrom != nil {
			if e.ValueFrom.SecretKeyRef != nil {
				m[e.Name] = fmt.Sprintf("<secretRef:%s/%s>", e.ValueFrom.SecretKeyRef.Name, e.ValueFrom.SecretKeyRef.Key)
			} else {
				m[e.Name] = "<valueFrom>"
			}
		} else {
			m[e.Name] = e.Value
		}
	}
	return m
}

func TestDoclingServeDeployment_RQEngineEnvVars(t *testing.T) {
	s := newScheme(t)
	r, _ := reconciler(s)

	// Helper: build a CR with both serve + valkey (triggers RQ auto-inference)
	crWithValkey := func() *openragv1alpha1.OpenRAG {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ds:latest"}},
			Valkey: &openragv1alpha1.ValkeySpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "valkey:latest"},
			},
		}
		return cr
	}

	t.Run("auto-infers rq when valkey present", func(t *testing.T) {
		cr := crWithValkey()
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)

		assert.Equal(t, "rq", env["DOCLING_SERVE_ENG_KIND"])
		assert.Equal(t, "false", env["DOCLING_INFERENCE_COMPILE_TORCH_MODELS"])
		assert.Contains(t, env, "DOCLING_SERVE_ENG_RQ_REDIS_URL")
		assert.Contains(t, env, "DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX")
		assert.Contains(t, env, "DOCLING_SERVE_ENG_RQ_SUB_CHANNEL")
		assert.Contains(t, env, "DOCLING_SERVE_ENG_RQ_RESULTS_TTL")
	})

	t.Run("auto-infers rq when worker present", func(t *testing.T) {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ds:latest"}},
			Worker:  &openragv1alpha1.DoclingWorkerSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "dw:latest"}},
		}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "rq", env["DOCLING_SERVE_ENG_KIND"])
	})

	t.Run("defaults to local when only serve present", func(t *testing.T) {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ds:latest"}},
		}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "local", env["DOCLING_SERVE_ENG_KIND"])
		assert.Equal(t, "false", env["DOCLING_INFERENCE_COMPILE_TORCH_MODELS"])
		assert.NotContains(t, env, "DOCLING_SERVE_ENG_RQ_REDIS_URL")
	})

	t.Run("explicit engine kind overrides inference", func(t *testing.T) {
		cr := crWithValkey()
		kind := openragv1alpha1.DoclingEngineLocal
		cr.Spec.DoclingComponents.Serve.Engine = &openragv1alpha1.DoclingServeEngineSpec{Kind: kind}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "local", env["DOCLING_SERVE_ENG_KIND"])
	})

	t.Run("redis url derived from operator-managed valkey (no password)", func(t *testing.T) {
		cr := crWithValkey()
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		// CR has no InstanceName → legacy name "openrag-valkey", FQDN form
		assert.Equal(t, "redis://openrag-valkey.ns.svc.cluster.local:6379/0", env["DOCLING_SERVE_ENG_RQ_REDIS_URL"])
	})

	t.Run("redis url from valkey with inline password", func(t *testing.T) {
		cr := crWithValkey()
		cr.Spec.DoclingComponents.Valkey.Password = "s3cr3t"
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "redis://:s3cr3t@openrag-valkey.ns.svc.cluster.local:6379/0", env["DOCLING_SERVE_ENG_RQ_REDIS_URL"])
	})

	t.Run("redis url from valkey with password secret uses env-var interpolation", func(t *testing.T) {
		cr := crWithValkey()
		cr.Spec.DoclingComponents.Valkey.PasswordSecret = &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: "valkey-secret"},
			Key:                  "VALKEY_PASSWORD",
		}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "redis://:$(VALKEY_PASSWORD)@openrag-valkey.ns.svc.cluster.local:6379/0", env["DOCLING_SERVE_ENG_RQ_REDIS_URL"])
		// The VALKEY_PASSWORD env var must be emitted before the URL that references it
		names := make([]string, 0, len(dep.Spec.Template.Spec.Containers[0].Env))
		for _, e := range dep.Spec.Template.Spec.Containers[0].Env {
			names = append(names, e.Name)
		}
		passwordIdx, urlIdx := -1, -1
		for i, n := range names {
			switch n {
			case "VALKEY_PASSWORD":
				passwordIdx = i
			case "DOCLING_SERVE_ENG_RQ_REDIS_URL":
				urlIdx = i
			}
		}
		require.NotEqual(t, -1, passwordIdx, "VALKEY_PASSWORD must be present")
		require.NotEqual(t, -1, urlIdx, "DOCLING_SERVE_ENG_RQ_REDIS_URL must be present")
		assert.Less(t, passwordIdx, urlIdx, "VALKEY_PASSWORD must appear before DOCLING_SERVE_ENG_RQ_REDIS_URL")
	})

	t.Run("custom rq settings from spec", func(t *testing.T) {
		cr := crWithValkey()
		ttl := int32(7200)
		cr.Spec.DoclingComponents.Serve.Engine = &openragv1alpha1.DoclingServeEngineSpec{
			Kind: openragv1alpha1.DoclingEngineRQ,
			RQ: &openragv1alpha1.DoclingRQEngineSpec{
				ResultsPrefix: "my:prefix",
				SubChannel:    "my:channel",
				ResultsTTL:    &ttl,
			},
		}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "my:prefix", env["DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX"])
		assert.Equal(t, "my:channel", env["DOCLING_SERVE_ENG_RQ_SUB_CHANNEL"])
		assert.Equal(t, "7200", env["DOCLING_SERVE_ENG_RQ_RESULTS_TTL"])
	})

	t.Run("default rq settings when unset", func(t *testing.T) {
		cr := crWithValkey()
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "docling:results", env["DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX"])
		assert.Equal(t, "docling:updates", env["DOCLING_SERVE_ENG_RQ_SUB_CHANNEL"])
		assert.Equal(t, "14400", env["DOCLING_SERVE_ENG_RQ_RESULTS_TTL"])
	})

	t.Run("performance env vars present with defaults", func(t *testing.T) {
		cr := crWithValkey()
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "4", env["DOCLING_NUM_THREADS"])
		assert.Equal(t, "4", env["DOCLING_PERF_PAGE_BATCH_SIZE"])
		assert.Equal(t, "16", env["DOCLING_PERF_ELEMENTS_BATCH_SIZE"])
	})

	t.Run("custom performance env vars", func(t *testing.T) {
		cr := crWithValkey()
		threads := int32(8)
		pages := int32(2)
		elems := int32(32)
		cr.Spec.DoclingComponents.Serve.Performance = &openragv1alpha1.DoclingServePerformanceSpec{
			NumThreads:        &threads,
			PageBatchSize:     &pages,
			ElementsBatchSize: &elems,
		}
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "8", env["DOCLING_NUM_THREADS"])
		assert.Equal(t, "2", env["DOCLING_PERF_PAGE_BATCH_SIZE"])
		assert.Equal(t, "32", env["DOCLING_PERF_ELEMENTS_BATCH_SIZE"])
	})

	t.Run("feature flags default to true", func(t *testing.T) {
		cr := crWithValkey()
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "true", env["DOCLING_SERVE_ENABLE_UI"])
		assert.Equal(t, "true", env["DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG"])
		assert.Equal(t, "true", env["DOCLING_SERVE_ENABLE_REMOTE_SERVICES"])
	})

	t.Run("feature flags overridable", func(t *testing.T) {
		cr := crWithValkey()
		f := false
		cr.Spec.DoclingComponents.Serve.EnableUI = &f
		cr.Spec.DoclingComponents.Serve.AllowCustomVlmConfig = &f
		cr.Spec.DoclingComponents.Serve.EnableRemoteServices = &f
		dep := r.doclingServeDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "false", env["DOCLING_SERVE_ENABLE_UI"])
		assert.Equal(t, "false", env["DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG"])
		assert.Equal(t, "false", env["DOCLING_SERVE_ENABLE_REMOTE_SERVICES"])
	})
}

func TestDoclingWorkerDeployment_RQEnvVars(t *testing.T) {
	s := newScheme(t)
	r, _ := reconciler(s)

	crWithValkey := func() *openragv1alpha1.OpenRAG {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ds:latest"}},
			Worker:  &openragv1alpha1.DoclingWorkerSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "dw:latest"}},
			Valkey: &openragv1alpha1.ValkeySpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "valkey:latest"},
			},
		}
		return cr
	}

	t.Run("defaults command to docling-serve rq-worker when spec.Command is nil", func(t *testing.T) {
		dep := r.doclingWorkerDeployment(crWithValkey(), "ns")
		assert.Equal(t, []string{"docling-serve", "rq-worker"}, dep.Spec.Template.Spec.Containers[0].Command)
	})

	t.Run("explicit spec.Command overrides the default rq-worker command", func(t *testing.T) {
		cr := crWithValkey()
		cr.Spec.DoclingComponents.Worker.Command = []string{"/custom/entrypoint", "--flag"}
		dep := r.doclingWorkerDeployment(cr, "ns")
		assert.Equal(t, []string{"/custom/entrypoint", "--flag"}, dep.Spec.Template.Spec.Containers[0].Command)
	})

	t.Run("always sets DOCLING_SERVE_ENG_KIND=rq", func(t *testing.T) {
		dep := r.doclingWorkerDeployment(crWithValkey(), "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "rq", env["DOCLING_SERVE_ENG_KIND"])
		assert.Equal(t, "false", env["DOCLING_INFERENCE_COMPILE_TORCH_MODELS"])
	})

	t.Run("emits DOCLING_SERVE_ENG_RQ_REDIS_URL alongside QUEUE_URL", func(t *testing.T) {
		dep := r.doclingWorkerDeployment(crWithValkey(), "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Contains(t, env, "DOCLING_SERVE_ENG_RQ_REDIS_URL")
		assert.Contains(t, env, "QUEUE_URL")
		assert.Equal(t, env["DOCLING_SERVE_ENG_RQ_REDIS_URL"], env["QUEUE_URL"])
	})

	t.Run("emits rq results/channel/ttl defaults", func(t *testing.T) {
		dep := r.doclingWorkerDeployment(crWithValkey(), "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "docling:results", env["DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX"])
		assert.Equal(t, "docling:updates", env["DOCLING_SERVE_ENG_RQ_SUB_CHANNEL"])
		assert.Equal(t, "14400", env["DOCLING_SERVE_ENG_RQ_RESULTS_TTL"])
	})

	t.Run("inherits rq settings from serve Engine.RQ spec", func(t *testing.T) {
		cr := crWithValkey()
		ttl := int32(3600)
		cr.Spec.DoclingComponents.Serve.Engine = &openragv1alpha1.DoclingServeEngineSpec{
			Kind: openragv1alpha1.DoclingEngineRQ,
			RQ: &openragv1alpha1.DoclingRQEngineSpec{
				ResultsPrefix: "custom:prefix",
				SubChannel:    "custom:channel",
				ResultsTTL:    &ttl,
			},
		}
		dep := r.doclingWorkerDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "custom:prefix", env["DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX"])
		assert.Equal(t, "custom:channel", env["DOCLING_SERVE_ENG_RQ_SUB_CHANNEL"])
		assert.Equal(t, "3600", env["DOCLING_SERVE_ENG_RQ_RESULTS_TTL"])
	})

	t.Run("performance vars inherited from serve spec", func(t *testing.T) {
		cr := crWithValkey()
		threads := int32(6)
		cr.Spec.DoclingComponents.Serve.Performance = &openragv1alpha1.DoclingServePerformanceSpec{
			NumThreads: &threads,
		}
		dep := r.doclingWorkerDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "6", env["DOCLING_NUM_THREADS"])
	})

	t.Run("QueueURL fallback also sets DOCLING_SERVE_ENG_RQ_REDIS_URL", func(t *testing.T) {
		cr := minimalCR("x", "ns")
		cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
			Enabled: true,
			Serve:   &openragv1alpha1.DoclingServeSpec{ComponentSpec: openragv1alpha1.ComponentSpec{Image: "ds:latest"}},
			Worker: &openragv1alpha1.DoclingWorkerSpec{
				ComponentSpec: openragv1alpha1.ComponentSpec{Image: "dw:latest"},
				QueueURL:      "redis://external-redis:6379/0",
			},
		}
		dep := r.doclingWorkerDeployment(cr, "ns")
		env := envVarMap(dep.Spec.Template.Spec.Containers[0].Env)
		assert.Equal(t, "redis://external-redis:6379/0", env["DOCLING_SERVE_ENG_RQ_REDIS_URL"])
		assert.Equal(t, "redis://external-redis:6379/0", env["QUEUE_URL"])
	})
}

func TestValkeyConfigMap_ProtectedMode(t *testing.T) {
	s := newScheme(t)
	r, _ := reconciler(s)

	valkeySpec := func(pm *bool) *openragv1alpha1.ValkeySpec {
		spec := &openragv1alpha1.ValkeySpec{
			ComponentSpec: openragv1alpha1.ComponentSpec{Image: "valkey:7.2"},
		}
		spec.ProtectedMode = pm
		return spec
	}

	cases := []struct {
		name          string
		protectedMode *bool
		wantInConf    string
	}{
		{
			name:          "default (nil) is off — safe for in-cluster use without password",
			protectedMode: nil,
			wantInConf:    "protected-mode no",
		},
		{
			name:          "explicit false stays off",
			protectedMode: func() *bool { v := false; return &v }(),
			wantInConf:    "protected-mode no",
		},
		{
			name:          "explicit true enables protection",
			protectedMode: func() *bool { v := true; return &v }(),
			wantInConf:    "protected-mode yes",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cr := minimalCR("x", "ns")
			cr.Spec.DoclingComponents = &openragv1alpha1.DoclingComponentsSpec{
				Enabled: true,
				Valkey:  valkeySpec(tc.protectedMode),
			}
			conf := r.valkeyConfigMap(cr, "ns").Data["valkey.conf"]
			assert.Contains(t, conf, tc.wantInConf)
			// Ensure only one protected-mode line exists
			assert.Equal(t, 1, strings.Count(conf, "protected-mode "),
				"valkey.conf must have exactly one protected-mode directive")
		})
	}
}
