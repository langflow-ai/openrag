package controller

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/intstr"

	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

const (
	finalizer           = "openr.ag/namespace-cleanup"
	envSecretFinalizer  = "openr.ag/env-secret-protection"
	userSecretFinalizer = "openr.ag/user-secret-protection"
	specHashAnnotation  = "openr.ag/spec-hash"
	immutableAnnotation = "openr.ag/immutable"

	// backendIngestRouterPort is the port the optional ingestion-callback proxy
	// router listens on inside the backend pod (OPENRAG_BACKEND_ROUTER_ENABLE).
	backendIngestRouterPort int32 = 8100

	// Condition types
	conditionBackendReady = "BackendReady"

	// Phase values
	phaseReconciled = "Reconciled"
	phaseScaledDown = "ScaledDown"
	phaseRunning    = "Running"
	phaseError      = "Error"
)

// OpenRAGReconciler reconciles an OpenRAG object.
type OpenRAGReconciler struct {
	EnvVarManager *EnvVarManager
	client.Client
	Scheme *runtime.Scheme
}

func NewOpenRAGReconciler(c client.Client, s *runtime.Scheme) *OpenRAGReconciler {
	return &OpenRAGReconciler{
		EnvVarManager: NewEnvVarManager(),
		Client:        c,
		Scheme:        s,
	}
}

// +kubebuilder:rbac:groups=openr.ag,resources=openrags,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=openr.ag,resources=openrags/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=openr.ag,resources=openrags/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=autoscaling,resources=horizontalpodautoscalers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=namespaces,verbs=get;list;watch;create;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=serviceaccounts,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=networking.k8s.io,resources=networkpolicies,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=coordination.k8s.io,resources=leases,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=events,verbs=create;patch

func (r *OpenRAGReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	logger.Info("reconcile triggered", "name", req.Name, "namespace", req.Namespace)

	instance := &openragv1alpha1.OpenRAG{}
	if err := r.Get(ctx, req.NamespacedName, instance); err != nil {
		if errors.IsNotFound(err) {
			logger.Info("CR not found - already deleted or never existed", "name", req.Name)
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	logger.Info("CR retrieved", "name", instance.Name, "deletionTimestamp", instance.DeletionTimestamp)

	if !instance.DeletionTimestamp.IsZero() {
		logger.Info("CR has deletionTimestamp - calling handleDeletion", "name", instance.Name)
		return ctrl.Result{}, r.handleDeletion(ctx, instance)
	}

	targetNS := targetNamespace(instance)
	logger.Info("target namespace determined", "targetNS", targetNS, "crNamespace", instance.Namespace)

	// Always add finalizer to CR so handleDeletion() can clean up .env secret finalizers
	// .env secrets have envSecretFinalizer that must be removed before secrets can be deleted
	if !controllerutil.ContainsFinalizer(instance, finalizer) {
		logger.Info("adding finalizer to CR", "finalizer", finalizer, "reason", "needed to cleanup secret finalizers")
		controllerutil.AddFinalizer(instance, finalizer)
		if err := r.Update(ctx, instance); err != nil {
			return ctrl.Result{}, err
		}
		// Return immediately after adding finalizer to avoid duplicate reconciliation.
		// The update will trigger a new reconcile that will do the actual work.
		logger.Info("added finalizer, will reconcile again")
		return ctrl.Result{}, nil
	} else {
		logger.Info("CR already has finalizer", "finalizer", finalizer)
	}

	// Reconcile all resources
	if err := r.reconcileNamespace(ctx, instance, targetNS); err != nil {
		return r.updateStatusError(ctx, instance, "namespace", err)
	}
	if err := r.reconcileServiceAccounts(ctx, instance, targetNS); err != nil {
		return r.updateStatusError(ctx, instance, "service accounts", err)
	}
	// Reconcile .env secrets and get their hashes to trigger pod restarts when secrets change
	backendEnvHash, langflowEnvHash, err := r.reconcileEnvSecrets(ctx, instance, targetNS)
	if err != nil {
		return r.updateStatusError(ctx, instance, "env secrets", err)
	}
	if err := r.reconcilePVCs(ctx, instance, targetNS); err != nil {
		return r.updateStatusError(ctx, instance, "pvcs", err)
	}
	if err := r.reconcileServices(ctx, instance, targetNS); err != nil {
		return r.updateStatusError(ctx, instance, "services", err)
	}
	if err := r.reconcileDeployments(ctx, instance, targetNS, backendEnvHash, langflowEnvHash); err != nil {
		return r.updateStatusError(ctx, instance, "deployments", err)
	}
	if err := r.reconcileDoclingComponents(ctx, instance, targetNS); err != nil {
		return r.updateStatusError(ctx, instance, "docling components", err)
	}
	if instance.Spec.NetworkPolicy.Enabled {
		if err := r.reconcileNetworkPolicy(ctx, instance, targetNS); err != nil {
			return r.updateStatusError(ctx, instance, "network policy", err)
		}
	}

	// Update status to success
	logger.Info("reconciled OpenRAG instance", "name", instance.Name, "targetNamespace", targetNS)
	return r.updateStatusSuccess(ctx, instance, targetNS)
}

func (r *OpenRAGReconciler) reconcileNamespace(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	if targetNS == o.Namespace {
		return nil
	}

	ns := &corev1.Namespace{}
	err := r.Get(ctx, client.ObjectKey{Name: targetNS}, ns)
	if errors.IsNotFound(err) {
		ns = &corev1.Namespace{
			ObjectMeta: metav1.ObjectMeta{
				Name: targetNS,
				Labels: map[string]string{
					managedByLabel:                 o.Name,
					"app.kubernetes.io/managed-by": "openrag-operator",
				},
			},
		}
		return r.Create(ctx, ns)
	}
	return err
}

func (r *OpenRAGReconciler) reconcileServiceAccounts(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type saDef struct {
		role string
		spec openragv1alpha1.ComponentSpec
	}
	defs := []saDef{
		{"fe", o.Spec.Frontend.ComponentSpec},
		{"be", o.Spec.Backend.ComponentSpec},
		{"lf", o.Spec.Langflow.ComponentSpec},
	}

	for _, d := range defs {
		// Only create ServiceAccount if flag is true
		if !shouldCreateServiceAccount(o, d.role) {
			continue
		}

		baseLabels := componentLabels(o.Name, d.role)
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceAccountName(o, d.role),
				Namespace:   targetNS,
				Labels:      mergeServiceAccountLabels(o, d.spec, baseLabels),
				Annotations: mergeServiceAccountAnnotations(o, d.spec),
			},
		}
		if err := r.setOwnerOrLabel(o, sa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return err
		}
	}
	return nil
}

// parseEnvValue extracts a value from .env file content for the given key
func parseEnvValue(envContent, key string) string {
	lines := strings.Split(envContent, "\n")
	prefix := key + "="
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, prefix) {
			val := strings.TrimPrefix(line, prefix)
			// Unquote values written by BuildEnvFileContent (KEY="value" format).
			// strconv.Unquote handles escape sequences in a single pass, avoiding
			// ordering bugs (e.g. \\n must become \n, not a newline).
			// Falls through for legacy unquoted values for backward compatibility.
			if unquoted, err := strconv.Unquote(val); err == nil {
				return unquoted
			}
			return val
		}
	}
	return ""
}

// reconcileEnvSecrets creates / updates the backend and Langflow .env Secrets
// from CR fields and fixed runtime defaults.
// All sensitive values (whether user-provided or generated) are consolidated into .env files.
// Returns SHA256 hashes of the backend and langflow .env content to use as pod annotations.
func (r *OpenRAGReconciler) reconcileEnvSecrets(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (backendHash, langflowHash string, err error) {
	// Build backend .env content with all secrets consolidated
	backendEnvContent, err := r.buildBackendEnv(ctx, o, targetNS)
	if err != nil {
		return "", "", fmt.Errorf("failed to build backend env: %w", err)
	}

	// Build langflow .env content with all secrets consolidated
	langflowEnvContent, err := r.buildLangflowEnv(ctx, o, targetNS)
	if err != nil {
		return "", "", fmt.Errorf("failed to build langflow env: %w", err)
	}

	// Calculate SHA256 hashes of .env content for pod restart triggering
	backendHash = calculateHash(backendEnvContent)
	langflowHash = calculateHash(langflowEnvContent)

	type envDef struct {
		name    string
		content string
		spec    openragv1alpha1.ComponentSpec
	}
	defs := []envDef{
		{instanceResourceName(o, "be-env"), backendEnvContent, o.Spec.Backend.ComponentSpec},
		{instanceResourceName(o, "lf-env"), langflowEnvContent, o.Spec.Langflow.ComponentSpec},
	}
	for _, d := range defs {
		baseLabels := map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"}

		// Merge custom labels and annotations
		mergedLabels := mergeSecretLabels(o, d.spec, baseLabels)
		mergedAnnotations := mergeSecretAnnotations(o, d.spec)
		// Ensure immutable annotation is always present
		mergedAnnotations[immutableAnnotation] = "true"

		secret := &corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{
				Name:        d.name,
				Namespace:   targetNS,
				Labels:      mergedLabels,
				Annotations: mergedAnnotations,
				Finalizers:  []string{envSecretFinalizer},
			},
			StringData: map[string]string{".env": d.content},
		}
		if err := r.setOwnerOrLabel(o, secret, targetNS); err != nil {
			return "", "", err
		}
		if err := r.createOrUpdate(ctx, secret); err != nil {
			return "", "", err
		}
	}
	return backendHash, langflowHash, nil
}

