package controller

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"
)

func TestReconcile_MetricsScrapingEnabledByDefault(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	// Check FE deployment
	feDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, feDep))
	assert.Equal(t, "true", feDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Equal(t, "9090", feDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Equal(t, "/metrics", feDep.Spec.Template.Annotations["prometheus.io/path"])

	fePorts := feDep.Spec.Template.Spec.Containers[0].Ports
	require.Len(t, fePorts, 2)
	assert.Equal(t, "http", fePorts[0].Name)
	assert.Equal(t, int32(3000), fePorts[0].ContainerPort)
	assert.Equal(t, "metrics", fePorts[1].Name)
	assert.Equal(t, int32(9090), fePorts[1].ContainerPort)

	// Check BE deployment
	beDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, beDep))
	assert.Equal(t, "true", beDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Equal(t, "8000", beDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Equal(t, "/metrics", beDep.Spec.Template.Annotations["prometheus.io/path"])

	// Check LF deployment
	lfDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, lfDep))
	assert.Equal(t, "true", lfDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Equal(t, "9090", lfDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Equal(t, "/metrics", lfDep.Spec.Template.Annotations["prometheus.io/path"])

	lfPorts := lfDep.Spec.Template.Spec.Containers[0].Ports
	require.Len(t, lfPorts, 2)
	assert.Equal(t, "http", lfPorts[0].Name)
	assert.Equal(t, int32(7860), lfPorts[0].ContainerPort)
	assert.Equal(t, "metrics", lfPorts[1].Name)
	assert.Equal(t, int32(9090), lfPorts[1].ContainerPort)

	// Check Services — metrics port present when enabled
	feSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, feSvc))
	require.Len(t, feSvc.Spec.Ports, 2)
	assert.Equal(t, "metrics", feSvc.Spec.Ports[1].Name)
	assert.Equal(t, int32(9090), feSvc.Spec.Ports[1].Port)

	lfSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, lfSvc))
	require.Len(t, lfSvc.Spec.Ports, 2)
	assert.Equal(t, "metrics", lfSvc.Spec.Ports[1].Name)
	assert.Equal(t, int32(9090), lfSvc.Spec.Ports[1].Port)
}

func TestReconcile_MetricsScrapingDisabled(t *testing.T) {
	s := newScheme(t)
	cr := minimalCR("my-openrag", "my-ns")
	disabled := true
	cr.Spec.MetricsScrapingDisabled = &disabled
	r, c := reconciler(s, cr)

	reconcileOnce(t, r, cr)

	// Check FE deployment — no prometheus annotations, only http port
	feDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, feDep))
	assert.Empty(t, feDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Empty(t, feDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Empty(t, feDep.Spec.Template.Annotations["prometheus.io/path"])
	fePorts := feDep.Spec.Template.Spec.Containers[0].Ports
	require.Len(t, fePorts, 1)
	assert.Equal(t, "http", fePorts[0].Name)

	// Check BE deployment — no prometheus annotations
	beDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "be"), Namespace: "my-ns"}, beDep))
	assert.Empty(t, beDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Empty(t, beDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Empty(t, beDep.Spec.Template.Annotations["prometheus.io/path"])

	// Check LF deployment — no prometheus annotations, only http port
	lfDep := &appsv1.Deployment{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, lfDep))
	assert.Empty(t, lfDep.Spec.Template.Annotations["prometheus.io/scrape"])
	assert.Empty(t, lfDep.Spec.Template.Annotations["prometheus.io/port"])
	assert.Empty(t, lfDep.Spec.Template.Annotations["prometheus.io/path"])
	lfPorts := lfDep.Spec.Template.Spec.Containers[0].Ports
	require.Len(t, lfPorts, 1)
	assert.Equal(t, "http", lfPorts[0].Name)

	// Check Services — metrics port absent when disabled
	feSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "fe"), Namespace: "my-ns"}, feSvc))
	require.Len(t, feSvc.Spec.Ports, 1)
	assert.Equal(t, "http", feSvc.Spec.Ports[0].Name)

	lfSvc := &corev1.Service{}
	require.NoError(t, c.Get(context.Background(),
		types.NamespacedName{Name: instanceResourceName(cr, "lf"), Namespace: "my-ns"}, lfSvc))
	require.Len(t, lfSvc.Spec.Ports, 1)
	assert.Equal(t, "http", lfSvc.Spec.Ports[0].Name)
}
