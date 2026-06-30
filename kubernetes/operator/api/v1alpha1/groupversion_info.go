/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

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