func (r *OpenRAGReconciler) buildBackendEnv(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (string, error) {
	// Start with defaults, operator env, and CR env (three-level priority)
	// This now resolves ALL env vars (including secrets/configmaps) for inclusion in .env file
	envVars, err := r.EnvVarManager.GetBackendEnvVars(ctx, r.Client, targetNS, o.Spec.Backend.Env)
	if err != nil {
		return "", fmt.Errorf("failed to merge backend env vars: %w", err)
	}

	// Get or generate encryption key (AES-256)
	// Priority: 1) User-provided secret in CR, 2) Existing value in .env, 3) Generate new
	encryptionKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Backend.EncryptionKeySecret, "OPENRAG_ENCRYPTION_KEY", instanceResourceName(o, "be-env"), GenerateAESKeyString32)
	if err != nil {
		return "", fmt.Errorf("failed to get encryption key: %w", err)
	}
	envVars["OPENRAG_ENCRYPTION_KEY"] = encryptionKey

	// Get or generate JWT signing key (base64 secret)
	jwtSigningKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Backend.JWTSigningKeySecret, "JWT_SIGNING_KEY", instanceResourceName(o, "be-env"), generateBase64SecretKey)
	if err != nil {
		return "", fmt.Errorf("failed to get JWT signing key: %w", err)
	}
	envVars["JWT_SIGNING_KEY"] = jwtSigningKey

	// Operator-derived values (always set)
	envVars["LANGFLOW_URL"] = "http://" + getServiceName(o, "lf") + ":7860"
	envVars["OPENRAG_BACKEND_INTERNAL_URL"] = "http://" + getServiceName(o, "be") + ":8000"

	// Override with CR-specific configuration
	if o.Spec.TenantID != "" {
		envVars["TENANT_ID"] = o.Spec.TenantID
	}

	// OpenSearch configuration from CR spec
	if os := o.Spec.OpenSearch; os != nil {
		envVars["OPENSEARCH_HOST"] = os.Host
		port := os.Port
		if port == 0 {
			port = 9200
		}
		envVars["OPENSEARCH_PORT"] = fmt.Sprintf("%d", port)
		scheme := os.Scheme
		if scheme == "" {
			scheme = "https"
		}
		envVars["OPENSEARCH_URL"] = fmt.Sprintf("%s://%s:%d", scheme, os.Host, port)
		if os.IndexName != "" {
			envVars["OPENSEARCH_INDEX_NAME"] = os.IndexName
		}

		// Read OpenSearch credentials from user-provided secret
		if os.CredentialsSecret != "" {
			// Read username
			usernameSecret := &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: os.CredentialsSecret},
				Key:                  "username",
			}
			username, err := r.readSecretValue(ctx, targetNS, usernameSecret)
			if err != nil {
				return "", fmt.Errorf("failed to read OpenSearch username: %w", err)
			}
			if username != "" {
				envVars["OPENSEARCH_USERNAME"] = username
			}

			// Read password
			passwordSecret := &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: os.CredentialsSecret},
				Key:                  "password",
			}
			password, err := r.readSecretValue(ctx, targetNS, passwordSecret)
			if err != nil {
				return "", fmt.Errorf("failed to read OpenSearch password: %w", err)
			}
			if password != "" {
				envVars["OPENSEARCH_PASSWORD"] = password
			}
		} else {
			// Default username when no credentials secret is provided
			envVars["OPENSEARCH_USERNAME"] = "admin"
		}
	}

	// WatsonX configuration from CR spec
	if wx := o.Spec.WatsonX; wx != nil {
		if wx.Endpoint != "" {
			envVars["WATSONX_ENDPOINT"] = wx.Endpoint
		}
		if wx.ProjectID != "" {
			envVars["WATSONX_PROJECT_ID"] = wx.ProjectID
		}

		// Read WatsonX API key from user-provided secret
		if wx.APIKeySecret != nil {
			apiKey, err := r.readSecretValue(ctx, targetNS, wx.APIKeySecret)
			if err != nil {
				return "", fmt.Errorf("failed to read WatsonX API key: %w", err)
			}
			if apiKey != "" {
				envVars["WATSONX_API_KEY"] = apiKey
			}
		}
	}

	// LLM configuration from CR spec
	if l := o.Spec.LLM; l != nil {
		if l.Provider != "" {
			envVars["LLM_PROVIDER"] = l.Provider
		}
		if l.Model != "" {
			envVars["LLM_MODEL"] = l.Model
		}
	}

	// Embedding configuration from CR spec
	if e := o.Spec.Embedding; e != nil {
		if e.Provider != "" {
			envVars["EMBEDDING_PROVIDER"] = e.Provider
		}
		if e.Model != "" {
			envVars["EMBEDDING_MODEL"] = e.Model
		}
	}

	// OAuth configuration from CR spec
	if o.Spec.Backend.IBMAuthEnabled {
		envVars["IBM_AUTH_ENABLED"] = "true"
	}
	if o.Spec.Backend.OAuthBrokerURL != "" {
		envVars["OAUTH_BROKER_URL"] = o.Spec.Backend.OAuthBrokerURL
	}
	if oa := o.Spec.Backend.OAuth; oa != nil {
		// Google OAuth
		if oa.Google != nil {
			if oa.Google.ClientID != "" {
				envVars["GOOGLE_OAUTH_CLIENT_ID"] = oa.Google.ClientID
			}
			if oa.Google.ClientSecret != nil {
				clientSecret, err := r.readSecretValue(ctx, targetNS, oa.Google.ClientSecret)
				if err != nil {
					return "", fmt.Errorf("failed to read Google OAuth client secret: %w", err)
				}
				if clientSecret != "" {
					envVars["GOOGLE_OAUTH_CLIENT_SECRET"] = clientSecret
				}
			}
		}

		// Microsoft OAuth
		if oa.Microsoft != nil {
			if oa.Microsoft.ClientID != "" {
				envVars["MICROSOFT_GRAPH_OAUTH_CLIENT_ID"] = oa.Microsoft.ClientID
			}
			if oa.Microsoft.ClientSecret != nil {
				clientSecret, err := r.readSecretValue(ctx, targetNS, oa.Microsoft.ClientSecret)
				if err != nil {
					return "", fmt.Errorf("failed to read Microsoft OAuth client secret: %w", err)
				}
				if clientSecret != "" {
					envVars["MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET"] = clientSecret
				}
			}
		}
	}

	// Docling configuration from CR spec
	// Priority: DoclingComponents (operator-managed) > Docling (external)
	if dc := o.Spec.DoclingComponents; dc != nil && dc.Enabled && dc.Serve != nil {
		// Use operator-managed docling-serve
		port := int32(5001)
		if dc.Serve.Port > 0 {
			port = dc.Serve.Port
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("http://%s:%d", getServiceName(o, "ds"), port)
	} else if d := o.Spec.Docling; d != nil {
		// Use external docling service
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("%s://%s:%d", scheme, d.Host, port)
		if d.VerifySsl != nil {
			envVars["DOCLING_SERVE_VERIFY_SSL"] = strconv.FormatBool(*d.VerifySsl)
		}
	}

	// Convert map to .env file format
	return r.EnvVarManager.BuildEnvFileContent(envVars), nil
}

func (r *OpenRAGReconciler) buildLangflowEnv(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (string, error) {
	// Start with defaults, operator env, and CR env (three-level priority)
	// This now resolves ALL env vars (including secrets/configmaps) for inclusion in .env file
	envVars, err := r.EnvVarManager.GetLangflowEnvVars(ctx, r.Client, targetNS, o.Spec.Langflow.Env)
	if err != nil {
		return "", fmt.Errorf("failed to merge langflow env vars: %w", err)
	}

	// Get or generate Langflow secret key (Fernet key - base64, shared with backend)
	langflowSecretKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Langflow.SecretKeySecret, "LANGFLOW_SECRET_KEY", instanceResourceName(o, "lf-env"), generateBase64SecretKey)
	if err != nil {
		return "", fmt.Errorf("failed to get langflow secret key: %w", err)
	}
	envVars["LANGFLOW_SECRET_KEY"] = langflowSecretKey

	// Override with CR-specific configuration
	if o.Spec.TenantID != "" {
		envVars["TENANT_ID"] = o.Spec.TenantID
	}

	// OpenSearch configuration from CR spec
	if os := o.Spec.OpenSearch; os != nil {
		envVars["OPENSEARCH_HOST"] = os.Host
		port := os.Port
		if port == 0 {
			port = 9200
		}
		envVars["OPENSEARCH_PORT"] = fmt.Sprintf("%d", port)
		scheme := os.Scheme
		if scheme == "" {
			scheme = "https"
		}
		envVars["OPENSEARCH_URL"] = fmt.Sprintf("%s://%s:%d", scheme, os.Host, port)
		if os.IndexName != "" {
			envVars["OPENSEARCH_INDEX_NAME"] = os.IndexName
		}
	}

	// WatsonX configuration from CR spec
	if wx := o.Spec.WatsonX; wx != nil {
		if wx.Endpoint != "" {
			envVars["WATSONX_ENDPOINT"] = wx.Endpoint
		}
		if wx.ProjectID != "" {
			envVars["WATSONX_PROJECT_ID"] = wx.ProjectID
		}
	}

	// LLM configuration from CR spec
	if l := o.Spec.LLM; l != nil {
		if l.Provider != "" {
			envVars["LLM_PROVIDER"] = l.Provider
		}
		if l.Model != "" {
			envVars["LLM_MODEL"] = l.Model
		}
	}

	// Embedding configuration from CR spec
	if e := o.Spec.Embedding; e != nil {
		if e.Provider != "" {
			envVars["EMBEDDING_PROVIDER"] = e.Provider
		}
		if e.Model != "" {
			envVars["EMBEDDING_MODEL"] = e.Model
		}
	}

	// Docling configuration from CR spec
	// Priority: DoclingComponents (operator-managed) > Docling (external)
	if dc := o.Spec.DoclingComponents; dc != nil && dc.Enabled && dc.Serve != nil {
		// Use operator-managed docling-serve
		port := int32(5001)
		if dc.Serve.Port > 0 {
			port = dc.Serve.Port
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("http://%s:%d", getServiceName(o, "ds"), port)
	} else if d := o.Spec.Docling; d != nil {
		// Use external docling service
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("%s://%s:%d", scheme, d.Host, port)
		if d.VerifySsl != nil {
			envVars["DOCLING_SERVE_VERIFY_SSL"] = strconv.FormatBool(*d.VerifySsl)
		}
	}

	// Ensure all variables in LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT exist with at least "None" value
	// This is critical because the list can be customized via CR spec, operator env vars, or defaults
	r.EnvVarManager.EnsureRequiredEnvVars(envVars)

	// Convert map to .env file format
	return r.EnvVarManager.BuildEnvFileContent(envVars), nil
}

func (r *OpenRAGReconciler) reconcilePVCs(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type pvcDef struct {
		name    string
		storage *openragv1alpha1.PersistenceSpec
	}
	defs := []pvcDef{
		{instanceResourceName(o, "lf-data"), o.Spec.Langflow.Storage},
		{instanceResourceName(o, "be-data"), o.Spec.Backend.Storage},
	}
	for _, d := range defs {
		if d.storage == nil || !d.storage.Enabled || d.storage.ExistingClaim != "" {
			continue
		}
		// Default to ReadWriteOnce if not specified
		accessModes := d.storage.AccessModes
		if len(accessModes) == 0 {
			accessModes = []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce}
		}

		// Base labels that cannot be overridden
		baseLabels := map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"}

		pvc := &corev1.PersistentVolumeClaim{
			ObjectMeta: metav1.ObjectMeta{
				Name:        d.name,
				Namespace:   targetNS,
				Labels:      mergePVCLabels(o, d.storage, baseLabels),
				Annotations: mergePVCAnnotations(o, d.storage),
			},
			Spec: corev1.PersistentVolumeClaimSpec{
				AccessModes:      accessModes,
				StorageClassName: d.storage.StorageClassName,
				Resources: corev1.VolumeResourceRequirements{
					Requests: corev1.ResourceList{
						corev1.ResourceStorage: d.storage.Size,
					},
				},
			},
		}
		if err := r.setOwnerOrLabel(o, pvc, targetNS); err != nil {
			return err
		}
		// PVCs are immutable once bound — only create, never update.
		existing := &corev1.PersistentVolumeClaim{}
		if err := r.Get(ctx, client.ObjectKeyFromObject(pvc), existing); err != nil {
			if errors.IsNotFound(err) {
				if err := r.Create(ctx, pvc); err != nil {
					return err
				}
			} else {
				return err
			}
		}
	}
	return nil
}

