package controller

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

// TestMapOrderingDoesNotAffectHash verifies that map iteration order doesn't cause
// unnecessary reconciliations. This test builds the same labels/annotations in different
// orders and verifies they produce the same hash.
func TestMapOrderingDoesNotAffectHash(t *testing.T) {
	// Create two services with identical labels but built in different orders
	labels1 := map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/instance":   "test",
		"app.kubernetes.io/component":  "backend",
		"app.kubernetes.io/managed-by": "openrag-operator",
		"environment":                  "production",
		"team":                         "platform",
		"cost-center":                  "12345",
	}

	labels2 := map[string]string{
		"cost-center":                  "12345",
		"team":                         "platform",
		"environment":                  "production",
		"app.kubernetes.io/managed-by": "openrag-operator",
		"app.kubernetes.io/component":  "backend",
		"app.kubernetes.io/instance":   "test",
		"app.kubernetes.io/name":       "openrag",
	}

	svc1 := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-service",
			Namespace: "default",
			Labels:    labels1,
		},
		Spec: corev1.ServiceSpec{
			Ports: []corev1.ServicePort{
				{Name: "http", Port: 8000},
			},
		},
	}

	svc2 := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-service",
			Namespace: "default",
			Labels:    labels2,
		},
		Spec: corev1.ServiceSpec{
			Ports: []corev1.ServicePort{
				{Name: "http", Port: 8000},
			},
		},
	}

	hash1, err := desiredHash(svc1)
	if err != nil {
		t.Fatalf("failed to compute hash1: %v", err)
	}

	hash2, err := desiredHash(svc2)
	if err != nil {
		t.Fatalf("failed to compute hash2: %v", err)
	}

	if hash1 != hash2 {
		t.Errorf("hashes differ despite identical content:\nhash1: %s\nhash2: %s", hash1, hash2)
	}
}

// TestMergeResourceLabelsIsDeterministic verifies that merging labels produces
// consistent results regardless of the order in which source maps are iterated.
func TestMergeResourceLabelsIsDeterministic(t *testing.T) {
	o := &openragv1alpha1.OpenRAG{
		Spec: openragv1alpha1.OpenRAGSpec{
			CommonResourceLabels: map[string]string{
				"environment": "production",
				"team":        "platform",
			},
		},
	}

	baseLabels := map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/managed-by": "openrag-operator",
	}

	componentLabels := map[string]string{
		"component-tier": "backend",
		"api":            "true",
	}

	resourceLabels := map[string]string{
		"storage-tier": "ssd",
		"backup":       "enabled",
	}

	// Merge multiple times to ensure consistency
	results := make([]map[string]string, 10)
	for i := 0; i < 10; i++ {
		results[i] = mergeResourceLabels(o, baseLabels, componentLabels, resourceLabels)
	}

	// Verify all results have the same keys and values
	for i := 1; i < len(results); i++ {
		if len(results[0]) != len(results[i]) {
			t.Errorf("result %d has different length: %d vs %d", i, len(results[0]), len(results[i]))
		}
		for k, v := range results[0] {
			if results[i][k] != v {
				t.Errorf("result %d differs at key %s: %s vs %s", i, k, v, results[i][k])
			}
		}
	}
}

// TestMergeResourceAnnotationsIsDeterministic verifies that merging annotations
// produces consistent results.
func TestMergeResourceAnnotationsIsDeterministic(t *testing.T) {
	o := &openragv1alpha1.OpenRAG{
		Spec: openragv1alpha1.OpenRAGSpec{
			CommonResourceAnnotations: map[string]string{
				"backup.velero.io/backup-volumes": "true",
				"monitoring.prometheus.io/scrape": "true",
			},
		},
	}

	componentAnnotations := map[string]string{
		"eks.amazonaws.com/role-arn":                        "arn:aws:iam::123:role/backend",
		"service.beta.kubernetes.io/aws-load-balancer-type": "nlb",
	}

	resourceAnnotations := map[string]string{
		"volume.beta.kubernetes.io/storage-provisioner": "ebs.csi.aws.com",
	}

	// Merge multiple times to ensure consistency
	results := make([]map[string]string, 10)
	for i := 0; i < 10; i++ {
		results[i] = mergeResourceAnnotations(o, componentAnnotations, resourceAnnotations)
	}

	// Verify all results have the same keys and values
	for i := 1; i < len(results); i++ {
		if len(results[0]) != len(results[i]) {
			t.Errorf("result %d has different length: %d vs %d", i, len(results[0]), len(results[i]))
		}
		for k, v := range results[0] {
			if results[i][k] != v {
				t.Errorf("result %d differs at key %s: %s vs %s", i, k, v, results[i][k])
			}
		}
	}
}

// TestLabelPrecedence verifies that labels are merged with the correct priority.
func TestLabelPrecedence(t *testing.T) {
	o := &openragv1alpha1.OpenRAG{
		Spec: openragv1alpha1.OpenRAGSpec{
			CommonResourceLabels: map[string]string{
				"environment": "dev",
				"team":        "platform",
			},
		},
	}

	baseLabels := map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/managed-by": "openrag-operator",
		"environment":                  "production", // Should override common
	}

	componentLabels := map[string]string{
		"team": "backend-team", // Should override common
	}

	resourceLabels := map[string]string{
		"team": "storage-team", // Should override component
	}

	result := mergeResourceLabels(o, baseLabels, componentLabels, resourceLabels)

	// Base labels should win
	if result["environment"] != "production" {
		t.Errorf("expected environment=production (from base), got %s", result["environment"])
	}

	// Resource labels should override component labels
	if result["team"] != "storage-team" {
		t.Errorf("expected team=storage-team (from resource), got %s", result["team"])
	}

	// Base labels should always be present
	if result["app.kubernetes.io/name"] != "openrag" {
		t.Errorf("expected app.kubernetes.io/name=openrag, got %s", result["app.kubernetes.io/name"])
	}
}

// Made with Bob
