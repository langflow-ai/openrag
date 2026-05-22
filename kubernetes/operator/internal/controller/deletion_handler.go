package controller

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
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
	for _, envSecretName := range []string{resourceName("be-env"), resourceName("lf-env")} {
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
			// Then delete the secret (necessary for cross-namespace or if owner ref not set)
			logger.Info("deleting .env secret", "name", envSecretName)
			if err := r.Delete(ctx, envSecret); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete env secret", "name", envSecretName)
				return fmt.Errorf("failed to delete env secret %s: %w", envSecretName, err)
			}
			logger.Info("successfully deleted .env secret", "name", envSecretName)
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
			// Then delete the secret (necessary for cross-namespace or if owner ref not set)
			logger.Info("deleting default secret", "name", secretName)
			if err := r.Delete(ctx, defaultSecret); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "failed to delete default secret", "name", secretName)
				return fmt.Errorf("failed to delete default secret %s: %w", secretName, err)
			}
			logger.Info("successfully deleted default secret", "name", secretName)
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

	controllerutil.RemoveFinalizer(o, finalizer)
	return r.Update(ctx, o)
}