func (r *OpenRAGReconciler) reconcileServices(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type svcDef struct {
		role string
		port int32
		spec openragv1alpha1.ComponentSpec
	}
	defs := []svcDef{
		{"fe", 3000, o.Spec.Frontend.ComponentSpec},
		{"be", 8000, o.Spec.Backend.ComponentSpec},
		{"lf", 7860, o.Spec.Langflow.ComponentSpec},
	}
	for _, d := range defs {
		// Only create Service if flag is true
		if !shouldCreateService(o, d.role) {
			continue
		}

		svcPorts := []corev1.ServicePort{
			{Name: "http", Port: d.port, Protocol: corev1.ProtocolTCP},
		}
		// The backend optionally serves the ingestion-callback proxy router on
		// its own port (OPENRAG_BACKEND_ROUTER_ENABLE); expose it so Langflow
		// can reach only that endpoint instead of the full backend API.
		if d.role == "be" {
			svcPorts = append(svcPorts, corev1.ServicePort{
				Name: "ingest-router", Port: backendIngestRouterPort, Protocol: corev1.ProtocolTCP,
			})
		}

		baseLabels := componentLabels(o.Name, d.role)
		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceName(o, d.role),
				Namespace:   targetNS,
				Labels:      mergeServiceLabels(o, d.spec, baseLabels),
				Annotations: mergeServiceAnnotations(o, d.spec),
			},
			Spec: corev1.ServiceSpec{
				Type:     corev1.ServiceTypeClusterIP,
				Selector: componentLabels(o.Name, d.role),
				Ports:    svcPorts,
			},
		}
		if err := r.setOwnerOrLabel(o, svc, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, svc); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) reconcileDeployments(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string, backendEnvHash, langflowEnvHash string) error {
	deploys := []client.Object{
		r.frontendDeployment(o, targetNS),
		r.backendDeployment(o, targetNS, backendEnvHash),
		r.langflowDeployment(o, targetNS, langflowEnvHash),
	}
	for _, d := range deploys {
		if err := r.setOwnerOrLabel(o, d, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, d); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) frontendDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
	spec := o.Spec.Frontend
	replicas := replicasOrDefault(spec.Replicas)
	baseLabels := componentLabels(o.Name, "fe")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "fe"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: podAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: getServiceAccountName(o, "fe"),
					ImagePullSecrets:   mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					SecurityContext:    spec.PodSecurityContext,
					Containers: []corev1.Container{
						{
							Name:            "frontend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 3000}},
							Env: append([]corev1.EnvVar{
								{Name: "OPENRAG_BACKEND_HOST", Value: getServiceName(o, "be")},
							}, spec.Env...),
							Resources:       spec.Resources,
							SecurityContext: spec.SecurityContext,
							LivenessProbe:   httpProbe("/", 3000, 30, 10),
							ReadinessProbe:  httpProbe("/", 3000, 10, 5),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) backendDeployment(o *openragv1alpha1.OpenRAG, targetNS string, envHash string) *appsv1.Deployment {
	spec := o.Spec.Backend
	replicas := replicasOrDefault(spec.Replicas)

	volumes := []corev1.Volume{
		{
			Name:         "backend-temp",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
		{
			Name: "backend-env",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{SecretName: instanceResourceName(o, "be-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "backend-temp", MountPath: "/tmp"},
		{Name: "backend-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := instanceResourceName(o, "be-data")
		if spec.Storage.ExistingClaim != "" {
			pvcName = spec.Storage.ExistingClaim
		}
		volumes = append(volumes, corev1.Volume{
			Name: "backend-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvcName},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "backend-data", MountPath: "/app/backend-data"})
	}

	// ALL env vars (including spec.Env) are now in the .env file
	// Container Env should be empty to prevent values from showing in 'env' command
	// The .env file is mounted and sourced by the application
	var envVars []corev1.EnvVar // Empty - all vars are in .env file

	baseLabels := componentLabels(o.Name, "be")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)
	// Add .env secret hash to trigger pod restart when secret changes
	podAnnotations["openr.ag/backend-env-hash"] = envHash
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "be"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: podAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: getServiceAccountName(o, "be"),
					ImagePullSecrets:   mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					SecurityContext:    spec.PodSecurityContext,
					Volumes:            volumes,
					Containers: []corev1.Container{
						{
							Name:            "backend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 8000}, {Name: "ingest-router", ContainerPort: backendIngestRouterPort}},
							Env:             envVars,
							Resources:       spec.Resources,
							SecurityContext: spec.SecurityContext,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 8000, 125, 30),
							ReadinessProbe:  httpProbe("/health", 8000, 125, 15),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) langflowDeployment(o *openragv1alpha1.OpenRAG, targetNS string, envHash string) *appsv1.Deployment {
	spec := o.Spec.Langflow
	replicas := replicasOrDefault(spec.Replicas)

	volumes := []corev1.Volume{
		{
			Name:         "langflow-temp",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
		{
			Name: "langflow-env",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{SecretName: instanceResourceName(o, "lf-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "langflow-temp", MountPath: "/tmp"},
		{Name: "langflow-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := instanceResourceName(o, "lf-data")
		if spec.Storage.ExistingClaim != "" {
			pvcName = spec.Storage.ExistingClaim
		}
		volumes = append(volumes, corev1.Volume{
			Name: "langflow-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvcName},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "langflow-data", MountPath: "/app/data"})
	}

	// Only create initContainer if FlowsRef is specified
	// Use nil (not empty slice) to ensure initContainers are removed when FlowsRef is cleared
	var initContainers []corev1.Container
	if spec.FlowsRef != "" {
		volumes = append(volumes, corev1.Volume{
			Name:         "langflow-flows",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "langflow-flows", MountPath: "/app/flows"})

		initImage := spec.FlowsInitImage
		if initImage == "" {
			initImage = "python:3-alpine"
		}
		initContainers = []corev1.Container{
			{
				Name:    "download-flows",
				Image:   initImage,
				Command: []string{"python3", "-c", flowsDownloadScript},
				Env: []corev1.EnvVar{
					{Name: "FLOWS_REF", Value: spec.FlowsRef},
				},
				VolumeMounts: []corev1.VolumeMount{
					{Name: "langflow-flows", MountPath: "/app/flows"},
				},
			},
		}
	} else {
		// Explicitly set to nil when FlowsRef is empty to ensure initContainers are removed
		initContainers = nil
	}

	// ALL env vars (including spec.Env) are now in the .env file
	// Container Env should be empty to prevent values from showing in 'env' command
	// The .env file is mounted and sourced by the application
	var envVars []corev1.EnvVar // Empty - all vars are in .env file

	baseLabels := componentLabels(o.Name, "lf")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)
	// Add .env secret hash to trigger pod restart when secret changes
	podAnnotations["openr.ag/langflow-env-hash"] = envHash
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "lf"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: podAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: getServiceAccountName(o, "lf"),
					ImagePullSecrets:   mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					SecurityContext:    spec.PodSecurityContext,
					InitContainers:     initContainers,
					Volumes:            volumes,
					Containers: []corev1.Container{
						{
							Name:            "langflow",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Command:         commandOrDefault(spec.Command, []string{"langflow"}),
							Args:            argsOrDefault(spec.Args, []string{"run", "--env-file", "/app/.env"}),
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 7860}},
							Env:             envVars,
							Resources:       spec.Resources,
							SecurityContext: spec.SecurityContext,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 7860, 110, 30),
							ReadinessProbe:  httpProbe("/health", 7860, 110, 30),
						},
					},
				},
			},
		},
	}
}

// reconcileDoclingComponents orchestrates docling deployment and HPA.
func (r *OpenRAGReconciler) reconcileDoclingComponents(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	if o.Spec.DoclingComponents == nil || !o.Spec.DoclingComponents.Enabled {
		return nil
	}

	dc := o.Spec.DoclingComponents

	// Deploy Valkey first if enabled
	if dc.Valkey != nil {
		if err := r.reconcileValkey(ctx, o, targetNS); err != nil {
			return fmt.Errorf("valkey: %w", err)
		}
	}

	// Reconcile service accounts for docling components
	if dc.Serve != nil && shouldCreateServiceAccount(o, "ds") {
		baseLabels := componentLabels(o.Name, "ds")
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceAccountName(o, "ds"),
				Namespace:   targetNS,
				Labels:      mergeServiceAccountLabels(o, dc.Serve.ComponentSpec, baseLabels),
				Annotations: mergeServiceAccountAnnotations(o, dc.Serve.ComponentSpec),
			},
		}
		if err := r.setOwnerOrLabel(o, sa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return fmt.Errorf("docling-serve serviceaccount: %w", err)
		}
	}

	if dc.Worker != nil && shouldCreateServiceAccount(o, "dw") {
		baseLabels := componentLabels(o.Name, "dw")
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceAccountName(o, "dw"),
				Namespace:   targetNS,
				Labels:      mergeServiceAccountLabels(o, dc.Worker.ComponentSpec, baseLabels),
				Annotations: mergeServiceAccountAnnotations(o, dc.Worker.ComponentSpec),
			},
		}
		if err := r.setOwnerOrLabel(o, sa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return fmt.Errorf("docling-worker serviceaccount: %w", err)
		}
	}

	// Reconcile PVCs for docling components
	if dc.Serve != nil && dc.Serve.Storage != nil && dc.Serve.Storage.Enabled {
		pvcName := instanceResourceName(o, "ds-data")
		if dc.Serve.Storage.ExistingClaim == "" {
			// Default to ReadWriteOnce if not specified
			accessModes := dc.Serve.Storage.AccessModes
			if len(accessModes) == 0 {
				accessModes = []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce}
			}

			baseLabels := componentLabels(o.Name, "ds")
			pvc := &corev1.PersistentVolumeClaim{
				ObjectMeta: metav1.ObjectMeta{
					Name:        pvcName,
					Namespace:   targetNS,
					Labels:      mergePVCLabels(o, dc.Serve.Storage, baseLabels),
					Annotations: mergePVCAnnotations(o, dc.Serve.Storage),
				},
				Spec: corev1.PersistentVolumeClaimSpec{
					AccessModes: accessModes,
					Resources: corev1.VolumeResourceRequirements{
						Requests: corev1.ResourceList{
							corev1.ResourceStorage: dc.Serve.Storage.Size,
						},
					},
					StorageClassName: dc.Serve.Storage.StorageClassName,
				},
			}
			if err := r.setOwnerOrLabel(o, pvc, targetNS); err != nil {
				return err
			}
			if err := r.createOrUpdate(ctx, pvc); err != nil {
				return fmt.Errorf("docling-serve pvc: %w", err)
			}
		}
	}

	if dc.Worker != nil && dc.Worker.Storage != nil && dc.Worker.Storage.Enabled {
		pvcName := instanceResourceName(o, "dw-data")
		if dc.Worker.Storage.ExistingClaim == "" {
			// Default to ReadWriteOnce if not specified
			accessModes := dc.Worker.Storage.AccessModes
			if len(accessModes) == 0 {
				accessModes = []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce}
			}

			baseLabels := componentLabels(o.Name, "dw")
			pvc := &corev1.PersistentVolumeClaim{
				ObjectMeta: metav1.ObjectMeta{
					Name:        pvcName,
					Namespace:   targetNS,
					Labels:      mergePVCLabels(o, dc.Worker.Storage, baseLabels),
					Annotations: mergePVCAnnotations(o, dc.Worker.Storage),
				},
				Spec: corev1.PersistentVolumeClaimSpec{
					AccessModes: accessModes,
					Resources: corev1.VolumeResourceRequirements{
						Requests: corev1.ResourceList{
							corev1.ResourceStorage: dc.Worker.Storage.Size,
						},
					},
					StorageClassName: dc.Worker.Storage.StorageClassName,
				},
			}
			if err := r.setOwnerOrLabel(o, pvc, targetNS); err != nil {
				return err
			}
			if err := r.createOrUpdate(ctx, pvc); err != nil {
				return fmt.Errorf("docling-worker pvc: %w", err)
			}
		}
	}

	// Reconcile service for docling-serve
	if dc.Serve != nil && shouldCreateService(o, "ds") {
		port := int32(5001)
		if dc.Serve.Port > 0 {
			port = dc.Serve.Port
		}

		// Default to ClusterIP if not specified
		serviceType := dc.Serve.ServiceType
		if serviceType == "" {
			serviceType = corev1.ServiceTypeClusterIP
		}

		baseLabels := componentLabels(o.Name, "ds")
		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceName(o, "ds"),
				Namespace:   targetNS,
				Labels:      mergeServiceLabels(o, dc.Serve.ComponentSpec, baseLabels),
				Annotations: mergeServiceAnnotations(o, dc.Serve.ComponentSpec),
			},
			Spec: corev1.ServiceSpec{
				Type:     serviceType,
				Selector: componentLabels(o.Name, "ds"),
				Ports: []corev1.ServicePort{
					{Name: "http", Port: port, TargetPort: intstr.FromInt32(port), Protocol: corev1.ProtocolTCP},
				},
			},
		}
		if err := r.setOwnerOrLabel(o, svc, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, svc); err != nil {
			return fmt.Errorf("docling-serve service: %w", err)
		}
	}

	// Reconcile deployments
	if dc.Serve != nil {
		deploy := r.doclingServeDeployment(o, targetNS)
		if err := r.setOwnerOrLabel(o, deploy, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, deploy); err != nil {
			return fmt.Errorf("docling-serve deployment: %w", err)
		}
	}

	if dc.Worker != nil {
		deploy := r.doclingWorkerDeployment(o, targetNS)
		if err := r.setOwnerOrLabel(o, deploy, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, deploy); err != nil {
			return fmt.Errorf("docling-worker deployment: %w", err)
		}
	}

	// Reconcile HPA for docling-serve
	if dc.Serve != nil && dc.Serve.HPA != nil && dc.Serve.HPA.Enabled {
		hpa := r.doclingServeHPA(o, targetNS)
		if err := r.setOwnerOrLabel(o, hpa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, hpa); err != nil {
			return fmt.Errorf("docling-serve hpa: %w", err)
		}
	} else {
		// Delete HPA if it exists but is now disabled
		hpa := &autoscalingv2.HorizontalPodAutoscaler{
			ObjectMeta: metav1.ObjectMeta{
				Name:      instanceResourceName(o, "ds-hpa"),
				Namespace: targetNS,
			},
		}
		if err := r.deleteIfExists(ctx, hpa); err != nil {
			return fmt.Errorf("delete docling-serve hpa: %w", err)
		}
	}

	// Reconcile HPA for docling-worker
	if dc.Worker != nil && dc.Worker.HPA != nil && dc.Worker.HPA.Enabled {
		hpa := r.doclingWorkerHPA(o, targetNS)
		if err := r.setOwnerOrLabel(o, hpa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, hpa); err != nil {
			return fmt.Errorf("docling-worker hpa: %w", err)
		}
	} else {
		// Delete HPA if it exists but is now disabled
		hpa := &autoscalingv2.HorizontalPodAutoscaler{
			ObjectMeta: metav1.ObjectMeta{
				Name:      instanceResourceName(o, "dw-hpa"),
				Namespace: targetNS,
			},
		}
		if err := r.deleteIfExists(ctx, hpa); err != nil {
			return fmt.Errorf("delete docling-worker hpa: %w", err)
		}
	}

	return nil
}

