package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
)

// OpenRAGReconciler reconciles an OpenRAG object.
type OpenRAGReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=openrag.io,resources=openrags,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=openrag.io,resources=openrags/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=openrag.io,resources=openrags/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=serviceaccounts,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=networking.k8s.io,resources=networkpolicies,verbs=get;list;watch;create;update;patch;delete

func (r *OpenRAGReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	instance := &openragv1alpha1.OpenRAG{}
	if err := r.Get(ctx, req.NamespacedName, instance); err != nil {
		if errors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	if err := r.reconcileServiceAccounts(ctx, instance); err != nil {
		return ctrl.Result{}, fmt.Errorf("service accounts: %w", err)
	}
	if err := r.reconcileServices(ctx, instance); err != nil {
		return ctrl.Result{}, fmt.Errorf("services: %w", err)
	}
	if err := r.reconcileDeployments(ctx, instance); err != nil {
		return ctrl.Result{}, fmt.Errorf("deployments: %w", err)
	}
	if instance.Spec.NetworkPolicy.Enabled {
		if err := r.reconcileNetworkPolicy(ctx, instance); err != nil {
			return ctrl.Result{}, fmt.Errorf("network policy: %w", err)
		}
	}

	logger.Info("reconciled OpenRAG instance", "name", instance.Name)
	return ctrl.Result{}, nil
}

func (r *OpenRAGReconciler) reconcileServiceAccounts(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	for _, role := range []string{"fe", "be", "lf"} {
		sa := &corev1.ServiceAccount{
			ObjectMeta: metav1.ObjectMeta{
				Name:      saName(o.Name, role),
				Namespace: o.Namespace,
				Labels:    componentLabels(o.Name, role),
			},
		}
		if err := ctrl.SetControllerReference(o, sa, r.Scheme); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, sa); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) reconcileServices(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	type svcDef struct {
		role string
		port int32
	}
	defs := []svcDef{
		{"fe", 3000},
		{"be", 8000},
		{"lf", 7860},
	}
	for _, d := range defs {
		svc := &corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName(o.Name, d.role),
				Namespace: o.Namespace,
				Labels:    componentLabels(o.Name, d.role),
			},
			Spec: corev1.ServiceSpec{
				Type:     corev1.ServiceTypeClusterIP,
				Selector: componentLabels(o.Name, d.role),
				Ports: []corev1.ServicePort{
					{Name: "http", Port: d.port, Protocol: corev1.ProtocolTCP},
				},
			},
		}
		if err := ctrl.SetControllerReference(o, svc, r.Scheme); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, svc); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) reconcileDeployments(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	deploys := []client.Object{
		r.frontendDeployment(o),
		r.backendDeployment(o),
		r.langflowDeployment(o),
	}
	for _, d := range deploys {
		if err := ctrl.SetControllerReference(o, d, r.Scheme); err != nil {
			return err
		}
		if err := r.createOrUpdate(ctx, d); err != nil {
			return err
		}
	}
	return nil
}

