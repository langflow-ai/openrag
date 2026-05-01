package controller

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
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
	client.Client
	Scheme *runtime.Scheme
}

func NewOpenRAGReconciler(c client.Client, s *runtime.Scheme) *OpenRAGReconciler {
	return &OpenRAGReconciler{Client: c, Scheme: s}
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

	if instance.Spec.TargetNamespace != "" && instance.Spec.TargetNamespace != instance.Namespace {
		if !controllerutil.ContainsFinalizer(instance, finalizer) {
			controllerutil.AddFinalizer(instance, finalizer)
			if err := r.Update(ctx, instance); err != nil {
				return ctrl.Result{}, err
			}
		}
	}

	targetNS := targetNamespace(instance)

	if err := r.reconcileNamespace(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("namespace: %w", err)
	}
	if err := r.reconcileServiceAccounts(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("service accounts: %w", err)
	}
	if err := r.reconcileGeneratedCreds(ctx, instance, targetNS); err != nil {
		return ctrl.Result{}, fmt.Errorf("generated creds: %w", err)
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

	ns := &corev1.Namespace{}
	err := r.Get(ctx, client.ObjectKey{Name: o.Spec.TargetNamespace}, ns)
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
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:      saName(o.Name, role),
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

// reconcileGeneratedCreds creates a stable Secret holding auto-generated
// LANGFLOW_SECRET_KEY and OPENRAG_ENCRYPTION_KEY. It is only created once —
// subsequent reconcile loops skip it to preserve the generated values.
func (r *OpenRAGReconciler) reconcileGeneratedCreds(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	secretName := resourceName(o.Name, "gen-creds")
	existing := &corev1.Secret{}
	err := r.Get(ctx, client.ObjectKey{Name: secretName, Namespace: targetNS}, existing)
	if err == nil {
		return nil // already exists, don't overwrite stable keys
	}
	if !errors.IsNotFound(err) {
		return err
	}

	langflowKey, err := generateKey(32)
	if err != nil {
		return err
	}
	encryptionKey, err := generateKey(32)
	if err != nil {
		return err
	}

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      secretName,
			Namespace: targetNS,
			Labels:    map[string]string{"app.kubernetes.io/managed-by": "openrag-operator"},
		},
		StringData: map[string]string{
			"LANGFLOW_SECRET_KEY":    langflowKey,
			"OPENRAG_ENCRYPTION_KEY": encryptionKey,
		},
	}
	if err := r.setOwnerOrLabel(o, secret, targetNS); err != nil {
		return err
	}
	return r.Create(ctx, secret)
}