// buildDoclingConfigEnv converts DoclingConfig to environment variables
func buildDoclingConfigEnv(config *openragv1alpha1.DoclingConfig) []corev1.EnvVar {
	if config == nil {
		return nil
	}

	envVars := []corev1.EnvVar{}

	// OCR configuration
	if config.OCR != nil {
		if config.OCR.Enabled != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_OCR_ENABLED",
				Value: fmt.Sprintf("%t", *config.OCR.Enabled),
			})
		}
		if config.OCR.Engine != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_OCR_ENGINE",
				Value: config.OCR.Engine,
			})
		}
		if len(config.OCR.Languages) > 0 {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_OCR_LANGUAGES",
				Value: strings.Join(config.OCR.Languages, ","),
			})
		}
		if config.OCR.ForceFullPageOCR != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_OCR_FORCE_FULL_PAGE",
				Value: fmt.Sprintf("%t", *config.OCR.ForceFullPageOCR),
			})
		}
	}

	// Table structure configuration
	if config.TableStructure != nil {
		if config.TableStructure.Enabled != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_TABLE_STRUCTURE_ENABLED",
				Value: fmt.Sprintf("%t", *config.TableStructure.Enabled),
			})
		}
		if config.TableStructure.Mode != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_TABLE_MODE",
				Value: config.TableStructure.Mode,
			})
		}
		if config.TableStructure.MinConfidencePercent != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_TABLE_MIN_CONFIDENCE",
				Value: fmt.Sprintf("%d", *config.TableStructure.MinConfidencePercent),
			})
		}
	}

	// Performance configuration
	if config.Performance != nil {
		if config.Performance.BatchSize != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_BATCH_SIZE",
				Value: fmt.Sprintf("%d", *config.Performance.BatchSize),
			})
		}
		if config.Performance.MaxWorkers != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_MAX_WORKERS",
				Value: fmt.Sprintf("%d", *config.Performance.MaxWorkers),
			})
		}
		if config.Performance.TimeoutSeconds != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_TIMEOUT",
				Value: fmt.Sprintf("%d", *config.Performance.TimeoutSeconds),
			})
		}
		if config.Performance.EnableGPU != nil {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_ENABLE_GPU",
				Value: fmt.Sprintf("%t", *config.Performance.EnableGPU),
			})
		}
	}

	// Models configuration
	if config.Models != nil {
		if config.Models.LayoutModel != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_LAYOUT_MODEL",
				Value: config.Models.LayoutModel,
			})
		}
		if config.Models.OCRModel != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_OCR_MODEL",
				Value: config.Models.OCRModel,
			})
		}
		if config.Models.TableModel != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_TABLE_MODEL",
				Value: config.Models.TableModel,
			})
		}
		if config.Models.ModelCachePath != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "DOCLING_MODEL_CACHE_PATH",
				Value: config.Models.ModelCachePath,
			})
		}
	}

	// Add extra environment variables
	envVars = append(envVars, config.ExtraEnv...)

	return envVars
}

func (r *OpenRAGReconciler) doclingServeDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
	spec := o.Spec.DoclingComponents.Serve
	replicas := replicasOrDefault(spec.Replicas)
	port := int32(5001)
	if spec.Port > 0 {
		port = spec.Port
	}

	volumes := []corev1.Volume{
		{
			Name:         "docling-serve-temp",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "docling-serve-temp", MountPath: "/tmp"},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := instanceResourceName(o, "ds-data")
		if spec.Storage.ExistingClaim != "" {
			pvcName = spec.Storage.ExistingClaim
		}
		volumes = append(volumes, corev1.Volume{
			Name: "docling-serve-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvcName},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "docling-serve-data", MountPath: "/app/cache"})
	}

	envVars := []corev1.EnvVar{
		{Name: "DOCLING_PORT", Value: fmt.Sprintf("%d", port)},
		{Name: "DOCLING_CACHE_DIR", Value: "/app/cache"},
	}
	// Add docling configuration environment variables
	envVars = append(envVars, buildDoclingConfigEnv(spec.Config)...)
	// Add user-specified environment variables
	envVars = append(envVars, spec.Env...)

	baseLabels := componentLabels(o.Name, "ds")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)

	deploymentSpec := appsv1.DeploymentSpec{
		Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
		Strategy: appsv1.DeploymentStrategy{Type: appsv1.RollingUpdateDeploymentStrategyType},
		Template: corev1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels:      podLabels,
				Annotations: podAnnotations,
			},
			Spec: corev1.PodSpec{
				ServiceAccountName:        getServiceAccountName(o, "ds"),
				ImagePullSecrets:          mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
				SecurityContext:           spec.PodSecurityContext,
				NodeSelector:              spec.NodeSelector,
				Tolerations:               spec.Tolerations,
				Affinity:                  spec.Affinity,
				TopologySpreadConstraints: spec.TopologySpreadConstraints,
				Volumes:                   volumes,
				Containers: []corev1.Container{
					{
						Name:            "docling-serve",
						Image:           spec.Image,
						ImagePullPolicy: spec.ImagePullPolicy,
						Command:         spec.Command,
						Args:            spec.Args,
						Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: port}},
						Env:             envVars,
						Resources:       spec.Resources,
						VolumeMounts:    mounts,
						SecurityContext: spec.SecurityContext,
						LivenessProbe:   probeOrDefault(spec.LivenessProbe, httpProbe("/health", port, 30, 10)),
						ReadinessProbe:  probeOrDefault(spec.ReadinessProbe, httpProbe("/health", port, 10, 5)),
					},
				},
			},
		},
	}

	// Only set Replicas if HPA is not enabled
	// When HPA is active, it controls the replica count
	if spec.HPA == nil || !spec.HPA.Enabled {
		deploymentSpec.Replicas = &replicas
	}

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "ds"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: deploymentSpec,
	}
}

