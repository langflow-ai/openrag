// Package v1alpha1 contains API Schema definitions for the openr.ag v1alpha1 API group.
// +kubebuilder:object:generate=true
// +groupName=openr.ag
package v1alpha1

import (
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var (
	GroupVersion  = schema.GroupVersion{Group: "openr.ag", Version: "v1alpha1"}
	SchemeBuilder = runtime.NewSchemeBuilder()
	AddToScheme   = SchemeBuilder.AddToScheme
)
