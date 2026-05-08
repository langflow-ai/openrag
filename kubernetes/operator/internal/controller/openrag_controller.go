package controller

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/utils/ptr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

const (
	finalizer          = "openr.ag/namespace-cleanup"
	specHashAnnotation = "openr.ag/spec-hash"
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

	instance := &openragv1alpha1.OpenRAG{}
	if err := r.Get(ctx, req.NamespacedName, instance); err != nil {
		if errors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	if !instance.DeletionTimestamp.IsZero() {
		return ctrl.Result{}, r.handleDeletion(ctx, instance)
	}

	targetNS := targetNamespace(instance)
	if targetNS != instance.Namespace {
		if !controllerutil.ContainsFinalizer(instance, finalizer) {
			controllerutil.AddFinalizer(instance, finalizer)
			if err := r.Update(ctx, instance); err != nil {
				return ctrl.Result{}, err
			}
			// Return immediately after adding finalizer to avoid duplicate reconciliation.
			// The update will trigger a new reconcile that will do the actual work.
			logger.Info("added finalizer, will reconcile again")
			return ctrl.Result{}, nil
		}
	}

	if err := r.reconcileNamespace(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("namespace: %w", err)
	}
	if err := r.reconcileServiceAccounts(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("service accounts: %w", err)
	}
	if err := r.reconcileEnvSecrets(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("env secrets: %w", err)
	}
	if err := r.reconcilePVCs(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("pvcs: %w", err)
	}
	if err := r.reconcileServices(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("services: %w", err)
	}
	if err := r.reconcileDeployments(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("deployments: %w", err)
	}
	if instance.Spec.NetworkPolicy.Enabled {
		if err := r.reconcileNetworkPolicy(ctx, instance, targetNS); err != nil {
			return ctrl.Result{}, fmt.Errorf("network policy: %w", err)
		}
	}

	logger.Info("reconciled OpenRAG instance", "name", instance.Name, "targetNamespace", targetNS)
	return ctrl.Result{}, nil
}

func (r *OpenRAGReconciler) handleDeletion(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	if !controllerutil.ContainsFinalizer(o, finalizer) {
		return nil
	}

	targetNS := targetNamespace(o)
	ns := &corev1.Namespace{}
	err := r.Get(ctx, client.ObjectKey{Name: targetNS}, ns)
	if err != nil && !errors.IsNotFound(err) {
		return err
	}
	if err == nil {
		if ns.Labels[managedByLabel] == o.Name {
			if err := r.Delete(ctx, ns); err != nil && !errors.IsNotFound(err) {
				return err
			}
		}
	}

	controllerutil.RemoveFinalizer(o, finalizer)
	return r.Update(ctx, o)
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
	for _, role := range []string{"fe", "be", "lf"} {
		// Only create ServiceAccount if flag is true
		if !shouldCreateServiceAccount(o, role) {
			continue
		}

		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:      getServiceAccountName(o, role), // Use custom name if specified
				Namespace: targetNS,
				Labels:    componentLabels(o.Name, role),
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
			return strings.TrimPrefix(line, prefix)
		}
	}
	return ""
}

// reconcileEnvSecrets creates / updates the backend and Langflow .env Secrets
// from CR fields and fixed runtime defaults.
// All sensitive values (whether user-provided or generated) are consolidated into .env files.
func (r *OpenRAGReconciler) reconcileEnvSecrets(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	// Build backend .env content with all secrets consolidated
	backendEnvContent, err := r.buildBackendEnv(ctx, o, targetNS)
	if err != nil {
		return fmt.Errorf("failed to build backend env: %w", err)
	}

	// Build langflow .env content with all secrets consolidated
	langflowEnvContent, err := r.buildLangflowEnv(ctx, o, targetNS)
	if err != nil {
		return fmt.Errorf("failed to build langflow env: %w", err)
	}

	type envDef struct {
		name    string
		content string
	}
	defs := []envDef{
		{resourceName("be-env"), backendEnvContent},
		{resourceName("lf-env"), langflowEnvContent},
	}
	for _, d := range defs {
		secret := &corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{
				Name:      d.name,
				Namespace: targetNS,
				Labels:    map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"},
			},
			StringData: map[string]string{".env": d.content},
		}
		if err := r.setOwnerOrLabel(o, secret, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, secret); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) buildBackendEnv(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (string, error) {
	// Start with defaults, operator env, and CR env (three-level priority)
	envVars := r.EnvVarManager.GetBackendEnvVars(o.Spec.Backend.Env)

	// Get or generate encryption key (AES-256)
	// Priority: 1) User-provided secret in CR, 2) Existing value in .env, 3) Generate new
	encryptionKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Backend.EncryptionKeySecret, "OPENRAG_ENCRYPTION_KEY", resourceName("be-env"), GenerateAESKeyString32)
	if err != nil {
		return "", fmt.Errorf("failed to get encryption key: %w", err)
	}
	envVars["OPENRAG_ENCRYPTION_KEY"] = encryptionKey

	// Get or generate JWT signing key (base64 secret)
	jwtSigningKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Backend.JWTSigningKeySecret, "JWT_PRIVATE_KEY", resourceName("be-env"), generateBase64SecretKey)
	if err != nil {
		return "", fmt.Errorf("failed to get JWT signing key: %w", err)
	}
	envVars["JWT_PRIVATE_KEY"] = jwtSigningKey

	// Operator-derived values (always set)
	envVars["LANGFLOW_URL"] = "http://" + getServiceName(o, "lf") + ":7860"

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
	if d := o.Spec.Docling; d != nil {
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("%s://%s:%d", scheme, d.Host, port)
	}

	// Convert map to .env file format
	return r.EnvVarManager.BuildEnvFileContent(envVars), nil
}

