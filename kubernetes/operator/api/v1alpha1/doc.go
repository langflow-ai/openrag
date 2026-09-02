// Package v1alpha1 contains API Schema definitions for the bomalogic.com v1alpha1 API group.
// +k8s:deepcopy-gen=package
// +groupName=bomalogic.com
package v1alpha1

import (
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// SchemeGroupVersion is group version used to register these objects
var SchemeGroupVersion = schema.GroupVersion{Group: "bomalogic.com", Version: "v1alpha1"}

// Resource takes an unqualified resource and returns a Group qualified GroupResource
func Resource(resource string) schema.GroupResource {
	return SchemeGroupVersion.WithResource(resource).GroupResource()
}
