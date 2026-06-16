package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

func (r *OpenRAGReconciler) handleDeletion(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	logger := log.FromContext(ctx)
	logger.Info("handleDeletion called", "name", o.Name, "namespace", o.Namespace)

	hasFinalizer := controllerutil.ContainsFinalizer(o, finalizer)
	logger.Info("checking for finalizer", "finalizer", finalizer, "hasFinalizer", hasFinalizer, "allFinalizers", o.Finalizers)

	if !hasFinalizer {
		logger.Info("CR has no finalizer - nothing to clean up, returning")
		return nil
	}

	logger.Info("CR has finalizer - proceeding with cleanup")

	targetNS := targetNamespace(o)
	logger.Info("starting secret cleanup", "targetNamespace", targetNS)

	// Remove finalizers from .env secrets and delete them
	for _, envSecretName := range []string{instanceResourceName(o, "be-env"), instanceResourceName(o, "lf-env")} {
		logger.Info("processing .env secret", "name", envSecretName, "namespace", targetNS)
		envSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: envSecretName, Namespace: targetNS}, envSecret)
		if err == nil {
			logger.Info("found .env secret", "name", envSecretName, "finalizers", envSecret.Finalizers)
			// Remove finalizer first
			if controllerutil.ContainsFinalizer(envSecret, envSecretFinalizer) {
				logger.Info("removing finalizer from .env secret", "name", envSecretName, "finalizer", envSecretFinalizer)
				controllerutil.RemoveFinalizer(envSecret, envSecretFinalizer)
				if err := r.Update(ctx, envSecret); err != nil {
					logger.Error(err, "failed to remove finalizer from env secret", "name", envSecretName)
					return fmt.Errorf("failed to remove finalizer from env secret %s: %w", envSecretName, err)
				}
				logger.Info("successfully removed finalizer from .env secret", "name", envSecretName)
			} else {
				logger.Info(".env secret has no finalizer to remove", "name", envSecretName)
			}

			// Only explicitly delete secrets in cross-namespace case (owner refs don't work across namespaces)
			// In same namespace, owner references will automatically delete the secret when CR is deleted
			if targetNS != o.Namespace {
				logger.Info("deleting .env secret (cross-namespace deployment)", "name", envSecretName)
				if err := r.Delete(ctx, envSecret); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete env secret", "name", envSecretName)
					return fmt.Errorf("failed to delete env secret %s: %w", envSecretName, err)
				}
				logger.Info("successfully deleted .env secret", "name", envSecretName)
			} else {
				logger.Info(".env secret will be automatically deleted by Kubernetes garbage collection via owner reference", "name", envSecretName)
			}
		} else if !errors.IsNotFound(err) {
			logger.Error(err, "failed to get env secret", "name", envSecretName)
			return fmt.Errorf("failed to get env secret %s: %w", envSecretName, err)
		} else {
			logger.Info(".env secret not found - already deleted or never created", "name", envSecretName)
		}
	}

	// Remove finalizers from user-provided secrets so they can be deleted
	userSecretRefs := collectProtectedSecrets(o)
	for _, secretRef := range userSecretRefs {
		userSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: secretRef.Name, Namespace: targetNS}, userSecret)
		if err == nil {
			if controllerutil.ContainsFinalizer(userSecret, userSecretFinalizer) {
				controllerutil.RemoveFinalizer(userSecret, userSecretFinalizer)
				if err := r.Update(ctx, userSecret); err != nil {
					return fmt.Errorf("failed to remove finalizer from user secret %s: %w", secretRef.Name, err)
				}
				logger.Info("removed finalizer from user-supplied secret", "secret", secretRef.Name, "namespace", targetNS, "finalizer", userSecretFinalizer)
			}
		} else if !errors.IsNotFound(err) {
			return fmt.Errorf("failed to get user secret %s: %w", secretRef.Name, err)
		}
	}

	// Remove finalizers from auto-generated default secrets and delete them
	// Use DNS-compliant names (lowercase, hyphens instead of underscores)
	// These names must match getOrGenerateSecret() logic: o.Name + "-" + strings.ToLower(strings.ReplaceAll(envKeyName, "_", "-")) + "-default"
	defaultSecretNames := []string{
		o.Name + "-openrag-encryption-key-default", // OPENRAG_ENCRYPTION_KEY
		o.Name + "-jwt-signing-key-default",        // JWT_SIGNING_KEY (not jwt-private-key!)
		o.Name + "-langflow-secret-key-default",    // LANGFLOW_SECRET_KEY
	}
	logger.Info("processing default secrets", "count", len(defaultSecretNames))
	for _, secretName := range defaultSecretNames {
		logger.Info("processing default secret", "name", secretName, "namespace", targetNS)
		defaultSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: secretName, Namespace: targetNS}, defaultSecret)
		if err == nil {
			logger.Info("found default secret", "name", secretName, "finalizers", defaultSecret.Finalizers)
			// Remove finalizer first
			if controllerutil.ContainsFinalizer(defaultSecret, userSecretFinalizer) {
				logger.Info("removing finalizer from default secret", "name", secretName, "finalizer", userSecretFinalizer)
				controllerutil.RemoveFinalizer(defaultSecret, userSecretFinalizer)
				if err := r.Update(ctx, defaultSecret); err != nil {
					logger.Error(err, "failed to remove finalizer from default secret", "name", secretName)
					return fmt.Errorf("failed to remove finalizer from default secret %s: %w", secretName, err)
				}
				logger.Info("successfully removed finalizer from default secret", "name", secretName)
			} else {
				logger.Info("default secret has no finalizer to remove", "name", secretName)
			}

			// Only explicitly delete secrets in cross-namespace case (owner refs don't work across namespaces)
			// In same namespace, owner references will automatically delete the secret when CR is deleted
			if targetNS != o.Namespace {
				logger.Info("deleting default secret (cross-namespace deployment)", "name", secretName)
				if err := r.Delete(ctx, defaultSecret); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete default secret", "name", secretName)
					return fmt.Errorf("failed to delete default secret %s: %w", secretName, err)
				}
				logger.Info("successfully deleted default secret", "name", secretName)
			} else {
				logger.Info("default secret will be automatically deleted by Kubernetes garbage collection via owner reference", "name", secretName)
			}
		} else if !errors.IsNotFound(err) {
			logger.Error(err, "failed to get default secret", "name", secretName)
			return fmt.Errorf("failed to get default secret %s: %w", secretName, err)
		} else {
			logger.Info("default secret not found - already deleted or never created", "name", secretName)
		}
	}

	// If targetNamespace is different from CR namespace, we need to clean up resources
	// We can only delete the namespace if WE created it (has managedByLabel)
	// Otherwise, we must delete resources individually
	if targetNS != o.Namespace {
		ns := &corev1.Namespace{}
		err := r.Get(ctx, client.ObjectKey{Name: targetNS}, ns)
		if err != nil && !errors.IsNotFound(err) {
			return err
		}

		// Check if we created this namespace
		if err == nil && ns.Labels[managedByLabel] == o.Name {
			// We created it, safe to delete the entire namespace
			if err := r.Delete(ctx, ns); err != nil && !errors.IsNotFound(err) {
				return err
			}
		} else {
			// Namespace exists but we didn't create it (user-provided)
			// Must delete resources individually to avoid orphans
			if err := r.deleteResources(ctx, o, targetNS); err != nil {
				return fmt.Errorf("failed to delete resources in namespace %s: %w", targetNS, err)
			}
		}
	}
	// If same namespace, owner references handle cleanup automatically

	// remove the CR finalizer
	controllerutil.RemoveFinalizer(o, finalizer)
	return r.Update(ctx, o)
}

