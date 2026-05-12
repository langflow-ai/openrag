package main

import (
	"flag"
	"os"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
	"github.com/langflow-ai/openrag-operator/internal/config"
	"github.com/langflow-ai/openrag-operator/internal/controller"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(appsv1.AddToScheme(scheme))
	utilruntime.Must(corev1.AddToScheme(scheme))
	utilruntime.Must(networkingv1.AddToScheme(scheme))
	utilruntime.Must(openragv1alpha1.AddToScheme(scheme))
}

func main() {
	cfg := config.NewOperatorConfig()

	opts := zap.Options{Development: true}
	opts.BindFlags(flag.CommandLine)
	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	mgrOptions := ctrl.Options{
		Scheme:                 scheme,
		Metrics:                metricsserver.Options{BindAddress: cfg.MetricsBindAddress},
		HealthProbeBindAddress: cfg.HealthProbeBindAddress,
		LeaderElection:         cfg.LeaderElectionEnabled,
		LeaderElectionID:       "openrag-operator.openr.ag",
	}

	// If WATCH_NAMESPACE is set, configure namespace-scoped watching
	watchNamespace := strings.TrimSpace(os.Getenv("WATCH_NAMESPACE"))
	if watchNamespace != "" {
		setupLog.Info("configuring namespace-scoped watching", "namespace", watchNamespace)
		// Note: Setting Cache.DefaultNamespaces limits the cache to specific namespaces
		// This is available in controller-runtime v0.15+
		mgrOptions.Cache.DefaultNamespaces = map[string]cache.Config{
			watchNamespace: {},
		}
	} else {
		setupLog.Info("configuring cluster-scoped watching")
	}

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), mgrOptions)
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	err = controller.NewOpenRAGReconciler(mgr.GetClient(), mgr.GetScheme()).SetupWithManager(mgr)
	if err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "OpenRAG")
		os.Exit(1)
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		setupLog.Error(err, "problem running manager")
		os.Exit(1)
	}
}
