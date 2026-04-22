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

// BackendSpec configures the OpenRAG backend (FastAPI).
type BackendSpec struct {
	ComponentSpec `json:",inline"`

	// EnvSecret is the name of a Secret whose keys are mounted as /app/.env.
	// The secret must contain a single key ".env" with the full dotenv content.
	// +optional
	EnvSecret string `json:"envSecret,omitempty"`

	// JWTSigningKeySecret references the Secret key that holds the JWT signing key.
	// If omitted the operator generates a random key and stores it in a managed Secret.
	// +optional
	JWTSigningKeySecret *corev1.SecretKeySelector `json:"jwtSigningKeySecret,omitempty"`

	// BackendDataStorage configures a PVC mounted at /app/backend-data.
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`
}

// LangflowSpec configures the Langflow instance.
type LangflowSpec struct {
	ComponentSpec `json:",inline"`

	// EnvSecret is the name of a Secret whose single ".env" key is mounted at /app/.env.
	// +optional
	EnvSecret string `json:"envSecret,omitempty"`

	// Storage configures a PVC mounted at /app/data (Langflow SQLite + flows).
	// +optional
	Storage *PersistenceSpec `json:"storage,omitempty"`
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
// The generated policy restricts ingress to RFC-1918 ranges and permits
// egress to Docling, DNS, OpenSearch (9200/443), and Langflow itself.
type NetworkPolicySpec struct {
	// +optional
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`
}

// OpenRAGSpec defines the desired state of an OpenRAG instance.
type OpenRAGSpec struct {
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

	// OpenSearch configures the external OpenSearch connection.
	// Required unless you supply the credentials via Backend.EnvSecret.
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