// deleteResources explicitly deletes all resources created by the operator in the target namespace
// This is necessary when deploying to an existing namespace that we don't manage
func (r *OpenRAGReconciler) deleteResources(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	logger := log.FromContext(ctx)

	// Delete .env secrets with finalizers first
	for _, envSecretName := range []string{instanceResourceName(o, "be-env"), instanceResourceName(o, "lf-env")} {
		envSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: envSecretName, Namespace: targetNS}, envSecret)
		if err == nil {
			// Remove finalizer first
			if controllerutil.ContainsFinalizer(envSecret, envSecretFinalizer) {
				controllerutil.RemoveFinalizer(envSecret, envSecretFinalizer)
				if err := r.Update(ctx, envSecret); err != nil {
					logger.Error(err, "failed to remove finalizer from env secret", "name", envSecretName)
				} else {
					logger.Info("Removed finalizer from .env secret", "name", envSecretName, "finalizer", envSecretFinalizer)
				}
			}
			// Then delete the secret
			if err := r.Delete(ctx, envSecret); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete env secret", "name", envSecretName)
			} else {
				logger.Info("Deleted .env secret", "name", envSecretName)
			}
		}
	}

	// Delete auto-generated default secrets with finalizers
	// These names must match getOrGenerateSecret() logic: o.Name + "-" + strings.ToLower(strings.ReplaceAll(envKeyName, "_", "-")) + "-default"
	defaultSecretNames := []string{
		o.Name + "-openrag-encryption-key-default", // OPENRAG_ENCRYPTION_KEY
		o.Name + "-jwt-signing-key-default",        // JWT_SIGNING_KEY (not jwt-private-key!)
		o.Name + "-langflow-secret-key-default",    // LANGFLOW_SECRET_KEY
	}
	for _, secretName := range defaultSecretNames {
		defaultSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: secretName, Namespace: targetNS}, defaultSecret)
		if err == nil {
			// Remove finalizer first
			if controllerutil.ContainsFinalizer(defaultSecret, userSecretFinalizer) {
				controllerutil.RemoveFinalizer(defaultSecret, userSecretFinalizer)
				if err := r.Update(ctx, defaultSecret); err != nil {
					logger.Error(err, "failed to remove finalizer from default secret", "name", secretName)
				} else {
					logger.Info("Removed finalizer from default secret", "name", secretName, "finalizer", userSecretFinalizer)
				}
			}
			// Then delete the secret
			if err := r.Delete(ctx, defaultSecret); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete default secret", "name", secretName)
			} else {
				logger.Info("Deleted default secret", "name", secretName)
			}
		}
	}

	// Remove finalizers from user-supplied secrets (but don't delete them)
	userSecretRefs := collectProtectedSecrets(o)
	for _, secretRef := range userSecretRefs {
		userSecret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{Name: secretRef.Name, Namespace: targetNS}, userSecret)
		if err == nil {
			if controllerutil.ContainsFinalizer(userSecret, userSecretFinalizer) {
				controllerutil.RemoveFinalizer(userSecret, userSecretFinalizer)
				if err := r.Update(ctx, userSecret); err != nil {
					logger.Error(err, "failed to remove finalizer from user secret", "name", secretRef.Name)
				} else {
					logger.Info("Removed finalizer from user-supplied secret", "secret", secretRef.Name, "finalizer", userSecretFinalizer)
				}
			}
		}
	}

	// Delete deployments
	for _, name := range []string{instanceResourceName(o, "fe"), instanceResourceName(o, "be"), instanceResourceName(o, "lf")} {
		deployment := &appsv1.Deployment{}
		err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, deployment)
		if err == nil {
			if err := r.Delete(ctx, deployment); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete deployment", "name", name)
			}
		}
	}

	// Delete services
	for _, name := range []string{getServiceName(o, "fe"), getServiceName(o, "be"), getServiceName(o, "lf")} {
		service := &corev1.Service{}
		err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, service)
		if err == nil {
			if err := r.Delete(ctx, service); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete service", "name", name)
			}
		}
	}

	// Delete service accounts (only if we created them)
	for _, role := range []string{"fe", "be", "lf"} {
		if shouldCreateServiceAccount(o, role) {
			name := getServiceAccountName(o, role)
			sa := &corev1.ServiceAccount{}
			err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, sa)
			if err == nil {
				if err := r.Delete(ctx, sa); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete service account", "name", name)
				}
			}
		}
	}

	// Delete PVCs based on pvcReclaimPolicy
	// Default is "Retain" to preserve user data
	policy := o.Spec.Langflow.PVCReclaimPolicy
	if policy == "" {
		policy = openragv1alpha1.PVCReclaimRetain // default if not specified
	}

	if policy == openragv1alpha1.PVCReclaimDelete {
		pvc := &corev1.PersistentVolumeClaim{}
		err := r.Get(ctx, client.ObjectKey{Name: instanceResourceName(o, "lf-data"), Namespace: targetNS}, pvc)
		if err == nil {
			logger.Info("Deleting Langflow PVC per pvcReclaimPolicy", "pvc", instanceResourceName(o, "lf-data"), "policy", policy)
			if err := r.Delete(ctx, pvc); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete PVC", "name", instanceResourceName(o, "lf-data"))
			}
		}
	} else {
		logger.Info("Retaining Langflow PVC to preserve user data", "pvc", instanceResourceName(o, "lf-data"), "policy", policy)
	}

	// Delete network policy if enabled
	if o.Spec.NetworkPolicy.Enabled {
		np := &networkingv1.NetworkPolicy{}
		err := r.Get(ctx, client.ObjectKey{Name: instanceResourceName(o, "lf-netpol"), Namespace: targetNS}, np)
		if err == nil {
			logger.Info("Deleting NetworkPolicy", "name", instanceResourceName(o, "lf-netpol"), "namespace", targetNS)
			if err := r.Delete(ctx, np); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete network policy", "name", instanceResourceName(o, "lf-netpol"))
			}
		} else if !errors.IsNotFound(err) {
			logger.Error(err, "failed to get network policy for deletion", "name", instanceResourceName(o, "lf-netpol"))
		}
	}

	// Delete Docling components if enabled
	if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Enabled {
		// Delete Docling deployments (ds and dw)
		for _, name := range []string{instanceResourceName(o, "ds"), instanceResourceName(o, "dw")} {
			deployment := &appsv1.Deployment{}
			err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, deployment)
			if err == nil {
				logger.Info("Deleting Docling deployment", "name", name)
				if err := r.Delete(ctx, deployment); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Docling deployment", "name", name)
				}
			}
		}

		// Delete Docling services
		for _, name := range []string{getServiceName(o, "ds"), getServiceName(o, "dw")} {
			service := &corev1.Service{}
			err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, service)
			if err == nil {
				logger.Info("Deleting Docling service", "name", name)
				if err := r.Delete(ctx, service); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Docling service", "name", name)
				}
			}
		}

		// Delete Docling service accounts (only if we created them)
		for _, role := range []string{"ds", "dw"} {
			if shouldCreateServiceAccount(o, role) {
				name := getServiceAccountName(o, role)
				sa := &corev1.ServiceAccount{}
				err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, sa)
				if err == nil {
					logger.Info("Deleting Docling service account", "name", name)
					if err := r.Delete(ctx, sa); err != nil && !errors.IsNotFound(err) {
						logger.Error(err, "failed to delete Docling service account", "name", name)
					}
				}
			}
		}

		// Delete Docling HPAs if enabled
		for _, name := range []string{instanceResourceName(o, "ds-hpa"), instanceResourceName(o, "dw-hpa")} {
			hpa := &autoscalingv2.HorizontalPodAutoscaler{}
			err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, hpa)
			if err == nil {
				logger.Info("Deleting Docling HPA", "name", name)
				if err := r.Delete(ctx, hpa); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Docling HPA", "name", name)
				}
			}
		}

		// Delete Docling PVCs if storage is enabled
		// Note: Could add reclaim policy for Docling PVCs in future
		for _, name := range []string{instanceResourceName(o, "ds-data"), instanceResourceName(o, "dw-data")} {
			pvc := &corev1.PersistentVolumeClaim{}
			err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, pvc)
			if err == nil {
				logger.Info("Deleting Docling PVC", "name", name)
				if err := r.Delete(ctx, pvc); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Docling PVC", "name", name)
				}
			}
		}

		// Delete Valkey resources if enabled
		if o.Spec.DoclingComponents.Valkey != nil {
			// Delete Valkey StatefulSet
			sts := &appsv1.StatefulSet{}
			err := r.Get(ctx, client.ObjectKey{Name: instanceResourceName(o, "valkey"), Namespace: targetNS}, sts)
			if err == nil {
				logger.Info("Deleting Valkey StatefulSet", "name", instanceResourceName(o, "valkey"))
				if err := r.Delete(ctx, sts); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Valkey StatefulSet")
				}
			}

			// Delete Valkey services
			for _, name := range []string{instanceResourceName(o, "valkey"), instanceResourceName(o, "valkey-headless")} {
				service := &corev1.Service{}
				err := r.Get(ctx, client.ObjectKey{Name: name, Namespace: targetNS}, service)
				if err == nil {
					logger.Info("Deleting Valkey service", "name", name)
					if err := r.Delete(ctx, service); err != nil && !errors.IsNotFound(err) {
						logger.Error(err, "failed to delete Valkey service", "name", name)
					}
				}
			}

			// Delete Valkey ConfigMap
			cm := &corev1.ConfigMap{}
			err = r.Get(ctx, client.ObjectKey{Name: instanceResourceName(o, "valkey-config"), Namespace: targetNS}, cm)
			if err == nil {
				logger.Info("Deleting Valkey ConfigMap", "name", instanceResourceName(o, "valkey-config"))
				if err := r.Delete(ctx, cm); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Valkey ConfigMap")
				}
			}

			// Delete Valkey Secret
			secret := &corev1.Secret{}
			err = r.Get(ctx, client.ObjectKey{Name: instanceResourceName(o, "valkey-auth"), Namespace: targetNS}, secret)
			if err == nil {
				logger.Info("Deleting Valkey Secret", "name", instanceResourceName(o, "valkey-auth"))
				if err := r.Delete(ctx, secret); err != nil && !errors.IsNotFound(err) {
					logger.Error(err, "failed to delete Valkey Secret")
				}
			}

			// Delete Valkey PVCs (from StatefulSet)
			// Note: StatefulSet PVCs have format: data-<statefulset-name>-<ordinal>
			// We should delete these to avoid orphaned PVCs
			for i := 0; i < 1; i++ { // Default replicas is 1
				pvcName := fmt.Sprintf("data-%s-%d", instanceResourceName(o, "valkey"), i)
				pvc := &corev1.PersistentVolumeClaim{}
				err := r.Get(ctx, client.ObjectKey{Name: pvcName, Namespace: targetNS}, pvc)
				if err == nil {
					logger.Info("Deleting Valkey PVC", "name", pvcName)
					if err := r.Delete(ctx, pvc); err != nil && !errors.IsNotFound(err) {
						logger.Error(err, "failed to delete Valkey PVC", "name", pvcName)
					}
				}
			}
		}
	}

	return nil
}
