package controller

import (
	"context"
	"fmt"
	"time"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

// updateStatusSuccess updates the status to indicate successful reconciliation
// Phase is set to "Reconciled" initially, then updated to "Running" if backend pod is ready
func (r *OpenRAGReconciler) updateStatusSuccess(ctx context.Context, instance *openragv1alpha1.OpenRAG, targetNS string) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	scaledDown := ((instance.Spec.Backend.Replicas != nil && *instance.Spec.Backend.Replicas == 0) &&
		(instance.Spec.Frontend.Replicas != nil && *instance.Spec.Frontend.Replicas == 0) &&
		(instance.Spec.Langflow.Replicas != nil && *instance.Spec.Langflow.Replicas == 0))

	// Update backend condition first
	backendConditionStatus, err := r.updateBackendCondition(ctx, instance, targetNS)
	if err != nil {
		logger.Error(err, "failed to update backend condition")
		// Continue anyway, don't fail reconciliation
	}

	// Determine phase based on scale state and backend readiness
	phase := phaseReconciled
	message := "All resources reconciled successfully, waiting for backend pod to be ready"
	if scaledDown {
		if backendConditionStatus == metav1.ConditionTrue {
			// Desired state is scaled down and backend is healthy (scaled to 0), treat as running
			phase = phaseScaledDown
			message = "All components scaled to 0 replicas"
		} else {
			// Desired state is scaled down but backend condition is not true, treat as scaled down but not ready
			message = "Scaling down all components to 0 replicas (in progress)"
		}
	} else if backendConditionStatus == metav1.ConditionTrue {
		phase = phaseRunning
		message = "All resources reconciled successfully and backend is running"
	}

	instance.Status.Phase = phase
	instance.Status.Message = message
	instance.Status.ObservedGeneration = instance.Generation

	if err := r.Status().Update(ctx, instance); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to update status: %w", err)
	}

	// Requeue after 1 minute to check backend pod status
	return ctrl.Result{RequeueAfter: 1 * time.Minute}, nil
}

// updateStatusError updates the status to indicate reconciliation failure and schedules retry after 5 minutes
func (r *OpenRAGReconciler) updateStatusError(ctx context.Context, instance *openragv1alpha1.OpenRAG, component string, reconcileErr error) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	instance.Status.Phase = phaseError
	instance.Status.Message = fmt.Sprintf("Failed to reconcile %s: %s", component, reconcileErr.Error())
	instance.Status.ObservedGeneration = instance.Generation

	if err := r.Status().Update(ctx, instance); err != nil {
		logger.Error(err, "failed to update status after error", "component", component, "reconcileError", reconcileErr.Error())
		// Return original error even if status update fails
		return ctrl.Result{}, reconcileErr
	}

	logger.Error(reconcileErr, "reconciliation failed, will retry in 5 minutes", "component", component)

	// Requeue after 5 minutes on failure
	return ctrl.Result{RequeueAfter: 5 * time.Minute}, nil
}

// updateBackendCondition checks the backend deployment pod status and updates the BackendReady condition
func (r *OpenRAGReconciler) updateBackendCondition(ctx context.Context, instance *openragv1alpha1.OpenRAG, targetNS string) (metav1.ConditionStatus, error) {
	logger := log.FromContext(ctx)

	deployment := &appsv1.Deployment{}
	err := r.Get(ctx, client.ObjectKey{
		Name:      instanceResourceName(instance, "be"),
		Namespace: targetNS,
	}, deployment)

	if err != nil {
		if errors.IsNotFound(err) {
			// Backend deployment doesn't exist yet
			meta.SetStatusCondition(&instance.Status.Conditions, metav1.Condition{
				Type:               conditionBackendReady,
				Status:             metav1.ConditionUnknown,
				Reason:             "DeploymentNotFound",
				Message:            "Backend deployment not found",
				ObservedGeneration: instance.Generation,
			})
			logger.Info("Backend deployment not found", "deployment", instanceResourceName(instance, "be"))
			return metav1.ConditionUnknown, nil
		}
		return metav1.ConditionUnknown, fmt.Errorf("failed to get backend deployment: %w", err)
	}

	// Backend intentionally scaled to 0 — desired state, treat as healthy
	if instance.Spec.Backend.Replicas != nil && *instance.Spec.Backend.Replicas == 0 {
		if deployment.Status.Replicas == 0 {
			meta.SetStatusCondition(&instance.Status.Conditions, metav1.Condition{
				Type:               conditionBackendReady,
				Status:             metav1.ConditionTrue,
				Reason:             "ScaledDown",
				Message:            "Backend is scaled to 0 replicas",
				ObservedGeneration: instance.Generation,
			})
			return metav1.ConditionTrue, nil
		} else {
			meta.SetStatusCondition(&instance.Status.Conditions, metav1.Condition{
				Type:               conditionBackendReady,
				Status:             metav1.ConditionFalse,
				Reason:             "ScaledDownNotReady",
				Message:            "Backend is scaled to 0 replicas but deployment has non-zero replicas",
				ObservedGeneration: instance.Generation,
			})
			logger.Info("Backend scaled to 0 but deployment has non-zero replicas", "desiredReplicas", *instance.Spec.Backend.Replicas, "deploymentReplicas", deployment.Status.Replicas)
			return metav1.ConditionFalse, nil
		}
	}

	reportedStatus := metav1.ConditionFalse
	// Check if backend pod is ready (single replica)
	if deployment.Status.ReadyReplicas > 0 && deployment.Status.ReadyReplicas == deployment.Status.Replicas {
		meta.SetStatusCondition(&instance.Status.Conditions, metav1.Condition{
			Type:               conditionBackendReady,
			Status:             metav1.ConditionTrue,
			Reason:             "PodRunning",
			Message:            "Backend pod is running and ready",
			ObservedGeneration: instance.Generation,
		})
		reportedStatus = metav1.ConditionTrue
		logger.Info("Backend pod is ready", "readyReplicas", deployment.Status.ReadyReplicas)
	} else {
		meta.SetStatusCondition(&instance.Status.Conditions, metav1.Condition{
			Type:               conditionBackendReady,
			Status:             metav1.ConditionFalse,
			Reason:             "PodNotReady",
			Message:            fmt.Sprintf("Backend pod not ready (ready: %d, desired: %d)", deployment.Status.ReadyReplicas, deployment.Status.Replicas),
			ObservedGeneration: instance.Generation,
		})
		logger.Info("Backend pod not ready", "readyReplicas", deployment.Status.ReadyReplicas, "desiredReplicas", deployment.Status.Replicas)
	}

	return reportedStatus, nil
}