func (r *OpenRAGReconciler) doclingWorkerDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
	spec := o.Spec.DoclingComponents.Worker
	replicas := replicasOrDefault(spec.Replicas)

	volumes := []corev1.Volume{
		{
			Name:         "docling-worker-temp",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "docling-worker-temp", MountPath: "/tmp"},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := instanceResourceName(o, "dw-data")
		if spec.Storage.ExistingClaim != "" {
			pvcName = spec.Storage.ExistingClaim
		}
		volumes = append(volumes, corev1.Volume{
			Name: "docling-worker-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvcName},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "docling-worker-data", MountPath: "/app/workspace"})
	}

	// Build environment variables
	envVars := []corev1.EnvVar{
		{Name: "DOCLING_WORKSPACE_DIR", Value: "/app/workspace"},
	}

	// Add DOCLING_SERVE_URL if serve component is enabled
	if o.Spec.DoclingComponents.Serve != nil {
		port := int32(5001)
		if o.Spec.DoclingComponents.Serve.Port > 0 {
			port = o.Spec.DoclingComponents.Serve.Port
		}
		envVars = append(envVars, corev1.EnvVar{
			Name:  "DOCLING_SERVE_URL",
			Value: fmt.Sprintf("http://%s:%d", getServiceName(o, "ds"), port),
		})
	}

	// Add queue URL - Priority: Valkey > spec.QueueURL > spec.QueueURLSecret
	if o.Spec.DoclingComponents.Valkey != nil {
		// Use operator-managed Valkey
		valkeySpec := o.Spec.DoclingComponents.Valkey
		port := int32(6379)
		if valkeySpec.Port > 0 {
			port = valkeySpec.Port
		}
		database := int32(0)
		if valkeySpec.Database > 0 {
			database = valkeySpec.Database
		}

		serviceName := getServiceName(o, "valkey")
		// If password is provided directly (not via secret), include it in URL
		if valkeySpec.Password != "" {
			envVars = append(envVars, corev1.EnvVar{
				Name:  "QUEUE_URL",
				Value: fmt.Sprintf("redis://:%s@%s.%s.svc.cluster.local:%d/%d", valkeySpec.Password, serviceName, targetNS, port, database),
			})
		} else if valkeySpec.PasswordSecret != nil {
			// Use secret reference for password
			envVars = append(envVars, corev1.EnvVar{
				Name: "VALKEY_PASSWORD",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: valkeySpec.PasswordSecret,
				},
			})
			// Build URL with password placeholder - app must construct final URL
			envVars = append(envVars, corev1.EnvVar{
				Name:  "QUEUE_URL",
				Value: fmt.Sprintf("redis://:$(VALKEY_PASSWORD)@%s.%s.svc.cluster.local:%d/%d", serviceName, targetNS, port, database),
			})
		} else {
			// No password
			envVars = append(envVars, corev1.EnvVar{
				Name:  "QUEUE_URL",
				Value: fmt.Sprintf("redis://%s.%s.svc.cluster.local:%d/%d", serviceName, targetNS, port, database),
			})
		}
	} else if spec.QueueURL != "" {
		// Use user-provided queue URL
		envVars = append(envVars, corev1.EnvVar{
			Name:  "QUEUE_URL",
			Value: spec.QueueURL,
		})
	} else if spec.QueueURLSecret != nil {
		// Use secret reference
		envVars = append(envVars, corev1.EnvVar{
			Name: "QUEUE_URL",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: spec.QueueURLSecret,
			},
		})
	}

	// Add concurrency setting
	if spec.Concurrency != nil {
		envVars = append(envVars, corev1.EnvVar{
			Name:  "DOCLING_WORKER_CONCURRENCY",
			Value: fmt.Sprintf("%d", *spec.Concurrency),
		})
	}

	// Add docling configuration environment variables
	envVars = append(envVars, buildDoclingConfigEnv(spec.Config)...)

	// Append additional env vars from spec
	envVars = append(envVars, spec.Env...)

	baseLabels := componentLabels(o.Name, "dw")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)

	deploymentSpec := appsv1.DeploymentSpec{
		Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
		Strategy: appsv1.DeploymentStrategy{Type: appsv1.RollingUpdateDeploymentStrategyType},
		Template: corev1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels:      podLabels,
				Annotations: podAnnotations,
			},
			Spec: corev1.PodSpec{
				ServiceAccountName:        getServiceAccountName(o, "dw"),
				ImagePullSecrets:          mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
				SecurityContext:           spec.PodSecurityContext,
				NodeSelector:              spec.NodeSelector,
				Tolerations:               spec.Tolerations,
				Affinity:                  spec.Affinity,
				TopologySpreadConstraints: spec.TopologySpreadConstraints,
				Volumes:                   volumes,
				Containers: []corev1.Container{
					{
						Name:            "docling-worker",
						Image:           spec.Image,
						ImagePullPolicy: spec.ImagePullPolicy,
						Command:         spec.Command,
						Args:            spec.Args,
						Env:             envVars,
						Resources:       spec.Resources,
						VolumeMounts:    mounts,
						SecurityContext: spec.SecurityContext,
						LivenessProbe:   spec.LivenessProbe,
						ReadinessProbe:  spec.ReadinessProbe,
					},
				},
			},
		},
	}

	// Only set Replicas if HPA is not enabled
	// When HPA is active, it controls the replica count
	if spec.HPA == nil || !spec.HPA.Enabled {
		deploymentSpec.Replicas = &replicas
	}

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "dw"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: deploymentSpec,
	}
}

func (r *OpenRAGReconciler) doclingServeHPA(o *openragv1alpha1.OpenRAG, targetNS string) *autoscalingv2.HorizontalPodAutoscaler {
	hpaSpec := o.Spec.DoclingComponents.Serve.HPA
	minReplicas := new(int32(1))
	if hpaSpec.MinReplicas != nil {
		minReplicas = hpaSpec.MinReplicas
	}

	metrics := []autoscalingv2.MetricSpec{}
	if hpaSpec.TargetCPUUtilizationPercentage != nil {
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceCPU,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: hpaSpec.TargetCPUUtilizationPercentage,
				},
			},
		})
	}
	if hpaSpec.TargetMemoryUtilizationPercentage != nil {
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceMemory,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: hpaSpec.TargetMemoryUtilizationPercentage,
				},
			},
		})
	}

	baseLabels := componentLabels(o.Name, "ds")
	return &autoscalingv2.HorizontalPodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instanceResourceName(o, "ds-hpa"),
			Namespace: targetNS,
			Labels:    baseLabels,
		},
		Spec: autoscalingv2.HorizontalPodAutoscalerSpec{
			ScaleTargetRef: autoscalingv2.CrossVersionObjectReference{
				APIVersion: "apps/v1",
				Kind:       "Deployment",
				Name:       instanceResourceName(o, "ds"),
			},
			MinReplicas: minReplicas,
			MaxReplicas: hpaSpec.MaxReplicas,
			Metrics:     metrics,
			Behavior:    hpaSpec.Behavior,
		},
	}
}

func (r *OpenRAGReconciler) doclingWorkerHPA(o *openragv1alpha1.OpenRAG, targetNS string) *autoscalingv2.HorizontalPodAutoscaler {
	hpaSpec := o.Spec.DoclingComponents.Worker.HPA
	minReplicas := new(int32(1))
	if hpaSpec.MinReplicas != nil {
		minReplicas = hpaSpec.MinReplicas
	}

	metrics := []autoscalingv2.MetricSpec{}
	if hpaSpec.TargetCPUUtilizationPercentage != nil {
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceCPU,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: hpaSpec.TargetCPUUtilizationPercentage,
				},
			},
		})
	}
	if hpaSpec.TargetMemoryUtilizationPercentage != nil {
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceMemory,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: hpaSpec.TargetMemoryUtilizationPercentage,
				},
			},
		})
	}

	baseLabels := componentLabels(o.Name, "dw")
	return &autoscalingv2.HorizontalPodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instanceResourceName(o, "dw-hpa"),
			Namespace: targetNS,
			Labels:    baseLabels,
		},
		Spec: autoscalingv2.HorizontalPodAutoscalerSpec{
			ScaleTargetRef: autoscalingv2.CrossVersionObjectReference{
				APIVersion: "apps/v1",
				Kind:       "Deployment",
				Name:       instanceResourceName(o, "dw"),
			},
			MinReplicas: minReplicas,
			MaxReplicas: hpaSpec.MaxReplicas,
			Metrics:     metrics,
			Behavior:    hpaSpec.Behavior,
		},
	}
}

// reconcileValkey deploys Valkey StatefulSet, Service, ConfigMap, and optional Secret.
func (r *OpenRAGReconciler) reconcileValkey(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	valkeySpec := o.Spec.DoclingComponents.Valkey

	// Reconcile ServiceAccount
	if shouldCreateServiceAccount(o, "valkey") {
		baseLabels := componentLabels(o.Name, "valkey")
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceAccountName(o, "valkey"),
				Namespace:   targetNS,
				Labels:      mergeServiceAccountLabels(o, valkeySpec.ComponentSpec, baseLabels),
				Annotations: mergeServiceAccountAnnotations(o, valkeySpec.ComponentSpec),
			},
		}
		if err := r.setOwnerOrLabel(o, sa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return fmt.Errorf("valkey serviceaccount: %w", err)
		}
	}

	// Reconcile ConfigMap
	cm := r.valkeyConfigMap(o, targetNS)
	if err := r.setOwnerOrLabel(o, cm, targetNS); err != nil {
		return err
	}
	if err := r.createOrUpdate(ctx, cm); err != nil {
		return fmt.Errorf("valkey configmap: %w", err)
	}

	// Reconcile Secret (if password is configured)
	if valkeySpec.Password != "" || valkeySpec.PasswordSecret != nil {
		secret, err := r.valkeySecret(ctx, o, targetNS)
		if err != nil {
			return fmt.Errorf("valkey secret: %w", err)
		}
		if err := r.setOwnerOrLabel(o, secret, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, secret); err != nil {
			return fmt.Errorf("valkey secret create: %w", err)
		}
	}

	// Reconcile headless Service (for StatefulSet)
	headlessSvc := r.valkeyHeadlessService(o, targetNS)
	if err := r.setOwnerOrLabel(o, headlessSvc, targetNS); err != nil {
		return err
	}
	if err := r.createOrUpdate(ctx, headlessSvc); err != nil {
		return fmt.Errorf("valkey headless service: %w", err)
	}

	// Reconcile Service
	if shouldCreateService(o, "valkey") {
		svc := r.valkeyService(o, targetNS)
		if err := r.setOwnerOrLabel(o, svc, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, svc); err != nil {
			return fmt.Errorf("valkey service: %w", err)
		}
	}

	// Reconcile StatefulSet
	sts := r.valkeyStatefulSet(o, targetNS)
	if err := r.setOwnerOrLabel(o, sts, targetNS); err != nil {
		return err
	}
	if err := r.createOrUpdate(ctx, sts); err != nil {
		return fmt.Errorf("valkey statefulset: %w", err)
	}

	return nil
}

func (r *OpenRAGReconciler) valkeyStatefulSet(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.StatefulSet {
	spec := o.Spec.DoclingComponents.Valkey
	replicas := replicasOrDefault(spec.Replicas)
	port := int32(6379)
	if spec.Port > 0 {
		port = spec.Port
	}

	volumes := []corev1.Volume{
		{
			Name: "valkey-config",
			VolumeSource: corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{Name: instanceResourceName(o, "valkey-config")},
				},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "valkey-config", MountPath: "/etc/valkey", ReadOnly: true},
		{Name: "valkey-data", MountPath: "/data"},
	}

	// Add password volume if configured
	if spec.Password != "" || spec.PasswordSecret != nil {
		volumes = append(volumes, corev1.Volume{
			Name: "valkey-auth",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{
					SecretName: instanceResourceName(o, "valkey-auth"),
				},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{
			Name:      "valkey-auth",
			MountPath: "/etc/valkey-auth",
			ReadOnly:  true,
		})
	}

	baseLabels := componentLabels(o.Name, "valkey")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)

	// Build command
	command := []string{"valkey-server", "/etc/valkey/valkey.conf"}
	if spec.Password != "" || spec.PasswordSecret != nil {
		command = append(command, "--requirepass", "$(cat /etc/valkey-auth/password)")
	}

	sts := &appsv1.StatefulSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "valkey"),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: appsv1.StatefulSetSpec{
			ServiceName: instanceResourceName(o, "valkey-headless"),
			Replicas:    &replicas,
			Selector:    &metav1.LabelSelector{MatchLabels: baseLabels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: podAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName:        getServiceAccountName(o, "valkey"),
					ImagePullSecrets:          mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
					NodeSelector:              spec.NodeSelector,
					Tolerations:               spec.Tolerations,
					Affinity:                  spec.Affinity,
					SecurityContext:           spec.PodSecurityContext,
					TopologySpreadConstraints: spec.TopologySpreadConstraints,
					Volumes:                   volumes,
					Containers: []corev1.Container{
						{
							Name:            "valkey",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Command:         []string{"/bin/sh", "-c"},
							Args:            []string{strings.Join(command, " ")},
							Ports:           []corev1.ContainerPort{{Name: "valkey", ContainerPort: port}},
							Resources:       spec.Resources,
							SecurityContext: spec.SecurityContext,
							VolumeMounts:    mounts,
							LivenessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									Exec: &corev1.ExecAction{
										Command: []string{"valkey-cli", "ping"},
									},
								},
								InitialDelaySeconds: 30,
								PeriodSeconds:       10,
							},
							ReadinessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									Exec: &corev1.ExecAction{
										Command: []string{"valkey-cli", "ping"},
									},
								},
								InitialDelaySeconds: 5,
								PeriodSeconds:       5,
							},
						},
					},
				},
			},
		},
	}

	// Add VolumeClaimTemplate if storage is enabled
	if spec.Storage != nil && spec.Storage.Enabled && spec.Storage.ExistingClaim == "" {
		// Default to ReadWriteOnce if not specified
		accessModes := spec.Storage.AccessModes
		if len(accessModes) == 0 {
			accessModes = []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce}
		}

		sts.Spec.VolumeClaimTemplates = []corev1.PersistentVolumeClaim{
			{
				ObjectMeta: metav1.ObjectMeta{
					Name:        "valkey-data",
					Labels:      mergePVCLabels(o, spec.Storage, baseLabels),
					Annotations: mergePVCAnnotations(o, spec.Storage),
				},
				Spec: corev1.PersistentVolumeClaimSpec{
					AccessModes: accessModes,
					Resources: corev1.VolumeResourceRequirements{
						Requests: corev1.ResourceList{
							corev1.ResourceStorage: spec.Storage.Size,
						},
					},
					StorageClassName: spec.Storage.StorageClassName,
				},
			},
		}
	} else if spec.Storage != nil && spec.Storage.ExistingClaim != "" {
		// Use existing PVC
		sts.Spec.Template.Spec.Volumes = append(sts.Spec.Template.Spec.Volumes, corev1.Volume{
			Name: "valkey-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: spec.Storage.ExistingClaim,
				},
			},
		})
	} else {
		// Use emptyDir if storage is not enabled
		sts.Spec.Template.Spec.Volumes = append(sts.Spec.Template.Spec.Volumes, corev1.Volume{
			Name:         "valkey-data",
			VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
		})
	}

	return sts
}

