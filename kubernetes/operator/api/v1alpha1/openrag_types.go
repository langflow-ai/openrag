// Run "make manifests" to regenerate CRD manifests after modifying this file.
// Run "make generate" to regenerate DeepCopy methods after modifying this file.
package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ComponentSpec defines common configuration shared by all three components.
type ComponentSpec struct {
	// Image is the container image (repository:tag).
	// +kubebuilder:validation:Required
	Image string `json:"image"`

	// +optional
	// +kubebuilder:default=IfNotPresent
	ImagePullPolicy corev1.PullPolicy `json:"imagePullPolicy,omitempty"`

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
}

// FrontendSpec configures the OpenRAG frontend (Next.js).
type FrontendSpec struct {
	ComponentSpec `json:",inline"`
}

// FlowIDsSpec holds the Langflow flow UUIDs consumed by the backend.
type FlowIDsSpec struct {
	// +optional
	Chat string `json:"chat,omitempty"`
	// +optional
	Ingest string `json:"ingest,omitempty"`
	// +optional
	URLIngest string `json:"urlIngest,omitempty"`
	// +optional
	Nudges string `json:"nudges,omitempty"`
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
	// +optional
	JWTSigningKeySecret *corev1.SecretKeySelector `json:"jwtSigningKeySecret,omitempty"`

	// EncryptionKeySecret references the Secret key for OPENRAG_ENCRYPTION_KEY.
	// If omitted the operator auto-generates a stable key.
	// +optional
	EncryptionKeySecret *corev1.SecretKeySelector `json:"encryptionKeySecret,omitempty"`

	// Storage configures a PVC mounted at /app/backend-data.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`

	// FlowIDs are the Langflow flow UUIDs the backend calls for chat, ingest, etc.
	// +optional
	FlowIDs *FlowIDsSpec `json:"flowIds,omitempty"`

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
	// shared between backend and Langflow. If omitted the operator auto-generates
	// a stable key stored in <cr-name>-openrag-gen-creds.
	// +optional
	SecretKeySecret *corev1.SecretKeySelector `json:"secretKeySecret,omitempty"`

	// DatabaseURL overrides LANGFLOW_DATABASE_URL.
	// Defaults to sqlite:////app/data/langflow.db when storage is enabled.
	// +optional
	DatabaseURL string `json:"databaseUrl,omitempty"`

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

	// ExistingClaim reuses a pre-existing PVC instead of creating one.
	// +optional
	ExistingClaim string `json:"existingClaim,omitempty"`
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
}

// NetworkPolicySpec controls whether the operator creates a NetworkPolicy for Langflow.
type NetworkPolicySpec struct {
	// +optional
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`
}

// OpenRAGSpec defines the desired state of an OpenRAG instance.
type OpenRAGSpec struct {
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
	ImagePullSecrets []corev1.LocalObjectReference `json:"imagePullSecrets,omitempty"`

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

	// Docling configures an optional external document-conversion service.
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
