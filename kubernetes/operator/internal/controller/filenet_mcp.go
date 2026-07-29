package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

const (
	// fileNetMCPRole is the component role used for resource naming/labels.
	fileNetMCPRole = "filenet-mcp"
	// defaultFileNetMCPPort is the sidecar's default HTTP port.
	defaultFileNetMCPPort int32 = 8811
)

// fileNetMCPPort resolves the sidecar port with its default.
func fileNetMCPPort(fn *openragv1alpha1.FileNetMCPSpec) int32 {
	if fn != nil && fn.Sidecar != nil && fn.Sidecar.Port > 0 {
		return fn.Sidecar.Port
	}
	return defaultFileNetMCPPort
}

// fileNetMCPDeployed reports whether the FileNet MCP sidecar should exist.
func fileNetMCPDeployed(o *openragv1alpha1.OpenRAG) bool {
	fn := o.Spec.FileNetMCP
	return fn != nil && fn.Enabled && fn.Sidecar != nil
}

// reconcileFileNetMCP manages the FileNet P8 MCP sidecar Deployment + Service.
// Modeled on reconcileDoclingComponents: no-op when disabled, per-resource
// error wrapping otherwise.
func (r *OpenRAGReconciler) reconcileFileNetMCP(ctx context.Context, o *openragv1alpha1.OpenRAG, targetNS string) error {
	if !fileNetMCPDeployed(o) {
		return nil
	}
	fn := o.Spec.FileNetMCP

	if shouldCreateServiceAccount(o, fileNetMCPRole) {
		baseLabels := componentLabels(o.Name, fileNetMCPRole)
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceAccountName(o, fileNetMCPRole),
				Namespace:   targetNS,
				Labels:      mergeServiceAccountLabels(o, fn.Sidecar.ComponentSpec, baseLabels),
				Annotations: mergeServiceAccountAnnotations(o, fn.Sidecar.ComponentSpec),
			},
		}
		if err := r.setOwnerOrLabel(o, sa, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return fmt.Errorf("filenet-mcp serviceaccount: %w", err)
		}
	}

	if shouldCreateService(o, fileNetMCPRole) {
		port := fileNetMCPPort(fn)
		baseLabels := componentLabels(o.Name, fileNetMCPRole)
		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:        getServiceName(o, fileNetMCPRole),
				Namespace:   targetNS,
				Labels:      mergeServiceLabels(o, fn.Sidecar.ComponentSpec, baseLabels),
				Annotations: mergeServiceAnnotations(o, fn.Sidecar.ComponentSpec),
			},
			Spec: corev1.ServiceSpec{
				Type:     corev1.ServiceTypeClusterIP,
				Selector: componentLabels(o.Name, fileNetMCPRole),
				Ports: []corev1.ServicePort{
					{Name: "http", Port: port, TargetPort: intstr.FromInt32(port), Protocol: corev1.ProtocolTCP},
				},
			},
		}
		if err := r.setOwnerOrLabel(o, svc, targetNS); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, svc); err != nil {
			return fmt.Errorf("filenet-mcp service: %w", err)
		}
	}

	deploy := r.fileNetMCPDeployment(o, targetNS)
	if err := r.setOwnerOrLabel(o, deploy, targetNS); err != nil {
		return err
	}
	if err := r.createOrUpdate(ctx, deploy); err != nil {
		return fmt.Errorf("filenet-mcp deployment: %w", err)
	}
	return nil
}

// fileNetMCPDeployment builds the sidecar Deployment. Credentials come from
// user-provided Secrets via env valueFrom (they never transit the operator);
// the boot performs a live CPE GraphQL call, so probe thresholds stay
// generous to avoid crash-looping on a briefly-unreachable CPE.
func (r *OpenRAGReconciler) fileNetMCPDeployment(o *openragv1alpha1.OpenRAG, targetNS string) *appsv1.Deployment {
	fn := o.Spec.FileNetMCP
	spec := fn.Sidecar
	replicas := replicasOrDefault(spec.Replicas)
	port := fileNetMCPPort(fn)

	sslEnabled := fn.SSLEnabled
	if sslEnabled == "" {
		sslEnabled = "true"
	}
	documentClass := fn.DocumentClass
	if documentClass == "" {
		documentClass = "Document"
	}

	envVars := []corev1.EnvVar{
		{Name: "SERVER_URL", Value: fn.GraphQLURL},
		{Name: "OBJECT_STORE", Value: fn.ObjectStore},
		{Name: "SSL_ENABLED", Value: sslEnabled},
		{Name: "FILENET_MCP_PORT", Value: fmt.Sprintf("%d", port)},
		{Name: "FILENET_MCP_DOCUMENT_CLASS", Value: documentClass},
	}
	if fn.CredentialsSecret != nil {
		envVars = append(envVars,
			corev1.EnvVar{
				Name: "USERNAME",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: *fn.CredentialsSecret,
						Key:                  "username",
					},
				},
			},
			corev1.EnvVar{
				Name: "PASSWORD",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: *fn.CredentialsSecret,
						Key:                  "password",
					},
				},
			},
		)
	}
	if fn.AuthTokenSecret != nil {
		envVars = append(envVars, corev1.EnvVar{
			Name:      "FILENET_MCP_AUTH_TOKEN",
			ValueFrom: &corev1.EnvVarSource{SecretKeyRef: fn.AuthTokenSecret},
		})
	}
	envVars = append(envVars, spec.Env...)

	baseLabels := componentLabels(o.Name, fileNetMCPRole)
	deploymentLabels := mergeDeploymentLabels(baseLabels, spec.Labels)
	deploymentAnnotations := mergeDeploymentAnnotations(spec.Annotations)
	podLabels := mergePodLabels(baseLabels, spec.PodLabels)
	podAnnotations := mergePodAnnotations(spec.PodAnnotations)

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        instanceResourceName(o, fileNetMCPRole),
			Namespace:   targetNS,
			Labels:      deploymentLabels,
			Annotations: deploymentAnnotations,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: baseLabels},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RollingUpdateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: podAnnotations,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName:        getServiceAccountName(o, fileNetMCPRole),
					ImagePullSecrets:          mergeImagePullSecrets(o.Spec.ImagePullSecrets, spec.ImagePullSecrets),
					SecurityContext:           spec.PodSecurityContext,
					NodeSelector:              spec.NodeSelector,
					Tolerations:               spec.Tolerations,
					Affinity:                  spec.Affinity,
					TopologySpreadConstraints: spec.TopologySpreadConstraints,
					Containers: []corev1.Container{
						{
							Name:            "filenet-mcp",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Command:         spec.Command,
							Args:            spec.Args,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: port}},
							Env:             envVars,
							Resources:       spec.Resources,
							SecurityContext: spec.SecurityContext,
							LivenessProbe:   probeOrDefault(spec.LivenessProbe, httpProbe("/health", port, 30, 20)),
							ReadinessProbe:  probeOrDefault(spec.ReadinessProbe, httpProbe("/health", port, 10, 10)),
						},
					},
				},
			},
		},
	}
}