func (r *OpenRAGReconciler) valkeyService(o *openragv1alpha1.OpenRAG, targetNS string) *corev1.Service {
	spec := o.Spec.DoclingComponents.Valkey
	port := int32(6379)
	if spec.Port > 0 {
		port = spec.Port
	}

	baseLabels := componentLabels(o.Name, "valkey")
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:        getServiceName(o, "valkey"),
			Namespace:   targetNS,
			Labels:      mergeServiceLabels(o, spec.ComponentSpec, baseLabels),
			Annotations: mergeServiceAnnotations(o, spec.ComponentSpec),
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: baseLabels,
			Ports: []corev1.ServicePort{
				{Name: "valkey", Port: port, TargetPort: intstr.FromInt32(port), Protocol: corev1.ProtocolTCP},
			},
		},
	}
}

func (r *OpenRAGReconciler) valkeyHeadlessService(o *openragv1alpha1.OpenRAG, targetNS string) *corev1.Service {
	spec := o.Spec.DoclingComponents.Valkey
	port := int32(6379)
	if spec.Port > 0 {
		port = spec.Port
	}

	baseLabels := componentLabels(o.Name, "valkey")
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "valkey-headless"),
			Namespace:   targetNS,
			Labels:      mergeServiceLabels(o, spec.ComponentSpec, baseLabels),
			Annotations: mergeServiceAnnotations(o, spec.ComponentSpec),
		},
		Spec: corev1.ServiceSpec{
			Type:      corev1.ServiceTypeClusterIP,
			ClusterIP: "None",
			Selector:  baseLabels,
			Ports: []corev1.ServicePort{
				{Name: "valkey", Port: port, TargetPort: intstr.FromInt32(port), Protocol: corev1.ProtocolTCP},
			},
		},
	}
}

func (r *OpenRAGReconciler) valkeyConfigMap(o *openragv1alpha1.OpenRAG, targetNS string) *corev1.ConfigMap {
	spec := o.Spec.DoclingComponents.Valkey
	port := int32(6379)
	if spec.Port > 0 {
		port = spec.Port
	}

	maxMemory := "256mb"
	if spec.MaxMemory != "" {
		maxMemory = spec.MaxMemory
	}

	maxMemoryPolicy := "allkeys-lru"
	if spec.MaxMemoryPolicy != "" {
		maxMemoryPolicy = spec.MaxMemoryPolicy
	}

	config := fmt.Sprintf(`# Valkey configuration
port %d
bind 0.0.0.0
protected-mode yes
maxmemory %s
maxmemory-policy %s
save 900 1
save 300 10
save 60 10000
dir /data
appendonly yes
appendfilename "appendonly.aof"
`, port, maxMemory, maxMemoryPolicy)

	baseLabels := componentLabels(o.Name, "valkey")
	return &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instanceResourceName(o, "valkey-config"),
			Namespace: targetNS,
			Labels:    baseLabels,
		},
		Data: map[string]string{
			"valkey.conf": config,
		},
	}
}

func (r *OpenRAGReconciler) valkeySecret(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (*corev1.Secret, error) {
	spec := o.Spec.DoclingComponents.Valkey
	var password string

	if spec.Password != "" {
		password = spec.Password
	} else if spec.PasswordSecret != nil {
		pwd, err := r.readSecretValue(ctx, targetNS, spec.PasswordSecret)
		if err != nil {
			return nil, fmt.Errorf("failed to read valkey password: %w", err)
		}
		password = pwd
	}

	baseLabels := componentLabels(o.Name, "valkey")
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, "valkey-auth"),
			Namespace:   targetNS,
			Labels:      mergeSecretLabels(o, spec.ComponentSpec, baseLabels),
			Annotations: mergeSecretAnnotations(o, spec.ComponentSpec),
		},
		StringData: map[string]string{
			"password": password,
		},
	}, nil
}

func (r *OpenRAGReconciler) reconcileNetworkPolicy(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	labels := componentLabels(o.Name, "lf")

	egress := []networkingv1.NetworkPolicyEgressRule{
		{
			Ports: []networkingv1.NetworkPolicyPort{tcpPort(7860)},
			To:    []networkingv1.NetworkPolicyPeer{{PodSelector: &metav1.LabelSelector{MatchLabels: labels}}},
		},
		{Ports: []networkingv1.NetworkPolicyPort{udpPort(53), tcpPort(53)}},
		{Ports: []networkingv1.NetworkPolicyPort{tcpPort(9200), tcpPort(443)}},
	}

	if o.Spec.Docling != nil {
		egress = append(egress, networkingv1.NetworkPolicyEgressRule{
			Ports: []networkingv1.NetworkPolicyPort{tcpPort(int32(o.Spec.Docling.Port))},
		})
	}

	np := &networkingv1.NetworkPolicy{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instanceResourceName(o, "lf-netpol"),
			Namespace: targetNS,
			Labels:    labels,
		},
		Spec: networkingv1.NetworkPolicySpec{
			PodSelector: metav1.LabelSelector{MatchLabels: labels},
			PolicyTypes: []networkingv1.PolicyType{networkingv1.PolicyTypeIngress, networkingv1.PolicyTypeEgress},
			Ingress: []networkingv1.NetworkPolicyIngressRule{
				{From: []networkingv1.NetworkPolicyPeer{
					{IPBlock: &networkingv1.IPBlock{CIDR: "10.0.0.0/8"}},
					{IPBlock: &networkingv1.IPBlock{CIDR: "172.16.0.0/12"}},
					{IPBlock: &networkingv1.IPBlock{CIDR: "192.168.0.0/16"}},
				}},
			},
			Egress: egress,
		},
	}
	if err := r.setOwnerOrLabel(o, np, targetNS); err != nil {
		return err
	}
	return r.createOrUpdate(ctx, np)
}

func (r *OpenRAGReconciler) setOwnerOrLabel(o *openragv1alpha1.OpenRAG, obj client.Object, targetNS string) error {
	if targetNS == o.Namespace {
		return ctrl.SetControllerReference(o, obj, r.Scheme)
	}
	labels := obj.GetLabels()
	if labels == nil {
		labels = make(map[string]string)
	}
	labels[managedByLabel] = o.Name
	obj.SetLabels(labels)
	return nil
}

func (r *OpenRAGReconciler) createOrUpdate(ctx context.Context, obj client.Object) error {
	existing := obj.DeepCopyObject().(client.Object)
	err := r.Get(ctx, client.ObjectKeyFromObject(obj), existing)
	if errors.IsNotFound(err) {
		// Object doesn't exist, create it with hash annotation
		hash, err := desiredHash(obj)
		if err != nil {
			return err
		}
		setAnnotation(obj, specHashAnnotation, hash)
		return r.Create(ctx, obj)
	}
	if err != nil {
		return err
	}

	// Object exists, check if update is needed
	hash, err := desiredHash(obj)
	if err != nil {
		return err
	}

	existingHash := existing.GetAnnotations()[specHashAnnotation]
	if existingHash == hash {
		// No changes needed
		return nil
	}

	// Update needed - set the new hash and resource version
	setAnnotation(obj, specHashAnnotation, hash)
	obj.SetResourceVersion(existing.GetResourceVersion())
	return r.Update(ctx, obj)
}

// deleteIfExists deletes an object if it exists, ignoring NotFound errors.
// This is useful for cleaning up resources when they are disabled in the CR.
func (r *OpenRAGReconciler) deleteIfExists(ctx context.Context, obj client.Object) error {
	err := r.Delete(ctx, obj)
	if err != nil && !errors.IsNotFound(err) {
		return err
	}
	return nil
}

func desiredHash(obj client.Object) (string, error) {
	tmp := obj.DeepCopyObject().(client.Object)
	tmp.SetResourceVersion("")
	tmp.SetUID("")
	tmp.SetGeneration(0)
	ann := tmp.GetAnnotations()
	if ann != nil {
		delete(ann, specHashAnnotation)
		if len(ann) == 0 {
			ann = nil
		}
		tmp.SetAnnotations(ann)
	}
	data, err := json.Marshal(tmp)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])[:16], nil
}

func setAnnotation(obj client.Object, key, value string) {
	ann := obj.GetAnnotations()
	if ann == nil {
		ann = make(map[string]string)
	}
	ann[key] = value
	obj.SetAnnotations(ann)
}

// flowsDownloadScript is run by the init container to fetch all *.json flow
// files from the langflow-ai/openrag GitHub repository at the given ref.
// It uses only Python stdlib so that python:3-alpine suffices.
const flowsDownloadScript = `
import urllib.request, json, os
ref = os.environ['FLOWS_REF']
api = 'https://api.github.com/repos/langflow-ai/openrag/contents/flows?ref=' + ref
req = urllib.request.Request(api, headers={
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'openrag-operator/1.0',
})
with urllib.request.urlopen(req) as r:
    entries = json.load(r)
os.makedirs('/app/flows', exist_ok=True)
for e in entries:
    if not e['name'].endswith('.json'):
        continue
    print('Downloading ' + e['name'] + '...', flush=True)
    with urllib.request.urlopen(e['download_url']) as r:
        data = r.read()
    with open('/app/flows/' + e['name'], 'wb') as f:
        f.write(data)
print('All flows downloaded', flush=True)
`

// SetupWithManager registers the controller with the manager.
func (r *OpenRAGReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&openragv1alpha1.OpenRAG{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ServiceAccount{}).
		Owns(&corev1.Secret{}).
		Owns(&networkingv1.NetworkPolicy{}).
		Complete(r)
}

// helpers

const managedByLabel = "openr.ag/managed-by"

func targetNamespace(o *openragv1alpha1.OpenRAG) string {
	if o.Spec.TargetNamespace != "" {
		return o.Spec.TargetNamespace
	}
	return o.Namespace
}