// reconcileEnvSecrets creates / updates the backend and Langflow .env Secrets
// from CR fields and fixed runtime defaults.
func (r *OpenRAGReconciler) reconcileEnvSecrets(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type envDef struct {
		name    string
		content string
	}
	defs := []envDef{
		{resourceName(o.Name, "be-env"), r.buildBackendEnv(o)},
		{resourceName(o.Name, "lf-env"), r.buildLangflowEnv(o)},
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

func (r *OpenRAGReconciler) buildBackendEnv(o *openragv1alpha1.OpenRAG) string {
	var b strings.Builder
	w := func(k, v string) { fmt.Fprintf(&b, "%s=%s\n", k, v) }

	// Operator-derived values
	w("LANGFLOW_URL", "http://"+resourceName(o.Name, "lf")+":7860")

	if o.Spec.TenantID != "" {
		w("TENANT_ID", o.Spec.TenantID)
	}

	// Flow IDs
	if f := o.Spec.Backend.FlowIDs; f != nil {
		if f.Chat != "" {
			w("LANGFLOW_CHAT_FLOW_ID", f.Chat)
		}
		if f.Ingest != "" {
			w("LANGFLOW_INGEST_FLOW_ID", f.Ingest)
		}
		if f.URLIngest != "" {
			w("LANGFLOW_URL_INGEST_FLOW_ID", f.URLIngest)
		}
		if f.Nudges != "" {
			w("NUDGES_FLOW_ID", f.Nudges)
		}
	}

	// OpenSearch
	if os := o.Spec.OpenSearch; os != nil {
		w("OPENSEARCH_HOST", os.Host)
		port := os.Port
		if port == 0 {
			port = 9200
		}
		w("OPENSEARCH_PORT", fmt.Sprintf("%d", port))
		scheme := os.Scheme
		if scheme == "" {
			scheme = "https"
		}
		w("OPENSEARCH_URL", fmt.Sprintf("%s://%s:%d", scheme, os.Host, port))
		if os.IndexName != "" {
			w("OPENSEARCH_INDEX_NAME", os.IndexName)
		}
		// Username injected as env var from credentials secret when set;
		// fall back to the common default.
		if os.CredentialsSecret == "" {
			w("OPENSEARCH_USERNAME", "admin")
		}
	}

	// WatsonX non-sensitive fields
	if wx := o.Spec.WatsonX; wx != nil {
		if wx.Endpoint != "" {
			w("WATSONX_ENDPOINT", wx.Endpoint)
		}
		if wx.ProjectID != "" {
			w("WATSONX_PROJECT_ID", wx.ProjectID)
		}
	}

	// LLM / Embedding
	if l := o.Spec.LLM; l != nil {
		if l.Provider != "" {
			w("LLM_PROVIDER", l.Provider)
		}
		if l.Model != "" {
			w("LLM_MODEL", l.Model)
		}
	}
	if e := o.Spec.Embedding; e != nil {
		if e.Provider != "" {
			w("EMBEDDING_PROVIDER", e.Provider)
		}
		if e.Model != "" {
			w("EMBEDDING_MODEL", e.Model)
		}
	}

	// OAuth non-sensitive fields
	if o.Spec.Backend.IBMAuthEnabled {
		w("IBM_AUTH_ENABLED", "true")
	}
	if o.Spec.Backend.OAuthBrokerURL != "" {
		w("OAUTH_BROKER_URL", o.Spec.Backend.OAuthBrokerURL)
	}
	if oa := o.Spec.Backend.OAuth; oa != nil {
		if oa.Google != nil && oa.Google.ClientID != "" {
			w("GOOGLE_OAUTH_CLIENT_ID", oa.Google.ClientID)
		}
		if oa.Microsoft != nil && oa.Microsoft.ClientID != "" {
			w("MICROSOFT_GRAPH_OAUTH_CLIENT_ID", oa.Microsoft.ClientID)
		}
	}

	// Docling
	if d := o.Spec.Docling; d != nil {
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		w("DOCLING_SERVE_URL", fmt.Sprintf("%s://%s:%d", scheme, d.Host, port))
	}

	// Fixed runtime defaults
	w("LANGFLOW_TIMEOUT", "2400")
	w("LANGFLOW_CONNECT_TIMEOUT", "30")
	w("INGESTION_TIMEOUT", "3600")
	w("UPLOAD_BATCH_SIZE", "25")
	w("LANGFLOW_KEY_RETRIES", "15")
	w("LANGFLOW_KEY_RETRY_DELAY", "2")
	w("LANGFLOW_KEY", "")
	w("LANGFLOW_AUTO_LOGIN", "true")
	w("OPENRAG_DATA_PATH", "/app/backend-data")
	w("OPENRAG_DOCUMENTS_PATH", "/app/openrag-documents")
	w("OPENRAG_DOCUMENT_PATH", "/app/openrag-documents")
	w("OPENRAG_FLOWS_BACKUP_PATH", "/app/backend-data/flow-backups")
	w("OPENRAG_KEYS_PATH", "/app/backend-data/keys")
	w("OPENRAG_CONFIG_PATH", "/app/backend-data/config")
	w("OPENRAG_VERSION", "latest")
	w("OPENSEARCH_DATA_PATH", "./opensearch-data")
	w("LOG_LEVEL", "DEBUG")
	w("LOG_FORMAT", "json")
	w("ACCESS_LOG", "true")
	w("SERVICE_NAME", "openrag")
	w("ENVIRONMENT", "development")
	w("INGEST_SAMPLE_DATA", "true")
	w("DISABLE_INGEST_WITH_LANGFLOW", "false")
	w("MAX_WORKERS", "4")
	w("SEGMENT_WRITE_KEY", "kUm1zOjl8CGbtMmEVOtmAaqyIpU7ExFb")

	return b.String()
}

func (r *OpenRAGReconciler) buildLangflowEnv(o *openragv1alpha1.OpenRAG) string {
	var b strings.Builder
	w := func(k, v string) { fmt.Fprintf(&b, "%s=%s\n", k, v) }

	if o.Spec.TenantID != "" {
		w("TENANT_ID", o.Spec.TenantID)
	}

	// OpenSearch
	if os := o.Spec.OpenSearch; os != nil {
		w("OPENSEARCH_HOST", os.Host)
		port := os.Port
		if port == 0 {
			port = 9200
		}
		w("OPENSEARCH_PORT", fmt.Sprintf("%d", port))
		scheme := os.Scheme
		if scheme == "" {
			scheme = "https"
		}
		w("OPENSEARCH_URL", fmt.Sprintf("%s://%s:%d", scheme, os.Host, port))
		if os.IndexName != "" {
			w("OPENSEARCH_INDEX_NAME", os.IndexName)
		}
	}

	// WatsonX non-sensitive fields
	if wx := o.Spec.WatsonX; wx != nil {
		if wx.Endpoint != "" {
			w("WATSONX_ENDPOINT", wx.Endpoint)
		}
		if wx.ProjectID != "" {
			w("WATSONX_PROJECT_ID", wx.ProjectID)
		}
	}

	// LLM / Embedding
	if l := o.Spec.LLM; l != nil {
		if l.Provider != "" {
			w("LLM_PROVIDER", l.Provider)
		}
		if l.Model != "" {
			w("LLM_MODEL", l.Model)
		}
	}
	if e := o.Spec.Embedding; e != nil {
		if e.Provider != "" {
			w("EMBEDDING_PROVIDER", e.Provider)
		}
		if e.Model != "" {
			w("EMBEDDING_MODEL", e.Model)
		}
	}

	// Docling
	if d := o.Spec.Docling; d != nil {
		scheme := d.Scheme
		if scheme == "" {
			scheme = "http"
		}
		port := d.Port
		if port == 0 {
			port = 5001
		}
		w("DOCLING_SERVE_URL", fmt.Sprintf("%s://%s:%d", scheme, d.Host, port))
	}

	// Database URL
	dbURL := o.Spec.Langflow.DatabaseURL
	if dbURL == "" {
		dbURL = "sqlite:////app/data/langflow.db"
	}
	w("LANGFLOW_DATABASE_URL", dbURL)

	// Fixed runtime defaults
	w("LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT", "JWT,OPENRAG_QUERY_FILTER,OPENSEARCH_PASSWORD,OPENSEARCH_URL,OPENSEARCH_INDEX_NAME,DOCLING_SERVE_URL,OWNER,OWNER_NAME,OWNER_EMAIL,CONNECTOR_TYPE,DOCUMENT_ID,SOURCE_URL,ALLOWED_USERS,ALLOWED_GROUPS,FILENAME,MIMETYPE,FILESIZE,SELECTED_EMBEDDING_MODEL,OPENAI_API_KEY,ANTHROPIC_API_KEY,WATSONX_API_KEY,WATSONX_ENDPOINT,WATSONX_PROJECT_ID,OLLAMA_BASE_URL")
	w("LANGFLOW_SKIP_AUTH_AUTO_LOGIN", "true")
	w("LANGFLOW_NEW_USER_IS_ACTIVE", "false")
	w("LANGFLOW_WORKERS", "4")
	w("LANGFLOW_CONFIG_DIR", "/tmp")
	w("LANGFLOW_LOG_LEVEL", "DEBUG")
	w("HIDE_GETTING_STARTED_PROGRESS", "true")
	w("LANGFLOW_AUTO_LOGIN", "true")
	w("LANGFLOW_ENABLE_SUPERUSER_CLI", "false")
	w("LANGFLOW_ALEMBIC_LOG_TO_STDOUT", "true")
	w("LANGFLOW_DEACTIVATE_TRACING", "true")
	w("LANGFLOW_LOAD_FLOWS_PATH", "/app/flows")
	w("LANGFUSE_HOST", "https://cloud.langfuse.com")
	w("LANGFLOW_KEY_RETRIES", "15")
	w("LANGFLOW_KEY_RETRY_DELAY", "2")
	// Flow context defaults
	w("JWT", "None")
	w("OWNER", "None")
	w("OWNER_NAME", "None")
	w("OWNER_EMAIL", "None")
	w("CONNECTOR_TYPE", "system")
	w("CONNECTOR_TYPE_URL", "url")
	w("DOCUMENT_ID", "")
	w("SOURCE_URL", "")
	w("ALLOWED_USERS", "[]")
	w("ALLOWED_GROUPS", "[]")
	w("OPENRAG_QUERY_FILTER", "{}")
	w("FILENAME", "None")
	w("MIMETYPE", "None")
	w("FILESIZE", "0")
	w("SELECTED_EMBEDDING_MODEL", "")
	w("OPENAI_API_KEY", "None")
	w("ANTHROPIC_API_KEY", "None")
	w("OLLAMA_BASE_URL", "None")

	return b.String()
}

func (r *OpenRAGReconciler) reconcilePVCs(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	type pvcDef struct {
		name    string
		storage *openragv1alpha1.PersistenceSpec
	}
	defs := []pvcDef{
		{resourceName(o.Name, "lf-data"), o.Spec.Langflow.Storage},
		{resourceName(o.Name, "be-data"), o.Spec.Backend.Storage},
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
		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName(o.Name, d.role),
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
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "fe"),
			Namespace: targetNS,
			Labels:    componentLabels(o.Name, "fe"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "fe")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "fe")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "fe"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
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
								{Name: "OPENRAG_BACKEND_HOST", Value: resourceName(o.Name, "be")},
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
				Secret: &corev1.SecretVolumeSource{SecretName: resourceName(o.Name, "be-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "backend-temp", MountPath: "/tmp"},
		{Name: "backend-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := resourceName(o.Name, "be-data")
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

	envVars := r.backendSensitiveEnvVars(o)
	if spec.JWTSigningKeySecret != nil {
		envVars = append(envVars, corev1.EnvVar{
			Name:      "JWT_SIGNING_KEY",
			ValueFrom: &corev1.EnvVarSource{SecretKeyRef: spec.JWTSigningKeySecret},
		})
	}
	envVars = append(envVars, spec.Env...)

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "be"),
			Namespace: targetNS,
			Labels:    componentLabels(o.Name, "be"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "be")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "be")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "be"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					Volumes:            volumes,
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

// backendSensitiveEnvVars returns env vars sourced from Secrets for the backend pod.
// These override any matching keys in the mounted .env file.
func (r *OpenRAGReconciler) backendSensitiveEnvVars(o *openragv1alpha1.OpenRAG) []corev1.EnvVar {
	genCreds := resourceName(o.Name, "gen-creds")
	var ev []corev1.EnvVar

	// LANGFLOW_SECRET_KEY
	if o.Spec.Langflow.SecretKeySecret != nil {
		ev = append(ev, secretEnvVar("LANGFLOW_SECRET_KEY", o.Spec.Langflow.SecretKeySecret))
	} else {
		ev = append(ev, secretEnvVar("LANGFLOW_SECRET_KEY", &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: genCreds},
			Key:                  "LANGFLOW_SECRET_KEY",
		}))
	}

	// OPENRAG_ENCRYPTION_KEY
	if o.Spec.Backend.EncryptionKeySecret != nil {
		ev = append(ev, secretEnvVar("OPENRAG_ENCRYPTION_KEY", o.Spec.Backend.EncryptionKeySecret))
	} else {
		ev = append(ev, secretEnvVar("OPENRAG_ENCRYPTION_KEY", &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: genCreds},
			Key:                  "OPENRAG_ENCRYPTION_KEY",
		}))
	}

	// OpenSearch credentials
	if o.Spec.OpenSearch != nil && o.Spec.OpenSearch.CredentialsSecret != "" {
		cred := o.Spec.OpenSearch.CredentialsSecret
		ev = append(ev,
			secretEnvVar("OPENSEARCH_USERNAME", &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: cred}, Key: "username",
			}),
			secretEnvVar("OPENSEARCH_PASSWORD", &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: cred}, Key: "password",
			}),
		)
	}

	// WatsonX API key
	if o.Spec.WatsonX != nil && o.Spec.WatsonX.APIKeySecret != nil {
		ev = append(ev, secretEnvVar("WATSONX_API_KEY", o.Spec.WatsonX.APIKeySecret))
	}

	// OAuth secrets
	if oa := o.Spec.Backend.OAuth; oa != nil {
		if oa.Google != nil && oa.Google.ClientSecret != nil {
			ev = append(ev, secretEnvVar("GOOGLE_OAUTH_CLIENT_SECRET", oa.Google.ClientSecret))
		}
		if oa.Microsoft != nil && oa.Microsoft.ClientSecret != nil {
			ev = append(ev, secretEnvVar("MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET", oa.Microsoft.ClientSecret))
		}
	}

	return ev
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
				Secret: &corev1.SecretVolumeSource{SecretName: resourceName(o.Name, "lf-env")},
			},
		},
	}
	mounts := []corev1.VolumeMount{
		{Name: "langflow-temp", MountPath: "/tmp"},
		{Name: "langflow-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true},
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := resourceName(o.Name, "lf-data")
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

	envVars := r.langflowSensitiveEnvVars(o)
	envVars = append(envVars, spec.Env...)

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "lf"),
			Namespace: targetNS,
			Labels:    componentLabels(o.Name, "lf"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "lf")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "lf")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "lf"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					InitContainers:     initContainers,
					Volumes:            volumes,
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