func (r *OpenRAGReconciler) buildLangflowEnv(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) (string, error) {
	// Start with defaults, operator env, and CR env (three-level priority)
	envVars := r.EnvVarManager.GetLangflowEnvVars(o.Spec.Langflow.Env)

	// Get or generate Langflow secret key (Fernet key - base64, shared with backend)
	langflowSecretKey, err := r.getOrGenerateSecret(ctx, o, targetNS, o.Spec.Langflow.SecretKeySecret, "LANGFLOW_SECRET_KEY", resourceName("lf-env"), generateBase64SecretKey)
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
	if d := o.Spec.Docling; d != nil {
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		envVars["DOCLING_SERVE_URL"] = fmt.Sprintf("%s://%s:%d", scheme, d.Host, port)
	}

	// Convert map to .env file format
	return r.EnvVarManager.BuildEnvFileContent(envVars), nil
}

func (r *OpenRAGReconciler) reconcilePVCs(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type pvcDef struct {
		name    string
		storage *openragv1alpha1.PersistenceSpec
	}
	defs := []pvcDef{
		{resourceName("lf-data"), o.Spec.Langflow.Storage},
		{resourceName("be-data"), o.Spec.Backend.Storage},
	}
	for _, d := range defs {
		if d.storage == nil || !d.storage.Enabled || d.storage.ExistingClaim != "" {
			continue
		}
		pvc := &corev1.PersistentVolumeClaim{
			ObjectMeta: metav1.ObjectMeta{
				Name:      d.name,
				Namespace: targetNS,
				Labels:    map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"},
			},
			Spec: corev1.PersistentVolumeClaimSpec{
				AccessModes:      []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
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
	}
	defs := []svcDef{
		{"fe", 3000},
		{"be", 8000},
		{"lf", 7860},
	}
	for _, d := range defs {
		// Only create Service if flag is true
		if !shouldCreateService(o, d.role) {
			continue
		}

		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:      getServiceName(o, d.role), // Use custom name if specified
				Namespace: targetNS,
				Labels:    componentLabels(o.Name, d.role),
			},
			Spec: corev1.ServiceSpec{
				Type:     corev1.ServiceTypeClusterIP,
				Selector: componentLabels(o.Name, d.role),
				Ports: []corev1.ServicePort{
					{Name: "http", Port: d.port, Protocol: corev1.ProtocolTCP},
				},
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

func (r *OpenRAGReconciler) reconcileDeployments(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	deploys := []client.Object{
		r.frontendDeployment(o, targetNS),
		r.backendDeployment(o, targetNS),
		r.langflowDeployment(o, targetNS),
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
			Name:        resourceName("fe"),
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
					Containers: []corev1.Container{
						{
							Name:            "frontend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 3000}},
							Env: append([]corev1.EnvVar{
								{Name: "OPENRAG_BACKEND_HOST", Value: getServiceName(o, "be")},
							}, spec.Env...),
							Resources:      spec.Resources,
							LivenessProbe:  httpProbe("/", 3000, 30, 10),
							ReadinessProbe: httpProbe("/", 3000, 10, 5),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) backendDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
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
				Secret: &corev1.SecretVolumeSource{SecretName: resourceName("be-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "backend-temp", MountPath: "/tmp"},
		{Name: "backend-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := resourceName("be-data")
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

	// All sensitive values are now consolidated in the .env file
	// Only use additional env vars from the CR spec
	envVars := spec.Env

	baseLabels := componentLabels(o.Name, "be")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        resourceName("be"),
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
					SecurityContext: &corev1.PodSecurityContext{
						FSGroup:      ptr.To[int64](1000),
						RunAsUser:    ptr.To[int64](1000),
						RunAsGroup:   ptr.To[int64](1000),
						RunAsNonRoot: ptr.To(true),
					},
					Volumes: volumes,
					Containers: []corev1.Container{
						{
							Name:            "backend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 8000}},
							Env:             envVars,
							Resources:       spec.Resources,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 8000, 45, 30),
							ReadinessProbe:  httpProbe("/health", 8000, 45, 10),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) langflowDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
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
				Secret: &corev1.SecretVolumeSource{SecretName: resourceName("lf-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "langflow-temp", MountPath: "/tmp"},
		{Name: "langflow-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := resourceName("lf-data")
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
	}

	// All sensitive values are now consolidated in the .env file
	// Only use additional env vars from the CR spec
	envVars := spec.Env

	baseLabels := componentLabels(o.Name, "lf")
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        resourceName("lf"),
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
					SecurityContext: &corev1.PodSecurityContext{
						FSGroup:      ptr.To[int64](1000), // Allow volume access for non-root users
						RunAsUser:    ptr.To[int64](1000),
						RunAsGroup:   ptr.To[int64](1000),
						RunAsNonRoot: ptr.To(true),
					},
					InitContainers: initContainers,
					Volumes:        volumes,
					Containers: []corev1.Container{
						{
							Name:            "langflow",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Args:            []string{"run", "--env-file", "/app/.env"},
							Command:         []string{"langflow"},
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 7860}},
							Env:             envVars,
							Resources:       spec.Resources,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 7860, 90, 30),
							ReadinessProbe:  httpProbe("/health", 7860, 90, 30),
						},
					},
				},
			},
		},
	}
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
			Name:      resourceName("lf-netpol"),
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

// resourceName generates a DNS-1035 compliant name for Kubernetes resources.
// Since each namespace is tenant-exclusive, we don't need to include the CR name.
// This provides clean, predictable names: openrag-fe, openrag-be, openrag-lf.
func resourceName(role string) string {
	return "openrag-" + role
}

// saName generates service account names.
// Since each namespace is tenant-exclusive, we don't need to include the CR name.
func saName(role string) string {
	return "openrag-" + role
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
	}
	if customName != "" {
		return customName
	}
	return saName(role)
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
	}
	if customName != "" {
		return customName
	}
	return resourceName(role)
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
		TimeoutSeconds:      10,
	}
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

// readSecretValue reads a secret value from a Kubernetes secret.
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

// getOrGenerateSecret retrieves a secret value following this priority:
// 1. If userSecretRef is provided in CR, read from that secret
// 2. If value exists in existing .env secret, use that (for stability - never regenerate)
// 3. Generate a new secret using the appropriate generation function
// This consolidates all secrets into .env files without creating separate Kubernetes secrets.
func (r *OpenRAGReconciler) getOrGenerateSecret(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string, userSecretRef *corev1.SecretKeySelector, envKeyName, envSecretName string, genFunc func() (string, error)) (string, error) {
	// Priority 1: User-provided secret in CR
	if userSecretRef != nil {
		value, err := r.readSecretValue(ctx, targetNS, userSecretRef)
		if err != nil {
			return "", fmt.Errorf("failed to read user-provided secret for %s: %w", envKeyName, err)
		}
		if value != "" {
			return value, nil
		}
	}

	// Priority 2: Check if key exists in the existing .env secret (for stability)
	existingEnvSecret := &corev1.Secret{}
	err := r.Get(ctx, client.ObjectKey{Name: envSecretName, Namespace: targetNS}, existingEnvSecret)
	switch {
	case err == nil:
		if value := parseEnvValue(string(existingEnvSecret.Data[".env"]), envKeyName); value != "" {
			return value, nil // Never regenerate existing key
		}
	case !errors.IsNotFound(err):
		return "", fmt.Errorf("failed to read existing env secret %s for %s: %w", envSecretName, envKeyName, err)
	}

	// Priority 3: Generate new secret using the provided generation function
	newSecret, err := genFunc()
	if err != nil {
		return "", fmt.Errorf("failed to generate secret for %s: %w", envKeyName, err)
	}

	// Log the secret generation for auditing and debugging
	logger := log.FromContext(ctx)
	logger.Info("Generated new secret",
		"secretKey", envKeyName,
		"openragName", o.Name,
		"namespace", o.Namespace,
		"tenantId", o.Spec.TenantID,
		"targetNamespace", targetNS)

	return newSecret, nil
}