// instanceResourceName returns the resource name for a role, respecting InstanceName.
// When InstanceName is empty (default), legacy static names are used for backwards
// compatibility. When set, the InstanceName is embedded to allow multiple CRs per namespace.
func instanceResourceName(o *openragv1alpha1.OpenRAG, role string) string {
	if o.Spec.InstanceName != "" {
		return resourceName(o.Spec.InstanceName, role)
	}
	return legacyResourceName(role)
}

// instanceSAName returns the ServiceAccount name for a role, respecting InstanceName.
func instanceSAName(o *openragv1alpha1.OpenRAG, role string) string {
	if o.Spec.InstanceName != "" {
		return saName(o.Spec.InstanceName, role)
	}
	return legacySAName(role)
}

// resourceName generates a per-CR resource name with the openrag- prefix.
// Max length with an 8-char instanceName: "openrag-"(8) + 8 + "-valkey-headless"(16) = 32 chars.
func resourceName(crName, role string) string {
	switch role {
	case "ds":
		return "openrag-" + crName + "-docling-serve"
	case "dw":
		return "openrag-" + crName + "-docling-worker"
	default:
		return "openrag-" + crName + "-" + role
	}
}

// saName generates per-CR ServiceAccount names.
func saName(crName, role string) string {
	switch role {
	case "ds":
		return "openrag-" + crName + "-docling-serve"
	case "dw":
		return "openrag-" + crName + "-docling-worker"
	default:
		return "openrag-" + crName + "-" + role
	}
}

// legacyResourceName returns the static resource names used before MultiInstance was introduced.
func legacyResourceName(role string) string {
	switch role {
	case "ds":
		return "docling-serve"
	case "dw":
		return "docling-worker"
	default:
		return "openrag-" + role
	}
}

// legacySAName returns the static ServiceAccount names used before MultiInstance was introduced.
func legacySAName(role string) string {
	switch role {
	case "ds":
		return "docling-serve"
	case "dw":
		return "docling-worker"
	default:
		return "openrag-" + role
	}
}

// getServiceAccountName returns the ServiceAccount name for a component.
// If a custom name is specified in the spec, returns that; otherwise returns the default.
func getServiceAccountName(o *openragv1alpha1.OpenRAG, role string) string {
	var customName string
	switch role {
	case "fe":
		customName = o.Spec.Frontend.ServiceAccountName
	case "be":
		customName = o.Spec.Backend.ServiceAccountName
	case "lf":
		customName = o.Spec.Langflow.ServiceAccountName
	case "ds":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Serve != nil {
			customName = o.Spec.DoclingComponents.Serve.ServiceAccountName
		}
	case "dw":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Worker != nil {
			customName = o.Spec.DoclingComponents.Worker.ServiceAccountName
		}
	case "valkey":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Valkey != nil {
			customName = o.Spec.DoclingComponents.Valkey.ServiceAccountName
		}
	}
	if customName != "" {
		return customName
	}
	return instanceSAName(o, role)
}

// shouldCreateServiceAccount returns true if the operator should create the ServiceAccount.
// Checks the CreateServiceAccount boolean flag (defaults to true if not specified).
func shouldCreateServiceAccount(o *openragv1alpha1.OpenRAG, role string) bool {
	var createFlag *bool
	switch role {
	case "fe":
		createFlag = o.Spec.Frontend.CreateServiceAccount
	case "be":
		createFlag = o.Spec.Backend.CreateServiceAccount
	case "lf":
		createFlag = o.Spec.Langflow.CreateServiceAccount
	case "ds":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Serve != nil {
			createFlag = o.Spec.DoclingComponents.Serve.CreateServiceAccount
		}
	case "dw":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Worker != nil {
			createFlag = o.Spec.DoclingComponents.Worker.CreateServiceAccount
		}
	case "valkey":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Valkey != nil {
			createFlag = o.Spec.DoclingComponents.Valkey.CreateServiceAccount
		}
	}
	// Default to true if not specified
	if createFlag == nil {
		return true
	}
	return *createFlag
}

// getServiceName returns the Service name for a component.
// If a custom name is specified in the spec, returns that; otherwise returns the default.
func getServiceName(o *openragv1alpha1.OpenRAG, role string) string {
	var customName string
	switch role {
	case "fe":
		customName = o.Spec.Frontend.ServiceName
	case "be":
		customName = o.Spec.Backend.ServiceName
	case "lf":
		customName = o.Spec.Langflow.ServiceName
	case "ds":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Serve != nil {
			customName = o.Spec.DoclingComponents.Serve.ServiceName
		}
	case "dw":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Worker != nil {
			customName = o.Spec.DoclingComponents.Worker.ServiceName
		}
	case "valkey":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Valkey != nil {
			customName = o.Spec.DoclingComponents.Valkey.ServiceName
		}
	}
	if customName != "" {
		return customName
	}
	return instanceResourceName(o, role)
}

// shouldCreateService returns true if the operator should create the Service.
// Checks the CreateService boolean flag (defaults to true if not specified).
func shouldCreateService(o *openragv1alpha1.OpenRAG, role string) bool {
	var createFlag *bool
	switch role {
	case "fe":
		createFlag = o.Spec.Frontend.CreateService
	case "be":
		createFlag = o.Spec.Backend.CreateService
	case "lf":
		createFlag = o.Spec.Langflow.CreateService
	case "ds":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Serve != nil {
			createFlag = o.Spec.DoclingComponents.Serve.CreateService
		}
	case "dw":
		if o.Spec.DoclingComponents != nil && o.Spec.DoclingComponents.Worker != nil {
			createFlag = o.Spec.DoclingComponents.Worker.CreateService
		}
	}
	// Default to true if not specified
	if createFlag == nil {
		return true
	}
	return *createFlag
}

func componentLabels(crName, role string) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/instance":   crName,
		"app.kubernetes.io/component":  role,
		"app.kubernetes.io/managed-by": "openrag-operator",
	}
}

// mergeLabels merges custom labels with base labels.
// Base labels always take precedence over custom labels.
func mergeLabels(baseLabels, customLabels map[string]string) map[string]string {
	merged := make(map[string]string)
	// Start with custom labels
	for k, v := range customLabels {
		merged[k] = v
	}
	// Base labels always override
	for k, v := range baseLabels {
		merged[k] = v
	}
	return merged
}

// mergeImagePullSecrets merges global and component-specific imagePullSecrets.
// Component-level secrets are added first, followed by global secrets.
// Duplicates (same name) are automatically deduplicated, keeping the first occurrence.
func mergeImagePullSecrets(global, component []corev1.LocalObjectReference) []corev1.LocalObjectReference {
	if len(component) == 0 && len(global) == 0 {
		return nil
	}

	seen := make(map[string]bool)
	var merged []corev1.LocalObjectReference

	// Add component secrets first
	for _, secret := range component {
		if !seen[secret.Name] {
			merged = append(merged, secret)
			seen[secret.Name] = true
		}
	}

	// Add global secrets
	for _, secret := range global {
		if !seen[secret.Name] {
			merged = append(merged, secret)
			seen[secret.Name] = true
		}
	}

	return merged
}

// mergeAnnotations merges custom annotations.
func mergeAnnotations(customAnnotations map[string]string) map[string]string {
	merged := make(map[string]string)
	for k, v := range customAnnotations {
		merged[k] = v
	}
	return merged
}

// mergePodLabels merges custom user labels with operator-managed labels for pod templates.
// Operator-managed labels (app.kubernetes.io/*) cannot be overridden.
func mergePodLabels(baseLabels, customLabels map[string]string) map[string]string {
	return mergeLabels(baseLabels, customLabels)
}

// mergePodAnnotations merges custom user annotations for pod templates.
func mergePodAnnotations(customAnnotations map[string]string) map[string]string {
	return mergeAnnotations(customAnnotations)
}

// mergeDeploymentLabels merges custom labels with base labels for Deployment/StatefulSet objects.
func mergeDeploymentLabels(baseLabels, customLabels map[string]string) map[string]string {
	return mergeLabels(baseLabels, customLabels)
}

// mergeDeploymentAnnotations merges custom annotations for Deployment/StatefulSet objects.
func mergeDeploymentAnnotations(customAnnotations map[string]string) map[string]string {
	return mergeAnnotations(customAnnotations)
}

// Note on map ordering: While Go maps have random iteration order, this doesn't cause
// unnecessary reconciliations because:
// 1. The createOrUpdate() function uses desiredHash() for change detection
// 2. desiredHash() uses json.Marshal() which sorts map keys alphabetically
// 3. Therefore, maps with the same content produce the same hash regardless of build order

// mergeResourceLabels merges labels for infrastructure resources (PVCs, Secrets, Services, ServiceAccounts).
// Priority (highest to lowest):
// 1. Base labels (operator-managed, cannot be overridden)
// 2. Resource-specific labels (e.g., from PersistenceSpec.Labels)
// 3. Component-level labels (e.g., from ComponentSpec.ServiceAccountLabels)
// 4. Common resource labels (from OpenRAGSpec.CommonResourceLabels)
func mergeResourceLabels(o *openragv1alpha1.OpenRAG, baseLabels, componentLabels, resourceLabels map[string]string) map[string]string {
	merged := make(map[string]string)

	// Start with common resource labels (lowest priority)
	for k, v := range o.Spec.CommonResourceLabels {
		merged[k] = v
	}

	// Add component-level labels
	for k, v := range componentLabels {
		merged[k] = v
	}

	// Add resource-specific labels
	for k, v := range resourceLabels {
		merged[k] = v
	}

	// Base labels always override (highest priority)
	for k, v := range baseLabels {
		merged[k] = v
	}

	return merged
}

// mergeResourceAnnotations merges annotations for infrastructure resources.
// Priority (highest to lowest):
// 1. Resource-specific annotations (e.g., from PersistenceSpec.Annotations)
// 2. Component-level annotations (e.g., from ComponentSpec.ServiceAccountAnnotations)
// 3. Common resource annotations (from OpenRAGSpec.CommonResourceAnnotations)
func mergeResourceAnnotations(o *openragv1alpha1.OpenRAG, componentAnnotations, resourceAnnotations map[string]string) map[string]string {
	merged := make(map[string]string)

	// Start with common resource annotations (lowest priority)
	for k, v := range o.Spec.CommonResourceAnnotations {
		merged[k] = v
	}

	// Add component-level annotations
	for k, v := range componentAnnotations {
		merged[k] = v
	}

	// Add resource-specific annotations (highest priority)
	for k, v := range resourceAnnotations {
		merged[k] = v
	}

	return merged
}

// mergePVCLabels merges labels for PersistentVolumeClaim resources.
func mergePVCLabels(o *openragv1alpha1.OpenRAG, storage *openragv1alpha1.PersistenceSpec, baseLabels map[string]string) map[string]string {
	var storageLabels map[string]string
	if storage != nil {
		storageLabels = storage.Labels
	}
	return mergeResourceLabels(o, baseLabels, nil, storageLabels)
}

// mergePVCAnnotations merges annotations for PersistentVolumeClaim resources.
func mergePVCAnnotations(o *openragv1alpha1.OpenRAG, storage *openragv1alpha1.PersistenceSpec) map[string]string {
	var storageAnnotations map[string]string
	if storage != nil {
		storageAnnotations = storage.Annotations
	}
	return mergeResourceAnnotations(o, nil, storageAnnotations)
}

// mergeServiceAccountLabels merges labels for ServiceAccount resources.
func mergeServiceAccountLabels(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec, baseLabels map[string]string) map[string]string {
	return mergeResourceLabels(o, baseLabels, spec.ServiceAccountLabels, nil)
}