// langflowSensitiveEnvVars returns env vars sourced from Secrets for the Langflow pod.
func (r *OpenRAGReconciler) langflowSensitiveEnvVars(o *openragv1alpha1.OpenRAG) []corev1.EnvVar {
	genCreds := resourceName(o.Name, "gen-creds")
	var ev []corev1.EnvVar

	// LANGFLOW_SECRET_KEY
	if o.Spec.Langflow.SecretKeySecret != nil {
		ev = append(ev, secretEnvVar("LANGFLOW_SECRET_KEY", o.Spec.Langflow.SecretKeySecret))
	} else {
		ev = append(ev, secretEnvVar("LANGFLOW_SECRET_KEY", &corev1.SecretKeySelector{
			LocalObjectReference: corev1.LocalObjectReference{Name: genCreds},
			Key:                  "LANGFLOW_SECRET_KEY",
		}))
	}

	// OpenSearch credentials
	if o.Spec.OpenSearch != nil && o.Spec.OpenSearch.CredentialsSecret != "" {
		cred := o.Spec.OpenSearch.CredentialsSecret
		ev = append(ev,
			secretEnvVar("OPENSEARCH_USERNAME", &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: cred}, Key: "username",
			}),
			secretEnvVar("OPENSEARCH_PASSWORD", &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: cred}, Key: "password",
			}),
		)
	}

	// WatsonX API key
	if o.Spec.WatsonX != nil && o.Spec.WatsonX.APIKeySecret != nil {
		ev = append(ev, secretEnvVar("WATSONX_API_KEY", o.Spec.WatsonX.APIKeySecret))
	}

	return ev
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
			Name:      resourceName(o.Name, "lf-netpol"),
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
	hash, err := desiredHash(obj)
	if err != nil {
		return err
	}
	setAnnotation(obj, specHashAnnotation, hash)

	existing := obj.DeepCopyObject().(client.Object)
	if err := r.Get(ctx, client.ObjectKeyFromObject(obj), existing); err != nil {
		if errors.IsNotFound(err) {
			return r.Create(ctx, obj)
		}
		return err
	}

	if existing.GetAnnotations()[specHashAnnotation] == hash {
		return nil
	}

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

func resourceName(crName, role string) string {
	return crName + "-openrag-" + role
}

func saName(crName, role string) string {
	return "openrag-" + crName + "-" + role
}

func componentLabels(crName, role string) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/instance":   crName,
		"app.kubernetes.io/component":  role,
		"app.kubernetes.io/managed-by": "openrag-operator",
	}
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

func secretEnvVar(name string, sel *corev1.SecretKeySelector) corev1.EnvVar {
	return corev1.EnvVar{
		Name:      name,
		ValueFrom: &corev1.EnvVarSource{SecretKeyRef: sel},
	}
}

func generateKey(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.URLEncoding.EncodeToString(b), nil
}