func (r *OpenRAGReconciler) frontendDeployment(o *openragv1alpha1.OpenRAG) *appsv1.Deployment {
	spec := o.Spec.Frontend
	replicas := replicasOrDefault(spec.Replicas)
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "fe"),
			Namespace: o.Namespace,
			Labels:    componentLabels(o.Name, "fe"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "fe")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "fe")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "fe"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					Containers: []corev1.Container{
						{
							Name:            "frontend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 3000}},
							Env: append([]corev1.EnvVar{
								{Name: "OPENRAG_BACKEND_HOST", Value: resourceName(o.Name, "be")},
							}, spec.Env...),
							Resources:      spec.Resources,
							LivenessProbe:  httpProbe("/", 3000, 30, 10),
							ReadinessProbe: httpProbe("/", 3000, 10, 5),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) backendDeployment(o *openragv1alpha1.OpenRAG) *appsv1.Deployment {
	spec := o.Spec.Backend
	replicas := replicasOrDefault(spec.Replicas)

	var volumes []corev1.Volume
	var mounts []corev1.VolumeMount

	mounts = append(mounts, corev1.VolumeMount{Name: "backend-temp", MountPath: "/tmp"})
	volumes = append(volumes, corev1.Volume{
		Name:         "backend-temp",
		VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
	})

	if spec.EnvSecret != "" {
		volumes = append(volumes, corev1.Volume{
			Name: "backend-env",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{SecretName: spec.EnvSecret},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{
			Name: "backend-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true,
		})
	}

	var envVars []corev1.EnvVar
	if spec.JWTSigningKeySecret != nil {
		envVars = append(envVars, corev1.EnvVar{
			Name:      "JWT_SIGNING_KEY",
			ValueFrom: &corev1.EnvVarSource{SecretKeyRef: spec.JWTSigningKeySecret},
		})
	}
	envVars = append(envVars, spec.Env...)

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "be"),
			Namespace: o.Namespace,
			Labels:    componentLabels(o.Name, "be"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "be")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "be")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "be"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					Volumes:            volumes,
					Containers: []corev1.Container{
						{
							Name:            "backend",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 8000}},
							Env:             envVars,
							Resources:       spec.Resources,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 8000, 45, 30),
							ReadinessProbe:  httpProbe("/health", 8000, 45, 10),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) langflowDeployment(o *openragv1alpha1.OpenRAG) *appsv1.Deployment {
	spec := o.Spec.Langflow
	replicas := replicasOrDefault(spec.Replicas)

	var volumes []corev1.Volume
	var mounts []corev1.VolumeMount

	mounts = append(mounts, corev1.VolumeMount{Name: "langflow-temp", MountPath: "/tmp"})
	volumes = append(volumes, corev1.Volume{
		Name:         "langflow-temp",
		VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{}},
	})

	if spec.EnvSecret != "" {
		volumes = append(volumes, corev1.Volume{
			Name: "langflow-env",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{SecretName: spec.EnvSecret},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{
			Name: "langflow-env", MountPath: "/app/.env", SubPath: ".env", ReadOnly: true,
		})
	}

	if spec.Storage != nil && spec.Storage.Enabled {
		pvcName := resourceName(o.Name, "lf-data")
		if spec.Storage.ExistingClaim != "" {
			pvcName = spec.Storage.ExistingClaim
		}
		volumes = append(volumes, corev1.Volume{
			Name: "langflow-data",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvcName},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{Name: "langflow-data", MountPath: "/app/data"})
	}

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "lf"),
			Namespace: o.Namespace,
			Labels:    componentLabels(o.Name, "lf"),
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: componentLabels(o.Name, "lf")},
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: componentLabels(o.Name, "lf")},
				Spec: corev1.PodSpec{
					ServiceAccountName: saName(o.Name, "lf"),
					ImagePullSecrets:   o.Spec.ImagePullSecrets,
					NodeSelector:       spec.NodeSelector,
					Tolerations:        spec.Tolerations,
					Affinity:           spec.Affinity,
					Volumes:            volumes,
					Containers: []corev1.Container{
						{
							Name:            "langflow",
							Image:           spec.Image,
							ImagePullPolicy: spec.ImagePullPolicy,
							Args:            []string{"run", "--env-file", "/app/.env"},
							Command:         []string{"langflow"},
							Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: 7860}},
							Env:             spec.Env,
							Resources:       spec.Resources,
							VolumeMounts:    mounts,
							LivenessProbe:   httpProbe("/health", 7860, 120, 30),
							ReadinessProbe:  httpProbe("/health", 7860, 120, 30),
						},
					},
				},
			},
		},
	}
}

