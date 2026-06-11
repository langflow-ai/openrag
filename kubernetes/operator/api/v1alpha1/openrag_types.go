// Run "make manifests" to regenerate CRD manifests after modifying this file.
// Run "make generate" to regenerate DeepCopy methods after modifying this file.
package v1alpha1

import (
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// PVCReclaimPolicy describes what happens to PVCs when the OpenRAG CR is deleted.
// +kubebuilder:validation:Enum=Retain;Delete
type PVCReclaimPolicy string

const (
	// PVCReclaimRetain means the PVC will be retained when the CR is deleted (preserves user data).
	PVCReclaimRetain PVCReclaimPolicy = "Retain"
	// PVCReclaimDelete means the PVC will be deleted when the CR is deleted (data loss).
	PVCReclaimDelete PVCReclaimPolicy = "Delete"
)

// ComponentSpec defines common configuration shared by all three components.
type ComponentSpec struct {
	// Image is the container image (repository:tag).
	// +kubebuilder:validation:Required
	Image string `json:"image"`

	// +optional
	// +kubebuilder:default=IfNotPresent
	ImagePullPolicy corev1.PullPolicy `json:"imagePullPolicy,omitempty"`

	// ImagePullSecrets for private registries, specific to this component.
	// These are merged with the global imagePullSecrets from the OpenRAG spec.
	// +optional
	// +kubebuilder:validation:XValidation:rule="self.all(x, x.name != '')",message="imagePullSecret name cannot be empty"
	ImagePullSecrets []corev1.LocalObjectReference `json:"imagePullSecrets,omitempty"`

	// +optional
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	Replicas *int32 `json:"replicas,omitempty"`

	// +optional
	Resources corev1.ResourceRequirements `json:"resources,omitempty"`

	// Additional environment variables injected into the container.
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`

	// +optional
	NodeSelector map[string]string `json:"nodeSelector,omitempty"`

	// +optional
	Tolerations []corev1.Toleration `json:"tolerations,omitempty"`

	// +optional
	Affinity *corev1.Affinity `json:"affinity,omitempty"`

	// Labels are custom labels to add to the Deployment/StatefulSet object metadata.
	// These labels appear on the workload resource itself, not the pods.
	// Useful for querying and grouping Deployment/StatefulSet objects.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	Labels map[string]string `json:"labels,omitempty"`

	// Annotations are custom annotations to add to the Deployment/StatefulSet object metadata.
	// These annotations appear on the workload resource itself, not the pods.
	// Useful for GitOps metadata, deployment tracking, and automation tools.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	Annotations map[string]string `json:"annotations,omitempty"`

	// PodLabels are custom labels to add to the pod template.
	// These labels appear on the actual pods created by the Deployment/StatefulSet.
	// Useful for pod selectors, monitoring queries, network policies, and service mesh.
	// Merged with operator-managed labels (app.kubernetes.io/*).
	// Cannot override operator-managed labels.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	PodLabels map[string]string `json:"podLabels,omitempty"`

	// PodAnnotations are custom annotations to add to the pod template.
	// These annotations appear on the actual pods created by the Deployment/StatefulSet.
	// Useful for sidecar injection (Istio, Vault), monitoring (Prometheus), and backup (Velero).
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	PodAnnotations map[string]string `json:"podAnnotations,omitempty"`

	// ServiceAccountName is the name of the ServiceAccount to use for this component's pod.
	// When CreateServiceAccount is true, the operator will create a ServiceAccount with this name.
	// When CreateServiceAccount is false, the ServiceAccount must already exist in the target namespace.
	// If not specified, defaults to "openrag-{role}" (e.g., "openrag-fe", "openrag-be", "openrag-lf").
	// +optional
	ServiceAccountName string `json:"serviceAccountName,omitempty"`

	// CreateServiceAccount indicates whether the operator should create the ServiceAccount.
	// If true (default), the operator creates a ServiceAccount with the name specified in ServiceAccountName.
	// If false, the operator assumes the ServiceAccount already exists and will only reference it.
	// +optional
	// +kubebuilder:default=true
	CreateServiceAccount *bool `json:"createServiceAccount,omitempty"`

	// ServiceName is the name of the Service to use for this component.
	// When CreateService is true, the operator will create a Service with this name.
	// When CreateService is false, the Service must already exist in the target namespace.
	// If not specified, defaults to "openrag-{role}" (e.g., "openrag-fe", "openrag-be", "openrag-lf").
	// +optional
	ServiceName string `json:"serviceName,omitempty"`

	// CreateService indicates whether the operator should create the Service.
	// If true (default), the operator creates a Service with the name specified in ServiceName.
	// If false, the operator assumes the Service already exists and will only reference it.
	// +optional
	// +kubebuilder:default=true
	CreateService *bool `json:"createService,omitempty"`

	// PodSecurityContext holds pod-level security attributes.
	// +optional
	PodSecurityContext *corev1.PodSecurityContext `json:"podSecurityContext,omitempty"`

	// SecurityContext holds container-level security attributes.
	// +optional
	SecurityContext *corev1.SecurityContext `json:"securityContext,omitempty"`

	// TopologySpreadConstraints for high availability pod distribution.
	// +optional
	TopologySpreadConstraints []corev1.TopologySpreadConstraint `json:"topologySpreadConstraints,omitempty"`

	// ServiceType specifies the type of Service to create (ClusterIP, LoadBalancer, NodePort).
	// +optional
	// +kubebuilder:default=ClusterIP
	ServiceType corev1.ServiceType `json:"serviceType,omitempty"`

	// ServiceAnnotations are annotations to add to the Service resource.
	// +optional
	ServiceAnnotations map[string]string `json:"serviceAnnotations,omitempty"`

	// ServiceLabels are custom labels to add to the Service resource.
	// Merged with operator-managed labels and CommonResourceLabels from OpenRAGSpec.
	// Useful for service discovery, monitoring, and network policies.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	ServiceLabels map[string]string `json:"serviceLabels,omitempty"`

	// ServiceAccountLabels are custom labels to add to the ServiceAccount resource.
	// Merged with operator-managed labels and CommonResourceLabels from OpenRAGSpec.
	// Useful for RBAC policies, auditing, and IAM integration.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	ServiceAccountLabels map[string]string `json:"serviceAccountLabels,omitempty"`

	// ServiceAccountAnnotations are custom annotations to add to the ServiceAccount resource.
	// Merged with CommonResourceAnnotations from OpenRAGSpec.
	// Useful for IAM role binding (e.g., eks.amazonaws.com/role-arn, iam.gke.io/gcp-service-account).
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	ServiceAccountAnnotations map[string]string `json:"serviceAccountAnnotations,omitempty"`

	// SecretLabels are custom labels to add to component-managed Secrets (e.g., .env secrets).
	// Merged with operator-managed labels and CommonResourceLabels from OpenRAGSpec.
	// Useful for secret management tools, backup policies, and auditing.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	SecretLabels map[string]string `json:"secretLabels,omitempty"`

	// SecretAnnotations are custom annotations to add to component-managed Secrets.
	// Merged with CommonResourceAnnotations from OpenRAGSpec.
	// Useful for secret injection tools (e.g., vault.hashicorp.com/agent-inject).
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	SecretAnnotations map[string]string `json:"secretAnnotations,omitempty"`

	// Command overrides the container's entrypoint.
	// +optional
	Command []string `json:"command,omitempty"`

	// Args overrides the container's command arguments.
	// +optional
	Args []string `json:"args,omitempty"`
}

// FrontendSpec configures the OpenRAG frontend (Next.js).
type FrontendSpec struct {
	ComponentSpec `json:",inline"`
}

// GoogleOAuthSpec holds Google OAuth2 client credentials.
type GoogleOAuthSpec struct {
	// +optional
	ClientID string `json:"clientId,omitempty"`
	// ClientSecret references the Secret key holding the OAuth client secret.
	// +optional
	ClientSecret *corev1.SecretKeySelector `json:"clientSecret,omitempty"`
}

// MicrosoftOAuthSpec holds Microsoft Graph OAuth2 client credentials.
type MicrosoftOAuthSpec struct {
	// +optional
	ClientID string `json:"clientId,omitempty"`
	// ClientSecret references the Secret key holding the OAuth client secret.
	// +optional
	ClientSecret *corev1.SecretKeySelector `json:"clientSecret,omitempty"`
}

// OAuthSpec aggregates supported OAuth provider configurations.
type OAuthSpec struct {
	// +optional
	Google *GoogleOAuthSpec `json:"google,omitempty"`
	// +optional
	Microsoft *MicrosoftOAuthSpec `json:"microsoft,omitempty"`
}

// BackendSpec configures the OpenRAG backend (FastAPI).
type BackendSpec struct {
	ComponentSpec `json:",inline"`

	// JWTSigningKeySecret references the Secret key that holds the JWT signing key.
	// If omitted, the operator auto-generates a stable key in the .env file.
	// WARNING: Do not change or delete after initial deployment - will break existing JWT tokens.
	// BEST PRACTICE: Create the referenced secret with immutable: true to prevent accidental modification.
	// +optional
	JWTSigningKeySecret *corev1.SecretKeySelector `json:"jwtSigningKeySecret,omitempty"`

	// EncryptionKeySecret references the Secret key for OPENRAG_ENCRYPTION_KEY.
	// If omitted, the operator auto-generates a stable key in the .env file.
	// WARNING: Do not change or delete after initial deployment - will make encrypted data unreadable.
	// BEST PRACTICE: Create the referenced secret with immutable: true to prevent accidental modification.
	// +optional
	EncryptionKeySecret *corev1.SecretKeySelector `json:"encryptionKeySecret,omitempty"`

	// Storage configures a PVC mounted at /app/backend-data.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// OAuthBrokerURL is the OAuth callback URL (OAUTH_BROKER_URL).
	// +optional
	OAuthBrokerURL string `json:"oauthBrokerUrl,omitempty"`

	// IBMAuthEnabled enables IBM IAM authentication (IBM_AUTH_ENABLED).
	// +optional
	IBMAuthEnabled bool `json:"ibmAuthEnabled,omitempty"`

	// OAuth configures Google and Microsoft OAuth providers.
	// +optional
	OAuth *OAuthSpec `json:"oauth,omitempty"`
}

// LangflowSpec configures the Langflow instance.
type LangflowSpec struct {
	ComponentSpec `json:",inline"`

	// SecretKeySecret references the Secret key for LANGFLOW_SECRET_KEY,
	// shared between backend and Langflow. If omitted, the operator auto-generates a stable key in the .env file.
	// WARNING: Do not change or delete after initial deployment - will break Langflow sessions and authentication.
	// BEST PRACTICE: Create the referenced secret with immutable: true to prevent accidental modification.
	// +optional
	SecretKeySecret *corev1.SecretKeySelector `json:"secretKeySecret,omitempty"`

	// FlowsRef is the git branch name or commit SHA from which flow JSON files
	// are downloaded at pod startup via an init container. When set, all *.json
	// files under flows/ in langflow-ai/openrag at that ref are fetched into
	// /app/flows (LANGFLOW_LOAD_FLOWS_PATH). Use a commit SHA for reproducibility.
	// +optional
	FlowsRef string `json:"flowsRef,omitempty"`

	// FlowsInitImage is the container image used by the flows-download init container.
	// Defaults to python:3-alpine.
	// +optional
	FlowsInitImage string `json:"flowsInitImage,omitempty"`

	// Storage configures a PVC mounted at /app/data (Langflow SQLite + flows).
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// PVCReclaimPolicy determines what happens to the Langflow PVC when the OpenRAG CR is deleted.
	// - "Retain" (default): PVC is retained to preserve user data (flows, SQLite database)
	// - "Delete": PVC is deleted along with other resources (WARNING: permanent data loss)
	// Similar to Kubernetes PersistentVolume reclaimPolicy.
	// +optional
	// +kubebuilder:default=Retain
	// +kubebuilder:validation:Enum=Retain;Delete
	PVCReclaimPolicy PVCReclaimPolicy `json:"pvcReclaimPolicy,omitempty"`
}

// LLMSpec configures the LLM provider used by backend and Langflow.
type LLMSpec struct {
	// +optional
	Provider string `json:"provider,omitempty"`
	// +optional
	Model string `json:"model,omitempty"`
}

// EmbeddingSpec configures the embedding provider.
type EmbeddingSpec struct {
	// +optional
	Provider string `json:"provider,omitempty"`
	// +optional
	Model string `json:"model,omitempty"`
}

// WatsonXSpec holds IBM WatsonX connection details.
type WatsonXSpec struct {
	// +optional
	Endpoint string `json:"endpoint,omitempty"`
	// +optional
	ProjectID string `json:"projectId,omitempty"`
	// APIKeySecret references the Secret key for WATSONX_API_KEY.
	// +optional
	APIKeySecret *corev1.SecretKeySelector `json:"apiKeySecret,omitempty"`
}

// PersistenceSpec describes a PVC to be created or reused for a component.
type PersistenceSpec struct {
	// +optional
	// +kubebuilder:default=true
	Enabled bool `json:"enabled,omitempty"`

	// StorageClassName passed to the PVC. Defaults to the cluster default.
	// +optional
	StorageClassName *string `json:"storageClassName,omitempty"`

	// Size of the PVC. Defaults to 10Gi.
	// +optional
	// +kubebuilder:default="10Gi"
	Size resource.Quantity `json:"size,omitempty"`

	// AccessModes for the PVC. Defaults to ["ReadWriteOnce"].
	// +optional
	AccessModes []corev1.PersistentVolumeAccessMode `json:"accessModes,omitempty"`

	// ExistingClaim reuses a pre-existing PVC instead of creating one.
	// +optional
	ExistingClaim string `json:"existingClaim,omitempty"`

	// Labels are custom labels to add to the PersistentVolumeClaim.
	// Merged with operator-managed labels and CommonResourceLabels from OpenRAGSpec.
	// Useful for storage policies, backup tools (e.g., Velero), and cost allocation.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	Labels map[string]string `json:"labels,omitempty"`

	// Annotations are custom annotations to add to the PersistentVolumeClaim.
	// Merged with CommonResourceAnnotations from OpenRAGSpec.
	// Useful for volume provisioning hints and backup policies.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	Annotations map[string]string `json:"annotations,omitempty"`
}

// OpenSearchSpec points the operator at an external OpenSearch cluster.
// OpenSearch is NOT deployed by this operator.
type OpenSearchSpec struct {
	// Host is the OpenSearch endpoint hostname or IP.
	// +kubebuilder:validation:Required
	Host string `json:"host"`

	// +optional
	// +kubebuilder:default=9200
	Port int32 `json:"port,omitempty"`

	// +optional
	// +kubebuilder:default="https"
	Scheme string `json:"scheme,omitempty"`

	// IndexName used for document storage.
	// +optional
	// +kubebuilder:default="documents"
	IndexName string `json:"indexName,omitempty"`

	// CredentialsSecret is the name of a Secret with keys "username" and "password".
	// +optional
	CredentialsSecret string `json:"credentialsSecret,omitempty"`
}

// DoclingSpec points the operator at an external Docling document-conversion service.
// Docling is NOT deployed by this operator.
type DoclingSpec struct {
	// Host is the Docling service hostname or IP.
	// +kubebuilder:validation:Required
	Host string `json:"host"`

	// +optional
	// +kubebuilder:default=5001
	Port int32 `json:"port,omitempty"`

	// +optional
	// +kubebuilder:default="http"
	Scheme string `json:"scheme,omitempty"`

	// +optional
	// +kubebuilder:default=false
	VerifySsl *bool `json:"verifySsl,omitempty"`
}

// DoclingServeSpec configures the Docling serve component (API server).
type DoclingServeSpec struct {
	ComponentSpec `json:",inline"`

	// Storage configures a PVC for model cache and temporary files.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// Port for the HTTP API.
	// +optional
	// +kubebuilder:default=5001
	Port int32 `json:"port,omitempty"`

	// LivenessProbe configures the liveness probe for the container.
	// +optional
	LivenessProbe *corev1.Probe `json:"livenessProbe,omitempty"`

	// ReadinessProbe configures the readiness probe for the container.
	// +optional
	ReadinessProbe *corev1.Probe `json:"readinessProbe,omitempty"`

	// HPA configures autoscaling for the docling-serve deployment.
	// +optional
	HPA *DoclingHPASpec `json:"hpa,omitempty"`

	// Config contains docling-specific configuration options.
	// +optional
	Config *DoclingConfig `json:"config,omitempty"`
}

// DoclingWorkerSpec configures the Docling worker component (document processing).
type DoclingWorkerSpec struct {
	ComponentSpec `json:",inline"`

	// Storage configures a PVC for processing workspace.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// QueueURL for worker communication (e.g., Redis, RabbitMQ).
	// Ignored when Valkey is enabled in DoclingComponentsSpec.
	// +optional
	QueueURL string `json:"queueUrl,omitempty"`

	// QueueURLSecret references a Secret key for the queue connection string.
	// Ignored when Valkey is enabled in DoclingComponentsSpec.
	// +optional
	QueueURLSecret *corev1.SecretKeySelector `json:"queueUrlSecret,omitempty"`

	// LivenessProbe configures the liveness probe for the container.
	// +optional
	LivenessProbe *corev1.Probe `json:"livenessProbe,omitempty"`

	// ReadinessProbe configures the readiness probe for the container.
	// +optional
	ReadinessProbe *corev1.Probe `json:"readinessProbe,omitempty"`

	// HPA configures autoscaling for the docling-worker deployment.
	// +optional
	HPA *DoclingHPASpec `json:"hpa,omitempty"`

	// Config contains docling-specific configuration options.
	// +optional
	Config *DoclingConfig `json:"config,omitempty"`

	// Concurrency sets the number of concurrent tasks per worker.
	// +optional
	// +kubebuilder:default=4
	// +kubebuilder:validation:Minimum=1
	Concurrency *int32 `json:"concurrency,omitempty"`
}

// ValkeySpec configures the Valkey (Redis-compatible) instance for docling queue.
type ValkeySpec struct {
	ComponentSpec `json:",inline"`

	// Port for the Valkey service.
	// +optional
	// +kubebuilder:default=6379
	Port int32 `json:"port,omitempty"`

	// Storage configures a PVC for Valkey data persistence.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// Password for Valkey authentication (optional).
	// +optional
	Password string `json:"password,omitempty"`

	// PasswordSecret references a Secret key for Valkey password.
	// +optional
	PasswordSecret *corev1.SecretKeySelector `json:"passwordSecret,omitempty"`

	// Database number to use (0-15).
	// +optional
	// +kubebuilder:default=0
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=15
	Database int32 `json:"database,omitempty"`

	// MaxMemory sets the max memory limit (e.g., "256mb", "1gb").
	// +optional
	MaxMemory string `json:"maxMemory,omitempty"`

	// MaxMemoryPolicy sets eviction policy (e.g., "allkeys-lru", "volatile-lru").
	// +optional
	// +kubebuilder:default="allkeys-lru"
	MaxMemoryPolicy string `json:"maxMemoryPolicy,omitempty"`
}

// DoclingConfig contains docling-specific configuration options for document processing.
type DoclingConfig struct {
	// OCR configures optical character recognition settings.
	// +optional
	OCR *DoclingOCRConfig `json:"ocr,omitempty"`

	// TableStructure configures table structure recognition settings.
	// +optional
	TableStructure *DoclingTableStructureConfig `json:"tableStructure,omitempty"`

	// Performance configures performance-related settings.
	// +optional
	Performance *DoclingPerformanceConfig `json:"performance,omitempty"`

	// Models configures which AI models to use for different tasks.
	// +optional
	Models *DoclingModelsConfig `json:"models,omitempty"`

	// ExtraEnv allows setting additional environment variables for docling configuration.
	// +optional
	ExtraEnv []corev1.EnvVar `json:"extraEnv,omitempty"`
}

// DoclingOCRConfig configures OCR (Optical Character Recognition) settings.
type DoclingOCRConfig struct {
	// Enabled controls whether OCR is enabled.
	// +optional
	// +kubebuilder:default=true
	Enabled *bool `json:"enabled,omitempty"`

	// Engine specifies the OCR engine to use (e.g., "easyocr", "tesseract").
	// +optional
	// +kubebuilder:default="easyocr"
	Engine string `json:"engine,omitempty"`

	// Languages is a list of language codes for OCR (e.g., ["en", "de", "fr"]).
	// +optional
	Languages []string `json:"languages,omitempty"`

	// ForceFullPageOCR forces OCR on all pages even if text is extractable.
	// +optional
	// +kubebuilder:default=false
	ForceFullPageOCR *bool `json:"forceFullPageOCR,omitempty"`
}

// DoclingTableStructureConfig configures table structure recognition settings.
type DoclingTableStructureConfig struct {
	// Enabled controls whether table structure recognition is enabled.
	// +optional
	// +kubebuilder:default=true
	Enabled *bool `json:"enabled,omitempty"`

	// Mode specifies the table extraction mode (e.g., "accurate", "fast").
	// +optional
	// +kubebuilder:default="accurate"
	Mode string `json:"mode,omitempty"`

	// MinConfidencePercent sets the minimum confidence threshold for table detection (0-100).
	// +optional
	// +kubebuilder:default=70
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=100
	MinConfidencePercent *int32 `json:"minConfidencePercent,omitempty"`
}

// DoclingPerformanceConfig configures performance-related settings.
type DoclingPerformanceConfig struct {
	// BatchSize sets the number of pages to process in a single batch.
	// +optional
	// +kubebuilder:default=10
	// +kubebuilder:validation:Minimum=1
	BatchSize *int32 `json:"batchSize,omitempty"`

	// MaxWorkers sets the maximum number of worker threads per process.
	// +optional
	// +kubebuilder:default=4
	// +kubebuilder:validation:Minimum=1
	MaxWorkers *int32 `json:"maxWorkers,omitempty"`

	// TimeoutSeconds sets the processing timeout per document in seconds.
	// +optional
	// +kubebuilder:default=300
	// +kubebuilder:validation:Minimum=1
	TimeoutSeconds *int32 `json:"timeoutSeconds,omitempty"`

	// EnableGPU enables GPU acceleration if available.
	// +optional
	// +kubebuilder:default=false
	EnableGPU *bool `json:"enableGPU,omitempty"`
}

// DoclingModelsConfig configures which AI models to use for different tasks.
type DoclingModelsConfig struct {
	// LayoutModel specifies the model for document layout analysis.
	// +optional
	LayoutModel string `json:"layoutModel,omitempty"`

	// OCRModel specifies the model for OCR.
	// +optional
	OCRModel string `json:"ocrModel,omitempty"`

	// TableModel specifies the model for table structure recognition.
	// +optional
	TableModel string `json:"tableModel,omitempty"`

	// ModelCachePath specifies where to cache downloaded models.
	// +optional
	// +kubebuilder:default="/models"
	ModelCachePath string `json:"modelCachePath,omitempty"`
}

// DoclingHPASpec configures HorizontalPodAutoscaler for docling components.
type DoclingHPASpec struct {
	// Enabled controls whether HPA is created.
	// +optional
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// MinReplicas is the lower limit for the number of replicas.
	// +optional
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	MinReplicas *int32 `json:"minReplicas,omitempty"`

	// MaxReplicas is the upper limit for the number of replicas.
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	MaxReplicas int32 `json:"maxReplicas"`

	// TargetCPUUtilizationPercentage is the target average CPU utilization.
	// +optional
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=100
	TargetCPUUtilizationPercentage *int32 `json:"targetCPUUtilizationPercentage,omitempty"`

	// TargetMemoryUtilizationPercentage is the target average memory utilization.
	// +optional
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=100
	TargetMemoryUtilizationPercentage *int32 `json:"targetMemoryUtilizationPercentage,omitempty"`

	// Behavior configures the scaling behavior (scale up/down policies, stabilization windows).
	// +optional
	Behavior *autoscalingv2.HorizontalPodAutoscalerBehavior `json:"behavior,omitempty"`
}

// DoclingComponentsSpec aggregates all docling-related components.
type DoclingComponentsSpec struct {
	// Enabled controls whether docling components are deployed.
	// +optional
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// Serve configures the docling-serve deployment.
	// +optional
	Serve *DoclingServeSpec `json:"serve,omitempty"`

	// Worker configures the docling-worker deployment.
	// +optional
	Worker *DoclingWorkerSpec `json:"worker,omitempty"`

	// Valkey configures an operator-managed Valkey instance for the queue.
	// When enabled, docling-worker automatically uses this Valkey instance.
	// +optional
	Valkey *ValkeySpec `json:"valkey,omitempty"`
}

// NetworkPolicySpec controls whether the operator creates a NetworkPolicy for Langflow.
type NetworkPolicySpec struct {
	// +optional
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`
}

// OpenRAGSpec defines the desired state of an OpenRAG instance.
type OpenRAGSpec struct {
	// InstanceName is a short unique identifier embedded in all resource names, enabling
	// multiple OpenRAG CRs to coexist in the same namespace (e.g. "prod", "staging").
	// Must start with a lowercase letter and contain only lowercase letters, digits, and
	// hyphens, with a maximum of 8 characters. When empty (default), resources use legacy
	// static names (openrag-fe, openrag-be, openrag-lf) for backwards compatibility.
	// This field is immutable after creation.
	// +optional
	// +kubebuilder:validation:MaxLength=8
	// +kubebuilder:validation:Pattern=`^[a-z][a-z0-9-]*$`
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="instanceName is immutable after creation"
	InstanceName string `json:"instanceName,omitempty"`

	// TargetNamespace is the namespace where all OpenRAG resources are created.
	// Defaults to the namespace of the CR itself. Cannot be "default".
	// +optional
	// +kubebuilder:validation:XValidation:rule="self != 'default'",message="targetNamespace must not be 'default'"
	TargetNamespace string `json:"targetNamespace,omitempty"`

	// TenantID sets TENANT_ID in both backend and Langflow.
	// +optional
	TenantID string `json:"tenantId,omitempty"`

	// ImagePullSecrets for private registries, applied to all component pods.
	// +optional
	// +kubebuilder:validation:XValidation:rule="self.all(x, x.name != '')",message="imagePullSecret name cannot be empty"
	ImagePullSecrets []corev1.LocalObjectReference `json:"imagePullSecrets,omitempty"`

	// CommonResourceLabels are labels applied to all managed infrastructure resources
	// (PVCs, Secrets, Services, ServiceAccounts). These labels are merged with
	// resource-specific labels, with resource-specific labels taking precedence.
	// Operator-managed labels (e.g., app.kubernetes.io/managed-by) cannot be overridden.
	// Useful for organization-wide policies, cost allocation, and resource grouping.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	CommonResourceLabels map[string]string `json:"commonResourceLabels,omitempty"`

	// CommonResourceAnnotations are annotations applied to all managed infrastructure resources
	// (PVCs, Secrets, Services, ServiceAccounts). These annotations are merged with
	// resource-specific annotations, with resource-specific annotations taking precedence.
	// Useful for backup policies, monitoring configuration, and GitOps metadata.
	// +optional
	// +kubebuilder:validation:MaxProperties=64
	CommonResourceAnnotations map[string]string `json:"commonResourceAnnotations,omitempty"`

	// Frontend configures the OpenRAG Next.js frontend.
	// +kubebuilder:validation:Required
	Frontend FrontendSpec `json:"frontend"`

	// Backend configures the OpenRAG FastAPI backend.
	// +kubebuilder:validation:Required
	Backend BackendSpec `json:"backend"`

	// Langflow configures the Langflow workflow engine.
	// +kubebuilder:validation:Required
	Langflow LangflowSpec `json:"langflow"`

	// LLM configures the LLM provider (LLM_PROVIDER, LLM_MODEL).
	// +optional
	LLM *LLMSpec `json:"llm,omitempty"`

	// Embedding configures the embedding provider (EMBEDDING_PROVIDER, EMBEDDING_MODEL).
	// +optional
	Embedding *EmbeddingSpec `json:"embedding,omitempty"`

	// WatsonX configures IBM WatsonX credentials.
	// +optional
	WatsonX *WatsonXSpec `json:"watsonx,omitempty"`

	// OpenSearch configures the external OpenSearch connection.
	// +optional
	OpenSearch *OpenSearchSpec `json:"opensearch,omitempty"`

	// DoclingComponents configures optional docling document-processing components.
	// When enabled, deploys docling-serve and docling-worker alongside OpenRAG.
	// +optional
	DoclingComponents *DoclingComponentsSpec `json:"doclingComponents,omitempty"`

	// Docling configures an optional external document-conversion service (legacy).
	// Use DoclingComponents to deploy docling within the operator.
	// +optional
	Docling *DoclingSpec `json:"docling,omitempty"`

	// NetworkPolicy controls creation of a NetworkPolicy for the Langflow pod.
	// +optional
	NetworkPolicy NetworkPolicySpec `json:"networkPolicy,omitempty"`
}

// OpenRAGStatus defines the observed state of an OpenRAG instance.
type OpenRAGStatus struct {
	// Conditions reflect the reconciliation state.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// Phase is a short human-readable summary (Pending, Running, Degraded, Error).
	// +optional
	Phase string `json:"phase,omitempty"`

	// Message provides human-readable detail about the current phase.
	// +optional
	Message string `json:"message,omitempty"`

	// ObservedGeneration is the metadata.generation this status reflects.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=or,scope=Namespaced
// +kubebuilder:printcolumn:name="Phase",type="string",JSONPath=".status.phase"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"
// +kubebuilder:printcolumn:name="Frontend",type="string",JSONPath=".spec.frontend.image"
// +kubebuilder:printcolumn:name="Backend",type="string",JSONPath=".spec.backend.image"
// +kubebuilder:printcolumn:name="Langflow",type="string",JSONPath=".spec.langflow.image"
// +genclient

// OpenRAG is the Schema for the openrags API.
type OpenRAG struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   OpenRAGSpec   `json:"spec,omitempty"`
	Status OpenRAGStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// OpenRAGList contains a list of OpenRAG.
type OpenRAGList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []OpenRAG `json:"items"`
}

func init() {
	SchemeBuilder.Register(&OpenRAG{}, &OpenRAGList{})
}
