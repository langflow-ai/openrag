// Package v1alpha1 contains API Schema definitions for the bomalogic.com v1alpha1 API group.
// +kubebuilder:object:generate=true
// +groupName=bomalogic.com
package v1alpha1

import (
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var (
	GroupVersion  = schema.GroupVersion{Group: "bomalogic.com", Version: "v1alpha1"}
	SchemeBuilder = runtime.NewSchemeBuilder()
	AddToScheme   = SchemeBuilder.AddToScheme
)