func (r *OpenRAGReconciler) reconcileNetworkPolicy(ctx context.Context, o *openragv1alpha1.OpenRAG) error {
	labels := componentLabels(o.Name, "lf")

	egress := []networkingv1.NetworkPolicyEgressRule{
		// langflow -> itself
		{
			Ports: []networkingv1.NetworkPolicyPort{tcpPort(7860)},
			To:    []networkingv1.NetworkPolicyPeer{{PodSelector: &metav1.LabelSelector{MatchLabels: labels}}},
		},
		// DNS
		{Ports: []networkingv1.NetworkPolicyPort{udpPort(53), tcpPort(53)}},
		// OpenSearch + external HTTPS
		{Ports: []networkingv1.NetworkPolicyPort{tcpPort(9200), tcpPort(443)}},
	}

	if o.Spec.Docling != nil {
		egress = append(egress, networkingv1.NetworkPolicyEgressRule{
			Ports: []networkingv1.NetworkPolicyPort{tcpPort(int32(o.Spec.Docling.Port))},
		})
	}

	np := &networkingv1.NetworkPolicy{
		ObjectMeta: metav1.ObjectMeta{
			Name:      resourceName(o.Name, "lf-netpol"),
			Namespace: o.Namespace,
			Labels:    labels,
		},
		Spec: networkingv1.NetworkPolicySpec{
			PodSelector: metav1.LabelSelector{MatchLabels: labels},
			PolicyTypes: []networkingv1.PolicyType{networkingv1.PolicyTypeIngress, networkingv1.PolicyTypeEgress},
			Ingress: []networkingv1.NetworkPolicyIngressRule{
				{From: []networkingv1.NetworkPolicyPeer{
					{IPBlock: &networkingv1.IPBlock{CIDR: "10.0.0.0/8"}},
					{IPBlock: &networkingv1.IPBlock{CIDR: "172.16.0.0/12"}},
					{IPBlock: &networkingv1.IPBlock{CIDR: "192.168.0.0/16"}},
				}},
			},
			Egress: egress,
		},
	}
	if err := ctrl.SetControllerReference(o, np, r.Scheme); err != nil {
		return err
	}
	return r.createOrUpdate(ctx, np)
}

func (r *OpenRAGReconciler) createOrUpdate(ctx context.Context, obj client.Object) error {
	existing := obj.DeepCopyObject().(client.Object)
	err := r.Get(ctx, client.ObjectKeyFromObject(obj), existing)
	if errors.IsNotFound(err) {
		return r.Create(ctx, obj)
	}
	if err != nil {
		return err
	}
	obj.SetResourceVersion(existing.GetResourceVersion())
	return r.Update(ctx, obj)
}

// SetupWithManager registers the controller with the manager.
func (r *OpenRAGReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&openragv1alpha1.OpenRAG{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ServiceAccount{}).
		Owns(&networkingv1.NetworkPolicy{}).
		Complete(r)
}

// helpers

func resourceName(crName, role string) string {
	return crName + "-openrag-" + role
}

func saName(crName, role string) string {
	return "openrag-" + crName + "-" + role
}

func componentLabels(crName, role string) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":       "openrag",
		"app.kubernetes.io/instance":   crName,
		"app.kubernetes.io/component":  role,
		"app.kubernetes.io/managed-by": "openrag-operator",
	}
}

func replicasOrDefault(r *int32) int32 {
	if r != nil {
		return *r
	}
	return 1
}

func httpProbe(path string, port, initialDelay, period int32) *corev1.Probe {
	portVal := intstr.FromInt32(port)
	return &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   path,
				Port:   portVal,
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: initialDelay,
		PeriodSeconds:       period,
		FailureThreshold:    5,
		TimeoutSeconds:      10,
	}
}

func tcpPort(p int32) networkingv1.NetworkPolicyPort {
	proto := corev1.ProtocolTCP
	v := intstr.FromInt32(p)
	return networkingv1.NetworkPolicyPort{Port: &v, Protocol: &proto}
}

func udpPort(p int32) networkingv1.NetworkPolicyPort {
	proto := corev1.ProtocolUDP
	v := intstr.FromInt32(p)
	return networkingv1.NetworkPolicyPort{Port: &v, Protocol: &proto}
}