// mergeServiceAccountAnnotations merges annotations for ServiceAccount resources.
func mergeServiceAccountAnnotations(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec) map[string]string {
	return mergeResourceAnnotations(o, spec.ServiceAccountAnnotations, nil)
}

// mergeServiceLabels merges labels for Service resources.
func mergeServiceLabels(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec, baseLabels map[string]string) map[string]string {
	return mergeResourceLabels(o, baseLabels, spec.ServiceLabels, nil)
}

// mergeServiceAnnotations merges annotations for Service resources (includes existing ServiceAnnotations).
func mergeServiceAnnotations(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec) map[string]string {
	return mergeResourceAnnotations(o, spec.ServiceAnnotations, nil)
}

// mergeSecretLabels merges labels for Secret resources.
func mergeSecretLabels(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec, baseLabels map[string]string) map[string]string {
	return mergeResourceLabels(o, baseLabels, spec.SecretLabels, nil)
}

// mergeSecretAnnotations merges annotations for Secret resources.
func mergeSecretAnnotations(o *openragv1alpha1.OpenRAG, spec openragv1alpha1.ComponentSpec) map[string]string {
	return mergeResourceAnnotations(o, spec.SecretAnnotations, nil)
}

func replicasOrDefault(r *int32) int32 {
	if r != nil {
		return *r
	}
	return 1
}

func httpProbe(path string, port, initialDelay, period int32) *corev1.Probe {
	portVal := intstr.FromInt32(port)
	return &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   path,
				Port:   portVal,
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: initialDelay,
		PeriodSeconds:       period,
		FailureThreshold:    5,
		TimeoutSeconds:      15,
	}
}

// probeOrDefault returns the custom probe if provided, otherwise returns the default probe.
func probeOrDefault(custom, defaultProbe *corev1.Probe) *corev1.Probe {
	if custom != nil {
		return custom
	}
	return defaultProbe
}

// commandOrDefault returns the custom command if provided, otherwise returns the default command.
func commandOrDefault(custom, defaultCommand []string) []string {
	if len(custom) > 0 {
		return custom
	}
	return defaultCommand
}

// argsOrDefault returns the custom args if provided, otherwise returns the default args.
func argsOrDefault(custom, defaultArgs []string) []string {
	if len(custom) > 0 {
		return custom
	}
	return defaultArgs
}

func tcpPort(p int32) networkingv1.NetworkPolicyPort {
	proto := corev1.ProtocolTCP
	v := intstr.FromInt32(p)
	return networkingv1.NetworkPolicyPort{Port: &v, Protocol: &proto}
}

func udpPort(p int32) networkingv1.NetworkPolicyPort {
	proto := corev1.ProtocolUDP
	v := intstr.FromInt32(p)
	return networkingv1.NetworkPolicyPort{Port: &v, Protocol: &proto}
}

// readSecretValue reads a secret value from a Kubernetes secret without protection.
// Use this for non-critical secrets like external service credentials (OpenSearch, OAuth, etc.)
// that users may need to rotate or update.
// Returns the value and nil error if found, empty string and error otherwise.
func (r *OpenRAGReconciler) readSecretValue(ctx context.Context, namespace string, sel *corev1.SecretKeySelector) (string, error) {
	if sel == nil {
		return "", nil
	}

	secret := &corev1.Secret{}
	err := r.Get(ctx, client.ObjectKey{Namespace: namespace, Name: sel.Name}, secret)
	if err != nil {
		return "", err
	}

	value, ok := secret.Data[sel.Key]
	if !ok {
		return "", fmt.Errorf("key %s not found in secret %s", sel.Key, sel.Name)
	}

	return string(value), nil
}

// readSecretRequiredProtection reads a secret value from a Kubernetes secret with protection.
// Use this for critical security-sensitive secrets (JWT, encryption, and Langflow secret keys).
// It enforces that the secret must be immutable and adds a finalizer to prevent accidental deletion.
// Returns the value and nil error if found, error otherwise.
func (r *OpenRAGReconciler) readSecretRequiredProtection(ctx context.Context, namespace string, sel *corev1.SecretKeySelector) (string, error) {
	if sel == nil {
		return "", nil
	}

	secret := &corev1.Secret{}
	err := r.Get(ctx, client.ObjectKey{Namespace: namespace, Name: sel.Name}, secret)
	if err != nil {
		return "", err
	}

	// Validate that security-sensitive secrets are immutable
	if secret.Immutable == nil || !*secret.Immutable {
		return "", fmt.Errorf("secret %s/%s must be immutable (set immutable: true) to prevent accidental modification of critical security keys", namespace, sel.Name)
	}

	// Add finalizer to prevent deletion (immutable only prevents modification, not deletion)
	needsUpdate := false
	if !controllerutil.ContainsFinalizer(secret, userSecretFinalizer) {
		controllerutil.AddFinalizer(secret, userSecretFinalizer)
		needsUpdate = true
	}

	if needsUpdate {
		if err := r.Update(ctx, secret); err != nil {
			return "", fmt.Errorf("failed to add protection finalizer to secret %s/%s: %w", namespace, sel.Name, err)
		}
	}

	value, ok := secret.Data[sel.Key]
	if !ok {
		return "", fmt.Errorf("key %s not found in secret %s", sel.Key, sel.Name)
	}

	return string(value), nil
}

// collectProtectedSecrets gathers all user-provided secret references from the OpenRAG CR
func collectProtectedSecrets(o *openragv1alpha1.OpenRAG) []*corev1.SecretKeySelector {
	var refs []*corev1.SecretKeySelector

	// Backend secrets
	if o.Spec.Backend.JWTSigningKeySecret != nil {
		refs = append(refs, o.Spec.Backend.JWTSigningKeySecret)
	}
	if o.Spec.Backend.EncryptionKeySecret != nil {
		refs = append(refs, o.Spec.Backend.EncryptionKeySecret)
	}

	// Langflow secret
	if o.Spec.Langflow.SecretKeySecret != nil {
		refs = append(refs, o.Spec.Langflow.SecretKeySecret)
	}

	return refs
}

// getOrGenerateSecret retrieves a secret value following this priority:
// 1. If userSecretRef is provided in CR, read from that secret
// 2. If default secret exists (auto-generated), read from that
// 3. If value exists in existing .env secret, use that (for backward compatibility)
// 4. Generate a new secret and store it in a default Kubernetes secret
// Auto-generated secrets are stored as immutable Kubernetes secrets with -default suffix for better debuggability.
func (r *OpenRAGReconciler) getOrGenerateSecret(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string, userSecretRef *corev1.SecretKeySelector, envKeyName, envSecretName string, genFunc func() (string, error)) (string, error) {
	// Read user-provided secret if specified
	var userProvidedValue string
	if userSecretRef != nil {
		value, err := r.readSecretRequiredProtection(ctx, targetNS, userSecretRef)
		if err != nil {
			return "", fmt.Errorf("failed to read user-provided secret for %s: %w", envKeyName, err)
		}
		userProvidedValue = value
	}

	// Construct default secret name (auto-generated by operator)
	// Convert envKeyName to DNS-compliant format (lowercase, hyphens instead of underscores)
	dnsCompliantName := strings.ToLower(strings.ReplaceAll(envKeyName, "_", "-"))
	defaultSecretName := o.Name + "-" + dnsCompliantName + "-default"

	// Check if default secret exists (auto-generated in previous reconcile)
	var defaultSecretValue string
	defaultSecret := &corev1.Secret{}
	err := r.Get(ctx, client.ObjectKey{Name: defaultSecretName, Namespace: targetNS}, defaultSecret)
	switch {
	case err == nil:
		// Default secret exists, read the value
		if val, ok := defaultSecret.Data["value"]; ok {
			defaultSecretValue = string(val)
		}
	case !errors.IsNotFound(err):
		return "", fmt.Errorf("failed to read default secret %s for %s: %w", defaultSecretName, envKeyName, err)
	}

	// Check if key exists in the existing .env secret (for backward compatibility)
	var existingEnvValue string
	existingEnvSecret := &corev1.Secret{}
	err = r.Get(ctx, client.ObjectKey{Name: envSecretName, Namespace: targetNS}, existingEnvSecret)
	switch {
	case err == nil:
		existingEnvValue = parseEnvValue(string(existingEnvSecret.Data[".env"]), envKeyName)
	case !errors.IsNotFound(err):
		return "", fmt.Errorf("failed to read existing env secret %s for %s: %w", envSecretName, envKeyName, err)
	}

	// If both user-provided secret and default/existing value exist, they MUST match
	// This prevents users from changing secret references or modifying secret values after initial deployment
	existingValue := defaultSecretValue
	if existingValue == "" {
		existingValue = existingEnvValue
	}
	if userProvidedValue != "" && existingValue != "" {
		if userProvidedValue != existingValue {
			return "", fmt.Errorf("security violation: %s value mismatch between user-provided secret and existing value (secret reference or value has been changed after initial deployment - this is not allowed for critical security keys)", envKeyName)
		}
	}

	// Priority 1: Use user-provided value if available
	if userProvidedValue != "" {
		return userProvidedValue, nil
	}

	// Priority 2: Use default secret value if available (auto-generated)
	if defaultSecretValue != "" {
		return defaultSecretValue, nil
	}

	// Priority 3: Use existing .env value if available (backward compatibility - never regenerate)
	if existingEnvValue != "" {
		return existingEnvValue, nil
	}

	// Priority 4: Generate new secret and store it in a default Kubernetes secret
	newSecret, err := genFunc()
	if err != nil {
		return "", fmt.Errorf("failed to generate secret for %s: %w", envKeyName, err)
	}

	// Create immutable Kubernetes secret for the auto-generated value
	immutableTrue := true
	generatedTime := metav1.Now().Format(time.RFC3339)
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      defaultSecretName,
			Namespace: targetNS,
			Labels: map[string]string{
				"app.kubernetes.io/managed-by": "openrag-operator",
				"openr.ag/auto-generated":      "true",
				"openr.ag/openrag-name":        o.Name,
			},
			Annotations: map[string]string{
				"openr.ag/generated-at": generatedTime,
				"openr.ag/secret-key":   envKeyName,
				"openr.ag/tenant-id":    o.Spec.TenantID,
				immutableAnnotation:     "true",
			},
			Finalizers: []string{userSecretFinalizer},
		},
		Immutable: &immutableTrue,
		Data: map[string][]byte{
			"value": []byte(newSecret),
		},
	}

	// Set owner reference or label
	if err := r.setOwnerOrLabel(o, secret, targetNS); err != nil {
		return "", err
	}

	// Create the secret
	if err := r.createOrUpdate(ctx, secret); err != nil {
		return "", fmt.Errorf("failed to create default secret %s for %s: %w", defaultSecretName, envKeyName, err)
	}

	// Log the secret generation for auditing and debugging
	logger := log.FromContext(ctx)
	logger.Info("Generated new secret and created default Kubernetes secret",
		"secretKey", envKeyName,
		"defaultSecretName", defaultSecretName,
		"openragName", o.Name,
		"namespace", o.Namespace,
		"tenantId", o.Spec.TenantID,
		"targetNamespace", targetNS)

	return newSecret, nil
}

// calculateHash calculates the SHA256 hash of a string and returns the hex-encoded result.
// This is used to create annotations on pod templates that trigger rolling restarts when secrets change.
func calculateHash(content string) string {
	hash := sha256.Sum256([]byte(content))
	return hex.EncodeToString(hash[:])
}
